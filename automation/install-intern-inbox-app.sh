#!/bin/zsh
# macOS extra — optional.
# Builds "Intern Inbox.app" in ~/Applications: a one-click launcher that starts
# the server and opens the inbox. You never need this — `uv run intern-inbox`
# does the same thing from a terminal.
# Usage: automation/install-intern-inbox-app.sh [--dock]   (--dock also pins it to the Dock)
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/Intern Inbox.app"

mkdir -p "$APP/Contents/MacOS"
# The app runs a one-line stub that calls the launcher in this clone, so the
# real script stays the single source of truth (edit it, no reinstall needed).
printf '#!/bin/zsh\nexec "%s/automation/intern-inbox-launcher.sh"\n' \
  "$REPO" > "$APP/Contents/MacOS/launcher"
chmod 755 "$APP/Contents/MacOS/launcher"
chmod 755 "$REPO/automation/intern-inbox-launcher.sh"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key><string>Intern Inbox</string>
	<key>CFBundleDisplayName</key><string>Intern Inbox</string>
	<key>CFBundleIdentifier</key><string>com.intern-inbox.app</string>
	<key>CFBundleVersion</key><string>1.0</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleExecutable</key><string>launcher</string>
	<key>LSUIElement</key><true/>
	<key>LSArchitecturePriority</key><array><string>arm64</string></array>
	<key>LSRequiresNativeExecution</key><true/>
</dict>
</plist>
PLIST
touch "$APP"
echo "installed: $APP"

if [[ "$1" == "--dock" ]]; then
  if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "Intern Inbox.app"; then
    echo "already in Dock"
  else
    defaults write com.apple.dock persistent-apps -array-add \
      "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>"
    killall Dock
    echo "added to Dock"
  fi
fi
