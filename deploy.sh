#!/bin/bash
set -e

# --- CONFIGURATION ---
APP_NAME="ImageHosting"
VENV_NAME="venv"

echo "=== Deploying $APP_NAME ==="

# ---------------------------------------------------
# 1. AUTO-INSTALL REDIS (AWS SPECIFIC)
# ---------------------------------------------------
if ! command -v redis-server &> /dev/null && ! command -v redis6-server &> /dev/null; then
    echo "Redis is not installed. Detecting OS to auto-install..."

    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$NAME" == "Amazon Linux"* ]]; then
            echo "Detected Amazon Linux. Attempting installation..."
            
            # Check for Amazon Linux 2 vs 2023
            if [[ "$VERSION_ID" == "2" ]]; then
                echo "Running Amazon Linux 2 installer..."
                sudo amazon-linux-extras install redis6 -y
            else
                echo "Running Amazon Linux 2023/Newer installer..."
                sudo dnf install redis6 -y
            fi
            
            echo "Redis installation complete."
        else
            echo "Error: Not on Amazon Linux. Please install Redis manually."
            exit 1
        fi
    else
        echo "Error: OS detection failed. Please install Redis manually."
        exit 1
    fi
else
    echo "Redis is already installed."
fi

# ---------------------------------------------------
# 2. SETUP PYTHON VIRTUAL ENVIRONMENT
# ---------------------------------------------------
if [ ! -d "$VENV_NAME" ]; then
    echo "Creating virtual environment..."
    python3 -m venv $VENV_NAME
fi

echo "Activating virtual environment..."
source $VENV_NAME/bin/activate

# ---------------------------------------------------
# 3. INSTALL PYTHON DEPENDENCIES
# ---------------------------------------------------
if [ -f requirements.txt ]; then
    echo "Installing Python dependencies..."
    pip install -r requirements.txt
fi

# ---------------------------------------------------
# 4. LOAD ENV VARIABLES
# ---------------------------------------------------
if [ -f .env ]; then
  echo "Loading environment variables..."
  export $(grep -v '^#' .env | xargs)
fi

# ---------------------------------------------------
# 5. START REDIS
# ---------------------------------------------------
echo "Checking Redis Status..."

# Detect which command to use
if command -v redis-server &> /dev/null; then
    REDIS_CMD="redis-server"
elif command -v redis6-server &> /dev/null; then
    REDIS_CMD="redis6-server"
fi

# Start if not running
if pgrep -f "$REDIS_CMD" > /dev/null; then
    echo "Redis is already running."
else
    echo "Starting Redis ($REDIS_CMD)..."
    $REDIS_CMD --daemonize yes
    sleep 2
fi

# ---------------------------------------------------
# 6. RUN THE APPLICATION
# ---------------------------------------------------
echo "Starting Application..."

# If user is 'ec2-user' or 'ubuntu', we assume Production
if [ "$USER" == "ec2-user" ] || [ "$USER" == "ubuntu" ]; then
    if pgrep -f "gunicorn" > /dev/null; then
        echo "Restarting Gunicorn..."
        pkill -f "gunicorn"
        sleep 1
    fi
    echo "Production environment detected. Using Gunicorn."
    nohup gunicorn -w 4 -b 0.0.0.0:8000 app:app > app.log 2>&1 &
    echo "App started in background! (Port 8000)"
else
    echo "Local environment detected. Running with Flask Development Server."
    python3 app.py
fi