#!/bin/bash
# ==============================================================================
# Ableton Agent Studio — macOS 1-Click Launcher
# ==============================================================================
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "======================================================="
echo "  🎹 Launching Ableton Agent Studio for macOS..."
echo "======================================================="

# Check Python 3
if command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
    PYTHON_BIN="python"
else
    osascript -e 'display alert "Python 3 Not Found" message "Please install Python 3 or run: brew install python"'
    exit 1
fi

# Run ableton-agent GUI
exec "$PYTHON_BIN" -m ableton_agent.cli app
