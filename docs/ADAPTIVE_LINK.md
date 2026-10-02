# Adaptive Link — this computer, from your phone

Your Android phone as the remote for this computer, at home and away: see and
control the screen (as video, with the computer's sound), trackpad and
keyboard, media remote, presentation controller, run commands, browse and
open files, send files both ways, the clipboard both ways, notifications both
ways, the phone's camera as a webcam, and the machine itself - processes,
drives, network, Bluetooth, displays, sound, services, windows.

Two parts: a daemon on the computer (`services/adaptive-link/`) and an Android
app (`apps/adaptive-link-android/`).

## Who can connect

The devices you pair - a phone, a tablet; up to five. Nothing else.

- **The phone holds a key that cannot be copied.** The app creates a key pair
  inside the phone's secure hardware (StrongBox where the phone has one, the
  TEE otherwise). The private key never exists outside it: not in the app's
  storage, not in a backup, not on another phone you restore to.
- **The computer accepts that key and no other.** Every connection is mutual
  TLS. The computer's trust store is the paired devices' certificates and
  nothing else, so a device without one of those keys cannot finish a
  handshake and never reaches a line of the server's code. The certificate is
  compared with the stored fingerprints a second time before any request is
  handled, which is also how the computer knows which device is asking.
- **Each device can be allowed less.** `link-cli.py phone NAME deny exec`
  keeps one device from something the others may do (pointer and keyboard,
  commands, files, power). A device is never allowed more than the switches
  for all of them; with several paired, the record says which did what.
- **The phone accepts this computer and no other.** The app pins the
  computer's certificate from the pairing code. No certificate authority is
  involved; a different certificate is refused.
- **Nothing listens until a phone is paired**, and switching the link off or
  unpairing closes the port and ends whatever the phone is doing at that
  moment.
- **The internet is refused.** Connections are taken only from private
  network addresses. If a router ever forwarded the port by mistake, it would
  not answer. (`allow_public` in the config turns this off; there is no
  reason to.) Away from home the phone does not come in through a port at
  all: see *Local and away*.
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
- Sign-in trusts your Google account to say which devices are yours. Someone
  who gets into that account can ask to connect, and can see the computer's
  name and addresses; they cannot connect without you pressing Pair on the
  computer - unless auto-approve is on, in which case they would be accepted.
  Keep two-step verification on.
- Everything rests on the computer's user account. Another program running
  as you on the computer can pair a device or read the link's key, as it
  could already read anything else of yours. Unpair from the computer
(`link-cli.py unpair`) if the phone is lost; it takes effect at once.

## Signing in, instead of pairing

The way Apple's devices find each other through an iCloud account, these find
each other through a Google account: your Gmail. There is no private network
to join and nothing else to install on the phone.

1. Once: make your own free Google project (*Your Google project*, below).
2. On the computer, once: `scripts/link-cli.py signin`. It shows a short code;
   enter it at google.com/device on anything you are signed in on. No
   password is typed on the computer.
3. In Adaptive Link on the phone: **Sign in with Google**, and pick the same
   account in Android's own account picker.

No code is scanned or typed. The first time, a window on the computer shows
the phone, the account and six digits, the phone shows the same six, and you
press **Pair**; after that it just connects, from anywhere.

What the account is, and is not:

- **A place for your devices to find each other.** Signed in, the computer
  writes its name, certificate fingerprint and addresses to a small database
  in your project, under your account's id. A rule on that database lets only
  someone signed in as you read or write there. The phone reads the computer
  from it and leaves its request to connect.
- **Not the key to the computer.** Being signed in is permission to ask, not
  to enter. The computer shows the request and you approve it there. What it
  then trusts is the phone's hardware key, exactly as with a pairing code -
  the account only replaces the code. Signing in on another phone later gets
  that phone a request window on the computer, not a connection.
