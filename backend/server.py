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
