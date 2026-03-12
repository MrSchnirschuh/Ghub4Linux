#!/usr/bin/env bash
# install.sh – Install Ghub4Linux and register it as a desktop application.
#
# Usage:
#   bash install.sh          # installs for the current user (no root required)
#   bash install.sh --system # installs system-wide (requires root / sudo)
#
# A dedicated Python virtual environment is created automatically so that the
# install works on distributions that enforce PEP 668 (Arch Linux, Ubuntu 23.04+,
# Fedora 38+, …) without requiring --break-system-packages.
#
# The venv is created with --system-site-packages so that system-provided GTK /
# GObject bindings (e.g. python-gobject installed via pacman / apt) are visible
# inside it.  Only the ghub4linux package itself is installed via pip.

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
    VENV_DIR="/opt/ghub4linux/venv"
    BIN_DIR="/usr/local/bin"
    INSTALL_CMD="sudo"
else
    APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
    VENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/ghub4linux/venv"
    BIN_DIR="$HOME/.local/bin"
    INSTALL_CMD=""
fi

DESKTOP_SRC="$SCRIPT_DIR/data/com.github.mrschnirschuh.ghub4linux.desktop"
ICON_SRC="$SCRIPT_DIR/data/icons/hicolor/scalable/apps/com.github.mrschnirschuh.ghub4linux.svg"

# ── 1. Install Python package ──────────────────────────────────────────────────
echo "==> Installing Python package …"
if [ -n "${VIRTUAL_ENV:-}" ]; then
    # User already activated a venv before running this script – install there.
    python3 -m pip install "$SCRIPT_DIR"
    INSTALLED_BIN="${VIRTUAL_ENV}/bin/ghub4linux"
elif $SYSTEM; then
    # System-wide: create a dedicated venv under /opt.
    sudo python3 -m venv --system-site-packages "$VENV_DIR"
    sudo "$VENV_DIR/bin/pip" install "$SCRIPT_DIR"
    INSTALLED_BIN="$VENV_DIR/bin/ghub4linux"
else
    # User install: create a dedicated venv under ~/.local/share/ghub4linux/.
    # --system-site-packages lets the venv use system GTK/GObject bindings.
    mkdir -p "$(dirname "$VENV_DIR")"
    python3 -m venv --system-site-packages "$VENV_DIR"
    "$VENV_DIR/bin/pip" install "$SCRIPT_DIR"
    INSTALLED_BIN="$VENV_DIR/bin/ghub4linux"
fi

# ── 2. Expose the launcher on PATH ────────────────────────────────────────────
# Skip this when the user ran the script from inside their own venv (the venv's
# bin/ is already on PATH while the venv is active).
if [ -z "${VIRTUAL_ENV:-}" ]; then
    echo "==> Installing launcher to $BIN_DIR …"
    $INSTALL_CMD mkdir -p "$BIN_DIR"
    $INSTALL_CMD ln -sf "$INSTALLED_BIN" "$BIN_DIR/ghub4linux"
fi

# ── 3. Install desktop entry ───────────────────────────────────────────────────
echo "==> Installing desktop entry to $APP_DIR …"
$INSTALL_CMD mkdir -p "$APP_DIR"
DESKTOP_DEST="$APP_DIR/$(basename "$DESKTOP_SRC")"
$INSTALL_CMD cp "$DESKTOP_SRC" "$DESKTOP_DEST"
# Patch Exec= to use the full absolute path so desktop environments (GNOME, KDE, …)
# can launch the app without inheriting the user's shell PATH.
if [ -z "${VIRTUAL_ENV:-}" ]; then
    $INSTALL_CMD sed -i "s|^Exec=ghub4linux|Exec=${BIN_DIR}/ghub4linux|" "$DESKTOP_DEST"
else
    $INSTALL_CMD sed -i "s|^Exec=ghub4linux|Exec=${INSTALLED_BIN}|" "$DESKTOP_DEST"
fi

# ── 4. Install icon ────────────────────────────────────────────────────────────
echo "==> Installing icon to $ICON_DIR …"
$INSTALL_CMD mkdir -p "$ICON_DIR"
$INSTALL_CMD cp "$ICON_SRC" "$ICON_DIR/"

# ── 5. Refresh desktop / icon cache ───────────────────────────────────────────
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

# Warn if ~/.local/bin is not yet on PATH (common on fresh user accounts).
if [ -z "${VIRTUAL_ENV:-}" ] && ! $SYSTEM; then
    if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
        echo ""
        echo "   ⚠  ${BIN_DIR} is not in your PATH."
        echo "   Add the following line to your shell profile (~/.bashrc, ~/.zshrc, …):"
        echo "     export PATH=\"${BIN_DIR}:\$PATH\""
    fi
fi