- **Checked by the six digits.** They are computed from both certificates.
  If the account's space had been tampered with - a different computer put
  in place of yours, or a different phone's certificate in the request - the
  two screens would show different digits.
- **Not on the path.** What you do on the computer never passes through
  Google. It goes directly between the two devices, inside the same mutual
  TLS as at home. Google carries only the few lines the two exchange to find
  each other.
- **Another account gets nothing.** A phone signed in to a different account
  has a different space: it does not see the computer, and nothing it writes
  reaches it.

If you want devices of your own account accepted without asking - closer to
how Apple's behave once you are signed in - turn it on:
`scripts/link-cli.py allow auto-approve on`. Then your Google account's
security is all that stands between anyone and this computer, and the six
digits are no longer compared by anybody, so only do that with two-step
verification on.

`scripts/link-cli.py signout` signs the computer out and removes it from the
account. `scripts/link-cli.py allow account off` leaves it signed in but
stops it listening to the account; pairing codes are then the only way in.

The difference from Apple that remains: Apple runs the account, the servers
and the devices. Here the account is Google's, the meeting place is a project
you own, and the trust between your devices is this project's.

## Your Google project

The meeting place is a Firebase project of your own, on the free plan: no
card, and this use is far inside its limits. It takes about ten minutes, once.

1. https://console.firebase.google.com → **Add project**. Analytics is not
   needed.
2. **Build → Authentication → Get started → Sign-in method → Google →
   Enable.**
3. **Build → Realtime Database → Create database** (locked mode), then under
   **Rules**:

   ```json
   {
     "rules": {
       "users": {
         "$uid": { ".read": "auth != null && auth.uid === $uid",
                   ".write": "auth != null && auth.uid === $uid" }
       }
     }
   }
   ```

   This is the whole of who may see what: each signed-in person, their own
   part, and nothing else. Anybody may sign in to the project with a Google
   account; all it gets them is an empty space of their own.
4. **Project settings → Your apps → Android**: package
   `com.karthi.adaptivelink`, and the SHA-1 of the key the app is built with
   (`keytool -list -v -keystore ~/.android/debug.keystore -storepass android`).
5. https://console.cloud.google.com/apis/credentials (the same project) →
   **Create credentials → OAuth client ID → TVs and Limited Input devices**.
   This is what lets the computer sign in by showing a code.

Five values come out of that:

| Value | Where |
| --- | --- |
| Web API key | Project settings → General |
| Database URL | Realtime Database, at the top of the Data tab |
| Web client ID | Credentials → "Web client (auto created by Google Service)" |
| Device client ID and secret | the "TVs and Limited Input devices" client |

Give them to the computer with `scripts/link-cli.py setup` (kept in
`~/.config/adaptive-desktop/link/cloud.json`, readable by you only), and the
first three to the app in `apps/adaptive-link-android/cloud.properties` before
building it:

```
api_key=...
database_url=https://...firebasedatabase.app
web_client_id=...apps.googleusercontent.com
```

Neither file is tracked. Without them everything still works by pairing
code, on the local network only. None of the values is a password - they
identify the project, and the rule above is what protects it - but they are
yours, which is why they are not in the repository.

## Pairing by code

1. On the computer: Command palette (Alt+Space) → **Pair Phone**, or
   `scripts/link-cli.py pair`. A window shows a QR code for two minutes.
2. In the app: **Scan pairing code**.
3. Both screens show the same six digits. They are derived from both
   certificates, so if anything sat between the two devices the digits would
   differ. Press **Pair** on the computer.

The QR code carries the computer's addresses, its certificate fingerprint and
a one-time code. The pairing port is open only during those two minutes,
takes one phone, and closes after five wrong codes. Pairing another device
adds it beside the first; `link-cli.py status` lists them, and
`link-cli.py unpair NAME` forgets one (without a name, all of them).

## Local and away

At home the phone reaches the computer directly over Wi-Fi.

