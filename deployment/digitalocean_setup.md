# FinTrust - DigitalOcean Deployment Guide

## Prerequisites
- DigitalOcean account
- Domain name (optional but recommended)
- SSH keys configured

## Step 1: Create a Droplet

1. **Droplet Configuration:**
   - **Distribution:** Ubuntu 24.04 LTS
   - **Plan:** Basic (Regular Intel)
   - **CPU Options:** 2 GB RAM / 1 vCPU ($12/month) or 4 GB RAM / 2 vCPU ($24/month)
   - **Datacenter:** Choose closest to your users
   - **Authentication:** SSH keys (recommended) or root password
   - **Hostname:** fintrust-prod

2. **Create the Droplet** and note the IP address

## Step 2: Initial Server Setup

```bash
# SSH into your droplet
ssh root@YOUR_DROPLET_IP

# Update system packages
apt update && apt upgrade -y

# Create a new user
adduser fintrust
usermod -aG sudo fintrust

# Configure firewall
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

# Switch to new user
su - fintrust
```

## Step 3: Install Dependencies

```bash
# Install Python 3.11
sudo apt install python3.11 python3.11-venv python3-pip -y

# Install Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Install Yarn
npm install -g yarn

# Install PM2 for process management
npm install -g pm2

# Install Nginx
sudo apt install nginx -y

# Install MongoDB (if not using Atlas)
# Since you're using MongoDB Atlas, skip this step
```

## Step 4: Clone and Setup Application

```bash
# Create application directory
mkdir -p /home/fintrust/app
cd /home/fintrust/app

# Upload your application files (use SCP or Git)
# Option 1: Git
git clone YOUR_REPO_URL .

# Option 2: SCP from local machine
# From your local machine:
# scp -r /path/to/app fintrust@YOUR_DROPLET_IP:/home/fintrust/app
```

## Step 5: Setup Backend

```bash
cd /home/fintrust/app/backend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy production environment file
cp .env.production .env

# Test backend
python server_production.py
# Press Ctrl+C after testing
```

## Step 6: Setup PM2 for Backend

```bash
# Create PM2 ecosystem file
cat > /home/fintrust/app/ecosystem.config.js << 'EOF'
module.exports = {
  apps: [
    {
      name: 'fintrust-backend',
      script: 'venv/bin/python',
      args: 'server_production.py',
      cwd: '/home/fintrust/app/backend',
      instances: 2,
      exec_mode: 'cluster',
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'production'
      },
      error_file: '/home/fintrust/logs/backend-error.log',
      out_file: '/home/fintrust/logs/backend-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    }
  ]
};
EOF

# Create logs directory
mkdir -p /home/fintrust/logs

# Start backend with PM2
pm2 start ecosystem.config.js
pm2 save
pm2 startup systemd -u fintrust --hp /home/fintrust
```

## Step 7: Configure Nginx

```bash
# Create Nginx configuration
sudo nano /etc/nginx/sites-available/fintrust
```

**Paste this configuration:**

```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN_OR_IP;

    # API Backend
    location /api {
        proxy_pass http://localhost:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # Health check
    location /health {
        proxy_pass http://localhost:8001/api/;
        proxy_http_version 1.1;
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
}
```

**Enable the site:**

```bash
sudo ln -s /etc/nginx/sites-available/fintrust /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## Step 8: Setup SSL with Let's Encrypt (Optional but Recommended)

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Obtain SSL certificate
sudo certbot --nginx -d YOUR_DOMAIN

# Auto-renewal is configured automatically
```

## Step 9: Configure Environment Variables

```bash
cd /home/fintrust/app/backend
nano .env
```

**Ensure all production values are set:**

```env
MONGO_URL=mongodb+srv://sairamanakula944:sairaman8919@trustscore.1ruyddz.mongodb.net/?appName=trustscore
DB_NAME=trustscore_db
JWT_SECRET_KEY=your-super-secret-key-change-this

WHATSAPP_ACCESS_TOKEN=your_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_id
WHATSAPP_BUSINESS_ACCOUNT_ID=your_account_id

R2_ACCESS_KEY_ID=your_r2_key
R2_SECRET_ACCESS_KEY=your_r2_secret
R2_BUCKET_NAME=trustscore-mvp
R2_ENDPOINT_URL=your_endpoint
R2_PUBLIC_URL=your_public_url

FIREBASE_CONFIG_PATH=./firebase_config.json
```

## Step 10: Setup Firebase Configuration

