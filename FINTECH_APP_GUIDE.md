# FinTrust - Fintech Application

A comprehensive mobile-first fintech application built with Expo React Native (frontend) and FastAPI (backend) for trust score assessment and lender recommendations.

## 📱 Features

### User Features
- **User Registration & Authentication**
  - Mobile OTP verification (Mock implementation)
  - Email/Mobile + Password login
  - Government ID upload (Aadhaar/PAN/DL)
  - JWT-based authentication

- **Trust Score Assessment**
  - Multi-step form for financial data collection
  - Employment type selection (Gig Worker, Freelancer, Content Creator, Self-Employed)
  - Income details (Daily/Weekly/Monthly)
  - Monthly expenses tracking
  - Bank statement uploads (last 4 months)
  - Loan history information

- **User Dashboard**
  - View KYC status
  - View trust score
  - Track application status
  - Access support resources

- **Profile Management**
  - View personal information
  - Check trust score status
  - Logout functionality

### Admin Features
- **Admin Dashboard**
  - View all registered users
  - Filter by trust score status
  - Quick access to user details

- **User Management**
  - View complete user data
  - Review KYC documents
  - Analyze financial information
  - Review bank statements

- **Trust Score Assignment**
  - Manual trust score calculation (0-100)
  - Add evaluation remarks
  - Generate PDF reports
  - Mock WhatsApp delivery

## 🏗️ Technical Architecture

### Frontend (Mobile)
- **Framework**: Expo React Native
- **Navigation**: Expo Router (file-based routing)
- **State Management**: React Context API
- **API Client**: Axios
- **UI Components**: React Native core components
- **Storage**: AsyncStorage for auth tokens

### Backend
- **Framework**: FastAPI
- **Database**: MongoDB (Motor async driver)
- **Authentication**: JWT (PyJWT + bcrypt)
- **PDF Generation**: ReportLab
- **File Handling**: Base64 encoding for images/documents

### Database Schema

#### Users Collection
```
{
  user_id: UUID,
  username: String,
  mobile: String,
  email: String,
  age: Number,
  password_hash: String,
  role: String (user/admin),
  created_at: DateTime,
  is_mobile_verified: Boolean
}
```

#### KYC Collection
```
{
  user_id: UUID,
  document_type: String,
  document_data: String (base64),
  verification_status: String,
  uploaded_at: DateTime
}
```

#### Income Details Collection
```
{
  user_id: UUID,
  employment_type: String,
  income_type: String,
  income_amount: Float,
  monthly_expenses: Float,
  submitted_at: DateTime
}
```

#### Bank Statements Collection
```
{
  user_id: UUID,
  statements: Array[String] (base64),
  upload_date: DateTime
}
```

#### Loan History Collection
```
{
  user_id: UUID,
  has_previous_loan: Boolean,
  submitted_at: DateTime
}
```

#### Trust Scores Collection
```
{
  user_id: UUID,
  admin_score: Number,
  remarks: String,
  status: String (pending_review/completed),
  submitted_at: DateTime,
  generated_date: DateTime,
  pdf_data: String (base64),
  sent_via_whatsapp: Boolean
}
```

## 🚀 API Endpoints

### Authentication
- `POST /api/auth/send-otp` - Send OTP (Mock)
- `POST /api/auth/verify-otp` - Verify OTP
- `POST /api/auth/register` - Register new user
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

## 🔧 Setup & Installation

### Prerequisites
- Node.js 18+ and Yarn
- Python 3.11+
- MongoDB

### Backend Setup
```bash
cd /app/backend
pip install -r requirements.txt
```

### Frontend Setup
```bash
cd /app/frontend
yarn install
```

### Environment Variables

**Backend (.env)**
```
MONGO_URL=mongodb://localhost:27017
DB_NAME=fintech_db
JWT_SECRET_KEY=your-secret-key-change-in-production
```

**Frontend (.env)**
```
EXPO_PUBLIC_BACKEND_URL=<backend-url>
```

### Running the Application

**Start Backend**
```bash
sudo supervisorctl restart backend
```

**Start Frontend**
```bash
sudo supervisorctl restart expo
```

## 👤 Default Admin Credentials

After creating the default admin account via API:
- **Email**: admin@fintech.com
- **Password**: admin123

To create admin account, call:
```bash
curl -X POST http://localhost:8001/api/admin/create-default
```

## 📱 Mobile App Structure

