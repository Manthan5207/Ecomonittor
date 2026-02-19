from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext
import jwt
import base64
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
import aiohttp

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'test_database')]

app = FastAPI()
api_router = APIRouter(prefix="/api")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

JWT_SECRET = os.environ.get('JWT_SECRET', 'ecolens_secret_key_2026')
JWT_ALGORITHM = "HS256"
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    name: str
    points: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    token: str
    user: User

class PlantAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    image_base64: Optional[str] = None
    diagnosis: str
    causes: str
    treatment: str
    prevention: str
    health_score: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class PlantAnalysisCreate(BaseModel):
    image_base64: str

class Event(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    event_type: str
    location: str
    date: datetime
    organizer: str
    registered_users: List[str] = []
    image_url: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class EventCreate(BaseModel):
    title: str
    description: str
    event_type: str
    location: str
    date: datetime
    organizer: str
    image_url: str

class EventRegister(BaseModel):
    event_id: str

class EcoTask(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    task_type: str
    description: str
    points: int
    proof_image: Optional[str] = None
    status: str = "pending"
    verified: bool = False
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class EcoTaskCreate(BaseModel):
    task_type: str
    description: str
    proof_image: Optional[str] = None

class EcoTaskVerify(BaseModel):
    task_id: str
    verified: bool

class FarmerGuide(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    crop_name: str
    season: str
    region: str
    fertilizer: str
    pest_control: str
    soil_type: str

class ClimateData(BaseModel):
    temperature: float
    humidity: float
    weather: str
    aqi: Optional[int] = None
    precautions: List[str]

def create_token(user_id: str, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@api_router.get("/")
async def root():
    return {"message": "EcoLens API is running", "status": "ok"}

@api_router.post("/auth/register", response_model=TokenResponse)
async def register(input: UserCreate):
    existing = await db.users.find_one({"email": input.email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_obj = User(email=input.email, name=input.name)
    user_dict = user_obj.model_dump()
    user_dict['password_hash'] = pwd_context.hash(input.password)
    user_dict['created_at'] = user_dict['created_at'].isoformat()
    
    await db.users.insert_one(user_dict)
    token = create_token(user_obj.id, user_obj.email)
    return TokenResponse(token=token, user=user_obj)

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(input: UserLogin):
    user = await db.users.find_one({"email": input.email}, {"_id": 0})
    if not user or not pwd_context.verify(input.password, user['password_hash']):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if isinstance(user['created_at'], str):
        user['created_at'] = datetime.fromisoformat(user['created_at'])
    
    user_obj = User(**user)
    token = create_token(user_obj.id, user_obj.email)
    return TokenResponse(token=token, user=user_obj)

@api_router.get("/auth/me", response_model=User)
async def get_me(current_user: dict = Depends(get_current_user)):
    if isinstance(current_user['created_at'], str):
        current_user['created_at'] = datetime.fromisoformat(current_user['created_at'])
    return User(**current_user)

@api_router.post("/plants/analyze", response_model=PlantAnalysis)
async def analyze_plant(input: PlantAnalysisCreate, current_user: dict = Depends(get_current_user)):
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"plant_analysis_{uuid.uuid4()}",
            system_message="You are an expert botanist and plant pathologist. Analyze plant images and provide detailed diagnosis."
        ).with_model("gemini", "gemini-3-flash-preview")
        
        image_content = ImageContent(image_base64=input.image_base64)
        user_message = UserMessage(
            text="""Analyze this plant image and provide:
1. Diagnosis: What is the condition of this plant?
2. Causes: What are the possible causes of any issues?
3. Treatment: How to treat any problems?
4. Prevention: How to prevent future issues?
5. Health Score: Rate the plant health from 0-100.

Format your response as:
DIAGNOSIS: [your diagnosis]
CAUSES: [causes]
TREATMENT: [treatment]
PREVENTION: [prevention]
HEALTH_SCORE: [number]""",
            file_contents=[image_content]
        )
        
        response = await chat.send_message(user_message)
        
        diagnosis = ""
        causes = ""
        treatment = ""
        prevention = ""
        health_score = 75
        
        lines = response.split('\n')
        for line in lines:
            if line.startswith('DIAGNOSIS:'):
                diagnosis = line.replace('DIAGNOSIS:', '').strip()
            elif line.startswith('CAUSES:'):
                causes = line.replace('CAUSES:', '').strip()
            elif line.startswith('TREATMENT:'):
                treatment = line.replace('TREATMENT:', '').strip()
            elif line.startswith('PREVENTION:'):
                prevention = line.replace('PREVENTION:', '').strip()
            elif line.startswith('HEALTH_SCORE:'):
                try:
                    health_score = int(line.replace('HEALTH_SCORE:', '').strip())
                except:
                    health_score = 75
        
        if not diagnosis:
            diagnosis = response[:200]
        if not causes:
            causes = "Multiple factors including environmental stress, nutrient deficiency, or disease."
        if not treatment:
            treatment = "Consult with a local plant expert for specific treatment recommendations."
        if not prevention:
            prevention = "Regular monitoring, proper watering, and adequate nutrition."
        
        analysis = PlantAnalysis(
            user_id=current_user['id'],
            diagnosis=diagnosis,
            causes=causes,
            treatment=treatment,
            prevention=prevention,
            health_score=health_score
        )
        
        analysis_dict = analysis.model_dump()
        analysis_dict['timestamp'] = analysis_dict['timestamp'].isoformat()
        await db.plants_analysis.insert_one(analysis_dict)
        
        return analysis
    except Exception as e:
        logging.error(f"Plant analysis error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@api_router.get("/plants/history", response_model=List[PlantAnalysis])
async def get_plant_history(current_user: dict = Depends(get_current_user)):
    analyses = await db.plants_analysis.find({"user_id": current_user['id']}, {"_id": 0}).sort("timestamp", -1).limit(20).to_list(20)
    for analysis in analyses:
        if isinstance(analysis['timestamp'], str):
            analysis['timestamp'] = datetime.fromisoformat(analysis['timestamp'])
    return analyses

@api_router.get("/events", response_model=List[Event])
async def get_events():
    events = await db.events.find({}, {"_id": 0}).to_list(100)
    for event in events:
        if isinstance(event['date'], str):
            event['date'] = datetime.fromisoformat(event['date'])
        if isinstance(event['created_at'], str):
            event['created_at'] = datetime.fromisoformat(event['created_at'])
    return events

@api_router.post("/events", response_model=Event)
async def create_event(input: EventCreate, current_user: dict = Depends(get_current_user)):
    event = Event(**input.model_dump())
    event_dict = event.model_dump()
    event_dict['date'] = event_dict['date'].isoformat()
    event_dict['created_at'] = event_dict['created_at'].isoformat()
    await db.events.insert_one(event_dict)
    return event

@api_router.post("/events/register")
async def register_event(input: EventRegister, current_user: dict = Depends(get_current_user)):
    event = await db.events.find_one({"id": input.event_id}, {"_id": 0})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    if current_user['id'] in event['registered_users']:
        raise HTTPException(status_code=400, detail="Already registered")
    
    await db.events.update_one(
        {"id": input.event_id},
        {"$push": {"registered_users": current_user['id']}}
    )
    
    await db.users.update_one(
        {"id": current_user['id']},
        {"$inc": {"points": 10}}
    )
    
    return {"message": "Registered successfully", "points_earned": 10}

@api_router.get("/tasks", response_model=List[EcoTask])
async def get_tasks(current_user: dict = Depends(get_current_user)):
    tasks = await db.eco_tasks.find({"user_id": current_user['id']}, {"_id": 0}).to_list(100)
    for task in tasks:
        if isinstance(task['completed_at'], str):
            task['completed_at'] = datetime.fromisoformat(task['completed_at'])
    return tasks

@api_router.post("/tasks", response_model=EcoTask)
async def create_task(input: EcoTaskCreate, current_user: dict = Depends(get_current_user)):
    points_map = {
        "plant_tree": 50,
        "attend_event": 30,
        "report_plant": 20,
        "cleanup": 40
    }
    
    task = EcoTask(
        user_id=current_user['id'],
        task_type=input.task_type,
        description=input.description,
        points=points_map.get(input.task_type, 10),
        proof_image=input.proof_image
    )
    
    task_dict = task.model_dump()
    task_dict['completed_at'] = task_dict['completed_at'].isoformat()
    await db.eco_tasks.insert_one(task_dict)
    
    return task

@api_router.post("/tasks/verify")
async def verify_task(input: EcoTaskVerify, current_user: dict = Depends(get_current_user)):
    task = await db.eco_tasks.find_one({"id": input.task_id}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    await db.eco_tasks.update_one(
        {"id": input.task_id},
        {"$set": {"verified": input.verified, "status": "verified" if input.verified else "rejected"}}
    )
    
    if input.verified:
        await db.users.update_one(
            {"id": task['user_id']},
            {"$inc": {"points": task['points']}}
        )
    
    return {"message": "Task verified", "points_awarded": task['points'] if input.verified else 0}

@api_router.get("/leaderboard", response_model=List[User])
async def get_leaderboard():
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("points", -1).limit(10).to_list(10)
    for user in users:
        if isinstance(user['created_at'], str):
            user['created_at'] = datetime.fromisoformat(user['created_at'])
    return users

@api_router.get("/farmer-guide", response_model=List[FarmerGuide])
async def get_farmer_guide(season: Optional[str] = None, region: Optional[str] = None):
    query = {}
    if season:
        query['season'] = season
    if region:
        query['region'] = region
    
    guides = await db.farmer_guide.find(query, {"_id": 0}).to_list(100)
    return guides

@api_router.get("/climate")
async def get_climate_data(lat: float, lon: float):
    try:
        async with aiohttp.ClientSession() as session:
            weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid=demo&units=metric"
            async with session.get(weather_url) as resp:
                if resp.status == 200:
                    weather_data = await resp.json()
                    temperature = weather_data.get('main', {}).get('temp', 25)
                    humidity = weather_data.get('main', {}).get('humidity', 60)
                    weather = weather_data.get('weather', [{}])[0].get('description', 'clear sky')
                else:
                    temperature = 25
                    humidity = 60
                    weather = "clear sky"
        
        precautions = []
        if temperature > 35:
            precautions.append("High temperature: Stay hydrated and avoid direct sunlight")
        if humidity > 80:
            precautions.append("High humidity: Risk of fungal diseases in plants")
        if "rain" in weather.lower():
            precautions.append("Rainy conditions: Ensure proper drainage for crops")
        
        return ClimateData(
            temperature=temperature,
            humidity=humidity,
            weather=weather,
            aqi=None,
            precautions=precautions
        )
    except Exception as e:
        logging.error(f"Climate data error: {str(e)}")
        return ClimateData(
            temperature=25.0,
            humidity=60.0,
            weather="clear sky",
            aqi=None,
            precautions=["Unable to fetch live data. Showing sample data."]
        )

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

@app.on_event("startup")
async def startup_db():
    count = await db.farmer_guide.count_documents({})
    if count == 0:
        sample_guides = [
            {
                "id": str(uuid.uuid4()),
                "crop_name": "Rice",
                "season": "Monsoon",
                "region": "South Asia",
                "fertilizer": "NPK 20:20:20 before planting, Urea during growth",
                "pest_control": "Use neem oil spray for pests. Monitor for stem borers.",
                "soil_type": "Clay or loamy soil with good water retention"
            },
            {
                "id": str(uuid.uuid4()),
                "crop_name": "Wheat",
                "season": "Winter",
                "region": "North India",
                "fertilizer": "DAP at sowing, Urea top dressing at tillering",
                "pest_control": "Monitor for aphids and rust. Use approved pesticides.",
                "soil_type": "Well-drained loamy soil"
            },
            {
                "id": str(uuid.uuid4()),
                "crop_name": "Tomato",
                "season": "All Year",
                "region": "Pan India",
                "fertilizer": "Compost and NPK 19:19:19 weekly",
                "pest_control": "Bacillus thuringiensis for caterpillars, neem for aphids",
                "soil_type": "Rich, well-drained soil with pH 6.0-7.0"
            },
            {
                "id": str(uuid.uuid4()),
                "crop_name": "Cotton",
                "season": "Summer",
                "region": "Central India",
                "fertilizer": "Nitrogen-rich fertilizers during growth phase",
                "pest_control": "Integrated pest management for bollworm control",
                "soil_type": "Black cotton soil with good drainage"
            }
        ]
        await db.farmer_guide.insert_many(sample_guides)