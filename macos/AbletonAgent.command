#!/bin/bash
# ==============================================================================
# ableton-agent — macOS 1-Click Interactive Terminal Launcher (Claude Code style)
# ==============================================================================
# Set terminal title
printf "\033]0;ableton-agent 🎹 (Claude Code Terminal)\007"

# Clear quarantine if downloaded from web
xattr -d com.apple.quarantine "$0" 2>/dev/null || true

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PARENT="$( cd "$DIR/.." && pwd )"

# Set PYTHONPATH to include project src if running from git/repo checkout
if [ -d "$PARENT/src" ]; then
    export PYTHONPATH="$PARENT/src:$PYTHONPATH"
fi

# Find Python 3
if command -v python3 &>/dev/null; then
    PY="python3"
elif [ -x "/usr/local/bin/python3" ]; then
    PY="/usr/local/bin/python3"
elif [ -x "/opt/homebrew/bin/python3" ]; then
    PY="/opt/homebrew/bin/python3"
else
    echo "Python 3 is required. Please install it via https://python.org or: brew install python"
    read -p "Press Enter to exit..."
    exit 1
fi

# Launch the interactive Claude Code-style CLI terminal
exec "$PY" -m ableton_agent.cli
