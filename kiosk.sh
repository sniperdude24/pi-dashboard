#!/usr/bin/env bash
# Show the dashboard full screen on this Pi's own screen.
#   ~/pi-dashboard/kiosk.sh on     open full screen at every startup (and now)
#   ~/pi-dashboard/kiosk.sh off    stop doing that (and close it now)
#   ~/pi-dashboard/kiosk.sh start  open full screen now (used by the above and
#                                  the "Pi Dashboard" desktop icon)
set -euo pipefail

main() {
    local app home_dir
    app="$(dirname "$(readlink -f "$0")")"
    home_dir="$(dirname "$app")"
    profile="$home_dir/data/browser"        # the full-screen browser's own files
    stop_flag="$home_dir/data/kiosk-stopped" # set by "Exit to desktop"
    local entries=(
        "$HOME/.config/autostart/pi-dashboard.desktop"        # runs at login
        "$HOME/.local/share/applications/pi-dashboard.desktop" # Pi menu
        "$HOME/Desktop/pi-dashboard.desktop"                  # desktop icon
    )

    # When run over SSH, find the screen's desktop session.
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then
        export WAYLAND_DISPLAY=wayland-0
    fi

    case "${1:-}" in
        on)
            for f in "${entries[@]}"; do
                mkdir -p "$(dirname "$f")"
                cat >"$f" <<EOF
[Desktop Entry]
Type=Application
Name=Pi Dashboard
Comment=Show the dashboard full screen
Exec=$home_dir/kiosk.sh start
Icon=video-display
Terminal=false
Categories=Utility;
EOF
            done
            echo "The dashboard will now open full screen at every startup."
            if [ -n "${WAYLAND_DISPLAY:-}" ]; then
                setsid "$home_dir/kiosk.sh" start >/dev/null 2>&1 </dev/null &
                echo "Opening it on the screen now."
            fi
            ;;
        off)
            rm -f "${entries[@]}"
            touch "$stop_flag"
            pkill -f -- "--user-data-dir=$profile" || true
            echo "Full screen turned off. The dashboard itself keeps running in the background."
            ;;
        start)
            rm -f "$stop_flag"
            if pgrep -f -- "--user-data-dir=$profile" >/dev/null; then
                exit 0 # already showing
            fi
            local port
            port="$(cd "$app" && .venv/bin/python -c \
                "import sys; from pathlib import Path; from dashboard import settings; print(settings.Settings(Path(sys.argv[1]))['port'])" \
                "$home_dir/settings.yaml")"
            # At startup the dashboard program may need a moment.
            for _ in $(seq 1 90); do
                curl -fs -o /dev/null "http://localhost:$port/api/config" && break
                sleep 1
            done
            # Reopen the browser if it ever closes, unless "Exit to desktop" was used.
            while [ ! -f "$stop_flag" ]; do
                calm_restore_prompt
                # Raspberry Pi OS's desktop is Wayland; without this Chromium looks for X11.
                chromium --ozone-platform=wayland --kiosk "http://localhost:$port/?kiosk" \
                    --user-data-dir="$profile" \
                    --noerrdialogs --disable-infobars --no-first-run --no-default-browser-check \
                    --disable-session-crashed-bubble --disable-features=Translate \
                    --password-store=basic --check-for-update-interval=31536000 \
                    --disable-pinch --overscroll-history-navigation=0 || true
                sleep 3
            done
            ;;
        *)
            echo "Usage: $0 on|off|start"
            exit 1
            ;;
    esac
}

# Stop Chromium offering to "restore pages" after it was closed by force.
calm_restore_prompt() {
    local prefs="$profile/Default/Preferences"
    [ -f "$prefs" ] || return 0
    sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]*"/"exit_type":"Normal"/' "$prefs"
}

main "$@"