```
frontend/
├── app/
│   ├── _layout.tsx           # Root layout with AuthProvider
│   ├── index.tsx              # Entry point with routing logic
│   ├── (auth)/                # Authentication screens
│   │   ├── welcome.tsx
│   │   ├── login.tsx
│   │   ├── register.tsx
│   │   └── verify-otp.tsx
│   ├── (user)/                # User screens (Bottom tabs)
│   │   ├── home.tsx
│   │   ├── profile.tsx
│   │   ├── support.tsx
│   │   └── trust-score.tsx
│   └── (admin)/               # Admin screens
│       ├── dashboard.tsx
│       └── user-details.tsx
├── contexts/
│   └── AuthContext.tsx        # Authentication context
└── utils/
    └── api.ts                 # Axios API client
```

## 🔐 Security Features

- **Password Hashing**: bcrypt with salt rounds
- **JWT Authentication**: Secure token-based auth
- **Role-Based Access Control**: Admin/User separation
- **Token Expiry**: 30-day token validity
- **Secure File Storage**: Base64 encoding for documents
- **CORS Protection**: Configured CORS middleware

## 🎯 User Flows

### User Journey
1. Welcome screen → Register
2. Fill registration form
3. Upload government ID
4. Send & verify OTP
5. Login to user dashboard
6. Complete trust score assessment
7. Wait for admin review
8. Receive trust score via WhatsApp (Mock)

### Admin Journey
1. Login with admin credentials
2. View all users in dashboard
3. Select user for review
4. View complete user data
5. Assign trust score (0-100)
6. Add evaluation remarks
7. Generate & send PDF report

## 🧪 Testing

### Backend Testing
All endpoints have been tested and verified:
- ✅ Authentication flow (OTP, Register, Login)
- ✅ KYC document upload
- ✅ Trust score submission
- ✅ Admin user management
- ✅ Trust score assignment
- ✅ PDF generation
- ✅ JWT authorization
- ✅ MongoDB ObjectId serialization

### Test Credentials
**Test User**:
- Email: testuser@example.com
- Password: password123

**Admin**:
- Email: admin@fintech.com
- Password: admin123

## 📝 Mock Integrations

The following features are currently MOCKED for development:

1. **OTP Verification**
   - Mock OTP is returned in API response
   - In production, integrate with Twilio/AWS SNS

2. **WhatsApp Delivery**
   - PDF generation works fully
   - WhatsApp sending is logged to console
   - In production, integrate with WhatsApp Business API

3. **File Storage**
   - Files stored as base64 in MongoDB
   - In production, consider using AWS S3/Google Cloud Storage

## 🚀 Deployment Considerations

### For Production

1. **Environment Variables**
   - Change JWT_SECRET_KEY
   - Use production MongoDB URL
   - Configure proper CORS origins

2. **Integrate Real Services**
   - SMS/OTP provider (Twilio, AWS SNS)
   - WhatsApp Business API
   - Cloud storage (S3, Google Cloud)

3. **Security Enhancements**
   - Rate limiting
   - Input validation
   - File size limits
   - Virus scanning for uploads

4. **Performance**
   - Implement caching (Redis)
   - Database indexing
   - CDN for static assets
   - Load balancing

## 🎨 UI/UX Features

- **Mobile-First Design**: Optimized for touch interactions
- **Bottom Tab Navigation**: Easy thumb-reach navigation
- **Multi-Step Forms**: Progressive disclosure for complex data
- **Visual Feedback**: Loading states, success/error messages
- **Responsive Layout**: Works on all mobile screen sizes
- **Safe Area Support**: Proper spacing for notches/home indicators

## 📊 Key Metrics Tracked

- User registrations
- KYC submissions
- Trust score assessments submitted
- Trust scores completed
- Average trust scores
- Admin review time

## 🛠️ Future Enhancements

1. **Real-time Notifications**: Push notifications for status updates
2. **Document Scanner**: In-app document scanning
3. **Biometric Auth**: Fingerprint/Face ID login
4. **Credit Score Integration**: Connect with credit bureaus
5. **Lender Marketplace**: Direct lender connections
6. **Analytics Dashboard**: User behavior insights
7. **Multi-language Support**: Regional language support
8. **Dark Mode**: Theme switching

## 📞 Support

For issues or questions:
- Email: support@fintrust.com
- Phone: +91 1800-XXX-XXXX
- WhatsApp: Available in app

## 📄 License

Proprietary - All rights reserved

---

Built with ❤️ using Expo React Native and FastAPI
