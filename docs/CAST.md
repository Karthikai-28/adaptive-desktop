# Cast - this laptop on the TV

`apps/adaptive-cast/` shows the laptop's screen on a TV over Miracast (Wi-Fi
Display over Wi-Fi Direct), and does the things around it: gets the TV ready,
keeps private things off it, and plays media on the TV without mirroring.
Built and tried against an LG webOS UQ7500PSF; the Wi-Fi card is a Qualcomm
QCA6174 (ath10k), which NetworkManager exposes as `p2p-dev-wlp2s0`.

## Ways in

| From | What |
| --- | --- |
| App grid | **Cast** (`com.karthi.AdaptiveCast`): TVs nearby, live preview, tabs for Picture, Overlay, Privacy, TV, Media |
| `Super+K` | cast to the last TV, or stop (`install-keybindings.sh`) |
| Control Center | **Screen Cast** tile: tap toggles, the arrow opens the window |
| Dynamic Island | a **Cast** activity while connecting or live; its card has Freeze, Curtain, Open, Stop |
| Palette | `cast` mode: cast, cast this window, stop, freeze, curtain, quality; a YouTube link or a media path plays on the TV |
| Files | right-click a video, song or photo: **Play on the TV** |
| Phone | Adaptive Link actions in `~/.config/adaptive-desktop/actions.d/cast-*.json` ("cast", "stop casting", "freeze tv", ...); the Cast window also opens on the phone as a laptop app and stacks to fit |
| Terminal | `scripts/adaptive-cast-launch.sh --toggle | --cast NAME | --stop | --show screen|window|left|right | --set KEY=VALUE | --freeze | --curtain [TEXT] | --resume | --play FILE | --media play|pause|stop | --youtube URL | --wall | --status` |

One copy runs; every later call hands it its command (GApplication command
line). Callers that wait for the command to finish (the shell, Adaptive Link)
use `scripts/adaptive-cast-action.sh`, which returns at once.

## How a cast goes

```
controller.Cast.start
  tv.TvControl.prepare     webOS: Wake-on-LAN if off, note the app on screen, open Screen Share
  audio.AudioRoute.start   apps play into a Cast_to_TV null sink (TV / laptop / both)
  session.Session.listen   RTSP server on :7236
  p2p.WifiDirect.connect_to  volatile wifi-p2p connection with our WFD IE (source, port 7236)
     TV joins, opens RTSP: M1-M7 (wfd.py picks the mode from the TV's list and the preset)
  stream.Stream            ximagesrc -> cairooverlay -> vaapih264enc -> mpegtsmux -> RTP/UDP
  desk.*                   banners off, no sleep; undone after, even after a crash
stop: TEARDOWN, link down, sound and banners back, TV back to what it showed
```

State is published to `$XDG_RUNTIME_DIR/adaptive-cast.json` on every change;
`shell/.../castStatus.js` watches it for the tile and the island (which goes
private while the TV is live, like a GNOME screencast).

## Options (`~/.config/adaptive-desktop/cast.json`, 0600)

Quality presets (`wfd.QUALITY`): Sharp 1080p30, Smooth 1080p60, Light 720p30,
Game 720p60. Fit: bars, crop, or a 6% safe margin. Sound: TV, laptop, both.
Overlays: cursor ring or spotlight, clock, badge, caption. Privacy: quiet
banners, black boxes over windows whose class or title matches a list,
Freeze (holds the last frame), Curtain (clock and a line). Record keeps a
Matroska copy in `~/Videos/Cast`. The file also holds the TV's webOS client
key, which is why it is 0600.

## Gotchas found on this machine

- **Intel encoder:** `vaapih264enc` takes NV12 only, and on this Gen9 iGPU the
  iHD driver refuses CBR/VBR (bitrate control needs HuC firmware the kernel
  does not load). Constant QP it is. The first symptom was a TV that showed a
  black screen and then "screen sharing stopped".
- **X connections:** the cursor overlay reads the pointer on every frame from
  GStreamer's thread. `threading.local` does not survive between those calls
  (each gets a fresh Python thread state), so a per-thread connection leaked
  one X client per frame and exhausted the server in seconds. `desk.Pointer`
  keys connections by OS thread id; `verify-cast.py` counts them.
- **cairooverlay leaves the BGRx padding byte at 0:** anything converted to
  RGBA from it is fully transparent. The preview is RGB.
- **PulseAudio module arguments:** a `device.description` with a space fails
  to load the module; hence `Cast_to_TV`.
- **Stale link events:** a deactivated Wi-Fi Direct connection still reports
  its end; `p2p.py` ignores events from connections it already let go of, or a
  quality change would end the new cast.
- **The TV right after a session** drops the next join for a few seconds; the
  controller retries once after 6 s. After two half-finished joins the TV
  timed out joins (`supplicant-timeout`) until it settled.
- **DLNA on this LG** accepted a file, then stalled in `LG_TRANSITIONING` and
  stopped answering until its media app was closed. Media therefore plays in
  the TV's browser (`player.html`), which streams the same files reliably;
  `ssap://media.viewer/open` does not exist on this firmware.
- **Pairing** is a prompt on the TV, once. Waking from standby needs the TV's
  "Turn on via Wi-Fi" setting.

## Not done

- Extended desktop (the TV as a second monitor): X11 here has no virtual
  output to extend onto.
- The TV remote driving the laptop (Miracast UIBC): the TV is asked for
  `wfd_uibc_capability` and the answer is logged, but nothing uses it yet.
- LPCM audio: mpegtsmux cannot write the WFD LPCM private header, so a TV
  without AAC gets picture only.

## Checks

`scripts/verify-cast.py` (in `verify-all.sh --quick`): WFD elements, RTSP
framing, mode choice and presets, the pipeline run with test sources for
every encoder and fit, all overlays drawn at once, recording, the X
connection count, and the media server's ranges, player page and commands.
Island behaviour is in `verify-dynamic-island.js`, the palette mode in
`verify-feature-logic.py`.
