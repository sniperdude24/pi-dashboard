# Pi Dashboard

A touchscreen dashboard for a Raspberry Pi with a 1920 × 720 screen.
The Pi fetches and stores its own data; nothing else needs to be installed anywhere.

The screen (`/`) rotates through the pages, each for as long as you choose. Touch it to
show a control bar (previous / next / pause / settings), or swipe to change pages.

Pages so far:
- **Weather** (`/weather`): radar loop, current conditions, alerts, next 12 hours and 7 days,
  from the US National Weather Service and NOAA (free, no account).
- **Flights** (`/flights`): live planes around home from an ADS-B feed (tar1090 / ultrafeeder
  `aircraft.json`), with airline routes from adsbdb.com when they make sense.
- **Backyard** (`/backyard`): the live camera (left, from the recorder's copy of the camera,
  passed through by ffmpeg without re-encoding) and the last-hour timelapse (right, downloaded
  from the reolink-timelapse server with the `dashboard` account). Both only play while the page
  is on screen. Logins go in `settings.yaml` under `backyard:`.
- **Pi-hole** (`/pihole`): totals for the last 24 hours, blocking on/off, a 24-hour chart, most
  blocked sites and busiest devices, read (only) from the Pi-hole v6 API with an app password.
- **Settings** (`/settings`): page order and timing, what each page shows, night dimming.
  Changes save to `settings.yaml`. Only the touchscreen itself can change settings
  (other computers see them read-only) unless `allow_settings_from_network: true`.

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

## Full screen at startup (per Pi)

```bash
~/pi-dashboard/kiosk.sh on
```

The Pi then opens the dashboard full screen every time it starts (it needs to log in to
the desktop automatically, which Raspberry Pi OS does by default). `kiosk.sh off` undoes it.
To get back to the desktop by touch: Settings → Screen → Exit to desktop. The
"Pi Dashboard" icon on the desktop brings it back.

If the screen shows the wrong size (some screens don't report their size to the Pi),
add `video=HDMI-A-2:1920x720@60` to the end of the single line in
`/boot/firmware/cmdline.txt` (HDMI-A-1 for the other port) and restart.

## Where things live

```
~/pi-dashboard/
├── app/             the program (updates replace this)
├── settings.yaml    all settings, one file
├── data/            all saved data
├── update.sh
├── kiosk.sh
└── uninstall.sh
```

The program runs in the background as the `pi-dashboard` service and serves the pages at
http://localhost:8090. Changes typed into `settings.yaml` are picked up within a few seconds
(a typo is ignored and the previous settings kept). Changing the port or location needs:

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
