# Adaptive Link — this computer, from your phone

Your Android phone as the remote for this computer, at home and away: see and
control the screen, trackpad and keyboard, media remote, presentation
controller, run commands, browse and open files, send files both ways, the
clipboard both ways, your phone's notifications on the computer, and the
phone's camera as a webcam.

Two parts: a daemon on the computer (`services/adaptive-link/`) and an Android
app (`apps/adaptive-link-android/`).

## Who can connect

One phone. Nothing else.

- **The phone holds a key that cannot be copied.** The app creates a key pair
  inside the phone's secure hardware (StrongBox where the phone has one, the
  TEE otherwise). The private key never exists outside it: not in the app's
  storage, not in a backup, not on another phone you restore to.
- **The computer accepts that key and no other.** Every connection is mutual
  TLS. The computer's trust store is the paired phone's certificate and
  nothing else, so a device without the key cannot finish a handshake and
  never reaches a line of the server's code. The certificate is compared with
  the stored fingerprint a second time before any request is handled.
- **The phone accepts this computer and no other.** The app pins the
  computer's certificate from the pairing code. No certificate authority is
  involved; a different certificate is refused.
- **Nothing listens until a phone is paired**, and switching the link off or
  unpairing closes the port and ends whatever the phone is doing at that
  moment.
- **The internet is refused.** Connections are taken only from private
  network addresses and Tailscale's. If a router ever forwarded the port by
  mistake, it would not answer. (`allow_public` in the config turns this off;
  there is no reason to.)
- **The app locks itself.** It asks for your fingerprint or screen lock each
  time it is opened, hides its contents from screenshots and the recent-apps
  list, and is excluded from Android backups.
- **There is a record.** Everything the phone does is written to
  `~/.local/state/adaptive-desktop/link.log` (`link-cli.py log`), and the
  computer shows a notification when the phone connects.

What this does not protect against:

- Someone who has your unlocked phone and can pass its screen lock has what
  you have. The app stays open for fifteen seconds after you leave it.
- With `allow power` on, the phone can unlock the computer's screen. That is
  what "complete control" means, and it is also what someone holding your
  open phone would have.
- Sign-in trusts your Tailscale network. Anyone you share a device into that
  network with, or who gets into the account it is signed in with, can ask to
  connect; with auto-approve on they would be accepted.
- Everything rests on the computer's user account. Another program running
  as you on the computer can pair a device or read the link's key, as it
  could already read anything else of yours. Unpair from the computer
(`link-cli.py unpair`) if the phone is lost; it takes effect at once.

## Signing in, instead of pairing

The way Apple's devices find each other through an iCloud account, these find
each other through the account both are signed in to on Tailscale - which can
be a Google account, so in practice: your Gmail.

1. On the computer, once: `scripts/install-link-tailnet.sh`, and sign in.
2. On the phone, once: install Tailscale, sign in with the same account.
3. In Adaptive Link on the phone: **Find my computer**.

No code is scanned or typed. The phone looks the computer up by its name on
your private network (`adaptive-link`), the computer asks Tailscale who is
calling, and if it is a device signed in to the computer's own account it may
ask to connect. The first time, a window on the computer shows the device,
the account and six digits, and you press **Pair**; after that it just
connects.

What makes this trustworthy:

- **The account is Tailscale's word, not the phone's.** The computer never
  believes what a device says about itself. It asks its own Tailscale node
  who is on the other end of the connection, and Tailscale answers from the
  keys that device signed in with.
- **Another account gets nothing.** A device on someone else's account, or
  not on Tailscale at all, is refused before it learns the computer's name or
  certificate, and no request ever reaches you.
- **Being on your account is permission to ask, not to enter.** You still
  approve each new device once, on the computer. If you want devices of your
  own account accepted without asking - closer to how Apple's behave once you
  are signed in - turn it on:
  `scripts/link-cli.py allow auto-approve on`. Then your Google account's
  security (its password and two-step verification) is what stands between
  anyone and this computer, so only do that with two-step verification on.
