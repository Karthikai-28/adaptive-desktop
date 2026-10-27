# Adaptive Home on the TV

A launcher installed on the LG TV (webOS 22, `[LG] webOS TV UQ7500PSF`) that shows every app on
the TV, its inputs and its power controls in the Adaptive look. It runs on the TV by itself: the
laptop is only needed to install or update it. Source: `apps/adaptive-tv/`.

What it is not: a replacement for LG's own home. The Home button, the LG launcher bar and the
system menus belong to the firmware and stay. Pin Adaptive Home first in the LG launcher bar so
it is one press away.

## What is on it

- **Favourites**: pinned apps (Blue button pins or unpins the focused app), then the most opened,
  then the rest in the order of the LG launcher bar.
- **Inputs**: AV and HDMI 1-3, named after the device on them (HDMI-CEC, e.g. "PlayStation 5"),
  with a green badge when something is connected.
- **All apps**: every launch point on the TV with its own icon and brand colour.
- **TV**: TV settings, Screen off (sound keeps playing), Turn off (OK twice), Weather city, Refresh.
- Clock, date, greeting, and the weather from Open-Meteo once a city is chosen.
- The focused tile lights the room in its brand colour. Remote arrows, OK and Back, or the Magic
  Remote pointer, work.

## How it works

| Part | File | Job |
| --- | --- | --- |
| Page | `app/index.html`, `home.css`, `home.js` | Draws the rows, moves focus, remembers pins, counts, the city and the icons in `localStorage` |
| Logic | `app/model.js` | Tiles from the TV's lists, favourites order, arrow-key navigation; pure, checked by `scripts/verify-tv-home.js` |
| Service | `service/service.js` | A webOS JS service in the same package: `home`, `icon`, `launch`, `input`, `power` |
| Socket | `service/ssap.js` | A WebSocket client in plain Node for the TV's own control socket, `wss://127.0.0.1:3001` |

The page can't talk to the TV's control socket itself: webOS 22 answers only on `wss` port 3001
with a self-signed certificate, and plain `ws` on port 3000 refuses the handshake. The service
skips certificate checking and holds the socket. The icons are on the same port with the same
certificate, so the service fetches them and the page caches them as `data:` URLs.

The first connection shows the TV's "Allow?" prompt; the client key is kept by the page and passed
on every call. It is the same pairing the laptop's Cast app did, but separate: the TV app has its
own key.

## Install and update

On the TV, once:

1. Install **Developer Mode** from the LG Content Store and sign in with an LG developer account
   (free, developer.lge.com).
2. Turn **Dev Mode Status** on (the TV restarts), then turn **Key Server** on.

On the laptop:

```sh
./scripts/install-tv-home.sh --setup      # once; the TV's address comes from Cast's pairing
./scripts/install-tv-home.sh              # package, install, open; run again after changes
./scripts/install-tv-home.sh --package    # only build dist/tv-home/*.ipk
./scripts/install-tv-home.sh --remove
```

The webOS CLI is pinned (`@webos-tools/cli` 3.2.6) in `.local/webos-cli`.

## Gotchas

- **The Developer Mode session runs out.** Extend it in the Developer Mode app on the TV before it
  does; if it lapses, the TV removes apps installed this way, and the install command puts it back.
- Pins, counts and the city live in the app's `localStorage` on the TV, so reinstalling after a
  lapse may lose them.
- **Previews.** Headless Chrome's `--window-size` includes window chrome: use `1920,1167` to get a
  1080-high viewport. It also doesn't fast-forward CSS transitions, so turn motion off for still
  screenshots.
- The page must stay simple enough for the TV's Chromium and small GPU: transforms and opacity
  for motion, with no animated blur.
