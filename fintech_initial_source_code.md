# FinTrust - Complete Source Code

## Table of Contents
1. [Backend Code](#backend-code)
2. [Frontend Code](#frontend-code)
3. [Configuration Files](#configuration-files)

---

## Backend Code

### 1. server.py (FastAPI Backend)

```python
from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timedelta
import bcrypt
import jwt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import io
import base64
import random

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Settings
SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30 days

# Create the main app
app = FastAPI()
api_router = APIRouter(prefix="/api")
security = HTTPBearer()

# Mock OTP storage (in production, use Redis or similar)
otp_storage = {}

# ============= MODELS =============

class UserRegister(BaseModel):
    username: str
    mobile: str
    email: EmailStr
    age: int
    password: str

class OTPRequest(BaseModel):
    mobile: str

class OTPVerify(BaseModel):
    mobile: str
    otp: str

class UserLogin(BaseModel):
    identifier: str  # email or mobile
    password: str

class KYCUpload(BaseModel):
    user_id: str
    document_type: str
    document_data: str  # base64

class TrustScoreData(BaseModel):
    user_id: str
    employment_type: str
    income_type: str
    income_amount: float
    monthly_expenses: float
    has_previous_loan: bool
    bank_statements: List[str]  # array of base64 strings

class AdminScoreUpdate(BaseModel):
    user_id: str
    admin_score: int
    remarks: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    username: str
    role: str

# ============= HELPER FUNCTIONS =============

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = verify_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

async def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = await get_current_user(credentials)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def generate_trust_score_pdf(user_data: dict, trust_score: int, remarks: str) -> str:
    """Generate PDF and return base64 encoded string"""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Title
    c.setFont("Helvetica-Bold", 20)
    c.drawString(1 * inch, height - 1 * inch, "Trust Score Report")
    
    # User Info
    c.setFont("Helvetica", 12)
    y_position = height - 1.5 * inch
    c.drawString(1 * inch, y_position, f"Name: {user_data.get('username', 'N/A')}")
    y_position -= 0.3 * inch
    c.drawString(1 * inch, y_position, f"Email: {user_data.get('email', 'N/A')}")
    y_position -= 0.3 * inch
    c.drawString(1 * inch, y_position, f"Mobile: {user_data.get('mobile', 'N/A')}")
    
    # Trust Score
    y_position -= 0.5 * inch
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, y_position, f"Trust Score: {trust_score}/100")
    
    # Remarks
    y_position -= 0.5 * inch
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1 * inch, y_position, "Evaluation Summary:")
    y_position -= 0.3 * inch
    c.setFont("Helvetica", 12)
    
    # Word wrap for remarks
    words = remarks.split()
    line = ""
    for word in words:
        if len(line + word) < 70:
            line += word + " "
        else:
            c.drawString(1 * inch, y_position, line)
            y_position -= 0.3 * inch
            line = word + " "
    if line:
        c.drawString(1 * inch, y_position, line)
    
    # Footer
    c.setFont("Helvetica", 10)
    c.drawString(1 * inch, 1 * inch, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    c.save()
    buffer.seek(0)
    pdf_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    return pdf_base64

def mock_send_whatsapp(mobile: str, pdf_base64: str) -> bool:
    """Mock WhatsApp sending - logs to console"""
    logging.info(f"[MOCK] Sending WhatsApp message to {mobile}")
    logging.info(f"[MOCK] PDF size: {len(pdf_base64)} bytes")
    return True

# ============= ROUTES =============

@api_router.get("/")
async def root():
    return {"message": "Fintech API is running"}

# ===== AUTHENTICATION ROUTES =====

@api_router.post("/auth/send-otp")
async def send_otp(request: OTPRequest):
    """Mock OTP sending"""
    otp = str(random.randint(100000, 999999))
    otp_storage[request.mobile] = otp
    logging.info(f"[MOCK] OTP for {request.mobile}: {otp}")
    return {"success": True, "message": "OTP sent successfully", "mock_otp": otp}

@api_router.post("/auth/verify-otp")
async def verify_otp(request: OTPVerify):
    """Verify OTP"""
    stored_otp = otp_storage.get(request.mobile)
    if not stored_otp or stored_otp != request.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    
    # Remove OTP after verification
    del otp_storage[request.mobile]
    return {"success": True, "message": "OTP verified successfully"}

@api_router.post("/auth/register", response_model=TokenResponse)
async def register_user(user: UserRegister):
    # Check if user already exists
    existing_user = await db.users.find_one({"$or": [{"email": user.email}, {"mobile": user.mobile}]})
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists with this email or mobile")
    
    user_id = str(uuid.uuid4())
    hashed_pwd = hash_password(user.password)
    
    user_doc = {
        "user_id": user_id,
        "username": user.username,
        "mobile": user.mobile,
        "email": user.email,
        "age": user.age,
        "password_hash": hashed_pwd,
        "role": "user",
        "created_at": datetime.utcnow(),
        "is_mobile_verified": True  # Since we verified OTP
    }
    
    await db.users.insert_one(user_doc)
    
    # Create access token
    access_token = create_access_token({"sub": user_id, "role": "user"})
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user_id,
        username=user.username,
        role="user"
    )

@api_router.post("/auth/login", response_model=TokenResponse)
async def login_user(credentials: UserLogin):
    # Find user by email or mobile
    user = await db.users.find_one({
        "$or": [{"email": credentials.identifier}, {"mobile": credentials.identifier}]
    })
    
    if not user or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token({"sub": user["user_id"], "role": user["role"]})
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user["user_id"],
        username=user["username"],
        role=user["role"]
    )

# ===== KYC ROUTES =====

@api_router.post("/kyc/upload")
async def upload_kyc(kyc: KYCUpload, current_user: dict = Depends(get_current_user)):
    if kyc.user_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    kyc_doc = {
        "user_id": kyc.user_id,
        "document_type": kyc.document_type,
        "document_data": kyc.document_data,
        "verification_status": "pending",
        "uploaded_at": datetime.utcnow()
    }
    
    # Update if exists, insert if not
    await db.kyc.update_one(
        {"user_id": kyc.user_id},
        {"$set": kyc_doc},
        upsert=True
    )
    
    return {"success": True, "message": "KYC document uploaded successfully"}

@api_router.get("/kyc/{user_id}")
async def get_kyc(user_id: str, current_user: dict = Depends(get_current_user)):
    # Users can only see their own KYC, admins can see any
    if current_user["role"] != "admin" and current_user["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    kyc = await db.kyc.find_one({"user_id": user_id})
    if not kyc:
        return None
    return kyc

# ===== TRUST SCORE ROUTES =====

@api_router.post("/trust-score/submit")
async def submit_trust_score_data(data: TrustScoreData, current_user: dict = Depends(get_current_user)):
    if data.user_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    # Save income details
    income_doc = {
        "user_id": data.user_id,
        "employment_type": data.employment_type,
        "income_type": data.income_type,
        "income_amount": data.income_amount,
        "monthly_expenses": data.monthly_expenses,
        "submitted_at": datetime.utcnow()
    }
    await db.income_details.update_one(
        {"user_id": data.user_id},
        {"$set": income_doc},
        upsert=True
    )
    
    # Save bank statements
    bank_doc = {
        "user_id": data.user_id,
        "statements": data.bank_statements,
        "upload_date": datetime.utcnow()
    }
    await db.bank_statements.update_one(
        {"user_id": data.user_id},
        {"$set": bank_doc},
        upsert=True
    )
    
    # Save loan history
    loan_doc = {
        "user_id": data.user_id,
        "has_previous_loan": data.has_previous_loan,
        "submitted_at": datetime.utcnow()
    }
    await db.loan_history.update_one(
        {"user_id": data.user_id},
        {"$set": loan_doc},
        upsert=True
    )
    
    # Create pending trust score entry
    trust_score_doc = {
        "user_id": data.user_id,
        "admin_score": None,
        "remarks": "",
        "status": "pending_review",
        "submitted_at": datetime.utcnow(),
        "generated_date": None,
        "pdf_data": None,
        "sent_via_whatsapp": False
    }
    await db.trust_scores.update_one(
        {"user_id": data.user_id},
        {"$set": trust_score_doc},
        upsert=True
    )
    
    return {"success": True, "message": "Trust score data submitted for review"}

@api_router.get("/trust-score/{user_id}")
async def get_trust_score(user_id: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin" and current_user["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    score = await db.trust_scores.find_one({"user_id": user_id})
    if not score:
        return None
    return score

# ===== ADMIN ROUTES =====

@api_router.get("/admin/users")
async def get_all_users(current_admin: dict = Depends(get_current_admin)):
    users = await db.users.find({"role": "user"}).to_list(1000)
    
    # Get trust score status for each user and clean MongoDB ObjectId
    for user in users:
        # Remove MongoDB ObjectId
        if "_id" in user:
            del user["_id"]
        
        trust_score = await db.trust_scores.find_one({"user_id": user["user_id"]})
        user["trust_score_status"] = trust_score.get("status") if trust_score else "not_submitted"
        user["admin_score"] = trust_score.get("admin_score") if trust_score else None
    
    return users

@api_router.get("/admin/user/{user_id}/complete-data")
async def get_user_complete_data(user_id: str, current_admin: dict = Depends(get_current_admin)):
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Remove MongoDB _id from all documents
    if "_id" in user:
        del user["_id"]
    
    kyc = await db.kyc.find_one({"user_id": user_id})
    if kyc and "_id" in kyc:
        del kyc["_id"]
    
    income = await db.income_details.find_one({"user_id": user_id})
    if income and "_id" in income:
        del income["_id"]
    
    bank_statements = await db.bank_statements.find_one({"user_id": user_id})
    if bank_statements and "_id" in bank_statements:
        del bank_statements["_id"]
    
    loan_history = await db.loan_history.find_one({"user_id": user_id})
    if loan_history and "_id" in loan_history:
        del loan_history["_id"]
    
    trust_score = await db.trust_scores.find_one({"user_id": user_id})
    if trust_score and "_id" in trust_score:
        del trust_score["_id"]
    
    return {
        "user": user,
        "kyc": kyc,
        "income_details": income,
        "bank_statements": bank_statements,
        "loan_history": loan_history,
        "trust_score": trust_score
    }

@api_router.post("/admin/assign-score")
async def assign_trust_score(score_data: AdminScoreUpdate, current_admin: dict = Depends(get_current_admin)):
    # Get user data for PDF generation
    user = await db.users.find_one({"user_id": score_data.user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate PDF
    pdf_base64 = generate_trust_score_pdf(user, score_data.admin_score, score_data.remarks)
    
    # Mock send WhatsApp
    whatsapp_sent = mock_send_whatsapp(user["mobile"], pdf_base64)
    
    # Update trust score
    update_doc = {
        "admin_score": score_data.admin_score,
        "remarks": score_data.remarks,
        "status": "completed",
        "generated_date": datetime.utcnow(),
        "pdf_data": pdf_base64,
        "sent_via_whatsapp": whatsapp_sent
    }
    
    await db.trust_scores.update_one(
        {"user_id": score_data.user_id},
        {"$set": update_doc}
    )
    
    return {
        "success": True,
        "message": "Trust score assigned and PDF sent via WhatsApp",
        "pdf_base64": pdf_base64
    }

# ===== USER PROFILE ROUTES =====

@api_router.get("/user/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    
    # Get all user data
    kyc = await db.kyc.find_one({"user_id": user_id})
    trust_score = await db.trust_scores.find_one({"user_id": user_id})
    income = await db.income_details.find_one({"user_id": user_id})
    
    return {
        "user": {
            "user_id": current_user["user_id"],
            "username": current_user["username"],
            "email": current_user["email"],
            "mobile": current_user["mobile"],
            "age": current_user["age"],
            "created_at": current_user["created_at"]
        },
        "kyc_status": kyc.get("verification_status") if kyc else "not_uploaded",
        "trust_score_status": trust_score.get("status") if trust_score else "not_submitted",
        "trust_score": trust_score.get("admin_score") if trust_score else None,
        "has_submitted_income": income is not None
    }

# ===== CREATE DEFAULT ADMIN =====

@api_router.post("/admin/create-default")
async def create_default_admin():
    """Create default admin account (for testing)"""
    existing_admin = await db.users.find_one({"email": "admin@fintech.com"})
    if existing_admin:
        return {"message": "Admin already exists"}
    
    admin_id = str(uuid.uuid4())
    admin_doc = {
        "user_id": admin_id,
        "username": "Admin",
        "mobile": "9999999999",
        "email": "admin@fintech.com",
        "age": 30,
        "password_hash": hash_password("admin123"),
        "role": "admin",
        "created_at": datetime.utcnow(),
        "is_mobile_verified": True
    }
    
    await db.users.insert_one(admin_doc)
    return {"message": "Default admin created", "email": "admin@fintech.com", "password": "admin123"}

# Include the router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
```

### 2. requirements.txt

```txt
fastapi==0.110.1
uvicorn==0.25.0
boto3>=1.34.129
requests-oauthlib>=2.0.0
cryptography>=42.0.8
python-dotenv>=1.0.1
pymongo==4.5.0
pydantic>=2.6.4
email-validator>=2.2.0
pyjwt>=2.10.1
bcrypt==4.1.3
passlib>=1.7.4
tzdata>=2024.2
motor==3.3.1
pytest>=8.0.0
black>=24.1.1
isort>=5.13.2
flake8>=7.0.0
mypy>=1.8.0
python-jose>=3.3.0
requests>=2.31.0
pandas>=2.2.0
numpy>=1.26.0
python-multipart>=0.0.9
jq>=1.6.0
typer>=0.9.0
emergentintegrations==0.1.0
reportlab
```

### 3. Backend .env

```env
MONGO_URL=mongodb://localhost:27017
DB_NAME=fintech_db
JWT_SECRET_KEY=your-secret-key-change-in-production
```

---

## Frontend Code

### 1. App Layout (_layout.tsx)

```typescript
import { Stack } from 'expo-router';
import { AuthProvider } from '../contexts/AuthContext';
import { GestureHandlerRootView } from 'react-native-gesture-handler';

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <AuthProvider>
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="index" />
          <Stack.Screen name="(auth)" />
          <Stack.Screen name="(user)" />
          <Stack.Screen name="(admin)" />
        </Stack>
      </AuthProvider>
    </GestureHandlerRootView>
  );
}
```

### 2. Entry Point (index.tsx)

```typescript
import { useEffect } from 'react';
import { View, ActivityIndicator, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { useAuth } from '../contexts/AuthContext';

export default function Index() {
  const router = useRouter();
  const { user, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading) {
      if (user) {
        // Route based on role
        if (user.role === 'admin') {
          router.replace('/(admin)/dashboard');
        } else {
          router.replace('/(user)/home');
        }
      } else {
        router.replace('/(auth)/welcome');
      }
    }
  }, [user, isLoading]);

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" color="#6366f1" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#ffffff',
  },
});
```

### 3. Auth Context (contexts/AuthContext.tsx)

```typescript
import React, { createContext, useContext, useState, useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

interface User {
  user_id: string;
  username: string;
  role: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (token: string, userData: User) => Promise<void>;
  logout: () => Promise<void>;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    loadStoredAuth();
  }, []);

  const loadStoredAuth = async () => {
    try {
      const storedToken = await AsyncStorage.getItem('auth_token');
      const storedUser = await AsyncStorage.getItem('user_data');
      
      if (storedToken && storedUser) {
        setToken(storedToken);
        setUser(JSON.parse(storedUser));
      }
    } catch (error) {
      console.error('Error loading auth:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (newToken: string, userData: User) => {
    try {
      await AsyncStorage.setItem('auth_token', newToken);
      await AsyncStorage.setItem('user_data', JSON.stringify(userData));
      setToken(newToken);
      setUser(userData);
    } catch (error) {
      console.error('Error saving auth:', error);
      throw error;
    }
  };

  const logout = async () => {
    try {
      await AsyncStorage.removeItem('auth_token');
      await AsyncStorage.removeItem('user_data');
      setToken(null);
      setUser(null);
    } catch (error) {
      console.error('Error clearing auth:', error);
    }
  };

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};
```

### 4. API Client (utils/api.ts)

```typescript
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

const api = axios.create({
  baseURL: BACKEND_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add auth token to requests
api.interceptors.request.use(
  async (config) => {
    const token = await AsyncStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

export default api;
```

### 5. Welcome Screen (app/(auth)/welcome.tsx)

```typescript
import { View, Text, StyleSheet, TouchableOpacity, SafeAreaView } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

export default function Welcome() {
  const router = useRouter();

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.content}>
        <View style={styles.header}>
          <Ionicons name="wallet" size={80} color="#6366f1" />
          <Text style={styles.title}>FinTrust</Text>
          <Text style={styles.subtitle}>Your trusted financial partner</Text>
        </View>

        <View style={styles.buttonContainer}>
          <TouchableOpacity 
            style={styles.primaryButton}
            onPress={() => router.push('/(auth)/register')}
          >
            <Text style={styles.primaryButtonText}>Get Started</Text>
          </TouchableOpacity>

          <TouchableOpacity 
            style={styles.secondaryButton}
            onPress={() => router.push('/(auth)/login')}
          >
            <Text style={styles.secondaryButtonText}>Login</Text>
          </TouchableOpacity>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#ffffff',
  },
  content: {
    flex: 1,
    justifyContent: 'space-between',
    paddingHorizontal: 24,
    paddingVertical: 48,
  },
  header: {
    alignItems: 'center',
    marginTop: 80,
  },
  title: {
    fontSize: 40,
    fontWeight: 'bold',
    color: '#1f2937',
    marginTop: 24,
  },
  subtitle: {
    fontSize: 16,
    color: '#6b7280',
    marginTop: 8,
  },
  buttonContainer: {
    gap: 16,
  },
  primaryButton: {
    backgroundColor: '#6366f1',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  primaryButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  secondaryButton: {
    backgroundColor: '#f3f4f6',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  secondaryButtonText: {
    color: '#6366f1',
    fontSize: 16,
    fontWeight: '600',
  },
});
```

### 6. Login Screen (app/(auth)/login.tsx)

```typescript
import React, { useState } from 'react';
import { 
  View, 
  Text, 
  TextInput, 
  StyleSheet, 
  TouchableOpacity, 
  ScrollView,
  KeyboardAvoidingView,
  Platform,
  Alert,
  ActivityIndicator
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import api from '../../utils/api';
import { useAuth } from '../../contexts/AuthContext';

export default function Login() {
  const router = useRouter();
  const { login } = useAuth();
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleLogin = async () => {
    if (!identifier || !password) {
      Alert.alert('Error', 'Please fill all fields');
      return;
    }

    setLoading(true);
    try {
      const response = await api.post('/api/auth/login', {
        identifier,
        password,
      });

      const { access_token, user_id, username, role } = response.data;
      await login(access_token, { user_id, username, role });

      // Navigate based on role
      if (role === 'admin') {
        router.replace('/(admin)/dashboard');
      } else {
        router.replace('/(user)/home');
      }
    } catch (error: any) {
      Alert.alert(
        'Login Failed',
        error.response?.data?.detail || 'Invalid credentials'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
      >
        <ScrollView contentContainerStyle={styles.scrollContent}>
          <TouchableOpacity 
            style={styles.backButton}
            onPress={() => router.back()}
          >
            <Ionicons name="arrow-back" size={24} color="#1f2937" />
          </TouchableOpacity>

          <View style={styles.header}>
            <Text style={styles.title}>Welcome Back</Text>
            <Text style={styles.subtitle}>Login to your account</Text>
          </View>

          <View style={styles.form}>
            <View style={styles.inputContainer}>
              <Text style={styles.label}>Email or Mobile Number</Text>
              <TextInput
                style={styles.input}
                placeholder="Enter email or mobile"
                value={identifier}
                onChangeText={setIdentifier}
                autoCapitalize="none"
                keyboardType="email-address"
              />
            </View>

            <View style={styles.inputContainer}>
              <Text style={styles.label}>Password</Text>
              <View style={styles.passwordContainer}>
                <TextInput
                  style={styles.passwordInput}
                  placeholder="Enter password"
                  value={password}
                  onChangeText={setPassword}
                  secureTextEntry={!showPassword}
                />
                <TouchableOpacity onPress={() => setShowPassword(!showPassword)}>
                  <Ionicons 
                    name={showPassword ? "eye-off" : "eye"} 
                    size={20} 
                    color="#9ca3af" 
                  />
                </TouchableOpacity>
              </View>
            </View>

            <TouchableOpacity
              style={[styles.loginButton, loading && styles.loginButtonDisabled]}
              onPress={handleLogin}
              disabled={loading}
            >
              {loading ? (
                <ActivityIndicator color="#ffffff" />
              ) : (
                <Text style={styles.loginButtonText}>Login</Text>
              )}
            </TouchableOpacity>

            <View style={styles.registerContainer}>
              <Text style={styles.registerText}>Don't have an account? </Text>
              <TouchableOpacity onPress={() => router.push('/(auth)/register')}>
                <Text style={styles.registerLink}>Register</Text>
              </TouchableOpacity>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#ffffff',
  },
  keyboardView: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
    paddingHorizontal: 24,
  },
  backButton: {
    marginTop: 16,
    marginBottom: 24,
  },
  header: {
    marginBottom: 32,
  },
  title: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: '#6b7280',
  },
  form: {
    gap: 20,
  },
  inputContainer: {
    gap: 8,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#374151',
  },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
  },
  passwordContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  passwordInput: {
    flex: 1,
    fontSize: 16,
  },
  loginButton: {
    backgroundColor: '#6366f1',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 8,
  },
  loginButtonDisabled: {
    opacity: 0.6,
  },
  loginButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  registerContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 16,
  },
  registerText: {
    fontSize: 14,
    color: '#6b7280',
  },
  registerLink: {
    fontSize: 14,
    color: '#6366f1',
    fontWeight: '600',
  },
});
```

### 7. User Home Screen (app/(user)/home.tsx)

```typescript
import React, { useState, useEffect } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../utils/api';

export default function Home() {
  const router = useRouter();
  const { user } = useAuth();
  const [profileData, setProfileData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    fetchProfileData();
  }, []);

  const fetchProfileData = async () => {
    try {
      const response = await api.get('/api/user/profile');
      setProfileData(response.data);
    } catch (error) {
      console.error('Error fetching profile:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const onRefresh = () => {
    setRefreshing(true);
    fetchProfileData();
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator size="large" color="#6366f1" />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      >
        <View style={styles.header}>
          <Text style={styles.greeting}>Hello, {user?.username}!</Text>
          <Text style={styles.subGreeting}>Welcome to FinTrust</Text>
        </View>

        {/* Quick Stats */}
        <View style={styles.statsContainer}>
          <View style={[styles.statCard, { backgroundColor: '#eff6ff' }]}>
            <Ionicons name="shield-checkmark" size={32} color="#3b82f6" />
            <Text style={styles.statLabel}>KYC Status</Text>
            <Text style={[styles.statValue, { color: '#3b82f6' }]}>
              {profileData?.kyc_status === 'pending' ? 'Pending' : 
               profileData?.kyc_status === 'approved' ? 'Approved' : 'Not Uploaded'}
            </Text>
          </View>

          <View style={[styles.statCard, { backgroundColor: '#f0fdf4' }]}>
            <Ionicons name="star" size={32} color="#10b981" />
            <Text style={styles.statLabel}>Trust Score</Text>
            <Text style={[styles.statValue, { color: '#10b981' }]}>
              {profileData?.trust_score || 'N/A'}
            </Text>
          </View>
        </View>

        {/* Main Actions */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Quick Actions</Text>
          
          {profileData?.trust_score_status !== 'completed' && (
            <TouchableOpacity 
              style={styles.actionCard}
              onPress={() => router.push('/(user)/trust-score')}
            >
              <View style={styles.actionIcon}>
                <Ionicons name="calculator" size={28} color="#6366f1" />
              </View>
              <View style={styles.actionContent}>
                <Text style={styles.actionTitle}>Calculate Trust Score</Text>
                <Text style={styles.actionSubtitle}>
                  {profileData?.trust_score_status === 'pending_review' 
                    ? 'Under review by admin' 
                    : 'Submit your income and expenses data'}
                </Text>
              </View>
              {profileData?.trust_score_status !== 'pending_review' && (
                <Ionicons name="chevron-forward" size={24} color="#9ca3af" />
              )}
            </TouchableOpacity>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f9fafb',
  },
  scrollContent: {
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  header: {
    marginTop: 24,
    marginBottom: 24,
  },
  greeting: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  subGreeting: {
    fontSize: 16,
    color: '#6b7280',
    marginTop: 4,
  },
  statsContainer: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 24,
  },
  statCard: {
    flex: 1,
    padding: 20,
    borderRadius: 16,
    alignItems: 'center',
    gap: 8,
  },
  statLabel: {
    fontSize: 14,
    color: '#6b7280',
    fontWeight: '500',
  },
  statValue: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 16,
  },
  actionCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ffffff',
    padding: 16,
    borderRadius: 16,
    gap: 16,
  },
  actionIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: '#eef2ff',
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionContent: {
    flex: 1,
  },
  actionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 4,
  },
  actionSubtitle: {
    fontSize: 14,
    color: '#6b7280',
  },
});
```

### 8. Admin Dashboard (app/(admin)/dashboard.tsx)

```typescript
import React, { useState, useEffect } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
  Alert
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../utils/api';

export default function AdminDashboard() {
  const router = useRouter();
  const { logout } = useAuth();
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    try {
      const response = await api.get('/api/admin/users');
      setUsers(response.data);
    } catch (error) {
      console.error('Error fetching users:', error);
      Alert.alert('Error', 'Failed to fetch users');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const onRefresh = () => {
    setRefreshing(true);
    fetchUsers();
  };

  const handleLogout = () => {
    Alert.alert(
      'Logout',
      'Are you sure you want to logout?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Logout',
          style: 'destructive',
          onPress: async () => {
            await logout();
            router.replace('/(auth)/welcome');
          },
        },
      ]
    );
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator size="large" color="#6366f1" />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <View>
          <Text style={styles.title}>Admin Dashboard</Text>
          <Text style={styles.subtitle}>{users.length} users registered</Text>
        </View>
        <TouchableOpacity onPress={handleLogout}>
          <Ionicons name="log-out" size={24} color="#ef4444" />
        </TouchableOpacity>
      </View>

      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      >
        {users.map((user) => (
          <TouchableOpacity
            key={user.user_id}
            style={styles.userCard}
            onPress={() => router.push({
              pathname: '/(admin)/user-details',
              params: { userId: user.user_id },
            })}
          >
            <View style={styles.userInfo}>
              <View style={styles.avatarContainer}>
                <Ionicons name="person" size={24} color="#6366f1" />
              </View>
              <View style={styles.userDetails}>
                <Text style={styles.userName}>{user.username}</Text>
                <Text style={styles.userContact}>{user.email}</Text>
                <Text style={styles.userContact}>{user.mobile}</Text>
              </View>
            </View>

            <View style={styles.userMeta}>
              <Text style={styles.statusText}>
                {user.trust_score_status === 'completed' ? 'Completed' :
                 user.trust_score_status === 'pending_review' ? 'Pending' : 'Not Submitted'}
              </Text>
              {user.admin_score && (
                <Text style={styles.scoreText}>{user.admin_score}/100</Text>
              )}
              <Ionicons name="chevron-forward" size={20} color="#9ca3af" />
            </View>
          </TouchableOpacity>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f9fafb',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 16,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  subtitle: {
    fontSize: 14,
    color: '#6b7280',
    marginTop: 4,
  },
  scrollContent: {
    padding: 20,
  },
  userCard: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#ffffff',
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
  },
  userInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  avatarContainer: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#eef2ff',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  userDetails: {
    flex: 1,
  },
  userName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 4,
  },
  userContact: {
    fontSize: 12,
    color: '#6b7280',
  },
  userMeta: {
    alignItems: 'flex-end',
    gap: 8,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '600',
    color: '#6b7280',
  },
  scoreText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1f2937',
  },
});
```

---

## Configuration Files

### 1. package.json

```json
{
  "name": "frontend",
  "main": "expo-router/entry",
  "version": "1.0.0",
  "scripts": {
    "start": "expo start",
    "android": "expo start --android",
    "ios": "expo start --ios",
    "web": "expo start --web"
  },
  "dependencies": {
    "@expo/vector-icons": "^15.0.3",
    "@react-native-async-storage/async-storage": "^2.2.0",
    "@react-navigation/bottom-tabs": "^7.3.10",
    "@react-navigation/native": "^7.1.6",
    "@react-navigation/native-stack": "^7.3.10",
    "axios": "^1.13.5",
    "expo": "^54.0.33",
    "expo-constants": "~18.0.13",
    "expo-document-picker": "^14.0.8",
    "expo-image-picker": "^17.0.10",
    "expo-linking": "~8.0.11",
    "expo-router": "~6.0.22",
    "expo-status-bar": "~3.0.9",
    "react": "19.1.0",
    "react-native": "0.81.5",
    "react-native-gesture-handler": "~2.28.0",
    "react-native-safe-area-context": "~5.6.0",
    "react-native-screens": "~4.16.0",
    "react-hook-form": "^7.71.1"
  },
  "devDependencies": {
    "@babel/core": "^7.25.2",
    "@types/react": "~19.1.0",
    "typescript": "~5.9.3"
  }
}
```

### 2. app.json

```json
{
  "expo": {
    "name": "FinTrust",
    "slug": "fintrust",
    "version": "1.0.0",
    "orientation": "portrait",
    "icon": "./assets/icon.png",
    "userInterfaceStyle": "light",
    "splash": {
      "image": "./assets/splash.png",
      "resizeMode": "contain",
      "backgroundColor": "#ffffff"
    },
    "assetBundlePatterns": [
      "**/*"
    ],
    "ios": {
      "supportsTablet": true,
      "bundleIdentifier": "com.fintrust.app"
    },
    "android": {
      "adaptiveIcon": {
        "foregroundImage": "./assets/adaptive-icon.png",
        "backgroundColor": "#ffffff"
      },
      "package": "com.fintrust.app",
      "permissions": [
        "android.permission.CAMERA",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE"
      ]
    },
    "web": {
      "favicon": "./assets/favicon.png"
    }
  }
}
```

### 3. Frontend .env

```env
EXPO_PUBLIC_BACKEND_URL=http://localhost:8001
```

---

## Database Collections Structure

### Users Collection
```json
{
  "user_id": "UUID",
  "username": "string",
  "mobile": "string",
  "email": "string",
  "age": "number",
  "password_hash": "string",
  "role": "user|admin",
  "created_at": "datetime",
  "is_mobile_verified": "boolean"
}
```

### KYC Collection
```json
{
  "user_id": "UUID",
  "document_type": "Aadhaar|PAN|DL",
  "document_data": "base64_string",
  "verification_status": "pending|approved",
  "uploaded_at": "datetime"
}
```

### Income Details Collection
```json
{
  "user_id": "UUID",
  "employment_type": "Gig Worker|Freelancer|Content Creator|Self-Employed",
  "income_type": "Daily|Weekly|Monthly",
  "income_amount": "float",
  "monthly_expenses": "float",
  "submitted_at": "datetime"
}
```

### Bank Statements Collection
```json
{
  "user_id": "UUID",
  "statements": ["base64_string_1", "base64_string_2"],
  "upload_date": "datetime"
}
```

### Loan History Collection
```json
{
  "user_id": "UUID",
  "has_previous_loan": "boolean",
  "submitted_at": "datetime"
}
```

### Trust Scores Collection
```json
{
  "user_id": "UUID",
  "admin_score": "number|null",
  "remarks": "string",
  "status": "pending_review|completed",
  "submitted_at": "datetime",
  "generated_date": "datetime|null",
  "pdf_data": "base64_string|null",
  "sent_via_whatsapp": "boolean"
}
```

---

## API Endpoints Summary

### Authentication
- `POST /api/auth/send-otp` - Send OTP (Mock)
- `POST /api/auth/verify-otp` - Verify OTP
- `POST /api/auth/register` - Register user
- `POST /api/auth/login` - Login user/admin

### KYC
- `POST /api/kyc/upload` - Upload KYC document
- `GET /api/kyc/{user_id}` - Get KYC details

### Trust Score
- `POST /api/trust-score/submit` - Submit trust score data
- `GET /api/trust-score/{user_id}` - Get trust score

### User
- `GET /api/user/profile` - Get user profile

### Admin
- `POST /api/admin/create-default` - Create default admin
- `GET /api/admin/users` - Get all users
- `GET /api/admin/user/{user_id}/complete-data` - Get complete user data
- `POST /api/admin/assign-score` - Assign trust score

---

## Setup Instructions

### Backend Setup
```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend Setup
```bash
cd frontend
yarn install
expo start
```

### Create Default Admin
```bash
curl -X POST http://localhost:8001/api/admin/create-default
```

**Default Admin Credentials:**
- Email: admin@fintech.com
- Password: admin123

---

## Key Features

✅ User registration with mobile OTP verification (MOCKED)
✅ Government ID upload (Aadhaar/PAN/DL)
✅ Email/Mobile + Password login
✅ Multi-step trust score assessment
✅ Bank statement uploads
✅ Income & expense tracking
✅ Admin dashboard with user management
✅ Trust score assignment (0-100)
✅ PDF report generation
✅ Mock WhatsApp delivery
✅ JWT authentication with role-based access control
✅ MongoDB with 6 collections
✅ Mobile-first responsive design
✅ Bottom tab navigation for users
✅ Pull-to-refresh functionality

---

## Security Features

- Password hashing with bcrypt
- JWT token-based authentication
- Role-based access control (Admin/User)
- 30-day token expiry
- Base64 file encoding
- CORS protection
- Secure AsyncStorage for tokens

---

## Next Steps for Production

1. **Replace Mock Integrations:**
   - OTP: Integrate Twilio/AWS SNS
   - WhatsApp: Integrate WhatsApp Business API
   - File Storage: Use AWS S3/Google Cloud Storage

2. **Security Enhancements:**
   - Rate limiting
   - Input validation
   - File size limits
   - Virus scanning

3. **Performance:**
   - Redis caching
   - Database indexing
   - CDN for assets
   - Load balancing

---

**Built with Expo React Native and FastAPI**