1. Go to Firebase Console: https://console.firebase.google.com/
2. Select your project: `trustscore-58d7e`
3. Go to **Project Settings** > **Service Accounts**
4. Click **"Generate New Private Key"**
5. Download the JSON file
6. Upload it to server:

```bash
# From local machine
scp firebase-service-account.json fintrust@YOUR_DROPLET_IP:/home/fintrust/app/backend/firebase_config.json
```

## Step 11: Monitoring and Logs

```bash
# View backend logs
pm2 logs fintrust-backend

# View Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Monitor system resources
pm2 monit

# Check application status
pm2 status
```

## Step 12: Application Management

```bash
# Restart backend
pm2 restart fintrust-backend

# Stop backend
pm2 stop fintrust-backend

# Reload backend (zero-downtime)
pm2 reload fintrust-backend

# View logs
pm2 logs fintrust-backend --lines 100

# Restart Nginx
sudo systemctl restart nginx
```

## Step 13: Database Backup (MongoDB Atlas)

```bash
# Install MongoDB tools
sudo apt-get install mongodb-database-tools -y

# Create backup directory
mkdir -p /home/fintrust/backups

# Backup script
cat > /home/fintrust/backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/home/fintrust/backups"
mongodump --uri="YOUR_MONGO_CONNECTION_STRING" --out="$BACKUP_DIR/backup_$DATE"
find $BACKUP_DIR -name "backup_*" -mtime +7 -exec rm -rf {} \;
EOF

chmod +x /home/fintrust/backup.sh

# Add to crontab (daily at 2 AM)
crontab -e
# Add: 0 2 * * * /home/fintrust/backup.sh
```

## Security Checklist

- [ ] Changed default passwords
- [ ] Configured firewall (UFW)
- [ ] SSL certificate installed
- [ ] MongoDB credentials secured
- [ ] API keys stored in environment variables
- [ ] Regular backups configured
- [ ] Fail2ban installed (optional): `sudo apt install fail2ban`
- [ ] Monitor disk space: `df -h`
- [ ] Monitor logs regularly

## Troubleshooting

### Backend Not Starting
```bash
# Check Python version
python3.11 --version

# Check virtual environment
source /home/fintrust/app/backend/venv/bin/activate
python --version

# Check dependencies
pip list | grep fastapi

# Test manually
cd /home/fintrust/app/backend
source venv/bin/activate
python server_production.py
```

### Database Connection Issues
```bash
# Test MongoDB connection
python -c "from motor.motor_asyncio import AsyncIOMotorClient; import asyncio; client = AsyncIOMotorClient('YOUR_MONGO_URL'); print(asyncio.run(client.server_info()))"
```

### Nginx Issues
```bash
# Test configuration
sudo nginx -t

# Check Nginx status
sudo systemctl status nginx

# Check error logs
sudo tail -f /var/log/nginx/error.log
```

## Performance Optimization

1. **Enable Redis Caching** (Optional):
```bash
sudo apt install redis-server -y
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

2. **Database Indexing**:
```javascript
// Connect to MongoDB Atlas and create indexes
db.users.createIndex({ "email": 1 })
db.users.createIndex({ "mobile": 1 })
db.trust_scores.createIndex({ "user_id": 1 })
```

3. **PM2 Cluster Mode**:
Already configured in ecosystem.config.js with 2 instances

## Monitoring Setup

```bash
# Install monitoring tools
sudo apt install htop iotop -y

# Setup PM2 monitoring (requires PM2 Plus account)
pm2 monitor
```

## Updating Application

```bash
cd /home/fintrust/app
git pull origin main

# Update backend
cd backend
source venv/bin/activate
pip install -r requirements.txt
pm2 reload fintrust-backend

# Verify
pm2 logs fintrust-backend --lines 50
```

## Cost Estimation

- **DigitalOcean Droplet:** $12-24/month
- **Domain Name:** $10-15/year
- **MongoDB Atlas (Free Tier):** $0 (up to 512MB)
- **Cloudflare R2:** $0.015/GB stored + $0.36/million Class A operations
- **WhatsApp Business API:** Free (Cloud API)
- **Total Est:** $12-30/month

## Support

For issues, check:
1. PM2 logs: `pm2 logs`
2. Nginx logs: `sudo tail -f /var/log/nginx/error.log`
3. System logs: `sudo journalctl -xe`
4. Disk space: `df -h`
5. Memory: `free -h`
