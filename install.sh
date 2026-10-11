#!/usr/bin/env bash
# Pi Dashboard installer. Run on the Pi as your normal user:
#   curl -sSL https://raw.githubusercontent.com/sniperdude24/pi-dashboard/main/install.sh | bash
# Running it again on an installed Pi just updates.
set -euo pipefail

main() {
    local repo="${PI_DASHBOARD_REPO:-https://github.com/sniperdude24/pi-dashboard.git}"
    local home_dir="$HOME/pi-dashboard"
    local app="$home_dir/app"

    if [ "$(id -u)" = 0 ]; then
        echo "Run this as your normal user (not with sudo). It asks for sudo when needed."
        exit 1
    fi

    local missing=()
    command -v git >/dev/null || missing+=(git)
    command -v ffmpeg >/dev/null || missing+=(ffmpeg) # live camera picture
    python3 -c "import venv, ensurepip" 2>/dev/null || missing+=(python3-venv)
    if [ ${#missing[@]} -gt 0 ]; then
        echo "Installing system tools: ${missing[*]}"
        sudo apt-get update -qq
        sudo apt-get install -y "${missing[@]}"
    fi

    if [ -d "$app/.git" ]; then
        echo "Already installed, updating instead."
        git -C "$app" pull --ff-only
    else
        mkdir -p "$home_dir"
        git clone --depth 1 "$repo" "$app"
    fi
    exec bash "$app/setup.sh"
}

main "$@"
