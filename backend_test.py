import requests
import json
import base64
import time

# API Configuration
BASE_URL = "https://kyc-fintech-app.preview.emergentagent.com/api"

class FintechAPITester:
    def __init__(self):
        self.base_url = BASE_URL
        self.user_token = None
        self.admin_token = None
        self.user_id = None
        self.otp_data = {}
        
    def test_health_check(self):
        """Test GET /api/"""
        print("\n=== Testing Health Check ===")
        try:
            response = requests.get(f"{self.base_url}/")
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_admin_creation(self):
        """Test POST /api/admin/create-default"""
        print("\n=== Testing Admin Creation ===")
        try:
            response = requests.post(f"{self.base_url}/admin/create-default")
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_send_otp(self):
        """Test POST /api/auth/send-otp"""
        print("\n=== Testing Send OTP ===")
        try:
            data = {"mobile": "9988776655"}
            response = requests.post(f"{self.base_url}/auth/send-otp", json=data)
            print(f"Status Code: {response.status_code}")
            resp_json = response.json()
            print(f"Response: {resp_json}")
            
            if response.status_code == 200:
                self.otp_data["mobile"] = data["mobile"]
                self.otp_data["otp"] = resp_json.get("mock_otp")
                print(f"Mock OTP: {self.otp_data['otp']}")
            
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_verify_otp(self):
        """Test POST /api/auth/verify-otp"""
        print("\n=== Testing Verify OTP ===")
        try:
            data = {
                "mobile": self.otp_data["mobile"],
                "otp": self.otp_data["otp"]
            }
            response = requests.post(f"{self.base_url}/auth/verify-otp", json=data)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_user_registration(self):
        """Test POST /api/auth/register"""
        print("\n=== Testing User Registration ===")
        try:
            data = {
                "username": "testuser123",
                "mobile": "9988776655",
                "email": "testuser@example.com",
                "age": 30,
                "password": "testpass123"
            }
            response = requests.post(f"{self.base_url}/auth/register", json=data)
            print(f"Status Code: {response.status_code}")
            resp_json = response.json()
            print(f"Response: {resp_json}")
            
            if response.status_code == 200:
                self.user_token = resp_json.get("access_token")
                self.user_id = resp_json.get("user_id")
                print(f"User ID: {self.user_id}")
                return True
            elif response.status_code == 400 and "already exists" in str(resp_json.get("detail", "")):
                # User already exists, this is acceptable for testing
                print("User already exists - will use login instead")
                return True
                
            return False
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_user_login(self):
        """Test POST /api/auth/login with user credentials"""
        print("\n=== Testing User Login ===")
        try:
            data = {
                "identifier": "testuser@example.com",
                "password": "testpass123"
            }
            response = requests.post(f"{self.base_url}/auth/login", json=data)
            print(f"Status Code: {response.status_code}")
            resp_json = response.json()
            print(f"Response: {resp_json}")
            
            if response.status_code == 200:
                self.user_token = resp_json.get("access_token")
                self.user_id = resp_json.get("user_id")
                
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_admin_login(self):
        """Test POST /api/auth/login with admin credentials"""
        print("\n=== Testing Admin Login ===")
        try:
            data = {
                "identifier": "admin@fintech.com",
                "password": "admin123"
            }
            response = requests.post(f"{self.base_url}/auth/login", json=data)
            print(f"Status Code: {response.status_code}")
            resp_json = response.json()
            print(f"Response: {resp_json}")
            
            if response.status_code == 200:
                self.admin_token = resp_json.get("access_token")
                print(f"Admin role: {resp_json.get('user', {}).get('role')}")
                
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_kyc_upload(self):
        """Test POST /api/kyc/upload"""
        print("\n=== Testing KYC Upload ===")
        try:
            # Create mock base64 document
            mock_doc = base64.b64encode(b"Mock document content").decode('utf-8')
            
            data = {
                "user_id": self.user_id,
                "document_type": "aadhar",
                "document_data": mock_doc
            }
            
            headers = {"Authorization": f"Bearer {self.user_token}"}
            response = requests.post(f"{self.base_url}/kyc/upload", json=data, headers=headers)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_trust_score_submit(self):
        """Test POST /api/trust-score/submit"""
        print("\n=== Testing Trust Score Submit ===")
        try:
            data = {
                "user_id": self.user_id,
                "employment_type": "salaried",
                "income_type": "salary",
                "income_amount": 50000.0,
                "monthly_expenses": 30000.0,
                "has_previous_loan": True,
                "bank_statements": [
                    base64.b64encode(json.dumps({
                        "month": "January 2025",
                        "opening_balance": 25000,
                        "closing_balance": 35000,
                        "total_credits": 55000,
                        "total_debits": 45000
                    }).encode()).decode()
                ]
            }
            
            headers = {"Authorization": f"Bearer {self.user_token}"}
            response = requests.post(f"{self.base_url}/trust-score/submit", json=data, headers=headers)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_user_profile(self):
        """Test GET /api/user/profile"""
        print("\n=== Testing User Profile ===")
        try:
            headers = {"Authorization": f"Bearer {self.user_token}"}
            response = requests.get(f"{self.base_url}/user/profile", headers=headers)
            print(f"Status Code: {response.status_code}")
            resp_json = response.json()
            print(f"Response: {json.dumps(resp_json, indent=2)}")
            
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_admin_get_users(self):
        """Test GET /api/admin/users - CRITICAL TEST"""
        print("\n=== Testing Admin Get All Users (CRITICAL) ===")
        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = requests.get(f"{self.base_url}/admin/users", headers=headers)
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                resp_json = response.json()
                print(f"Successfully retrieved {len(resp_json)} users")
                print(f"Sample user data: {json.dumps(resp_json[0] if resp_json else 'No users', indent=2)}")
                return True
            else:
                print(f"Error Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_admin_get_user_complete_data(self):
        """Test GET /api/admin/user/{user_id}/complete-data - CRITICAL TEST"""
        print("\n=== Testing Admin Get User Complete Data (CRITICAL) ===")
        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            url = f"{self.base_url}/admin/user/{self.user_id}/complete-data"
            response = requests.get(url, headers=headers)
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                resp_json = response.json()
                print(f"Successfully retrieved complete user data")
                print(f"Data keys: {list(resp_json.keys())}")
                print(f"User data: {json.dumps(resp_json.get('user', {}), indent=2)}")
                return True
            else:
                print(f"Error Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_admin_assign_score(self):
        """Test POST /api/admin/assign-score"""
        print("\n=== Testing Admin Assign Score ===")
        try:
            data = {
                "user_id": self.user_id,
                "admin_score": 750,
                "remarks": "Good financial profile, low risk user"
            }
            
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = requests.post(f"{self.base_url}/admin/assign-score", json=data, headers=headers)
            print(f"Status Code: {response.status_code}")
            resp_json = response.json()
            print(f"Response: {resp_json}")
            
            if response.status_code == 200:
                print(f"PDF Generated: {len(resp_json.get('pdf_base64', ''))} characters")
                print(f"WhatsApp Mock: {resp_json.get('whatsapp_sent')}")
            
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_user_profile_after_score(self):
        """Test GET /api/user/profile after score assignment"""
        print("\n=== Testing User Profile After Score Assignment ===")
        try:
            headers = {"Authorization": f"Bearer {self.user_token}"}
            response = requests.get(f"{self.base_url}/user/profile", headers=headers)
            print(f"Status Code: {response.status_code}")
            resp_json = response.json()
            print(f"Trust Score Status: {resp_json.get('trust_score_status')}")
            print(f"Admin Score: {resp_json.get('admin_score')}")
            
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False

def main():
    """Run comprehensive backend testing focused on ObjectId fix verification"""
    tester = FintechAPITester()
    
    print("=== FINTECH BACKEND API TESTING ===")
    print("Focusing on ObjectId serialization fix verification")
    print(f"Testing against: {BASE_URL}")
    
    results = {}
    
    # Setup tests - these should all pass based on previous results
    print("\n--- SETUP TESTS ---")
    results["health_check"] = tester.test_health_check()
    results["admin_creation"] = tester.test_admin_creation()
    results["send_otp"] = tester.test_send_otp()
    results["verify_otp"] = tester.test_verify_otp()
    results["user_registration"] = tester.test_user_registration()
    results["user_login"] = tester.test_user_login()
    results["admin_login"] = tester.test_admin_login()
    
    # User functionality tests
    print("\n--- USER FUNCTIONALITY TESTS ---")
    results["kyc_upload"] = tester.test_kyc_upload()
    results["trust_score_submit"] = tester.test_trust_score_submit()
    results["user_profile"] = tester.test_user_profile()
    
    # CRITICAL OBJECTID FIX TESTS
    print("\n--- CRITICAL OBJECTID FIX TESTS ---")
    results["admin_get_users"] = tester.test_admin_get_users()
    results["admin_get_user_complete_data"] = tester.test_admin_get_user_complete_data()
    
    # Admin functionality tests
    print("\n--- ADMIN FUNCTIONALITY TESTS ---")
    results["admin_assign_score"] = tester.test_admin_assign_score()
    results["user_profile_after_score"] = tester.test_user_profile_after_score()
    
    # Final summary
    print("\n=== FINAL TEST RESULTS ===")
    passed = sum(results.values())
    total = len(results)
    
    print(f"PASSED: {passed}/{total} tests")
    
    print("\nDetailed Results:")
    for test, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test}: {status}")
    
    # Critical ObjectId fix status
    print(f"\n=== CRITICAL OBJECTID FIX STATUS ===")
    objectid_tests = ["admin_get_users", "admin_get_user_complete_data"]
    objectid_passed = all(results.get(test, False) for test in objectid_tests)
    
    if objectid_passed:
        print("✅ ObjectId serialization issues FIXED - Admin endpoints working")
    else:
        print("❌ ObjectId serialization issues PERSIST - Admin endpoints failing")
        
    return results

if __name__ == "__main__":
    main()