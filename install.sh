#!/usr/bin/env bash
set -euo pipefail

RESET="\033[0m";  BOLD="\033[1m"
GREEN="\033[32m"; CYAN="\033[36m"; YELLOW="\033[33m"; RED="\033[31m"

info()    { echo -e "${CYAN}  ♪  $*${RESET}"; }
success() { echo -e "${GREEN}  ✓  $*${RESET}"; }
warn()    { echo -e "${YELLOW}  !  $*${RESET}"; }
err()     { echo -e "${RED}  ✗  $*${RESET}"; exit 1; }

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${BOLD}  SpotiDL — Installer${RESET}"
echo "  ─────────────────────────────────────"
echo ""

command -v python3 >/dev/null 2>&1 || err "python3 not found. Install it and try again."

# ── 1. Python dependencies ────────────────────────────────────────────────────
info "Installing Python dependencies..."
pip3 install -q -r "$INSTALL_DIR/requirements.txt"
success "Dependencies ready"
echo ""

# ── 2. Install the 'dj' entry-point via pip ───────────────────────────────────
info "Installing 'dj' command..."
pip3 install -q -e "$INSTALL_DIR" || true

# Resolve where pip put the script
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
CANDIDATES=(
    "$(python3 -m site --user-base 2>/dev/null)/bin/dj"
    "$HOME/Library/Python/$PY_VER/bin/dj"
    "/usr/local/bin/dj"
    "/opt/homebrew/bin/dj"
)

DJ_PATH=""
for c in "${CANDIDATES[@]}"; do
    if [ -f "$c" ]; then DJ_PATH="$c"; break; fi
done

# Fallback: write a wrapper script to ~/.local/bin
if [ -z "$DJ_PATH" ]; then
    warn "pip entry-point not found in standard locations — creating wrapper"
    mkdir -p "$HOME/.local/bin"
    cat > "$HOME/.local/bin/dj" <<EOF
#!/usr/bin/env bash
cd "$INSTALL_DIR"
exec python3 -m cli.main "\$@"
EOF
    chmod +x "$HOME/.local/bin/dj"
    DJ_PATH="$HOME/.local/bin/dj"
fi

# Ensure the bin directory is in PATH for future shells
DJ_BIN_DIR="$(dirname "$DJ_PATH")"
for RC in "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bashrc"; do
    if [ -f "$RC" ] && ! grep -qF "$DJ_BIN_DIR" "$RC" 2>/dev/null; then
        printf '\n# SpotiDL\nexport PATH="%s:$PATH"\n' "$DJ_BIN_DIR" >> "$RC"
        success "Added $DJ_BIN_DIR to PATH in $RC"
    fi
done
export PATH="$DJ_BIN_DIR:$PATH"

success "'dj' installed → $DJ_PATH"
echo ""

# ── 3. macOS Spotlight app bundle ─────────────────────────────────────────────
info "Creating DJ.app for Spotlight (Cmd+Space)..."

APP="$HOME/Applications/DJ.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Executable — opens a new Terminal window and runs dj
cat > "$APP/Contents/MacOS/DJ" <<'APPSCRIPT'
#!/usr/bin/env bash
osascript <<'APPLESCRIPT'
tell application "Terminal"
    activate
    do script "dj"
end tell
APPLESCRIPT
APPSCRIPT
chmod +x "$APP/Contents/MacOS/DJ"

# Info.plist
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>    <string>DJ</string>
    <key>CFBundleIdentifier</key>   <string>com.spotidl.dj</string>
    <key>CFBundleName</key>         <string>DJ</string>
    <key>CFBundleDisplayName</key>  <string>DJ</string>
    <key>CFBundleVersion</key>      <string>1.0.0</string>
    <key>CFBundleShortVersionString</key> <string>1.0.0</string>
    <key>CFBundlePackageType</key>  <string>APPL</string>
    <key>LSMinimumSystemVersion</key> <string>10.13</string>
    <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
PLIST

# Force Spotlight to index the new app immediately
/System/Library/CoreServices/mdimport/mdimport "$APP" 2>/dev/null || true

success "DJ.app → $APP"
echo ""

# ── Done ──────────────────────────────────────────────────────────────────────
echo -e "${BOLD}${GREEN}  ✓  All done!${RESET}"
echo ""
echo "  Terminal  →  open a new tab and type  ${BOLD}dj${RESET}"
echo "  Spotlight →  ${BOLD}Cmd+Space${RESET}  ›  type  ${BOLD}DJ${RESET}  ›  Enter"
echo ""
