#!/bin/bash
# Install ccs wrapper script to ~/bin
#
# Author: PB and Claude
# Date: 2025-01-09
# License: (c) HRDAG, 2025, GPL-2 or newer

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
WRAPPER_PATH="$HOME/bin/ccs"

mkdir -p "$HOME/bin"

cat > "$WRAPPER_PATH" << EOF
#!/bin/bash
uv run --project "$PROJECT_DIR" ccs "\$@"
EOF

chmod +x "$WRAPPER_PATH"

echo "Installed: $WRAPPER_PATH"
echo "Project:   $PROJECT_DIR"

# Check if ~/bin is in PATH
if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then
    echo ""
    echo "Warning: ~/bin is not in your PATH"
    echo "Add this to your shell config (.bashrc, .zshrc, etc.):"
    echo "  export PATH=\"\$HOME/bin:\$PATH\""
fi

# Verify
echo ""
echo "Testing: ccs --help"
"$WRAPPER_PATH" --help | head -5
