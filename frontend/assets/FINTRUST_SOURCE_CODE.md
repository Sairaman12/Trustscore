# FinTrust - Complete Source Code
## Fintech Trust Score Application

---

## Backend - server.py
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
import requests
import boto3
from botocore.client import Config
import random

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file (for local development)
ROOT_DIR = Path(__file__).parent
env_file = ROOT_DIR / '.env'
if env_file.exists():
    load_dotenv(env_file)
    logger.info(f"Loaded .env from {env_file}")
else:
    logger.info("No .env file found, using system environment variables")

# MongoDB Atlas Connection - Try multiple sources for the connection string
mongo_url = os.environ.get('MONGO_URL') or os.environ.get('MONGODB_URI') or os.environ.get('DATABASE_URL')

# Hardcode the production MongoDB Atlas URL as fallback for deployment
if not mongo_url or mongo_url == "mongodb://localhost:27017":
    mongo_url = "mongodb+srv://sairamanakula944:sairaman8919@trustscore.1ruyddz.mongodb.net/?appName=trustscore"
    logger.warning("Using hardcoded MongoDB Atlas URL - MONGO_URL env var not properly set")

logger.info(f"Connecting to MongoDB: {mongo_url[:50]}...")

client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'trustscore')]
logger.info(f"Using database: {os.environ.get('DB_NAME', 'trustscore')}")

# JWT Settings - Secret key is required for security
SECRET_KEY = os.environ.get('JWT_SECRET_KEY')
if not SECRET_KEY:
    SECRET_KEY = "fintech-production-secret-key-2025-auto-generated"
    logging.warning("JWT_SECRET_KEY not set, using default. Set this in production!")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30 days

# WhatsApp Business API Configuration
WHATSAPP_ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
WHATSAPP_PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages" if WHATSAPP_PHONE_NUMBER_ID else None

# Cloudflare R2 Storage Configuration (S3-compatible)
R2_CONFIGURED = False
r2_client = None
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL')

if os.getenv('R2_ENDPOINT_URL') and os.getenv('R2_ACCESS_KEY_ID'):
    try:
        r2_client = boto3.client(
            's3',
            endpoint_url=os.getenv('R2_ENDPOINT_URL'),
            aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
            config=Config(signature_version='s3v4'),
            region_name='auto'
        )
        R2_CONFIGURED = True
        logging.info("Cloudflare R2 configured successfully")
    except Exception as e:
        logging.warning(f"R2 configuration failed: {e}")

# Create the main app
app = FastAPI(title="FinTrust Production API", version="1.0.0")
api_router = APIRouter(prefix="/api")
security = HTTPBearer()

# ============= ROOT ENDPOINT =============
@app.get("/")
async def root():
    """Root endpoint for health checks and service discovery"""
    return {
        "service": "FinTrust API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "api": "/api"
    }

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

def get_file_extension_from_content_type(content_type: str) -> str:
    """Get file extension from content type"""
    extension_map = {
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'application/pdf': '.pdf',
    }
    return extension_map.get(content_type, '.bin')

