#!/bin/bash

# Server Information
SERVER_ADDRESS="15.222.65.210"
SERVER_USER="ubuntu"
KEY_PATH="~/.ssh/LightsailDefaultKey-ca-central-1.pem"

# First, check if we can connect to the server
echo "Testing connection to AWS Lightsail..."
ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'echo "Connection successful!"'

if [ $? -ne 0 ]; then
    echo "Error: Unable to connect to the server. Please check your connection details."
    exit 1
fi

# Copy updated requirements.txt to the server
echo "Copying updated requirements.txt to the server..."
scp -i $KEY_PATH requirements.txt $SERVER_USER@$SERVER_ADDRESS:~/switchmyplan/

# Connect to server and create script to fix the environment
cat << 'EOF' | ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'cat > ~/fix.sh && chmod +x ~/fix.sh'
#!/bin/bash

# Stop the service
sudo systemctl stop switchmyplan

# Navigate to app directory
cd ~/switchmyplan

# Activate the virtual environment
source venv/bin/activate

# Uninstall problematic packages
pip uninstall -y flask werkzeug

# Install the exact required versions from requirements.txt
pip install -r requirements.txt

# Restart the service
sudo systemctl start switchmyplan

# Check the service status
sudo systemctl status switchmyplan --no-pager

echo "Fix completed!"
EOF

# Execute the fix script on the server
echo "Running fix script on the server..."
ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'bash ~/fix.sh'

# Check if the service is running
echo "Checking service status..."
ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo systemctl status switchmyplan'

# Check if port 5000 is open in AWS Lightsail
echo "Checking if port 5000 is open in AWS Lightsail..."
ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo lsof -i :5000'

echo "Fix deployment completed! Your application should be running at http://$SERVER_ADDRESS:5000"
echo "Important: Make sure to open port 5000 in the AWS Lightsail console if you haven't already."
echo "  1. Log in to AWS Lightsail console"
echo "  2. Select your instance"
echo "  3. Go to the 'Networking' tab"
echo "  4. Add a custom TCP port 5000" 