- **The phone only asks inside Tailscale.** The one question the app asks a
  computer it does not know yet ("who are you?") is only ever sent to an
  address in Tailscale's own range, so an ordinary network can never answer
  in the computer's place.
- **After that, nothing changes.** The phone's hardware key and mutual TLS
  are exactly as before; the account only replaces the pairing code.

`scripts/link-cli.py allow account off` turns sign-in off and leaves pairing
codes as the only way in.

The difference from Apple that remains: Apple runs the account, the network
and the devices. Here the account is Google's, the private network is
Tailscale's, and the trust between your devices is this project's.

## Closing the rest of the computer

**Do this once after signing the computer in.** The link's Tailscale node runs
in userspace, which is why it needs no root - and the consequence is that any
connection it is allowed to receive is handed to that port on this machine's
own loopback. Tailscale's default policy allows every port between your
devices. Together that means every service listening on this computer,
*including ones bound to localhost only* (a development database, a local AI
server, a print service), can be reached from your other devices on the
account - and so by any app on your phone.

`scripts/link-cli.py status` warns while that is so. Close it by telling
Tailscale that only the link's two ports are reachable on this computer. In
the admin console, **Access controls** (https://login.tailscale.com/admin/acls),
replace the policy with:

```json
{
  "hosts": { "adaptive-link": "100.x.y.z" },
  "acls": [
    { "action": "accept", "src": ["autogroup:member"], "dst": ["adaptive-link:47823-47824"] }
  ]
}
```

with the computer's Tailscale address from `link-cli.py status` in place of
`100.x.y.z`. Your devices can then reach Adaptive Link on this computer and
nothing else on it. (This policy also stops your devices reaching each other
on other ports; add rules for anything else you use Tailscale for.) The
warning goes away within a minute of saving.

The alternative that needs no policy is the system Tailscale
(`sudo tailscale up`), which does not hand connections to loopback; services
bound to localhost stay private, though ones bound to every interface are
reachable as they already are on your Wi-Fi.

## Pairing by code

1. On the computer: Command palette (Alt+Space) → **Pair Phone**, or
   `scripts/link-cli.py pair`. A window shows a QR code for two minutes.
2. In the app: **Scan pairing code**.
3. Both screens show the same six digits. They are derived from both
   certificates, so if anything sat between the two devices the digits would
   differ. Press **Pair** on the computer.

The QR code carries the computer's addresses, its certificate fingerprint and
a one-time code. The pairing port is open only during those two minutes,
takes one phone, and closes after five wrong codes. Pairing another phone
replaces the first.

## Local and away

At home the phone reaches the computer directly over Wi-Fi. Away, it comes
through **Tailscale**: a private network between your own devices, so the
computer is never exposed to the internet and nothing on your router changes.
The app tries every address at once and uses whichever answers.

The link has its own Tailscale node on the computer, which needs no root:

```sh
scripts/install-link-tailnet.sh    # prints a sign-in link the first time
```

Open the link, sign in (a Google account works), and install Tailscale on the
phone with the same account. The computer then has a name on your private
network - `<host>-link.<your-tailnet>.ts.net` - that identifies it rather than
where it is, so the phone reaches it from any network. The pairing code
carries that name first and the numeric addresses as fallbacks, and the
computer tells the phone its current addresses on every connection, so a
changed address at home never means pairing again.

A pairing code can also be typed instead of scanned (the pairing window can
copy it as text), for when the phone is not in front of the computer.

If the phone cannot connect on Wi-Fi, check the firewall: `sudo ufw status`,
and if it is active, `sudo ufw allow 47823/tcp` and, for pairing,
`sudo ufw allow 47824/tcp`.

## Setting it up

```sh
./install.sh --only link          # the daemon, as a user service
scripts/build-link-app.sh         # the app: dist/adaptive-link.apk
scripts/build-link-app.sh --install   # ...and onto the phone over USB
scripts/install-link-camera.sh    # once, sudo: the virtual webcam
scripts/link-cli.py pair
```

The app is not on the Play Store; it is installed from the APK. Over USB that
needs Developer options → USB debugging on the phone. Or copy
`dist/adaptive-link.apk` to the phone and open it there.

The daemon needs `aiohttp` and `cryptography` (`pip install --user aiohttp
cryptography`), `xdotool` and `xclip`.

## What the phone can do

| In the app | On the computer |
| --- | --- |
| Screen | The screen as JPEG frames (three qualities); tap to click, drag to drag, long-press for right-click, a scroll mode, a keyboard |
| Trackpad | Relative pointer, a scroll strip, both buttons, a keyboard with the keys a phone lacks |
| Media | Whatever is playing (MPRIS): play, pause, next, previous, seek, volume |
| Presenter | Next and previous slide (also on the phone's volume buttons), start, blank, end, a timer |
| Run | A command, with its output; or started and left running (a player, an app) |
| Files | Browse, open a file on the computer (play a movie), download to the phone, send a file to `~/Downloads/Phone` |
| Webcam | The phone's camera as "Phone Camera" in any app that takes a webcam |
| More | Clipboard both ways, lock, unlock, screen off, suspend, restart, shut down, the phone's notifications on the computer, unpair |

Switches on the computer narrow that, each taking effect at once:

```sh
scripts/link-cli.py allow input off    # watch only: no pointer, keyboard or launching apps
scripts/link-cli.py allow exec off     # no Run screen
scripts/link-cli.py allow files off    # no file access
scripts/link-cli.py allow power off    # no lock, unlock, suspend, restart
scripts/link-cli.py off                # nothing at all, until "on"
```

They are not independent, and it is better to know it than to trust a switch
that does less than its name: while `input` is on, the phone has a keyboard,
and a keyboard can type a command into a terminal or open a file, whatever
`exec` and `files` say. To stop the phone acting on the computer, turn
`input` off as well. The clipboard, media controls and the phone's
notifications are always available to the paired phone.

## How it is checked

- `scripts/verify-link.py` — the decisions as functions, then the real daemon
  on a virtual display: a client with the paired certificate, and three
  things that are not the phone (another certificate, no certificate, the
  wrong pairing code). It never locks, suspends or changes the volume of the
  machine it runs on.
- `scripts/verify-link-android.py` — the Android code itself, on an emulator
  (`scripts/link-emulator.sh`): the keystore key, pairing, mutual TLS, a
  screen frame, a command, an impostor computer and a replaced key, then
  every screen of the app opened and read back, and a command typed on the
  phone's own screen.
- The app's unit tests check that the phone computes the same pairing digits
  and fingerprints as the computer's code.

What that leaves for a real phone is in `record-live-verification.py`: your
own device, Tailscale from mobile data, and the camera.

## Known limits

- X11 only, like the rest of the desktop's window handling
  (`docs/GNOME_PORT.md`): screen capture is `ximagesrc`, input is `xdotool`.
- The screen is a stream of JPEG frames, not video: simple and robust, but it
  uses more data than a video codec would. Use the low quality away from
  Wi-Fi.
- No sound from the computer on the phone.
- The computer must be awake. A suspended laptop cannot be woken from the
  phone.
- Android only.

## Building the app from scratch

The SDK, emulator and test device are kept out of the repository, in
`.local/android-sdk`:

```sh
mkdir -p .local/android-sdk && cd .local/android-sdk
# command-line tools from https://developer.android.com/studio#command-line-tools-only,
# unpacked to cmdline-tools/latest, then:
cmdline-tools/latest/bin/sdkmanager --sdk_root=$PWD \
    "platforms;android-35" "build-tools;35.0.0" "platform-tools" \
    "emulator" "system-images;android-34;default;x86_64"
```

Gradle 8.13 and JDK 17 or newer build it (`scripts/build-link-app.sh`).
