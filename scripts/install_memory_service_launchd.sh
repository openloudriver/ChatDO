#!/bin/bash

# Install Memory Service as a launchd background service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHATDO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOME_DIR="$HOME"
PLIST_NAME="com.chatdo.memoryservice.plist"
LAUNCH_AGENTS_DIR="$HOME_DIR/Library/LaunchAgents"
TEMPLATE_FILE="$SCRIPT_DIR/memory_service.plist.template"
PLIST_FILE="$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo "Installing Memory Service launchd service..."
echo "ChatDO root: $CHATDO_ROOT"
echo "Home directory: $HOME_DIR"

# Ensure LaunchAgents directory exists
mkdir -p "$LAUNCH_AGENTS_DIR"

# Find Python in virtual environment
VENV_PYTHON="$CHATDO_ROOT/.venv/bin/python3"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Virtual environment not found at $VENV_PYTHON"
    echo "Please create a virtual environment first: python3 -m venv .venv"
    exit 1
fi

# Create plist from template
echo "Creating plist file..."
sed -e "s|__CHATDO_ROOT__|$CHATDO_ROOT|g" \
    -e "s|__HOME__|$HOME_DIR|g" \
    -e "s|__VENV_PYTHON__|$VENV_PYTHON|g" \
    "$TEMPLATE_FILE" > "$PLIST_FILE"

echo "Plist file created at: $PLIST_FILE"

# Unload existing service if it exists
if launchctl list | grep -q "$PLIST_NAME"; then
    echo "Unloading existing service..."
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
fi

# Load the service
echo "Loading service..."
launchctl load "$PLIST_FILE"

echo "Memory Service installed successfully!"
echo "Service will start automatically at login."
echo "To check status: launchctl list | grep $PLIST_NAME"
echo "To view logs: tail -f $HOME_DIR/Library/Logs/chatdo-memory-service.log"
echo ""
echo "To uninstall, run:"
echo "  launchctl unload $PLIST_FILE"
echo "  rm $PLIST_FILE"