Away, with both signed in to the account, the two connect **directly to each
other** across the internet. Each tells the other, through the account's
space, the addresses it can be reached at; they then open a connection
straight between them (WebRTC, the way a video call does), and the link runs
inside it unchanged: the same pinned certificate, the same hardware key, the
same mutual TLS. The app tries the home addresses first and falls back to
this by itself; the home screen says which it is using.

What that means for the computer:

- **No port is opened to the internet**, on the computer or the router. The
  connection is made outwards from both ends.
- **Only the link is reachable through it.** The connection ends at the
  link's own port and nowhere else: nothing else running on the computer can
  be reached through it, whatever it listens on.
- **No server in the middle, unless it is yours.** By default there is no
  relay, so nobody else carries the traffic. The cost is that a few networks
  make a direct connection impossible (some mobile carriers and locked-down
  office Wi-Fi put every device behind an address that changes per
  destination). On those the app says a direct connection could not be made.
  If you need to get through from such a network, run a relay of your own -
  see *A relay of your own* below.
- Google's public STUN server is asked one question by each end - "what
  address do you see me at?" - and nothing else.

### A relay of your own

A relay is a small server on the internet that both devices can reach, which
passes their packets on when they cannot reach each other (a TURN server;
`coturn` is the usual one, on any machine with a public address). The link
does not come with one and never uses anyone else's. If you run one:

```sh
scripts/link-cli.py relay turn:relay.example.org:3478 USER   # asks for the password
scripts/link-cli.py relay                                    # which relay, if any
scripts/link-cli.py relay off
```

The computer keeps the address and password in a private file and tells each
paired phone the next time it connects (over the link, so only a paired phone
learns it). From then on both offer the relay beside the direct way, and the
connection uses it only where the direct way fails. What goes through it is
the same tunnel with the same mutual TLS inside: the relay sees how much is
sent and between which addresses, and cannot read or alter any of it.

### Waking a sleeping computer

A computer that is asleep cannot be reached, but its network card can be left
listening for one particular packet (wake-on-LAN). `scripts/link-cli.py wake
on` sets the connections in use to do that; the phone remembers where to send
the packet, and offers **Wake it** when it cannot reach the computer.

It only works on the computer's own network (the packet is a broadcast, which
routers do not pass on), reliably only over Ethernet (few Wi-Fi cards wake
the machine), and from a full shutdown only if the firmware allows it.

A pairing code can also be typed instead of scanned (the pairing window can
copy it as text). Pairing by code needs the phone on the computer's network;
pairing by signing in does not.

If the phone cannot connect on Wi-Fi, check the firewall: `sudo ufw status`,
and if it is active, `sudo ufw allow 47823/tcp` and, for pairing,
`sudo ufw allow 47824/tcp`.

## Setting it up

```sh
./install.sh --only link          # the daemon, as a user service
scripts/build-link-app.sh         # the app: dist/adaptive-link.apk
scripts/build-link-app.sh --install   # ...and onto the phone over USB
scripts/install-link-camera.sh    # once, sudo: the virtual webcam
scripts/install-link-usb.sh       # once, sudo: switching USB devices off and on
scripts/link-cli.py setup         # once, with a Google project: its five values
scripts/link-cli.py signin        # ...and sign in; or, with no account:
scripts/link-cli.py pair
```

The app is not on the Play Store; it is installed from the APK. Over USB that
needs Developer options → USB debugging on the phone. Or copy
`dist/adaptive-link.apk` to the phone and open it there.

The daemon needs `aiohttp` and `cryptography` (`pip install --user aiohttp
cryptography`), `xdotool` and `xclip`. The direct connection used away from
home, and the screen as video, need `aiortc`, kept apart from the system's
Python packages because it brings newer versions of some of them:
`pip install --target .local/link-pydeps aiortc`. Without it the link works
on the local network only and the screen is sent a picture at a time.

## What the phone can do

