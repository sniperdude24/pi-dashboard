# Pi Dashboard

A touchscreen dashboard for a Raspberry Pi with a 1920 × 720 screen.
The Pi fetches and stores its own data; nothing else needs to be installed anywhere.

Pages so far:
- **Weather** (`/weather`): radar loop, current conditions, alerts, next 12 hours and 7 days,
  from the US National Weather Service and NOAA (free, no account).

## Install, update, remove

On the Pi, as your normal user:

```bash
curl -sSL https://raw.githubusercontent.com/sniperdude24/pi-dashboard/main/install.sh | bash
```
```bash
~/pi-dashboard/update.sh
```
```bash
~/pi-dashboard/uninstall.sh
```

Uninstall asks whether to keep your settings and saved data (handy when moving to another Pi).

## Where things live

```
~/pi-dashboard/
├── app/             the program (updates replace this)
├── settings.yaml    all settings, one file
├── data/            all saved data
├── update.sh
└── uninstall.sh
```

The program runs in the background as the `pi-dashboard` service and serves the pages at
http://localhost:8090. After editing `settings.yaml`:

```bash
sudo systemctl restart pi-dashboard
```

To see what it's doing: `journalctl -u pi-dashboard -f`

## Moving to another Pi

Copy `settings.yaml` and `data/` to `~/pi-dashboard/` on the new Pi, then run the install command there.

## Developing on a PC

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # .venv/bin/pip on Linux/Mac
cp settings.example.yaml dev/settings.yaml
.venv/Scripts/python -m dashboard --settings dev/settings.yaml --data dev/data
```

Then open http://localhost:8090/weather (the `dev/` folder is ignored by git).

## Credits

Weather data: National Weather Service. Radar: NOAA/NCEP. Map: Esri.
Icons: [Tabler Icons](https://tabler.io/icons) (MIT). Map tool: [Leaflet](https://leafletjs.com) (BSD-2).
Font: [Inter](https://rsms.me/inter/) (OFL).
