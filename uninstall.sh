#!/usr/bin/env bash
# Remove Pi Dashboard from this Pi:  ~/pi-dashboard/uninstall.sh
#   --all   also delete settings and saved data, without asking
#   --keep  keep settings and saved data, without asking
set -euo pipefail

main() {
    local app home_dir service=pi-dashboard answer="${1:-}"
    app="$(dirname "$(readlink -f "$0")")"
    home_dir="$(dirname "$app")"

    # Refuse to delete anything that doesn't look like a Pi Dashboard folder.
    if [ ! -f "$app/dashboard/__init__.py" ] || [ "$home_dir" = "$HOME" ] || [ "$home_dir" = "/" ]; then
        echo "This doesn't look like a Pi Dashboard install ($app). Nothing removed."
        exit 1
    fi

    if [ "$answer" != "--all" ] && [ "$answer" != "--keep" ]; then
        read -r -p "Also delete your settings and saved data? [y/N] " reply </dev/tty
        case "$reply" in [yY]*) answer=--all ;; *) answer=--keep ;; esac
    fi

    echo "Stopping and removing the background service..."
    [ -f "$app/kiosk.sh" ] && bash "$app/kiosk.sh" off >/dev/null 2>&1 || true
    sudo systemctl disable --now "$service" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/$service.service"
    sudo systemctl daemon-reload

    if [ "$answer" = "--all" ]; then
        rm -rf "$home_dir"
        echo "Pi Dashboard removed completely."
    else
        rm -rf "$app" "$home_dir/update.sh" "$home_dir/uninstall.sh" "$home_dir/kiosk.sh" \
            "$home_dir/data/browser" "$home_dir/data/kiosk-stopped"
        echo "Pi Dashboard removed. Your settings.yaml and data/ are still in $home_dir"
    fi
}

main "$@"
