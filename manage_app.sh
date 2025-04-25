#!/bin/bash

# Server Information
SERVER_ADDRESS="15.222.65.210"
SERVER_USER="ubuntu"
KEY_PATH="~/.ssh/LightsailDefaultKey-ca-central-1.pem"

# Function to display usage information
function show_usage {
  echo "Usage: $0 [command]"
  echo "Commands:"
  echo "  start     - Start the SwitchMyPlan service"
  echo "  stop      - Stop the SwitchMyPlan service"
  echo "  restart   - Restart the SwitchMyPlan service"
  echo "  status    - Check the status of the SwitchMyPlan service"
  echo "  logs      - View the last 50 log entries"
  echo "  update    - Update the application (copies new_backend.py and requirements.txt)"
  echo "  check     - Check if port 5000 is open and the service is responding"
  echo "  help      - Show this help message"
}

# Check if we have a command argument
if [ $# -eq 0 ]; then
  show_usage
  exit 1
fi

# Process the command
case "$1" in
  start)
    echo "Starting the SwitchMyPlan service..."
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo systemctl start switchmyplan'
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo systemctl status switchmyplan --no-pager'
    ;;

  stop)
    echo "Stopping the SwitchMyPlan service..."
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo systemctl stop switchmyplan'
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo systemctl status switchmyplan --no-pager'
    ;;

  restart)
    echo "Restarting the SwitchMyPlan service..."
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo systemctl restart switchmyplan'
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo systemctl status switchmyplan --no-pager'
    ;;

  status)
    echo "Checking SwitchMyPlan service status..."
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo systemctl status switchmyplan --no-pager'
    ;;

  logs)
    echo "Viewing SwitchMyPlan service logs..."
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'journalctl -u switchmyplan --no-pager -n 50'
    ;;

  update)
    echo "Updating SwitchMyPlan application..."
    # Copy the updated backend file and requirements
    scp -i $KEY_PATH new_backend.py $SERVER_USER@$SERVER_ADDRESS:~/switchmyplan/
    scp -i $KEY_PATH requirements.txt $SERVER_USER@$SERVER_ADDRESS:~/switchmyplan/
    
    # Update dependencies if needed
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'cd ~/switchmyplan && source venv/bin/activate && pip install -r requirements.txt'
    
    # Restart the service
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo systemctl restart switchmyplan'
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo systemctl status switchmyplan --no-pager'
    ;;

  check)
    echo "Checking if port 5000 is open on the server..."
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'sudo lsof -i :5000'
    
    echo "Checking if the service is responding..."
    ssh -i $KEY_PATH $SERVER_USER@$SERVER_ADDRESS 'curl -I http://localhost:5000/'
    ;;

  help)
    show_usage
    ;;

  *)
    echo "Unknown command: $1"
    show_usage
    exit 1
    ;;
esac

exit 0 