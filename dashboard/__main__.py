"""Start the dashboard:  python -m dashboard --settings ../settings.yaml --data ../data"""

import argparse
import logging
from pathlib import Path

from . import server, settings

parser = argparse.ArgumentParser(prog="pi-dashboard")
parser.add_argument("--settings", type=Path, required=True, help="path to settings.yaml")
parser.add_argument("--data", type=Path, required=True, help="folder for saved data")
parser.add_argument("--verbose", action="store_true")
args = parser.parse_args()

logging.basicConfig(
    level=logging.DEBUG if args.verbose else logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
args.data.mkdir(parents=True, exist_ok=True)
server.serve(settings.load(args.settings), args.data)