def upload_to_r2(file_data: str, file_name: str, content_type: str = 'application/octet-stream') -> str:
    """Upload base64 file to Cloudflare R2 and return public URL"""
    if not R2_CONFIGURED:
        logger.warning("R2 not configured, storing data reference only")
        return f"local://{file_name}"
    
    try:
        detected_content_type = content_type
        
        # Handle base64 data - strip data URL prefix if present
        # e.g., "data:image/jpeg;base64,/9j/4AAQ..." -> "/9j/4AAQ..."
        if ',' in file_data and ';base64,' in file_data:
            # Extract content type from data URL
            header = file_data.split(',')[0]
            if 'image/jpeg' in header or 'image/jpg' in header:
                detected_content_type = 'image/jpeg'
            elif 'image/png' in header:
                detected_content_type = 'image/png'
            elif 'image/gif' in header:
                detected_content_type = 'image/gif'
            elif 'image/webp' in header:
                detected_content_type = 'image/webp'
            elif 'application/pdf' in header:
                detected_content_type = 'application/pdf'
            # Get the actual base64 data after the comma
            file_data = file_data.split(',')[1]
        
        # Update file extension based on detected content type
        base_name = file_name.rsplit('.', 1)[0] if '.' in file_name else file_name
        correct_extension = get_file_extension_from_content_type(detected_content_type)
        file_name = f"{base_name}{correct_extension}"
        
        # Decode base64
        file_bytes = base64.b64decode(file_data)
        
        # Upload to R2
        r2_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=file_name,
            Body=file_bytes,
            ContentType=detected_content_type
        )
        
        # Return public URL
        public_url = f"{R2_PUBLIC_URL}/{file_name}"
        logger.info(f"File uploaded to R2: {public_url}, size: {len(file_bytes)} bytes, type: {detected_content_type}")
        return public_url
    except Exception as e:
        logger.error(f"R2 Upload Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

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

def send_whatsapp_document(mobile: str, pdf_base64: str, filename: str = "trust_score_report.pdf") -> bool:
    """Send PDF via WhatsApp Business API"""
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_API_URL:
        logger.warning("WhatsApp not configured, skipping message")
        return False
    
    try:
        # First, upload PDF to R2 to get a public URL
        pdf_filename = f"reports/{uuid.uuid4()}_{filename}"
        pdf_url = upload_to_r2(pdf_base64, pdf_filename, 'application/pdf')
        
        # Format phone number (ensure country code for India)
        clean_mobile = mobile.replace('+', '').replace(' ', '')
        if len(clean_mobile) == 10:
            clean_mobile = f"91{clean_mobile}"
        
        # Send via WhatsApp Business API
        headers = {
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_mobile,
            "type": "document",
            "document": {
                "link": pdf_url,
                "filename": filename,
                "caption": "Your Trust Score Report from FinTrust"
            }
        }
        
        response = requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
        
        if response.status_code == 200:
            logger.info(f"WhatsApp message sent successfully to {clean_mobile}")
            return True
        else:
            logger.error(f"WhatsApp API Error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"WhatsApp Send Error: {str(e)}")
        return False

# ============= ROUTES =============

@api_router.get("/")
async def root():
    return {"message": "FinTrust Production API is running", "version": "1.0.0"}

@api_router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test MongoDB connection
        await db.command('ping')
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    # Get collection stats
    collections = await db.list_collection_names()
    
    return {
        "status": "healthy",
        "service": "FinTrust API",
        "version": "1.0.0",
        "database": db_status,
        "database_name": db.name,
        "collections": collections,
        "r2_storage": "configured" if R2_CONFIGURED else "not_configured",
        "whatsapp": "configured" if WHATSAPP_ACCESS_TOKEN else "not_configured"
    }

@api_router.get("/debug/db-stats")
async def debug_db_stats():
    """Debug endpoint to check database statistics"""
    try:
        collections = await db.list_collection_names()
        stats = {}
        for coll in collections:
            count = await db[coll].count_documents({})
            stats[coll] = count
        
        return {
            "database": db.name,
            "mongo_url_prefix": mongo_url[:60] + "..." if len(mongo_url) > 60 else mongo_url,
            "collections": stats
        }
    except Exception as e:
        return {"error": str(e)}

# ===== AUTHENTICATION ROUTES =====

@api_router.post("/auth/send-otp")
async def send_otp(request: OTPRequest):
    """Send OTP - Store in MongoDB for persistence across container restarts"""
    otp = str(random.randint(100000, 999999))
    
    # Store OTP in MongoDB for persistence
    otp_doc = {
        "mobile": request.mobile,
        "otp": otp,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(minutes=5)
    }
    
    # Upsert - replace existing OTP for this mobile
    await db.otp_codes.update_one(
        {"mobile": request.mobile},
        {"$set": otp_doc},
        upsert=True
    )
    
    # TODO: Integrate real SMS service (Twilio, Firebase Phone Auth, etc.)
    logger.info(f"OTP for {request.mobile}: {otp}")
    
    return {
        "success": True,
        "message": "OTP sent successfully",
        "mock_otp": otp,  # Remove in production when SMS is integrated
        "note": "OTP expires in 5 minutes"
    }

@api_router.post("/auth/verify-otp")
async def verify_otp(request: OTPVerify):
    """Verify OTP from MongoDB storage"""
    # Get OTP from MongoDB
    stored_data = await db.otp_codes.find_one({"mobile": request.mobile})
    
    if not stored_data:
        raise HTTPException(status_code=400, detail="OTP not found. Please request a new OTP.")
    
    if stored_data["expires_at"] < datetime.utcnow():
        # Delete expired OTP
        await db.otp_codes.delete_one({"mobile": request.mobile})
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new OTP.")
    
    if stored_data["otp"] != request.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    
    # Remove OTP after successful verification
    await db.otp_codes.delete_one({"mobile": request.mobile})
    return {"success": True, "message": "OTP verified successfully"}

@api_router.post("/auth/register", response_model=TokenResponse)
async def register_user(user: UserRegister):
    # Check if user already exists
    existing_user = await db.users.find_one(
        {"$or": [{"email": user.email}, {"mobile": user.mobile}]},
        {"_id": 1}
    )
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
        "is_mobile_verified": True
    }
    
    await db.users.insert_one(user_doc)
    logger.info(f"New user registered: {user.email}")
    
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
    user = await db.users.find_one({
        "$or": [{"email": credentials.identifier}, {"mobile": credentials.identifier}]
    })
    
    if not user or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token({"sub": user["user_id"], "role": user["role"]})
    logger.info(f"User logged in: {credentials.identifier}")
    
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
    
    # Upload document to R2
    doc_filename = f"kyc/{kyc.user_id}_{uuid.uuid4()}_{kyc.document_type}.jpg"
    doc_url = upload_to_r2(kyc.document_data, doc_filename, 'image/jpeg')
    
    kyc_doc = {
        "user_id": kyc.user_id,
        "document_type": kyc.document_type,
        "document_url": doc_url,
        "verification_status": "pending",
        "uploaded_at": datetime.utcnow()
    }
    
    await db.kyc.update_one(
        {"user_id": kyc.user_id},
        {"$set": kyc_doc},
        upsert=True
    )
    
    logger.info(f"KYC uploaded for user: {kyc.user_id}")
    return {"success": True, "message": "KYC document uploaded successfully", "document_url": doc_url}

@api_router.get("/kyc/{user_id}")
async def get_kyc(user_id: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin" and current_user["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    kyc = await db.kyc.find_one({"user_id": user_id})
    if kyc and "_id" in kyc:
        del kyc["_id"]
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
    
    # Upload bank statements to R2
    statement_urls = []
    for idx, statement_base64 in enumerate(data.bank_statements):
        if statement_base64:  # Only upload if data exists
            statement_filename = f"bank_statements/{data.user_id}_{uuid.uuid4()}_statement_{idx}.pdf"
            statement_url = upload_to_r2(statement_base64, statement_filename, 'application/pdf')
            statement_urls.append(statement_url)
    
    bank_doc = {
        "user_id": data.user_id,
        "statement_urls": statement_urls,
        "upload_date": datetime.utcnow()
    }
    await db.bank_statements.update_one(
        {"user_id": data.user_id},
        {"$set": bank_doc},
        upsert=True
    )
    
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
    
    trust_score_doc = {
        "user_id": data.user_id,
        "admin_score": None,
        "remarks": "",
        "status": "pending_review",
        "submitted_at": datetime.utcnow(),
        "generated_date": None,
        "pdf_url": None,
        "sent_via_whatsapp": False
    }
    await db.trust_scores.update_one(
        {"user_id": data.user_id},
        {"$set": trust_score_doc},
        upsert=True
    )
    
    logger.info(f"Trust score data submitted for user: {data.user_id}")
    return {"success": True, "message": "Trust score data submitted for review"}

@api_router.get("/trust-score/{user_id}")
async def get_trust_score(user_id: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin" and current_user["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    score = await db.trust_scores.find_one({"user_id": user_id})
    if score and "_id" in score:
        del score["_id"]
    return score

# ===== ADMIN ROUTES =====

@api_router.get("/admin/users")
async def get_all_users(current_admin: dict = Depends(get_current_admin)):
    # Fetch users with projection (exclude sensitive data)
    users = await db.users.find(
        {"role": "user"},
        {"_id": 0, "password_hash": 0}
    ).to_list(1000)
    
    # Batch query trust scores to avoid N+1 problem
    user_ids = [user["user_id"] for user in users]
    trust_scores_cursor = db.trust_scores.find(
        {"user_id": {"$in": user_ids}},
        {"_id": 0, "user_id": 1, "status": 1, "admin_score": 1}
    )
    trust_scores_dict = {ts["user_id"]: ts async for ts in trust_scores_cursor}
    
    # Attach trust score data to users
    for user in users:
        trust_score = trust_scores_dict.get(user["user_id"])
        user["trust_score_status"] = trust_score.get("status") if trust_score else "not_submitted"
        user["admin_score"] = trust_score.get("admin_score") if trust_score else None
    
    return users

@api_router.get("/admin/user/{user_id}/complete-data")
async def get_user_complete_data(user_id: str, current_admin: dict = Depends(get_current_admin)):
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if "_id" in user:
        del user["_id"]
    if "password_hash" in user:
        del user["password_hash"]
    
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
    user = await db.users.find_one({"user_id": score_data.user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate PDF
    pdf_base64 = generate_trust_score_pdf(user, score_data.admin_score, score_data.remarks)
    
    # Upload PDF to R2
    pdf_filename = f"reports/{score_data.user_id}_{uuid.uuid4()}_trust_score.pdf"
    pdf_url = upload_to_r2(pdf_base64, pdf_filename, 'application/pdf')
    
    # Send via WhatsApp
    whatsapp_sent = send_whatsapp_document(user["mobile"], pdf_base64, "trust_score_report.pdf")
    
    # Update trust score
    update_doc = {
        "admin_score": score_data.admin_score,
        "remarks": score_data.remarks,
        "status": "completed",
        "generated_date": datetime.utcnow(),
        "pdf_url": pdf_url,
        "sent_via_whatsapp": whatsapp_sent
    }
    
    await db.trust_scores.update_one(
        {"user_id": score_data.user_id},
        {"$set": update_doc}
    )
    
    logger.info(f"Trust score assigned for user: {score_data.user_id}, Score: {score_data.admin_score}")
    
    return {
        "success": True,
        "message": "Trust score assigned and PDF sent via WhatsApp" if whatsapp_sent else "Trust score assigned (WhatsApp delivery pending)",
        "pdf_url": pdf_url,
        "whatsapp_sent": whatsapp_sent
    }

# ===== USER PROFILE ROUTES =====

@api_router.get("/user/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    
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
    logger.info("Default admin created")
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

@app.on_event("startup")
async def startup_event():
    logger.info("FinTrust Production API starting up...")
    logger.info(f"Database: {os.environ.get('DB_NAME', 'trustscore')}")
    logger.info(f"R2 Storage: {'Configured' if R2_CONFIGURED else 'Not configured'}")
    logger.info(f"WhatsApp: {'Configured' if WHATSAPP_ACCESS_TOKEN else 'Not configured'}")
    
    # Create TTL index on otp_codes collection to auto-delete expired OTPs
    try:
        await db.otp_codes.create_index("expires_at", expireAfterSeconds=0)
        logger.info("OTP TTL index created/verified")
    except Exception as e:
        logger.warning(f"Could not create OTP TTL index: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    logger.info("Database connection closed")
```

## Backend - .env
```
# Production Environment Variables
MONGO_URL=mongodb+srv://sairamanakula944:sairaman8919@trustscore.1ruyddz.mongodb.net/?appName=trustscore
DB_NAME=trustscore
JWT_SECRET_KEY=fintech-production-secret-key-change-this-in-deployment-2025

# WhatsApp Business API (Meta Cloud API)
WHATSAPP_ACCESS_TOKEN=EAFxrN4Hz23MBQvWr4l9eo9PKibO5ikJyBc8egxILavpWrGrlkMMk7gaB378aDOKcmIxDunxKuxNtEZClFOSxg2p2XHMTBKmn319ZAZCXeZBH0XePlTsKdm6fvoSnZCuAuudmeUCHVHW65ZBSTXxDZAfDfOOTgeLZCvkrATwMcDY1xrlWOxktCpt2Aka6jvKN04iX8zZCtfwOTVucAuY90coOOsY2QVFZAxwdRcc1YT332PZCRwXPHpZAyh2B4oG3dGjrmsgtyNDeocK52r6aBFLKEukg
WHATSAPP_PHONE_NUMBER_ID=901839846356116
WHATSAPP_BUSINESS_ACCOUNT_ID=2423106781482515

# Cloudflare R2 Storage (S3-compatible)
R2_ACCESS_KEY_ID=272fc6e7f5b3fd432588acfb53b07e7b
R2_SECRET_ACCESS_KEY=0a7c7f79643486dea3947184ff0574296a2a7a3e0d114f4d3173039a095770e4
R2_BUCKET_NAME=trustscore-mvp
R2_ENDPOINT_URL=https://0e33ab516b200473997d06bab1b7f416.r2.cloudflarestorage.com
R2_PUBLIC_URL=https://0e33ab516b200473997d06bab1b7f416.r2.cloudflarestorage.com

# Firebase Configuration
FIREBASE_CONFIG_PATH=./firebase_config.json
```

## Backend - requirements.txt
```
aiohappyeyeballs==2.6.1
aiohttp==3.13.3
aiosignal==1.4.0
annotated-types==0.7.0
anyio==4.12.1
attrs==25.4.0
bcrypt==4.1.3
black==26.1.0
boto3==1.42.42
botocore==1.42.42
CacheControl==0.14.4
certifi==2026.1.4
cffi==2.0.0
charset-normalizer==3.4.4
click==8.3.1
cryptography==46.0.4
distro==1.9.0
dnspython==2.8.0
ecdsa==0.19.1
email-validator==2.3.0
emergentintegrations==0.1.0
fastapi==0.110.1
fastuuid==0.14.0
filelock==3.20.3
firebase_admin==7.1.0
flake8==7.3.0
frozenlist==1.8.0
fsspec==2026.1.0
google-ai-generativelanguage==0.6.15
google-api-core==2.29.0
google-api-python-client==2.189.0
google-auth==2.49.0.dev0
google-auth-httplib2==0.3.0
google-cloud-core==2.5.0
google-cloud-firestore==2.23.0
google-cloud-storage==3.9.0
google-crc32c==1.8.0
google-genai==1.62.0
google-generativeai==0.8.6
google-resumable-media==2.8.0
googleapis-common-protos==1.72.0
grpcio==1.76.0
grpcio-status==1.71.2
h11==0.16.0
h2==4.3.0
hf-xet==1.2.0
hpack==4.1.0
httpcore==1.0.9
httplib2==0.31.2
httpx==0.28.1
huggingface_hub==1.4.0
hyperframe==6.1.0
idna==3.11
importlib_metadata==8.7.1
iniconfig==2.3.0
isort==7.0.0
Jinja2==3.1.6
jiter==0.13.0
jmespath==1.1.0
jq==1.11.0
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
librt==0.7.8
litellm==1.80.0
markdown-it-py==4.0.0
MarkupSafe==3.0.3
mccabe==0.7.0
mdurl==0.1.2
motor==3.3.1
msgpack==1.1.2
multidict==6.7.1
mypy==1.19.1
mypy_extensions==1.1.0
numpy==2.4.2
oauthlib==3.3.1
openai==1.99.9
packaging==26.0
pandas==3.0.0
passlib==1.7.4
pathspec==1.0.4
pillow==12.1.0
platformdirs==4.5.1
pluggy==1.6.0
propcache==0.4.1
proto-plus==1.27.1
protobuf==5.29.6
pyasn1==0.6.2
pyasn1_modules==0.4.2
pycodestyle==2.14.0
pycparser==3.0
pydantic==2.12.5
pydantic_core==2.41.5
pyflakes==3.4.0
Pygments==2.19.2
PyJWT==2.11.0
pymongo==4.5.0
pyparsing==3.3.2
pytest==9.0.2
python-dateutil==2.9.0.post0
python-dotenv==1.2.1
python-jose==3.5.0
python-multipart==0.0.22
pytokens==0.4.1
PyYAML==6.0.3
referencing==0.37.0
regex==2026.1.15
reportlab==4.4.9
requests==2.32.5
requests-oauthlib==2.0.0
rich==14.3.2
rpds-py==0.30.0
rsa==4.9.1
s3transfer==0.16.0
s5cmd==0.2.0
shellingham==1.5.4
six==1.17.0
sniffio==1.3.1
starlette==0.37.2
stripe==14.3.0
tenacity==9.1.2
tiktoken==0.12.0
tokenizers==0.22.2
tqdm==4.67.3
typer==0.21.1
typer-slim==0.21.1
typing-inspection==0.4.2
typing_extensions==4.15.0
tzdata==2025.3
uritemplate==4.2.0
urllib3==2.6.3
uvicorn==0.25.0
watchfiles==1.1.1
websockets==15.0.1
yarl==1.22.0
zipp==3.23.0
```

## Frontend - app/_layout.tsx
```tsx
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

## Frontend - app/index.tsx
```tsx
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

## Frontend - contexts/AuthContext.tsx
```tsx
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

## Frontend - utils/api.ts
```ts
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

## Frontend - app/(auth)/_layout.tsx
```tsx
import { Stack } from 'expo-router';

export default function AuthLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="welcome" />
      <Stack.Screen name="login" />
      <Stack.Screen name="register" />
      <Stack.Screen name="verify-otp" />
    </Stack>
  );
}
```

## Frontend - app/(auth)/login.tsx
```tsx
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

## Frontend - app/(auth)/register.tsx
```tsx
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
import * as ImagePicker from 'expo-image-picker';
import api from '../../utils/api';

export default function Register() {
  const router = useRouter();
  const [formData, setFormData] = useState({
    username: '',
    mobile: '',
    email: '',
    age: '',
    password: '',
    confirmPassword: '',
  });
  const [governmentId, setGovernmentId] = useState<string | null>(null);
  const [documentType, setDocumentType] = useState('Aadhaar');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [otpSent, setOtpSent] = useState(false);
  const [mockOtp, setMockOtp] = useState('');

  const updateField = (field: string, value: string) => {
    setFormData({ ...formData, [field]: value });
  };

  const pickDocument = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: true,
      quality: 0.5,
      base64: true,
    });

    if (!result.canceled && result.assets[0].base64) {
      setGovernmentId(result.assets[0].base64);
      Alert.alert('Success', 'Document uploaded successfully');
    }
  };

  const sendOTP = async () => {
    if (!formData.mobile || formData.mobile.length < 10) {
      Alert.alert('Error', 'Please enter a valid mobile number');
      return;
    }

    setLoading(true);
    try {
      const response = await api.post('/api/auth/send-otp', {
        mobile: formData.mobile,
      });
      setMockOtp(response.data.mock_otp);
      setOtpSent(true);
      Alert.alert(
        'OTP Sent',
        `Mock OTP: ${response.data.mock_otp}\n\n(In production, this will be sent via SMS)`,
        [{ text: 'OK' }]
      );
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Failed to send OTP');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async () => {
    // Validation
    if (!formData.username || !formData.mobile || !formData.email || !formData.age || !formData.password) {
      Alert.alert('Error', 'Please fill all fields');
      return;
    }

    if (formData.password !== formData.confirmPassword) {
      Alert.alert('Error', 'Passwords do not match');
      return;
    }

    if (!governmentId) {
      Alert.alert('Error', 'Please upload a government ID');
      return;
    }

    if (!otpSent) {
      Alert.alert('Error', 'Please verify your mobile number first');
      return;
    }

    // Proceed to OTP verification screen
    router.push({
      pathname: '/(auth)/verify-otp',
      params: {
        ...formData,
        governmentId,
        documentType,
        mockOtp,
      },
    });
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
            <Text style={styles.title}>Create Account</Text>
            <Text style={styles.subtitle}>Register to get started</Text>
          </View>

          <View style={styles.form}>
            <View style={styles.inputContainer}>
              <Text style={styles.label}>Username</Text>
              <TextInput
                style={styles.input}
                placeholder="Enter username"
                value={formData.username}
                onChangeText={(value) => updateField('username', value)}
              />
            </View>

            <View style={styles.inputContainer}>
              <Text style={styles.label}>Mobile Number</Text>
              <View style={styles.mobileContainer}>
                <TextInput
                  style={styles.mobileInput}
                  placeholder="Enter mobile number"
                  value={formData.mobile}
                  onChangeText={(value) => updateField('mobile', value)}
                  keyboardType="phone-pad"
                  maxLength={10}
                />
                <TouchableOpacity 
                  style={[styles.otpButton, otpSent && styles.otpButtonSuccess]}
                  onPress={sendOTP}
                  disabled={loading || otpSent}
                >
                  <Text style={styles.otpButtonText}>
                    {otpSent ? 'Sent' : 'Send OTP'}
                  </Text>
                </TouchableOpacity>
              </View>
            </View>

            <View style={styles.inputContainer}>
              <Text style={styles.label}>Email Address</Text>
              <TextInput
                style={styles.input}
                placeholder="Enter email"
                value={formData.email}
                onChangeText={(value) => updateField('email', value)}
                keyboardType="email-address"
                autoCapitalize="none"
              />
            </View>

            <View style={styles.inputContainer}>
              <Text style={styles.label}>Age</Text>
              <TextInput
                style={styles.input}
                placeholder="Enter age"
                value={formData.age}
                onChangeText={(value) => updateField('age', value)}
                keyboardType="numeric"
                maxLength={2}
              />
            </View>

            <View style={styles.inputContainer}>
              <Text style={styles.label}>Government ID</Text>
              <TouchableOpacity style={styles.uploadButton} onPress={pickDocument}>
                <Ionicons 
                  name={governmentId ? "checkmark-circle" : "cloud-upload"} 
                  size={24} 
                  color={governmentId ? "#10b981" : "#6366f1"} 
                />
                <Text style={styles.uploadButtonText}>
                  {governmentId ? 'Document Uploaded' : 'Upload Aadhaar/PAN/DL'}
                </Text>
              </TouchableOpacity>
            </View>

            <View style={styles.inputContainer}>
              <Text style={styles.label}>Password</Text>
              <View style={styles.passwordContainer}>
                <TextInput
                  style={styles.passwordInput}
                  placeholder="Enter password"
                  value={formData.password}
                  onChangeText={(value) => updateField('password', value)}
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

            <View style={styles.inputContainer}>
              <Text style={styles.label}>Confirm Password</Text>
              <TextInput
                style={styles.input}
                placeholder="Re-enter password"
                value={formData.confirmPassword}
                onChangeText={(value) => updateField('confirmPassword', value)}
                secureTextEntry={!showPassword}
              />
            </View>

            <TouchableOpacity
              style={styles.registerButton}
              onPress={handleRegister}
              disabled={loading}
            >
              {loading ? (
                <ActivityIndicator color="#ffffff" />
              ) : (
                <Text style={styles.registerButtonText}>Continue</Text>
              )}
            </TouchableOpacity>

            <View style={styles.loginContainer}>
              <Text style={styles.loginText}>Already have an account? </Text>
              <TouchableOpacity onPress={() => router.push('/(auth)/login')}>
                <Text style={styles.loginLink}>Login</Text>
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
    paddingBottom: 32,
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
  mobileContainer: {
    flexDirection: 'row',
    gap: 8,
  },
  mobileInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
  },
  otpButton: {
    backgroundColor: '#6366f1',
    paddingHorizontal: 20,
    justifyContent: 'center',
    borderRadius: 12,
  },
  otpButtonSuccess: {
    backgroundColor: '#10b981',
  },
  otpButtonText: {
    color: '#ffffff',
    fontWeight: '600',
  },
  uploadButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderWidth: 2,
    borderColor: '#6366f1',
    borderStyle: 'dashed',
    borderRadius: 12,
    paddingVertical: 20,
    paddingHorizontal: 16,
    justifyContent: 'center',
  },
  uploadButtonText: {
    fontSize: 16,
    color: '#6366f1',
    fontWeight: '600',
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
  registerButton: {
    backgroundColor: '#6366f1',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 8,
  },
  registerButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  loginContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 16,
  },
  loginText: {
    fontSize: 14,
    color: '#6b7280',
  },
  loginLink: {
    fontSize: 14,
    color: '#6366f1',
    fontWeight: '600',
  },
});
```

## Frontend - app/(auth)/verify-otp.tsx
```tsx
import React, { useState } from 'react';
import { 
  View, 
  Text, 
  TextInput, 
  StyleSheet, 
  TouchableOpacity, 
  Alert,
  ActivityIndicator
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import api from '../../utils/api';
import { useAuth } from '../../contexts/AuthContext';

export default function VerifyOTP() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const { login } = useAuth();
  const [otp, setOtp] = useState('');
  const [loading, setLoading] = useState(false);

  const handleVerifyAndRegister = async () => {
    if (!otp || otp.length !== 6) {
      Alert.alert('Error', 'Please enter a valid 6-digit OTP');
      return;
    }

    setLoading(true);
    try {
      // First verify OTP
      await api.post('/api/auth/verify-otp', {
        mobile: params.mobile,
        otp,
      });

      // Then register user
      const registerResponse = await api.post('/api/auth/register', {
        username: params.username,
        mobile: params.mobile,
        email: params.email,
        age: parseInt(params.age as string),
        password: params.password,
      });

      const { access_token, user_id, username, role } = registerResponse.data;

      // Upload KYC document
      await api.post('/api/kyc/upload', {
        user_id,
        document_type: params.documentType || 'Aadhaar',
        document_data: params.governmentId,
      });

      // Login user
      await login(access_token, { user_id, username, role });

      Alert.alert(
        'Success',
        'Registration successful!',
        [{ text: 'OK', onPress: () => router.replace('/(user)/home') }]
      );
    } catch (error: any) {
      Alert.alert(
        'Error',
        error.response?.data?.detail || 'Registration failed'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <TouchableOpacity 
        style={styles.backButton}
        onPress={() => router.back()}
      >
        <Ionicons name="arrow-back" size={24} color="#1f2937" />
      </TouchableOpacity>

      <View style={styles.content}>
        <View style={styles.header}>
          <Ionicons name="lock-closed" size={60} color="#6366f1" />
          <Text style={styles.title}>Verify OTP</Text>
          <Text style={styles.subtitle}>
            Enter the 6-digit code sent to{' \n'}
            {params.mobile}
          </Text>
          {params.mockOtp && (
            <Text style={styles.mockOtpText}>Mock OTP: {params.mockOtp}</Text>
          )}
        </View>

        <View style={styles.form}>
          <TextInput
            style={styles.otpInput}
            placeholder="Enter OTP"
            value={otp}
            onChangeText={setOtp}
            keyboardType="number-pad"
            maxLength={6}
            textAlign="center"
          />

          <TouchableOpacity
            style={[styles.verifyButton, loading && styles.verifyButtonDisabled]}
            onPress={handleVerifyAndRegister}
            disabled={loading}
          >
            {loading ? (
              <ActivityIndicator color="#ffffff" />
            ) : (
              <Text style={styles.verifyButtonText}>Verify & Register</Text>
            )}
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
    paddingHorizontal: 24,
  },
  backButton: {
    marginTop: 16,
  },
  content: {
    flex: 1,
    justifyContent: 'center',
  },
  header: {
    alignItems: 'center',
    marginBottom: 48,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#1f2937',
    marginTop: 24,
  },
  subtitle: {
    fontSize: 16,
    color: '#6b7280',
    textAlign: 'center',
    marginTop: 8,
  },
  mockOtpText: {
    fontSize: 14,
    color: '#ef4444',
    fontWeight: '600',
    marginTop: 12,
    padding: 8,
    backgroundColor: '#fee2e2',
    borderRadius: 8,
  },
  form: {
    gap: 24,
  },
  otpInput: {
    borderWidth: 2,
    borderColor: '#6366f1',
    borderRadius: 12,
    paddingVertical: 20,
    fontSize: 24,
    fontWeight: '600',
    letterSpacing: 8,
  },
  verifyButton: {
    backgroundColor: '#6366f1',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  verifyButtonDisabled: {
    opacity: 0.6,
  },
  verifyButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
});
```

## Frontend - app/(auth)/welcome.tsx
```tsx
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

## Frontend - app/(user)/_layout.tsx
```tsx
import { Tabs } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

export default function UserLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: '#6366f1',
        tabBarInactiveTintColor: '#9ca3af',
        tabBarStyle: {
          paddingBottom: 8,
          paddingTop: 8,
          height: 60,
        },
      }}
    >
      <Tabs.Screen
        name="home"
        options={{
          title: 'Home',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="home" size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: 'Profile',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="person" size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="support"
        options={{
          title: 'Support',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="help-circle" size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="trust-score"
        options={{
          href: null,  // Hide from tab bar
        }}
      />
    </Tabs>
  );
}
```

## Frontend - app/(user)/home.tsx
```tsx
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

          {profileData?.trust_score_status === 'completed' && (
            <View style={[styles.actionCard, { backgroundColor: '#f0fdf4' }]}>
              <View style={[styles.actionIcon, { backgroundColor: '#dcfce7' }]}>
                <Ionicons name="checkmark-circle" size={28} color="#10b981" />
              </View>
              <View style={styles.actionContent}>
                <Text style={styles.actionTitle}>Trust Score Ready</Text>
                <Text style={styles.actionSubtitle}>
                  Your trust score is {profileData.trust_score}/100. Check your registered WhatsApp for the detailed report.
                </Text>
              </View>
            </View>
          )}
        </View>

        {/* Information Section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>How It Works</Text>
          
          <View style={styles.infoCard}>
            <View style={styles.stepContainer}>
              <View style={styles.stepNumber}>
                <Text style={styles.stepNumberText}>1</Text>
              </View>
              <View style={styles.stepContent}>
                <Text style={styles.stepTitle}>Complete Registration</Text>
                <Text style={styles.stepDescription}>Upload your government ID and verify mobile</Text>
              </View>
            </View>

            <View style={styles.stepContainer}>
              <View style={styles.stepNumber}>
                <Text style={styles.stepNumberText}>2</Text>
              </View>
              <View style={styles.stepContent}>
                <Text style={styles.stepTitle}>Submit Financial Data</Text>
                <Text style={styles.stepDescription}>Provide income details and bank statements</Text>
              </View>
            </View>

            <View style={styles.stepContainer}>
              <View style={styles.stepNumber}>
                <Text style={styles.stepNumberText}>3</Text>
              </View>
              <View style={styles.stepContent}>
                <Text style={styles.stepTitle}>Get Trust Score</Text>
                <Text style={styles.stepDescription}>Receive your score and lender recommendations</Text>
              </View>
            </View>
          </View>
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
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
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
  infoCard: {
    backgroundColor: '#ffffff',
    padding: 20,
    borderRadius: 16,
    gap: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  stepContainer: {
    flexDirection: 'row',
    gap: 16,
  },
  stepNumber: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#6366f1',
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepNumberText: {
    color: '#ffffff',
    fontWeight: 'bold',
    fontSize: 16,
  },
  stepContent: {
    flex: 1,
  },
  stepTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 4,
  },
  stepDescription: {
    fontSize: 14,
    color: '#6b7280',
  },
});
```

## Frontend - app/(user)/profile.tsx
```tsx
import React, { useState, useEffect } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  ScrollView,
  TouchableOpacity,
  Alert,
  ActivityIndicator
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../utils/api';

export default function Profile() {
  const router = useRouter();
  const { user, logout } = useAuth();
  const [profileData, setProfileData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

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
    }
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
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <View style={styles.header}>
          <Text style={styles.title}>Profile</Text>
        </View>

        {/* Profile Card */}
        <View style={styles.profileCard}>
          <View style={styles.avatarContainer}>
            <Ionicons name="person" size={40} color="#6366f1" />
          </View>
          <Text style={styles.userName}>{profileData?.user?.username}</Text>
          <Text style={styles.userEmail}>{profileData?.user?.email}</Text>
        </View>

        {/* Info Section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Personal Information</Text>
          
          <View style={styles.infoCard}>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Mobile Number</Text>
              <Text style={styles.infoValue}>{profileData?.user?.mobile}</Text>
            </View>
            
            <View style={styles.divider} />
            
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Age</Text>
              <Text style={styles.infoValue}>{profileData?.user?.age} years</Text>
            </View>
            
            <View style={styles.divider} />
            
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>KYC Status</Text>
              <View style={[
                styles.statusBadge,
                profileData?.kyc_status === 'approved' ? styles.statusSuccess : styles.statusWarning
              ]}>
                <Text style={styles.statusText}>
                  {profileData?.kyc_status || 'Pending'}
                </Text>
              </View>
            </View>
          </View>
        </View>

        {/* Trust Score Section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Trust Score</Text>
          
          <View style={styles.scoreCard}>
            <Ionicons name="star" size={48} color="#6366f1" />
            <Text style={styles.scoreValue}>
              {profileData?.trust_score ? `${profileData.trust_score}/100` : 'Not Calculated'}
            </Text>
            <Text style={styles.scoreStatus}>
              Status: {profileData?.trust_score_status === 'completed' ? 'Completed' :
                       profileData?.trust_score_status === 'pending_review' ? 'Under Review' : 'Not Submitted'}
            </Text>
          </View>
        </View>

        {/* Actions */}
        <View style={styles.section}>
          <TouchableOpacity style={styles.actionButton} onPress={handleLogout}>
            <Ionicons name="log-out" size={24} color="#ef4444" />
            <Text style={styles.actionButtonText}>Logout</Text>
          </TouchableOpacity>
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
    paddingBottom: 24,
  },
  header: {
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 16,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  profileCard: {
    backgroundColor: '#ffffff',
    marginHorizontal: 20,
    marginBottom: 24,
    padding: 24,
    borderRadius: 16,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  avatarContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#eef2ff',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  userName: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 4,
  },
  userEmail: {
    fontSize: 16,
    color: '#6b7280',
  },
  section: {
    marginBottom: 24,
    paddingHorizontal: 20,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 12,
  },
  infoCard: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 12,
  },
  infoLabel: {
    fontSize: 14,
    color: '#6b7280',
  },
  infoValue: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
  },
  divider: {
    height: 1,
    backgroundColor: '#f3f4f6',
  },
  statusBadge: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
  },
  statusSuccess: {
    backgroundColor: '#d1fae5',
  },
  statusWarning: {
    backgroundColor: '#fef3c7',
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#1f2937',
    textTransform: 'capitalize',
  },
  scoreCard: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 32,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  scoreValue: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#1f2937',
    marginTop: 16,
  },
  scoreStatus: {
    fontSize: 14,
    color: '#6b7280',
    marginTop: 8,
  },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    backgroundColor: '#ffffff',
    padding: 16,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#ef4444',
  },
  actionButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#ef4444',
  },
});
```

## Frontend - app/(user)/support.tsx
```tsx
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Linking } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';

