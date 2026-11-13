#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"
DESKTOP_FILE="$APP_DIR/agent-shadi-review-desk.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Agent Shadi Review Desk
Comment=Keyboard-first standalone human review workspace
Exec="$ROOT/review.sh"
Icon=$ROOT/app/static/shadi-icon.svg
Terminal=false
Categories=Office;Utility;Development;
StartupNotify=true
EOF
chmod 644 "$DESKTOP_FILE"
update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
echo "Installed: Agent Shadi Review Desk"
echo "Find it in your application launcher. It opens in a separate terminal window."
echo "Target: $DESKTOP_FILE"
