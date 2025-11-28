#!/bin/bash
# ImageHosting Shutdown Script

echo "=== Stopping ImageHosting Application ==="

# 1. STOP GUNICORN (The Python App)
if pgrep -f "gunicorn" > /dev/null; then
    echo "Stopping Gunicorn..."
    pkill -f "gunicorn"
    echo "Gunicorn stopped."
else
    echo "Gunicorn is not running."
fi

# 2. STOP FLASK DEV SERVER (Just in case you ran python app.py)
if pgrep -f "python3 app.py" > /dev/null; then
    echo "Stopping Flask Development Server..."
    pkill -f "python3 app.py"
    echo "Flask stopped."
fi

# 3. STOP REDIS
if pgrep -f "redis" > /dev/null; then
    echo "Stopping Redis..."
    
    # Try the standard command first
    if command -v redis-cli &> /dev/null; then
        redis-cli shutdown
    elif command -v redis6-cli &> /dev/null; then
        redis6-cli shutdown
    else
        # Force kill if CLI isn't found
        pkill -f "redis"
    fi
    
    echo "Redis stopped."
else
    echo "Redis is not running."
fi

echo "=== Application is completely down ==="