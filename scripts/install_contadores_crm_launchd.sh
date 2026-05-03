#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/Users/fgoiriz/private/repos/contadores"
LABEL="com.konecta.contadores.crm-followup"
SOURCE_PLIST="$ROOT_DIR/scripts/launchd/$LABEL.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT_DIR/data/reports" "$ROOT_DIR/data/locks"
cp "$SOURCE_PLIST" "$TARGET_PLIST"

launchctl bootout "$GUI_DOMAIN" "$TARGET_PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "$GUI_DOMAIN" "$TARGET_PLIST"
launchctl enable "$GUI_DOMAIN/$LABEL"

echo "installed=$TARGET_PLIST"
echo "label=$LABEL"
echo "status: launchctl print $GUI_DOMAIN/$LABEL"
echo "run now: launchctl kickstart -k $GUI_DOMAIN/$LABEL"