export default function Support() {
  const contactOptions = [
    {
      icon: 'mail',
      title: 'Email Support',
      subtitle: 'support@fintrust.com',
      action: () => Linking.openURL('mailto:support@fintrust.com'),
    },
    {
      icon: 'call',
      title: 'Phone Support',
      subtitle: '+91 1800-XXX-XXXX',
      action: () => Linking.openURL('tel:+911800XXXXXXX'),
    },
    {
      icon: 'logo-whatsapp',
      title: 'WhatsApp',
      subtitle: 'Chat with us',
      action: () => Linking.openURL('https://wa.me/911800XXXXXXX'),
    },
  ];

  const faqItems = [
    {
      question: 'How is my trust score calculated?',
      answer: 'Your trust score is calculated based on your income details, monthly expenses, bank statements, and loan history. Our admin team manually reviews all submissions.',
    },
    {
      question: 'How long does verification take?',
      answer: 'Typically, verification takes 2-3 business days. You will receive your trust score report via WhatsApp once completed.',
    },
    {
      question: 'Is my data secure?',
      answer: 'Yes, all your data is encrypted and stored securely. We follow industry-standard security practices to protect your information.',
    },
    {
      question: 'Can I update my information?',
      answer: 'Currently, you can submit your information once. For updates, please contact our support team.',
    },
  ];

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <View style={styles.header}>
          <Text style={styles.title}>Support</Text>
          <Text style={styles.subtitle}>We're here to help</Text>
        </View>

        {/* Contact Options */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Contact Us</Text>
          {contactOptions.map((option, index) => (
            <TouchableOpacity
              key={index}
              style={styles.contactCard}
              onPress={option.action}
            >
              <View style={styles.contactIcon}>
                <Ionicons name={option.icon as any} size={24} color="#6366f1" />
              </View>
              <View style={styles.contactContent}>
                <Text style={styles.contactTitle}>{option.title}</Text>
                <Text style={styles.contactSubtitle}>{option.subtitle}</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color="#9ca3af" />
            </TouchableOpacity>
          ))}
        </View>

        {/* FAQ Section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Frequently Asked Questions</Text>
          {faqItems.map((item, index) => (
            <View key={index} style={styles.faqCard}>
              <Text style={styles.faqQuestion}>{item.question}</Text>
              <Text style={styles.faqAnswer}>{item.answer}</Text>
            </View>
          ))}
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
    paddingBottom: 24,
  },
  header: {
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 24,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 16,
    color: '#6b7280',
  },
  section: {
    marginBottom: 24,
    paddingHorizontal: 20,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 12,
  },
  contactCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ffffff',
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  contactIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#eef2ff',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 16,
  },
  contactContent: {
    flex: 1,
  },
  contactTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 4,
  },
  contactSubtitle: {
    fontSize: 14,
    color: '#6b7280',
  },
  faqCard: {
    backgroundColor: '#ffffff',
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  faqQuestion: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 8,
  },
  faqAnswer: {
    fontSize: 14,
    color: '#6b7280',
    lineHeight: 20,
  },
});
```

## Frontend - app/(user)/trust-score.tsx
```tsx
import React, { useState } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as DocumentPicker from 'expo-document-picker';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../utils/api';

const EMPLOYMENT_TYPES = ['Gig Worker', 'Freelancer', 'Content Creator', 'Self-Employed'];
const INCOME_TYPES = ['Daily', 'Weekly', 'Monthly'];

export default function TrustScore() {
  const router = useRouter();
  const { user } = useAuth();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  
  const [formData, setFormData] = useState({
    employment_type: '',
    income_type: '',
    income_amount: '',
    monthly_expenses: '',
    has_previous_loan: false,
  });
  const [bankStatements, setBankStatements] = useState<string[]>([]);

  const updateField = (field: string, value: any) => {
    setFormData({ ...formData, [field]: value });
  };

  const pickBankStatement = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ['image/*', 'application/pdf'],
        multiple: true,
      });

      if (!result.canceled && result.assets) {
        // Convert to base64 with data URL prefix for proper content type detection
        const base64Files: string[] = [];
        for (const asset of result.assets) {
          try {
            const response = await fetch(asset.uri);
            const blob = await response.blob();
            const reader = new FileReader();
            reader.readAsDataURL(blob);
            await new Promise((resolve, reject) => {
              reader.onloadend = () => {
                // Send full data URL (includes content type prefix)
                const base64data = reader.result as string;
                if (base64data) {
                  base64Files.push(base64data);
                }
                resolve(null);
              };
              reader.onerror = reject;
            });
          } catch (err) {
            console.error('Error reading file:', err);
          }
        }
        setBankStatements([...bankStatements, ...base64Files]);
        Alert.alert('Success', `${base64Files.length} document(s) uploaded`);
      }
    } catch (error) {
      console.error('Error picking document:', error);
      Alert.alert('Error', 'Failed to upload documents');
    }
  };

  const handleSubmit = async () => {
    // Validation
    if (!formData.employment_type || !formData.income_type || !formData.income_amount || !formData.monthly_expenses) {
      Alert.alert('Error', 'Please fill all fields');
      return;
    }

    if (bankStatements.length === 0) {
      Alert.alert('Error', 'Please upload at least one bank statement');
      return;
    }

    setLoading(true);
    try {
      await api.post('/api/trust-score/submit', {
        user_id: user?.user_id,
        employment_type: formData.employment_type,
        income_type: formData.income_type,
        income_amount: parseFloat(formData.income_amount),
        monthly_expenses: parseFloat(formData.monthly_expenses),
        has_previous_loan: formData.has_previous_loan,
        bank_statements: bankStatements,
      });

      Alert.alert(
        'Success',
        'Your trust score data has been submitted for review. You will receive your score via WhatsApp once the admin reviews your application.',
        [
          {
            text: 'OK',
            onPress: () => router.replace('/(user)/home'),
          },
        ]
      );
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Failed to submit data');
    } finally {
      setLoading(false);
    }
  };

  const renderStep = () => {
    switch (step) {
      case 1:
        return (
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Employment Type</Text>
            <Text style={styles.stepSubtitle}>Select your employment category</Text>
            
            {EMPLOYMENT_TYPES.map((type) => (
              <TouchableOpacity
                key={type}
                style={[
                  styles.optionButton,
                  formData.employment_type === type && styles.optionButtonSelected,
                ]}
                onPress={() => updateField('employment_type', type)}
              >
                <Text
                  style={[
                    styles.optionButtonText,
                    formData.employment_type === type && styles.optionButtonTextSelected,
                  ]}
                >
                  {type}
                </Text>
                {formData.employment_type === type && (
                  <Ionicons name="checkmark-circle" size={24} color="#6366f1" />
                )}
              </TouchableOpacity>
            ))}

            <TouchableOpacity
              style={[styles.nextButton, !formData.employment_type && styles.nextButtonDisabled]}
              onPress={() => setStep(2)}
              disabled={!formData.employment_type}
            >
              <Text style={styles.nextButtonText}>Next</Text>
            </TouchableOpacity>
          </View>
        );

      case 2:
        return (
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Income Details</Text>
            <Text style={styles.stepSubtitle}>Tell us about your income</Text>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Income Frequency</Text>
              <View style={styles.radioGroup}>
                {INCOME_TYPES.map((type) => (
                  <TouchableOpacity
                    key={type}
                    style={[
                      styles.radioButton,
                      formData.income_type === type && styles.radioButtonSelected,
                    ]}
                    onPress={() => updateField('income_type', type)}
                  >
                    <Text
                      style={[
                        styles.radioButtonText,
                        formData.income_type === type && styles.radioButtonTextSelected,
                      ]}
                    >
                      {type}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Income Amount (₹)</Text>
              <TextInput
                style={styles.input}
                placeholder="Enter amount"
                value={formData.income_amount}
                onChangeText={(value) => updateField('income_amount', value)}
                keyboardType="numeric"
              />
            </View>

            <View style={styles.buttonRow}>
              <TouchableOpacity style={styles.backButton} onPress={() => setStep(1)}>
                <Text style={styles.backButtonText}>Back</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.nextButton, (!formData.income_type || !formData.income_amount) && styles.nextButtonDisabled]}
                onPress={() => setStep(3)}
                disabled={!formData.income_type || !formData.income_amount}
              >
                <Text style={styles.nextButtonText}>Next</Text>
              </TouchableOpacity>
            </View>
          </View>
        );

      case 3:
        return (
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Expenses & Loan History</Text>
            <Text style={styles.stepSubtitle}>Complete your financial profile</Text>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Monthly Expenses (₹)</Text>
              <TextInput
                style={styles.input}
                placeholder="Enter monthly expenses"
                value={formData.monthly_expenses}
                onChangeText={(value) => updateField('monthly_expenses', value)}
                keyboardType="numeric"
              />
            </View>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Previous Loan History</Text>
              <View style={styles.radioGroup}>
                <TouchableOpacity
                  style={[
                    styles.radioButton,
                    formData.has_previous_loan === true && styles.radioButtonSelected,
                  ]}
                  onPress={() => updateField('has_previous_loan', true)}
                >
                  <Text
                    style={[
                      styles.radioButtonText,
                      formData.has_previous_loan === true && styles.radioButtonTextSelected,
                    ]}
                  >
                    Yes
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.radioButton,
                    formData.has_previous_loan === false && styles.radioButtonSelected,
                  ]}
                  onPress={() => updateField('has_previous_loan', false)}
                >
                  <Text
                    style={[
                      styles.radioButtonText,
                      formData.has_previous_loan === false && styles.radioButtonTextSelected,
                    ]}
                  >
                    No
                  </Text>
                </TouchableOpacity>
              </View>
            </View>

            <View style={styles.buttonRow}>
              <TouchableOpacity style={styles.backButton} onPress={() => setStep(2)}>
                <Text style={styles.backButtonText}>Back</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.nextButton, !formData.monthly_expenses && styles.nextButtonDisabled]}
                onPress={() => setStep(4)}
                disabled={!formData.monthly_expenses}
              >
                <Text style={styles.nextButtonText}>Next</Text>
              </TouchableOpacity>
            </View>
          </View>
        );

      case 4:
        return (
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Bank Statements</Text>
            <Text style={styles.stepSubtitle}>Upload statements from last 4 months</Text>

            <TouchableOpacity style={styles.uploadCard} onPress={pickBankStatement}>
              <Ionicons name="cloud-upload" size={48} color="#6366f1" />
              <Text style={styles.uploadText}>Upload Bank Statements</Text>
              <Text style={styles.uploadSubtext}>PDF or Images (last 4 months)</Text>
            </TouchableOpacity>

            {bankStatements.length > 0 && (
              <View style={styles.uploadedInfo}>
                <Ionicons name="checkmark-circle" size={24} color="#10b981" />
                <Text style={styles.uploadedText}>
                  {bankStatements.length} document(s) uploaded
                </Text>
              </View>
            )}

            <View style={styles.buttonRow}>
              <TouchableOpacity style={styles.backButton} onPress={() => setStep(3)}>
                <Text style={styles.backButtonText}>Back</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.submitButton, (loading || bankStatements.length === 0) && styles.submitButtonDisabled]}
                onPress={handleSubmit}
                disabled={loading || bankStatements.length === 0}
              >
                {loading ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <Text style={styles.submitButtonText}>Submit</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        );

      default:
        return null;
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()}>
            <Ionicons name="arrow-back" size={24} color="#1f2937" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Trust Score Assessment</Text>
          <View style={{ width: 24 }} />
        </View>

        {/* Progress Indicator */}
        <View style={styles.progressContainer}>
          {[1, 2, 3, 4].map((item) => (
            <View
              key={item}
              style={[
                styles.progressDot,
                step >= item && styles.progressDotActive,
              ]}
            />
          ))}
        </View>

        <ScrollView contentContainerStyle={styles.scrollContent}>
          {renderStep()}
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
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
  },
  progressContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 20,
  },
  progressDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#e5e7eb',
  },
  progressDotActive: {
    backgroundColor: '#6366f1',
    width: 32,
  },
  scrollContent: {
    flexGrow: 1,
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  stepContent: {
    gap: 20,
  },
  stepTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  stepSubtitle: {
    fontSize: 16,
    color: '#6b7280',
    marginBottom: 8,
  },
  optionButton: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    borderWidth: 2,
    borderColor: '#e5e7eb',
    borderRadius: 12,
  },
  optionButtonSelected: {
    borderColor: '#6366f1',
    backgroundColor: '#eef2ff',
  },
  optionButtonText: {
    fontSize: 16,
    color: '#6b7280',
    fontWeight: '500',
  },
  optionButtonTextSelected: {
    color: '#6366f1',
    fontWeight: '600',
  },
  inputGroup: {
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
  radioGroup: {
    flexDirection: 'row',
    gap: 12,
    flexWrap: 'wrap',
  },
  radioButton: {
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderWidth: 2,
    borderColor: '#e5e7eb',
    borderRadius: 24,
  },
  radioButtonSelected: {
    borderColor: '#6366f1',
    backgroundColor: '#eef2ff',
  },
  radioButtonText: {
    fontSize: 14,
    color: '#6b7280',
    fontWeight: '500',
  },
  radioButtonTextSelected: {
    color: '#6366f1',
    fontWeight: '600',
  },
  uploadCard: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: 40,
    borderWidth: 2,
    borderColor: '#6366f1',
    borderStyle: 'dashed',
    borderRadius: 16,
    gap: 12,
  },
  uploadText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#6366f1',
  },
  uploadSubtext: {
    fontSize: 14,
    color: '#6b7280',
  },
  uploadedInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 16,
    backgroundColor: '#f0fdf4',
    borderRadius: 12,
  },
  uploadedText: {
    fontSize: 16,
    color: '#10b981',
    fontWeight: '600',
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 8,
  },
  backButton: {
    flex: 1,
    paddingVertical: 16,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#e5e7eb',
    alignItems: 'center',
  },
  backButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#6b7280',
  },
  nextButton: {
    flex: 1,
    backgroundColor: '#6366f1',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  nextButtonDisabled: {
    opacity: 0.5,
  },
  nextButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  submitButton: {
    flex: 1,
    backgroundColor: '#10b981',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  submitButtonDisabled: {
    opacity: 0.5,
  },
  submitButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
});
```

## Frontend - app/(admin)/_layout.tsx
```tsx
import { Stack } from 'expo-router';

