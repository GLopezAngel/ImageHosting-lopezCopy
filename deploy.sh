#!/bin/bash
set -e

# --- CONFIGURATION ---
APP_NAME="ImageHosting"
VENV_NAME="venv"

echo "=== Deploying $APP_NAME ==="

# 1. SETUP PYTHON VIRTUAL ENVIRONMENT
# It is bad practice to install libraries globally. We use a virtual env.
if [ ! -d "$VENV_NAME" ]; then
    echo "Creating virtual environment..."
    python3 -m venv $VENV_NAME
fi

echo "Activating virtual environment..."
source $VENV_NAME/bin/activate

# 2. INSTALL PYTHON DEPENDENCIES
if [ -f requirements.txt ]; then
    echo "Installing Python dependencies..."
    pip install -r requirements.txt
fi

# 3. LOAD ENV VARIABLES
if [ -f .env ]; then
  echo "Loading environment variables..."
  export $(grep -v '^#' .env | xargs)
fi

# 4. REDIS DETECTION & STARTUP
# This function checks for standard redis-server or amazon specific redis6-server
echo "Checking Redis..."

if command -v redis-server &> /dev/null; then
    REDIS_CMD="redis-server"
elif command -v redis6-server &> /dev/null; then
    REDIS_CMD="redis6-server"
else
    echo "ERROR: Redis is not installed."
    echo "  - If on Mac: brew install redis"
    echo "  - If on AWS (Amazon Linux 2): sudo amazon-linux-extras install redis6"
    echo "  - If on AWS (Amazon Linux 2023): sudo dnf install redis6"
    exit 1
fi

# Check if running
if pgrep -f "$REDIS_CMD" > /dev/null; then
    echo "Redis is already running."
else
    echo "Starting Redis ($REDIS_CMD)..."
    $REDIS_CMD --daemonize yes
    sleep 2
fi

# 5. RUN THE APPLICATION
echo "Starting Application..."

# If we are on AWS (implied by the presence of EC2 user or specific hostnames), use Gunicorn
# If we are just testing locally, use standard Python
if [ "$USER" == "ec2-user" ] || [ "$USER" == "ubuntu" ]; then
    echo "Production environment detected. Using Gunicorn."
    # Runs in background, 4 worker processes, binding to port 8000
    nohup gunicorn -w 4 -b 0.0.0.0:8000 app:app > app.log 2>&1 &
    echo "App started in background. Check app.log for details."
else
    echo "Local environment detected. Running with Flask Development Server."
    python3 app.py
fi