# TrustScore - Fintech Trust Score Application

A full-stack fintech application for generating trust scores for gig workers, freelancers, and self-employed individuals.

## Features

- **User Registration & Login** - Phone/Email with OTP verification
- **KYC Document Upload** - Aadhaar, PAN card uploads to Cloudflare R2
- **Income & Bank Statement Submission** - Multi-step data collection
- **Admin Dashboard** - Review users, assign trust scores
- **PDF Report Generation** - Auto-generated trust score reports
- **WhatsApp Integration** - Send PDF reports via WhatsApp Business API

## Tech Stack

### Backend
- FastAPI (Python)
- MongoDB Atlas
- Cloudflare R2 (File Storage)
- Meta WhatsApp Business API
- JWT Authentication

### Frontend
- React Native (Expo)
- Expo Router (File-based routing)
- TypeScript

## Setup

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001
```

### Frontend
```bash
cd frontend
yarn install
yarn expo start
```

## Environment Variables

### Backend (.env)
```
MONGO_URL=your_mongodb_atlas_url
DB_NAME=trustscore
JWT_SECRET_KEY=your_secret_key
WHATSAPP_ACCESS_TOKEN=your_whatsapp_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
R2_ACCESS_KEY_ID=your_r2_access_key
R2_SECRET_ACCESS_KEY=your_r2_secret_key
R2_BUCKET_NAME=your_bucket_name
R2_ENDPOINT_URL=your_r2_endpoint
R2_PUBLIC_URL=your_r2_public_url
```

## Admin Credentials
- Email: admin@fintech.com
- Password: admin123

## API Endpoints

- `POST /api/auth/send-otp` - Send OTP
- `POST /api/auth/verify-otp` - Verify OTP
- `POST /api/auth/register` - Register user
- `POST /api/auth/login` - Login
- `POST /api/trust-score/submit` - Submit trust score data
- `GET /api/admin/users` - Get all users (admin)
- `POST /api/admin/assign-score` - Assign trust score (admin)

## License
MIT
