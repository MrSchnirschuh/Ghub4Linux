#!/usr/bin/env bash
# install.sh – Install Ghub4Linux and register it as a desktop application.
#
# Usage:
#   bash install.sh          # installs for the current user (no root required)
#   bash install.sh --system # installs system-wide (requires root / sudo)

set -euo pipefail

SYSTEM=false
for arg in "$@"; do
    case "$arg" in
        --system) SYSTEM=true ;;
        -h|--help)
            echo "Usage: bash install.sh [--system]"
            echo "  (no flag)  Install for the current user only"
            echo "  --system   Install system-wide (requires sudo)"
            exit 0
            ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Paths ──────────────────────────────────────────────────────────────────────
if $SYSTEM; then
    APP_DIR="/usr/share/applications"
    ICON_DIR="/usr/share/icons/hicolor/scalable/apps"
    INSTALL_CMD="sudo"
else
    APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
    INSTALL_CMD=""
fi

DESKTOP_SRC="$SCRIPT_DIR/data/com.github.mrschnirschuh.ghub4linux.desktop"
ICON_SRC="$SCRIPT_DIR/data/icons/hicolor/scalable/apps/com.github.mrschnirschuh.ghub4linux.svg"

# ── 1. Install Python package ──────────────────────────────────────────────────
echo "==> Installing Python package …"
$INSTALL_CMD pip install -e "$SCRIPT_DIR"

# ── 2. Install desktop entry ───────────────────────────────────────────────────
echo "==> Installing desktop entry to $APP_DIR …"
$INSTALL_CMD mkdir -p "$APP_DIR"
$INSTALL_CMD cp "$DESKTOP_SRC" "$APP_DIR/"

# ── 3. Install icon ────────────────────────────────────────────────────────────
echo "==> Installing icon to $ICON_DIR …"
$INSTALL_CMD mkdir -p "$ICON_DIR"
$INSTALL_CMD cp "$ICON_SRC" "$ICON_DIR/"

# ── 4. Refresh desktop / icon cache ───────────────────────────────────────────
if command -v update-desktop-database &>/dev/null; then
    echo "==> Updating desktop database …"
    $INSTALL_CMD update-desktop-database "$APP_DIR"
fi

if command -v gtk-update-icon-cache &>/dev/null; then
    echo "==> Updating icon cache …"
    if $SYSTEM; then
        $INSTALL_CMD gtk-update-icon-cache -f -t /usr/share/icons/hicolor
    else
        gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
    fi
fi

echo ""
echo "✔  Ghub4Linux installed successfully!"
echo "   You can now launch it from your application menu or by running: ghub4linux"
