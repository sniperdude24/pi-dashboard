#!/usr/bin/env bash
# Update Pi Dashboard to the latest version:  ~/pi-dashboard/update.sh
set -euo pipefail

main() {
    local app
    app="$(dirname "$(readlink -f "$0")")"
    git -C "$app" pull --ff-only
    exec bash "$app/setup.sh"
}

main "$@"
