# A new machine

From a laptop with nothing of Adaptive Desktop on it to the full desktop,
paired with your phone: one clone, one command, one reboot, one login.

`bootstrap.sh` is for that first time. On a machine that already has it,
`./install.sh` keeps it current.

## What the laptop needs

- **Ubuntu 22.04 LTS** (Desktop or minimal). Not 24.04: its GNOME 46 cannot
  load this shell ([GNOME_PORT.md](GNOME_PORT.md)). If GNOME is missing, the
  bootstrap installs it.
- x86_64, 30 GB free on `/`, internet, and an account that can use `sudo`.
- Run it from a terminal **inside your desktop**, not over SSH or `su`.

## Before: on the old machine (optional)

Take your settings with you - projects, dock, snippets, commands, templates,
workspace names, notes, and the link's Google project:

```sh
<your checkout>/scripts/adaptive-backup.py export --notes ~/adaptive-settings.tar.gz
```

Copy that file to the new laptop. The export never carries the old computer's
link identity or paired phones (each computer has its own key, so the phone
pairs with the laptop as a second computer), nor passwords or accounts.

The Agent Office's work (its projects, meetings, ledger) is outside settings;
to bring it too, copy `~/.local/share/adaptive-desktop/agent-office/` across.

## 1. Clone and run

Clone it wherever you like, under any user name: nothing assumes a home
folder or a path (see *Where it lives* in the README). The only rule is no
spaces in the path, which systemd units and desktop entries cannot hold.

```sh
sudo apt install -y git
git clone https://github.com/Karthikai-28/adaptive-desktop.git ~/adaptive-desktop   # or anywhere
cd ~/adaptive-desktop
./bootstrap.sh --restore ~/adaptive-settings.tar.gz    # or just ./bootstrap.sh
```

It asks for your password once and then runs about 30-60 minutes, most of it
building Files and downloading. Leave it alone; it says what it is doing.

| Stage | What it does |
| --- | --- |
| preflight | Checks Ubuntu 22.04, GNOME 42, disk, network; records where the checkout is |
| packages | Every apt package the shell, apps, link and office use (and GNOME itself if missing) |
| groups | Adds you to `plugdev` (USB switches from the phone) and `input` (touchpad gestures) |
| python | `aiortc` into `.local/link-pydeps` (screen as video, away access) |
| terminal | KTERM: Terminator, Zsh, the JetBrainsMono Nerd Font (`--skip terminal` to keep bash) |
| files-fork | Enables source repositories, builds Nautilus 42.6 into `.local/adaptive-nautilus`, links Open in Terminal and nautilus-python into it, routes Files to it inside Adaptive only |
| session | The **Adaptive Desktop** entry on the login screen, with its own dconf database |
| restore | Your old settings, from `--restore FILE` |
| desktop | `./install.sh`: shell, theme, fonts, shortcuts, Settings, gestures, Files inspector, wallpaper, file index, Adaptive Link, Agent Office (started at login); the lid watcher |
| gnome | In the Adaptive session only: the shell extension on, Ubuntu Dock off |
| link-extras | The phone as a webcam and as a second display (kernel modules), its stylus as a drawing pen, USB switches |
| link-cloud | The link's Google project, from `--link-cloud FILE` or the restored settings |
| ollama | Ollama and the office's local model (`--skip ollama` saves a few GB) |
| tailscale | Tailscale, for the Control Center network tile |
| first-login | A one-time helper for your first Adaptive login |

The normal **Ubuntu** session is left exactly as it was: everything Adaptive
sets in GNOME goes into the Adaptive session's own settings database.

If a stage fails, fix what it says and run `./bootstrap.sh` again: finished
stages are skipped, failed ones retried. `./bootstrap.sh --status` shows
where it is; `--list` the stages; `--skip a,b` leaves optional ones out.

### Secure Boot

If the laptop has Secure Boot on, the link-extras stage asks you to choose a
password for the camera and display modules. At the reboot a blue **Perform
MOK management** screen appears: **Enroll MOK → Continue → Yes**, type that
password, **Reboot**. Miss it and those two features stay off until you run
`sudo mokutil --import /var/lib/shim-signed/mok/MOK.der` and reboot again.

## 2. Reboot and log in to Adaptive Desktop

On the login screen pick your name, then the **gear** at the bottom right →
**Adaptive Desktop**, then your password. (Ubuntu stays on the same menu.)

## 3. Finish, in the terminal that opens

A terminal titled *Finish Adaptive Desktop setup* opens by itself and walks
through what only you can do:

1. **Claude Code** sign-in - the Agent Office's manager.
2. **agy** sign-in - the Gemini agents, with the Google account that has AI Pro.
   Quit agy once it shows you are signed in.
3. **Tailscale** - connects the laptop to your tailnet.
4. **Your phone.** If the link's Google project came across, it offers to sign
   the laptop in to your Google account first. Then pairing:
   on the phone open **Adaptive Link → computer icon → add → Scan pairing code**;
   when both screens show the same six digits, press **Pair** on the laptop.
   The phone keeps the old computer too: switch with the computer icon.
5. Optionally, **sudo by fingerprint**: the phone approves `sudo` here (the
   password still works).
6. The checks: `install.sh --status` and the live readiness check.

It removes itself when done. Run `bootstrap.sh --finish` from the checkout
any time to go through it again.

## After

- `Alt+Space` the command palette, `Super+/` every shortcut.
- Agent Office: http://127.0.0.1:8790 (Chrome, for voice input).
- Things to record by hand on this machine (reboot, suspend, external
  monitor, TTY recovery): `scripts/record-live-verification.py status`.
- Optional extras not installed for you: the Codex CLI (the office's first
  backup, [AGENT_OFFICE.md](AGENT_OFFICE.md)) and KDE Connect/GSConnect.

## If something goes wrong

The Ubuntu session is always on the login screen's gear menu and never
changed. From a terminal there: `gnome-extensions disable adaptive-shell@local`
does nothing to it, and the full procedures are in
[RECOVERY_RUNBOOK.md](RECOVERY_RUNBOOK.md). To take Adaptive off again:
`./uninstall.sh --session`.
