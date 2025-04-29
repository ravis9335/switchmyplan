#!/bin/bash

# Update system packages
sudo apt-get update
sudo apt-get upgrade -y

# Install required system packages
sudo apt-get install -y python3-pip python3-venv nginx

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Create necessary directories
mkdir -p logs
mkdir -p public
mkdir -p templates
mkdir -p carrierlogos

# Set proper permissions
sudo chown -R ubuntu:ubuntu /var/www/switchmyplan
sudo chmod -R 755 /var/www/switchmyplan

# Copy systemd service file
sudo cp switchmyplan.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable switchmyplan
sudo systemctl start switchmyplan

# Configure Nginx
sudo tee /etc/nginx/sites-available/switchmyplan << EOF
server {
    listen 80;
    server_name switchmyplan.ca www.switchmyplan.ca;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static/ {
        alias /var/www/switchmyplan/public/;
    }
}
EOF

# Enable Nginx site
sudo ln -sf /etc/nginx/sites-available/switchmyplan /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Install Certbot for SSL
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d switchmyplan.ca -d www.switchmyplan.ca

echo "Deployment completed successfully!" 