export default function AdminLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="dashboard" />
      <Stack.Screen name="user-details" />
    </Stack>
  );
}
```

## Frontend - app/(admin)/dashboard.tsx
```tsx
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

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return '#10b981';
      case 'pending_review':
        return '#f59e0b';
      default:
        return '#6b7280';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'completed':
        return 'Completed';
      case 'pending_review':
        return 'Pending Review';
      default:
        return 'Not Submitted';
    }
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
              <View
                style={[
                  styles.statusBadge,
                  { backgroundColor: `${getStatusColor(user.trust_score_status)}20` },
                ]}
              >
                <Text
                  style={[
                    styles.statusText,
                    { color: getStatusColor(user.trust_score_status) },
                  ]}
                >
                  {getStatusText(user.trust_score_status)}
                </Text>
              </View>
              {user.admin_score && (
                <View style={styles.scoreContainer}>
                  <Ionicons name="star" size={16} color="#f59e0b" />
                  <Text style={styles.scoreText}>{user.admin_score}/100</Text>
                </View>
              )}
              <Ionicons name="chevron-forward" size={20} color="#9ca3af" />
            </View>
          </TouchableOpacity>
        ))}

        {users.length === 0 && (
          <View style={styles.emptyState}>
            <Ionicons name="people" size={64} color="#d1d5db" />
            <Text style={styles.emptyText}>No users found</Text>
          </View>
        )}
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
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
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
  statusBadge: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '600',
  },
  scoreContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  scoreText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1f2937',
  },
  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
  },
  emptyText: {
    fontSize: 16,
    color: '#9ca3af',
    marginTop: 16,
  },
});
```

## Frontend - app/(admin)/user-details.tsx
```tsx
import React, { useState, useEffect } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Image
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import api from '../../utils/api';