| In the app | On the computer |
| --- | --- |
| Screen | The screen as video with the computer's sound (three qualities), or a picture at a time where video cannot be had; tap to click, drag to drag, long-press for right-click, pinch to zoom, a scroll mode, a keyboard |
| Trackpad | Relative pointer, a scroll strip, both buttons, a keyboard with the keys a phone lacks |
| Media | Whatever is playing (MPRIS): play, pause, next, previous, seek, volume |
| Presenter | Next and previous slide (also on the phone's volume buttons), start, blank, end, a timer |
| Run | A command, with its output; or started and left running (a player, an app). Commands you run often are kept as buttons |
| Files | Browse, open a file on the computer (play a movie), download to the phone, send a file to `~/Downloads/Phone` |
| Webcam | The phone's camera as "Phone Camera" in any app that takes a webcam |
| Tasks | Load, memory and disks, the battery (time left, wear), temperatures and fans, the power profile; the processes, found by name; pause, resume, end or kill one of yours, alone or with everything it started; make it less important |
| Devices | What is plugged in over USB, each switched off and on (as if unplugged); the drives: browse, mount, unmount, safely remove |
| Network | Each connection with its addresses and its speed; Wi-Fi on and off, the networks in range and joining one (with its password if it is new), connecting and disconnecting, VPNs up and down |
| Desktop | Projects, focus, window placement, reports, quick notes, appearance, saving the session |
| Windows | The windows that are open: bring one to the front, minimise it, move it to the next display, close it |
| Display | Brightness; each display on or off, its size, which is the main one. Where sound comes out and which microphone is used, the volume of each, mute |
| Bluetooth | On and off; the devices the computer knows, each connected and disconnected |
| Services | Your own services (systemd, `--user`): start, stop, restart, and what each last wrote |
| More | Clipboard both ways, lock, unlock, screen off, suspend, restart, shut down, the phone's notifications on the computer, the computer's alerts and notifications on the phone, unpair |

And without opening the app:

- **Share** in any other app → *Send to computer*: a link opens in the
  computer's browser, text goes to its clipboard or the project's notes,
  files go to `~/Downloads/Phone`.
- **A home-screen widget and quick-settings tiles**: lock the computer,
  play/pause, next, mute, focus. Only what is harmless to do by accident:
  nothing that unlocks the computer, runs a command or turns it off is
  reachable without the app's own lock.
- **Alerts** (More → *The computer's alerts and notifications*): a disk
  nearly full, memory running out, a low battery, a hot processor, a device
  plugged in or taken out, a service that failed, a command you started from
  the phone and left running that has finished. With the second switch, the
  computer's own notifications too. The phone keeps a connection open for
  these and says so in its notification shade; what it missed while out of
  reach it is given on coming back.

Switches on the computer narrow that, each taking effect at once:

```sh
scripts/link-cli.py allow input off    # watch only: no pointer, keyboard or launching apps,
                                       # and no change to the network, the drives, USB or the desktop
scripts/link-cli.py allow exec off     # no Run screen and no Tasks screen
scripts/link-cli.py allow files off    # no file access
scripts/link-cli.py allow power off    # no lock, unlock, suspend, restart, power profile
scripts/link-cli.py allow notifications off   # the computer's notifications stay on the computer
scripts/link-cli.py phone NAME deny exec      # one device only; "allow" lifts it
scripts/link-cli.py off                # nothing at all, until "on"
```

They are not independent, and it is better to know it than to trust a switch
that does less than its name: while `input` is on, the phone has a keyboard,
and a keyboard can type a command into a terminal or open a file, whatever
`exec` and `files` say. To stop the phone acting on the computer, turn
`input` off as well. The clipboard, media controls and the phone's
notifications are always available to the paired phone.

### The screen as video

The screen used to be sent as one JPEG after another, each whole. It is now
video: the phone and the computer set up a media connection (the same WebRTC
the direct tunnel uses), the screen is encoded as H.264 or VP8 - which send
only what changed - and what the computer is playing goes with it as Opus.
The offer and the answer travel over the link, so only a paired device can
set it up, and the media is encrypted between the two with keys agreed in
that exchange. Pointer and keyboard keep their own socket.

If the two cannot make that connection the app says so and falls back to
JPEG frames by itself; *Video: off* in the screen's menu chooses that
outright. Sound needs PulseAudio (or PipeWire's stand-in for it) on the
computer; without it the picture is sent alone.

### Changes that could cut the phone off

The phone reaches the computer over the network, so some of what it can now
change would end the conversation: turning Wi-Fi off, joining another
network, disconnecting, bringing a VPN up, switching off the USB adapter the
network comes through. The app asks before each of these, and the computer
does not take the phone's word that it went well. After such a change the
phone has 45 seconds to come back over the link and say it can still reach
the computer; if it does not, the computer undoes the change and records
that in the audit log. A phone that was on the old network and finds the
computer on the new one (through the account, see *Local and away*) counts
as coming back.

What the computer is changed through is what it would be changed through at
its own keyboard: NetworkManager for the network, UDisks for the drives, the
owner's own permissions for processes. So the phone cannot do what the owner
could not: stop another user's process, make a process more important than
it was, or unmount the drive the computer runs from (that one is refused
before anything is asked). USB devices are the exception - their switch is
the system's until `scripts/install-link-usb.sh` hands it to the owner.
A Wi-Fi password typed on the phone is given to NetworkManager as input,
never as part of a command line that other programs could read.

## How it is checked

- `scripts/verify-link.py` — the decisions as functions, then the real daemon
  on a virtual display: a client with the paired certificate, and three
  things that are not the phone (another certificate, no certificate, the
  wrong pairing code). Then the account, against a stand-in for Google
  (`scripts/fake_cloud.py`) that enforces the database's rule: signing in by
  code, a phone of the account asking and being approved, a phone of another
  account seeing nothing, and the link used through a direct connection. It
  never locks, suspends or changes the volume of the machine it runs on: the
  network, drives, Bluetooth, sound devices, services and power profiles it
  changes are stand-ins (`scripts/fake_system_tools.py`), not the machine's
  own. The screen as video is received by a second WebRTC peer in the check
  itself.
- `scripts/verify-link-android.py` — the Android code itself, on an emulator
  (`scripts/link-emulator.sh`): the keystore key, pairing, mutual TLS, a
  screen frame, a command, the computer reached through a direct connection
  when none of its addresses answers, an impostor computer and a replaced
  key; then the app itself - signing in, every screen opened and every
  control pressed, and a command typed on the phone's own screen.
- The app's unit tests check that the phone computes the same pairing digits
  and fingerprints as the computer's code.

What that leaves for a real phone is in `record-live-verification.py`: your
own device, Google's real sign-in (the emulator has no Google account, so the
checks hand the app a stand-in's answer), the direct connection from mobile
data, the camera, and everything that was checked only against a stand-in:
the real NetworkManager and UDisks (turning Wi-Fi off and having it come
back, joining a network with its password, removing a real drive), real
Bluetooth, displays and sound devices, waking the computer from sleep, the
computer's sound on the phone, a relay, and the widget and tiles on a real
home screen.

## Known limits

- X11 only, like the rest of the desktop's window handling
  (`docs/GNOME_PORT.md`): screen capture is `ximagesrc`, input is `xdotool`.
- Video is encoded in software on the computer (aiortc), up to about 3 Mbit/s:
  good for work, not for watching a film full-screen.
- A sleeping computer can be woken only on its own network, and in practice
  only over Ethernet (see *Waking a sleeping computer*).
- Away from home, on a network that forbids direct connections, the phone
  cannot reach the computer unless you run a relay of your own.
- The widget and the tiles act without the app's lock; they are limited to
  what is safe for that (see above).
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
