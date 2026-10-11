#!/usr/bin/env bash
# Shared last step of install and update: Python packages, settings file,
# background service. Safe to run any number of times.
set -euo pipefail

main() {
    local app home_dir service=pi-dashboard
    app="$(dirname "$(readlink -f "$0")")"
    home_dir="$(dirname "$app")"

    echo "Setting up Python packages..."
    [ -x "$app/.venv/bin/python" ] || python3 -m venv "$app/.venv"
    "$app/.venv/bin/pip" install -q --disable-pip-version-check -r "$app/requirements.txt"

    mkdir -p "$home_dir/data"
    if [ ! -f "$home_dir/settings.yaml" ]; then
        cp "$app/settings.example.yaml" "$home_dir/settings.yaml"
        echo "Created $home_dir/settings.yaml"
    fi
    ln -sfn app/update.sh "$home_dir/update.sh"
    ln -sfn app/uninstall.sh "$home_dir/uninstall.sh"

    local port
    port="$(cd "$app" && .venv/bin/python -c \
        "import sys; from pathlib import Path; from dashboard import settings; print(settings.load(Path(sys.argv[1]))['port'])" \
        "$home_dir/settings.yaml")"
    if ! systemctl is-active --quiet "$service" && ss -ltnH "sport = :$port" | grep -q .; then
        echo "Port $port is already used by another program. Change 'port' in"
        echo "$home_dir/settings.yaml, then run ~/pi-dashboard/update.sh"
        exit 1
    fi

    echo "Setting up the background service (asks for your password if needed)..."
    sudo tee "/etc/systemd/system/$service.service" >/dev/null <<EOF
[Unit]
Description=Pi Dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$app
ExecStart=$app/.venv/bin/python -m dashboard --settings $home_dir/settings.yaml --data $home_dir/data
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable --quiet "$service"
    sudo systemctl restart "$service"

    for _ in $(seq 1 20); do
        if curl -fs -o /dev/null "http://localhost:$port/api/config"; then
            echo
            echo "Pi Dashboard is running: http://localhost:$port"
            echo "From another computer:   http://$(hostname -I | awk '{print $1}'):$port"
            exit 0
        fi
        sleep 1
    done
    echo "The service didn't answer. See what went wrong with:"
    echo "  journalctl -u $service -n 50"
    exit 1
}

main "$@"
