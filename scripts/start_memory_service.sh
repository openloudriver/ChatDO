#!/bin/bash

# Safe startup script for Memory Service
# Checks for existing instances before starting

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHATDO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PORT=5858
HOST="127.0.0.1"

echo "Starting Memory Service..."

# Check if port is already in use
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  Port $PORT is already in use!"
    echo "Checking if it's Memory Service..."
    
    # Try to connect to health endpoint
    if curl -s --max-time 1 "http://$HOST:$PORT/health" >/dev/null 2>&1; then
        echo "✅ Memory Service is already running on port $PORT"
        echo "   PID: $(lsof -ti :$PORT)"
        exit 0
    else
        echo "❌ Port $PORT is in use by a different service"
        echo "   Please stop the service using port $PORT or use a different port"
        exit 1
    fi
fi

# Check for existing Memory Service processes
EXISTING_PIDS=$(ps aux | grep -E "uvicorn.*memory_service.api" | grep -v grep | awk '{print $2}' || true)
if [ -n "$EXISTING_PIDS" ]; then
    echo "⚠️  Found existing Memory Service processes: $EXISTING_PIDS"
    echo "   Killing existing processes..."
    echo "$EXISTING_PIDS" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# Change to ChatDO root
cd "$CHATDO_ROOT"

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Start Memory Service
echo "🚀 Starting Memory Service on $HOST:$PORT..."
nohup python -m uvicorn memory_service.api:app --host "$HOST" --port "$PORT" > /tmp/memory_service.log 2>&1 &

# Wait a moment for startup
sleep 2

# Check if it started successfully
if curl -s --max-time 2 "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    NEW_PID=$(lsof -ti :$PORT)
    echo "✅ Memory Service started successfully!"
    echo "   PID: $NEW_PID"
    echo "   Logs: tail -f /tmp/memory_service.log"
else
    echo "❌ Memory Service failed to start"
    echo "   Check logs: tail -20 /tmp/memory_service.log"
    exit 1
fi

