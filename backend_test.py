import requests
import sys
import base64
import json
from datetime import datetime, timezone
from typing import Dict, Any

class EcoLensAPITester:
    def __init__(self, base_url="https://enviro-detect.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_base = f"{base_url}/api"
        self.token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def log_test(self, test_name: str, success: bool, details: str = ""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            status = "✅ PASSED"
        else:
            status = "❌ FAILED"
        
        result = f"{status} - {test_name}"
        if details:
            result += f" | {details}"
        print(result)
        self.test_results.append({
            "test": test_name,
            "success": success,
            "details": details
        })
        return success

    def run_request(self, method: str, endpoint: str, expected_status: int, 
                   data: Dict[Any, Any] = None, headers: Dict[str, str] = None) -> tuple:
        """Execute API request and return success status and response"""
        url = f"{self.api_base}/{endpoint}"
        
        default_headers = {'Content-Type': 'application/json'}
        if self.token:
            default_headers['Authorization'] = f'Bearer {self.token}'
        if headers:
            default_headers.update(headers)

        try:
            if method == 'GET':
                response = requests.get(url, headers=default_headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=default_headers, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=default_headers, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=default_headers, timeout=30)
            
            success = response.status_code == expected_status
            response_data = {}
            
            try:
                response_data = response.json() if response.content else {}
            except:
                response_data = {"text": response.text}
                
            return success, response_data, response.status_code
            
        except Exception as e:
            return False, {"error": str(e)}, 0

    def test_root_endpoint(self):
        """Test API root endpoint"""
        success, data, status_code = self.run_request('GET', '', 200)
        return self.log_test(
            "API Root Endpoint", 
            success and data.get('message') == 'EcoLens API is running',
            f"Status: {status_code}, Response: {data}"
        )

    def test_user_registration(self):
        """Test user registration"""
        timestamp = datetime.now().strftime('%H%M%S')
        user_data = {
            "email": f"test_user_{timestamp}@example.com",
            "password": "TestPass123!",
            "name": f"Test User {timestamp}"
        }
        
        success, data, status_code = self.run_request('POST', 'auth/register', 200, user_data)
        
        if success and 'token' in data and 'user' in data:
            self.token = data['token']
            self.user_id = data['user']['id']
            return self.log_test(
                "User Registration", 
                True,
                f"Status: {status_code}, Token received, User ID: {self.user_id}"
            )
        else:
            return self.log_test(
                "User Registration", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def test_user_login(self):
        """Test user login with existing credentials"""
        if not self.user_id:
            return self.log_test("User Login", False, "No user registered for login test")
            
        # Try login with same credentials used in registration
        timestamp = datetime.now().strftime('%H%M%S')
        login_data = {
            "email": f"test_user_{timestamp}@example.com",
            "password": "TestPass123!"
        }
        
        success, data, status_code = self.run_request('POST', 'auth/login', 200, login_data)
        
        if success and 'token' in data:
            return self.log_test(
                "User Login", 
                True,
                f"Status: {status_code}, Login successful"
            )
        else:
            return self.log_test(
                "User Login", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def test_get_user_profile(self):
        """Test getting current user profile"""
        if not self.token:
            return self.log_test("Get User Profile", False, "No authentication token")
            
        success, data, status_code = self.run_request('GET', 'auth/me', 200)
        
        if success and 'id' in data and 'email' in data:
            return self.log_test(
                "Get User Profile", 
                True,
                f"Status: {status_code}, User data retrieved"
            )
        else:
            return self.log_test(
                "Get User Profile", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def create_sample_base64_image(self):
        """Create a small sample image in base64 format for testing"""
        # Create a simple 1x1 pixel PNG in base64 (valid image data)
        # This is a minimal PNG file that represents a 1x1 red pixel
        png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xdd\x8d\xb4\x1c\x00\x00\x00\x00IEND\xaeB`\x82'
        return base64.b64encode(png_data).decode('utf-8')

    def test_plant_analysis(self):
        """Test plant analysis with image upload"""
        if not self.token:
            return self.log_test("Plant Analysis", False, "No authentication token")
            
        base64_image = self.create_sample_base64_image()
        analysis_data = {
            "image_base64": base64_image
        }
        
        success, data, status_code = self.run_request('POST', 'plants/analyze', 200, analysis_data)
        
        if success and 'diagnosis' in data and 'health_score' in data:
            return self.log_test(
                "Plant Analysis", 
                True,
                f"Status: {status_code}, Analysis completed with health score: {data.get('health_score')}"
            )
        else:
            return self.log_test(
                "Plant Analysis", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def test_get_plant_history(self):
        """Test getting plant analysis history"""
        if not self.token:
            return self.log_test("Plant History", False, "No authentication token")
            
        success, data, status_code = self.run_request('GET', 'plants/history', 200)
        
        if success and isinstance(data, list):
            return self.log_test(
                "Plant History", 
                True,
                f"Status: {status_code}, Retrieved {len(data)} plant analyses"
            )
        else:
            return self.log_test(
                "Plant History", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def test_get_events(self):
        """Test getting events list"""
        success, data, status_code = self.run_request('GET', 'events', 200)
        
        if success and isinstance(data, list):
            return self.log_test(
                "Get Events", 
                True,
                f"Status: {status_code}, Retrieved {len(data)} events"
            )
        else:
            return self.log_test(
                "Get Events", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def test_create_event(self):
        """Test creating a new event"""
        if not self.token:
            return self.log_test("Create Event", False, "No authentication token")
            
        event_data = {
            "title": "Test Environmental Event",
            "description": "This is a test event for environmental awareness",
            "event_type": "tree_plantation",
            "location": "Test Location, Test City",
            "date": datetime.now(timezone.utc).isoformat(),
            "organizer": "Test Organizer",
            "image_url": "https://example.com/test-image.jpg"
        }
        
        success, data, status_code = self.run_request('POST', 'events', 200, event_data)
        
        if success and 'id' in data and 'title' in data:
            return self.log_test(
                "Create Event", 
                True,
                f"Status: {status_code}, Event created with ID: {data.get('id')}"
            )
        else:
            return self.log_test(
                "Create Event", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def test_get_tasks(self):
        """Test getting user tasks"""
        if not self.token:
            return self.log_test("Get Tasks", False, "No authentication token")
            
        success, data, status_code = self.run_request('GET', 'tasks', 200)
        
        if success and isinstance(data, list):
            return self.log_test(
                "Get Tasks", 
                True,
                f"Status: {status_code}, Retrieved {len(data)} tasks"
            )
        else:
            return self.log_test(
                "Get Tasks", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def test_create_task(self):
        """Test creating a new eco task"""
        if not self.token:
            return self.log_test("Create Task", False, "No authentication token")
            
        task_data = {
            "task_type": "plant_tree",
            "description": "Planted 5 trees in the local park for environmental conservation",
            "proof_image": "https://example.com/tree-planting-proof.jpg"
        }
        
        success, data, status_code = self.run_request('POST', 'tasks', 200, task_data)
        
        if success and 'id' in data and 'points' in data:
            return self.log_test(
                "Create Task", 
                True,
                f"Status: {status_code}, Task created with {data.get('points')} points"
            )
        else:
            return self.log_test(
                "Create Task", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def test_get_leaderboard(self):
        """Test getting leaderboard"""
        success, data, status_code = self.run_request('GET', 'leaderboard', 200)
        
        if success and isinstance(data, list):
            return self.log_test(
                "Get Leaderboard", 
                True,
                f"Status: {status_code}, Retrieved {len(data)} users in leaderboard"
            )
        else:
            return self.log_test(
                "Get Leaderboard", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def test_get_farmer_guide(self):
        """Test getting farmer guide"""
        success, data, status_code = self.run_request('GET', 'farmer-guide', 200)
        
        if success and isinstance(data, list):
            return self.log_test(
                "Get Farmer Guide", 
                True,
                f"Status: {status_code}, Retrieved {len(data)} crop guides"
            )
        else:
            return self.log_test(
                "Get Farmer Guide", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def test_get_climate_data(self):
        """Test getting climate data"""
        # Test with coordinates for Delhi, India
        success, data, status_code = self.run_request('GET', 'climate?lat=28.6139&lon=77.2090', 200)
        
        if success and 'temperature' in data and 'humidity' in data:
            return self.log_test(
                "Get Climate Data", 
                True,
                f"Status: {status_code}, Climate data retrieved - Temp: {data.get('temperature')}°C, Humidity: {data.get('humidity')}%"
            )
        else:
            return self.log_test(
                "Get Climate Data", 
                False,
                f"Status: {status_code}, Response: {data}"
            )

    def run_all_tests(self):
        """Run all API tests"""
        print(f"🔍 Starting EcoLens API Testing...")
        print(f"Base URL: {self.base_url}")
        print("=" * 60)
        
        # Basic API tests
        self.test_root_endpoint()
        
        # Authentication tests
        self.test_user_registration()
        self.test_user_login()
        self.test_get_user_profile()
        
        # Feature-specific tests
        self.test_plant_analysis()
        self.test_get_plant_history()
        self.test_get_events()
        self.test_create_event()
        self.test_get_tasks()
        self.test_create_task()
        self.test_get_leaderboard()
        self.test_get_farmer_guide()
        self.test_get_climate_data()
        
        # Print summary
        print("=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        success_rate = (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0
        print(f"🎯 Success Rate: {success_rate:.1f}%")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return 0
        else:
            failed_tests = [result for result in self.test_results if not result['success']]
            print(f"❌ {len(failed_tests)} tests failed:")
            for failed in failed_tests:
                print(f"   - {failed['test']}: {failed['details']}")
            return 1

def main():
    tester = EcoLensAPITester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())