export default function UserDetails() {
  const router = useRouter();
  const { userId } = useLocalSearchParams();
  const [userData, setUserData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [score, setScore] = useState('');
  const [remarks, setRemarks] = useState('');

  useEffect(() => {
    fetchUserData();
  }, [userId]);

  const fetchUserData = async () => {
    try {
      const response = await api.get(`/api/admin/user/${userId}/complete-data`);
      setUserData(response.data);
      
      // Pre-fill if already scored
      if (response.data.trust_score?.admin_score) {
        setScore(response.data.trust_score.admin_score.toString());
        setRemarks(response.data.trust_score.remarks || '');
      }
    } catch (error) {
      console.error('Error fetching user data:', error);
      Alert.alert('Error', 'Failed to fetch user data');
    } finally {
      setLoading(false);
    }
  };

  const handleAssignScore = async () => {
    if (!score || parseInt(score) < 0 || parseInt(score) > 100) {
      Alert.alert('Error', 'Please enter a valid score (0-100)');
      return;
    }

    if (!remarks) {
      Alert.alert('Error', 'Please enter remarks');
      return;
    }

    Alert.alert(
      'Confirm',
      'Are you sure you want to assign this trust score? A PDF report will be generated and sent to the user via WhatsApp.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Confirm',
          onPress: async () => {
            setSubmitting(true);
            try {
              await api.post('/api/admin/assign-score', {
                user_id: userId,
                admin_score: parseInt(score),
                remarks,
              });

              Alert.alert(
                'Success',
                'Trust score assigned successfully! PDF report sent via WhatsApp (Mock).',
                [
                  {
                    text: 'OK',
                    onPress: () => router.back(),
                  },
                ]
              );
            } catch (error: any) {
              Alert.alert('Error', error.response?.data?.detail || 'Failed to assign score');
            } finally {
              setSubmitting(false);
            }
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
      <KeyboardAvoidingView 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()}>
            <Ionicons name="arrow-back" size={24} color="#1f2937" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>User Details</Text>
          <View style={{ width: 24 }} />
        </View>

        <ScrollView contentContainerStyle={styles.scrollContent}>
          {/* User Info */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Personal Information</Text>
            <View style={styles.card}>
              <View style={styles.infoRow}>
                <Text style={styles.label}>Name:</Text>
                <Text style={styles.value}>{userData?.user?.username}</Text>
              </View>
              <View style={styles.infoRow}>
                <Text style={styles.label}>Email:</Text>
                <Text style={styles.value}>{userData?.user?.email}</Text>
              </View>
              <View style={styles.infoRow}>
                <Text style={styles.label}>Mobile:</Text>
                <Text style={styles.value}>{userData?.user?.mobile}</Text>
              </View>
              <View style={styles.infoRow}>
                <Text style={styles.label}>Age:</Text>
                <Text style={styles.value}>{userData?.user?.age} years</Text>
              </View>
            </View>
          </View>

          {/* KYC Document */}
          {userData?.kyc && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>KYC Document</Text>
              <View style={styles.card}>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Document Type:</Text>
                  <Text style={styles.value}>{userData.kyc.document_type}</Text>
                </View>
                {userData.kyc.document_data && (
                  <View style={styles.documentPreview}>
                    <Image
                      source={{ uri: `data:image/jpeg;base64,${userData.kyc.document_data}` }}
                      style={styles.documentImage}
                      resizeMode="contain"
                    />
                  </View>
                )}
              </View>
            </View>
          )}

          {/* Income Details */}
          {userData?.income_details && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Income Details</Text>
              <View style={styles.card}>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Employment:</Text>
                  <Text style={styles.value}>{userData.income_details.employment_type}</Text>
                </View>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Income Type:</Text>
                  <Text style={styles.value}>{userData.income_details.income_type}</Text>
                </View>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Income Amount:</Text>
                  <Text style={styles.value}>₹{userData.income_details.income_amount}</Text>
                </View>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Monthly Expenses:</Text>
                  <Text style={styles.value}>₹{userData.income_details.monthly_expenses}</Text>
                </View>
              </View>
            </View>
          )}

          {/* Loan History */}
          {userData?.loan_history && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Loan History</Text>
              <View style={styles.card}>
                <View style={styles.infoRow}>
                  <Text style={styles.label}>Previous Loan:</Text>
                  <Text style={styles.value}>
                    {userData.loan_history.has_previous_loan ? 'Yes' : 'No'}
                  </Text>
                </View>
              </View>
            </View>
          )}

          {/* Bank Statements */}
          {userData?.bank_statements && userData.bank_statements.statements && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Bank Statements</Text>
              <View style={styles.card}>
                <Text style={styles.value}>
                  {userData.bank_statements.statements.length} document(s) uploaded
                </Text>
              </View>
            </View>
          )}

          {/* Assign Trust Score */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Assign Trust Score</Text>
            <View style={styles.card}>
              <View style={styles.inputGroup}>
                <Text style={styles.label}>Trust Score (0-100)</Text>
                <TextInput
                  style={styles.input}
                  placeholder="Enter score"
                  value={score}
                  onChangeText={setScore}
                  keyboardType="numeric"
                  maxLength={3}
                  editable={!submitting}
                />
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.label}>Remarks</Text>
                <TextInput
                  style={[styles.input, styles.textArea]}
                  placeholder="Enter evaluation remarks"
                  value={remarks}
                  onChangeText={setRemarks}
                  multiline
                  numberOfLines={4}
                  textAlignVertical="top"
                  editable={!submitting}
                />
              </View>

              <TouchableOpacity
                style={[styles.submitButton, submitting && styles.submitButtonDisabled]}
                onPress={handleAssignScore}
                disabled={submitting}
              >
                {submitting ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <>
                    <Ionicons name="checkmark-circle" size={20} color="#ffffff" />
                    <Text style={styles.submitButtonText}>Assign Score & Send Report</Text>
                  </>
                )}
              </TouchableOpacity>

              {userData?.trust_score?.status === 'completed' && (
                <View style={styles.successMessage}>
                  <Ionicons name="checkmark-circle" size={20} color="#10b981" />
                  <Text style={styles.successText}>
                    Score already assigned and report sent
                  </Text>
                </View>
              )}
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
    backgroundColor: '#f9fafb',
  },
  keyboardView: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
  },
  scrollContent: {
    padding: 20,
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 12,
  },
  card: {
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6b7280',
  },
  value: {
    fontSize: 14,
    color: '#1f2937',
    flex: 1,
    textAlign: 'right',
  },
  documentPreview: {
    marginTop: 12,
    borderRadius: 8,
    overflow: 'hidden',
  },
  documentImage: {
    width: '100%',
    height: 200,
  },
  inputGroup: {
    marginBottom: 16,
  },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    marginTop: 8,
  },
  textArea: {
    minHeight: 100,
  },
  submitButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#6366f1',
    paddingVertical: 14,
    borderRadius: 8,
    marginTop: 8,
  },
  submitButtonDisabled: {
    opacity: 0.6,
  },
  submitButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  successMessage: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 16,
    padding: 12,
    backgroundColor: '#d1fae5',
    borderRadius: 8,
  },
  successText: {
    fontSize: 14,
    color: '#10b981',
    fontWeight: '500',
  },
});
```

## Frontend - package.json
```json
{
  "name": "frontend",
  "main": "expo-router/entry",
  "version": "1.0.0",
  "scripts": {
    "start": "expo start",
    "reset-project": "node ./scripts/reset-project.js",
    "android": "expo start --android",
    "ios": "expo start --ios",
    "web": "expo start --web",
    "lint": "expo lint"
  },
  "dependencies": {
    "@babel/runtime": "^7.20.6",
    "@expo/metro-runtime": "^6.1.2",
    "@expo/ngrok": "^4.1.3",
    "@expo/vector-icons": "^15.0.3",
    "@react-native-async-storage/async-storage": "^2.2.0",
    "@react-navigation/bottom-tabs": "^7.3.10",
    "@react-navigation/elements": "^2.3.8",
    "@react-navigation/native": "^7.1.6",
    "@react-navigation/native-stack": "^7.3.10",
    "axios": "^1.13.5",
    "expo": "^54.0.33",
    "expo-blur": "~15.0.8",
    "expo-constants": "~18.0.13",
    "expo-document-picker": "^14.0.8",
    "expo-font": "~14.0.11",
    "expo-haptics": "~15.0.8",
    "expo-image": "~3.0.11",
    "expo-image-picker": "^17.0.10",
    "expo-linking": "~8.0.11",
    "expo-router": "~6.0.22",
    "expo-splash-screen": "~31.0.13",
    "expo-status-bar": "~3.0.9",
    "expo-symbols": "~1.0.8",
    "expo-system-ui": "~6.0.9",
    "expo-web-browser": "~15.0.10",
    "react": "19.1.0",
    "react-dom": "19.1.0",
    "react-hook-form": "^7.71.1",
    "react-native": "0.81.5",
    "react-native-dotenv": "^3.4.11",
    "react-native-gesture-handler": "~2.28.0",
    "react-native-reanimated": "~4.1.1",
    "react-native-safe-area-context": "~5.6.0",
    "react-native-screens": "~4.16.0",
    "react-native-web": "^0.21.0",
    "react-native-webview": "13.15.0",
    "react-native-worklets": "0.5.1"
  },
  "devDependencies": {
    "@babel/core": "^7.25.2",
    "@types/react": "~19.1.0",
    "eslint": "^9.25.0",
    "eslint-config-expo": "~10.0.0",
    "typescript": "~5.9.3"
  },
  "private": true,
  "packageManager": "yarn@1.22.22+sha512.a6b2f7906b721bba3d67d4aff083df04dad64c399707841b7acf00f6b133b7ac24255f2652fa22ae3534329dc6180534e98d17432037ff6fd140556e2bb3137e"
}
```

## Frontend - app.json
```json
{
  "expo": {
    "name": "frontend",
    "slug": "frontend",
    "version": "1.0.0",
    "orientation": "portrait",
    "icon": "./assets/images/icon.png",
    "scheme": "frontend",
    "userInterfaceStyle": "automatic",
    "newArchEnabled": true,
    "ios": {
      "supportsTablet": true
    },
    "android": {
      "adaptiveIcon": {
        "foregroundImage": "./assets/images/adaptive-icon.png",
        "backgroundColor": "#000"
      },
      "edgeToEdgeEnabled": true
    },
    "web": {
      "bundler": "metro",
      "output": "static",
      "favicon": "./assets/images/favicon.png"
    },
    "plugins": [
      "expo-router",
      [
        "expo-splash-screen",
        {
          "image": "./assets/images/splash-icon.png",
          "imageWidth": 200,
          "resizeMode": "contain",
          "backgroundColor": "#000"
        }
      ]
    ],
    "experiments": {
      "typedRoutes": true
    }
  }
}
```

## Frontend - .env
```
EXPO_TUNNEL_SUBDOMAIN=kyc-fintech-app
EXPO_PACKAGER_HOSTNAME=https://kyc-fintech-app.preview.emergentagent.com
EXPO_PUBLIC_BACKEND_URL=https://kyc-fintech-app.preview.emergentagent.com
EXPO_USE_FAST_RESOLVER="1"
EXPO_PACKAGER_PROXY_URL=https://payment-core-1.ngrok.io
METRO_CACHE_ROOT=/app/frontend/.metro-cache```
