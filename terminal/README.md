# KTERM Futureproof 3.0.0

KTERM turns a freshly installed Ubuntu workstation or Raspberry Pi into a reversible, visual, keyboard-efficient terminal environment built around **Terminator + Zsh**.

This bundle contains two self-contained installers:

- `install-kterm-ubuntu.sh` — Ubuntu and compatible apt-based desktop/workstation systems.
- `install-kterm-raspberry-pi.sh` — Raspberry Pi OS or Ubuntu running on Raspberry Pi hardware.

Both scripts install the same shell experience. The Raspberry Pi installer adds ARM-aware binary selection, SoC telemetry, and best-effort Labwc/Openbox/PCManFM integration.

> **Future-resilient, not magically guaranteed:** the installers avoid Ubuntu codenames and PPAs, discover packages and desktop APIs at runtime, select binaries by CPU architecture, and degrade optional features safely. No script can guarantee compatibility with every unknown future Ubuntu, Raspberry Pi OS, GNOME, Nautilus, or third-party release. The design fails closed for core requirements and skips optional components when an upstream asset or API is unavailable.

---

## 1. What the installation builds

```text
Ctrl+Alt+T ───────────────┐
Nautilus/PCManFM action ──┼──> mode-aware KTERM launcher
plain Terminator ─────────┘            │
                                      ▼
                            Terminator modern profile
                                      │
                                      ▼
                                     Zsh
                                      │
       ┌──────────────────────────────┼──────────────────────────────┐
       │                              │                              │
  Starship prompt              Visual interaction             Monitoring/TUIs
  startup HUD                  fzf/fzf-tab                    btop / nvtop
  command blocks               Atuin or fzf history           Yazi / LazyGit
  Git/Python/CUDA context      zoxide navigation              tmux dashboard
```

The installer preserves the original `~/.zshrc` and runs it first. Existing PATH entries, aliases, functions, Conda, CUDA, ROS, SSH agents, and project setup remain in place. KTERM is appended as a managed layer afterwards.

Core commands such as `ls`, `cat`, `cd`, `grep`, and `git` are not replaced. Visual alternatives have explicit `k...` names, and short aliases are added only when the name was previously unused.

---

## 2. Compatibility strategy

### Ubuntu installer

Designed for:

- Ubuntu 22.04, 24.04, 26.x and later apt-based Ubuntu releases.
- Debian-family systems with compatible package names when run with `--force`.
- `amd64`, `arm64`, and reduced-fallback support for 32-bit ARM/x86.
- GNOME/Nautilus desktop integration when those APIs are present.
- Headless servers with `--no-desktop`.

### Raspberry Pi installer

Designed for:

- Raspberry Pi OS desktop and Lite variants.
- Ubuntu Desktop/Server on Raspberry Pi.
- 64-bit `arm64` and reduced optional-binary support on `armhf`/`armel`.
- Labwc and legacy Openbox Ctrl+Alt+T configuration.
- Nautilus when Ubuntu Desktop is used, and a PCManFM action where supported.
- Pi telemetry through `vcgencmd`, with thermal-sysfs fallback.

### Why it is more resilient than the earlier iterative setup

1. It uses distro package discovery instead of hard-coded Ubuntu codenames or PPAs.
2. Optional tools are installed only when packages/assets exist; core shell operation remains available when they do not.
3. Atuin is installed only from static MUSL assets and is enabled only after `atuin --version` succeeds, avoiding the GLIBC mismatch seen on Ubuntu 22.04.
4. Ctrl+R is always safe: Atuin replaces fzf history only after its ZLE widget is confirmed to exist.
5. The Nautilus integration is a small bundled extension in the documented user extension directory. It uses variadic provider methods to span Nautilus API 3.x and 4.x rather than pinning a fragile third-party release.
6. Terminator contains identical `default` and `modern` profiles and enables `always_split_with_profile`, so new horizontal/vertical panes keep the same colors and font.
7. The dashboard explicitly splits the right pane and provides command fallbacks, so a missing GPU utility or exited monitor does not silently produce an empty panel.
8. Every destructive integration step has a snapshot or restoration path.

---

## 3. Install on Ubuntu

Copy the bundle to the fresh machine, open a terminal as the normal user, and run:

```bash
cd /path/to/KTERM-Futureproof-v3.0.0
chmod +x install-kterm-ubuntu.sh
./install-kterm-ubuntu.sh
```

Do **not** run `sudo ./install-kterm-ubuntu.sh` or `sudo bash ...`. The installer requests sudo only for apt packages, the login shell, alternatives, and removal/restoration of competing desktop extensions.

After it completes:

```bash
# Log out of Ubuntu and sign in again once.
# Then open Ctrl+Alt+T and run:
kterm-doctor
```

Test the uniform Terminator panes:

```text
Ctrl+Shift+E    vertical split
Ctrl+Shift+O    horizontal split
```

Test the dashboard:

```bash
kdashboard --reset
```

---

## 4. Install on Raspberry Pi

For Raspberry Pi OS Desktop or Ubuntu Desktop on Pi:

```bash
cd /path/to/KTERM-Futureproof-v3.0.0
chmod +x install-kterm-raspberry-pi.sh
./install-kterm-raspberry-pi.sh
```

For Raspberry Pi OS Lite, Ubuntu Server, SSH-only, or a Pi without a GUI:

```bash
./install-kterm-raspberry-pi.sh --no-desktop
```

Log out and reconnect after installation so Zsh becomes the account login shell. On a desktop Pi, also restart the desktop session once so Labwc/Openbox/file-manager integration is fully reloaded.

Check Pi telemetry:

```bash
kgputop
```

On supported Raspberry Pi OS installations this displays temperature, throttling state, ARM clock, and core voltage through `vcgencmd`. Otherwise it falls back to the kernel thermal sensor.

---

## 5. Installer options

| Option | Effect |
|---|---|
| no option | Full idempotent installation. Safe to run again. |
| `--update` | Refresh managed packages, release binaries, plugins, and configuration. |
| `--repair` | Reapply configuration and missing components without running `apt-get update`. |
| `--uninstall` | Remove KTERM-managed integration and restore saved shell/terminal/desktop state where possible. |
| `--no-desktop` | Install Zsh/TUI features only. No Terminator, Ctrl+Alt+T, or file-manager routing. |
| `--desktop` | Force graphical integration even when auto-detection cannot see a running session. |
| `--minimal` | Keep the prompt, shell plugins, fzf, zoxide, tmux, and fallbacks; skip larger optional release binaries. |
| `--no-chsh` | Do not change the account login shell to Zsh. |
| `--force` | Bypass distro/hardware target checks. Use only on an apt-compatible system you understand. |
| `--help` | Show installer usage. |

Optional environment variables:

```bash
GITHUB_TOKEN=... ./install-kterm-ubuntu.sh
KTERM_SKIP_APT_UPDATE=1 ./install-kterm-ubuntu.sh --repair
```

A GitHub token is not required; it only increases unauthenticated API rate limits when current release assets are queried.

---

## 6. Modern/classic mode and recovery

| Command | Purpose |
|---|---|
| `kterm-modern` | Restart the current shell in the complete visual profile. |
| `kterm-classic` | Restart the current shell with the original `~/.zshrc` behavior and no modern enhancement layer. |
| `kterm-system modern` | Make future Ctrl+Alt+T, right-click terminals, and plain Terminator launches modern. |
| `kterm-system classic` | Make all future desktop terminal launches use the saved classic Terminator profile. |
| `kterm-system status` | Show the current desktop/default mode. |
| `kterm-default modern\|classic` | Equivalent future-terminal mode selector. |
| `kterm-safe` | Start `zsh -f`: a clean recovery shell that ignores normal startup files. |
| `kterm-reload` | Restart Zsh in the currently selected mode. |
| `terminator-modern` | Open one explicit modern Terminator window. |
| `terminator-classic` | Open one explicit saved-classic Terminator window. |
| `kterm-terminal` | Internal mode-aware launcher used by desktop integrations. |

A practical rollback sequence is:

```bash
kterm-system classic
kterm-classic
```

Return to the full setup with:

```bash
kterm-system modern
kterm-modern
```

---

## 7. Appearance controls

| Command | Purpose |
|---|---|
| `kprompt rich` | Two-line prompt with OS, user/host, path, Git, language/toolchain, environment, status, duration, jobs, memory/battery, and time where applicable. |
| `kprompt compact` | Compact single-line contextual prompt. |
| `khud on` | Show the KTERM startup HUD in newly opened modern shells. |
| `khud off` | Disable the startup HUD. |
| `khud now` | Render the HUD immediately. |
| `khud status` | Show the persisted HUD setting. |
| `kblocks on` | Show Warp-like `RUN`, `OK`, `ERR`, exit code, and elapsed-time separators around commands. |
| `kblocks off` | Disable visual command separators. |
| `kblocks status` | Show the persisted command-block setting. |

The command separators are visual shell hooks; Terminator remains a traditional terminal buffer and does not gain Warp's selectable GUI command objects.

---

## 8. Visual files, search, and navigation

| Command | Purpose and fallback behavior |
|---|---|
| `kvls [PATH]` | Icon-aware, directory-first listing through eza; falls back to colored `ls`. |
| `kvll [PATH]` | Detailed listing with hidden files, sizes, timestamps, icons, and Git state. |
| `kvtree [DEPTH] [PATH]` | Visual directory tree. Default depth is 3; falls back to `tree` or `find`. |
| `kvcat FILE` | Syntax-highlighted, numbered file viewer through bat; falls back to `cat`. |
| `kvgrep QUERY [PATH]` | Recursive smart-case search through ripgrep; falls back to recursive grep. |
| `kff` | Fuzzy file selector with preview; opens the result in `$VISUAL`, `$EDITOR`, or nano. |
| `kfcd` | Fuzzy directory chooser with visual preview, then changes the current shell directory. |
| `z TEXT` | zoxide smart jump to a frequently/recently used directory. |
| `zi` | Interactive zoxide directory picker. |
| `kyazi [PATH]` | Yazi terminal file manager; when it exits, the shell changes into Yazi's selected directory. |
| `kpreview PATH` | Render the same multi-format preview backend used by fzf directly. |
| `kmkcd DIRECTORY` | Create a directory hierarchy and enter it. |
| `kserve [PORT] [BIND]` | Serve the current directory with Python. Defaults to port 8000 and `127.0.0.1`. |

The fzf preview helper understands directories, source/text files, JSON, images, PDFs, archives, and media metadata when the corresponding optional utility is installed.

---

## 9. Git, Python, Conda, Docker, and processes

| Command | Purpose |
|---|---|
| `kvgit` | Launch LazyGit; falls back to a concise Git status when LazyGit is unavailable. |
| `kvdiff [git diff args]` | Render Git diff through delta when available, otherwise colored Git diff in `less`. |
| `kfbranch` | Fuzzy-select and switch a local Git branch with commit preview. |
| `kfvenv` | Find and activate a nearby Python virtual environment. |
| `kfconda` | Fuzzy-select and activate a Conda environment. |
| `kfdocker` | Fuzzy-select a running Docker container and open zsh/bash/sh inside it. |
| `kfkill` | Fuzzy-select a process and send SIGTERM. It intentionally does not default to SIGKILL. |

The prompt automatically reveals relevant Git branch/status/metrics and Python, venv, Conda, Docker, Kubernetes, C/C++, CMake, Node.js, Rust, Go, and package context only when those contexts exist.

---

## 10. Monitoring and workstation dashboards

| Command | Purpose |
|---|---|
| `ksysinfo` | Fastfetch system summary, with a built-in OS/CPU/model/RAM/disk fallback. |
| `ksysmon` | btop system dashboard; falls back to `top`. |
| `kgputop` | nvtop, NVIDIA `nvidia-smi`, AMD `rocm-smi`, Raspberry Pi `vcgencmd`, or thermal-sysfs monitor. |
| `kpitemp` | Print Raspberry Pi/SBC temperature once. |
| `kpistatus` | Print Pi/SBC model, temperature, throttling, clock, voltage, memory, disk, and uptime summary. |
| `knetmon` | nload live network dashboard; falls back to watched `ip -s link`. |
| `kdashboard` | Open or attach the three-pane tmux workstation. |
| `kdashboard --reset` | Destroy a stale session and rebuild the corrected layout. |
| `kdashboard --status` | Show pane titles, process IDs, dead/alive status, and current commands. |
| `kdashboard --kill` | Close the dashboard session. |

Dashboard layout:

```text
┌──────────────────────────────────────┬──────────────────────────────┐
│ DEV SHELL                            │ SYSTEM // btop               │
│ project commands, build, evaluation  │ CPU / RAM / processes        │
│                                      ├──────────────────────────────┤
│                                      │ HARDWARE // GPU + NET        │
│                                      │ GPU/SoC / memory / disk / IP │
└──────────────────────────────────────┴──────────────────────────────┘
```

Basic tmux keys inside the dashboard:

| Key | Action |
|---|---|
| `Ctrl+B`, then arrow key | Move between panes. |
| Mouse click | Focus a pane; mouse mode is enabled. |
| `Ctrl+B`, then `d` | Detach without stopping the dashboard. |
| `kdashboard` | Reattach later. |

---

## 11. Search, completion, and typing features

| Key | Feature |
|---|---|
| `Ctrl+R` | Atuin contextual history when a compatible MUSL binary is available; otherwise fzf history. |
| `Alt+R` | Original incremental Zsh history search. |
| `Ctrl+T` | Fuzzy-select a file/directory and insert its path into the current command. |
| `Alt+C` | Fuzzy-select and enter a directory. |
| `Tab` | fzf-tab visual completion with context previews. |
| Right Arrow | Accept the displayed zsh-autosuggestions completion. |
| `Ctrl+/` inside fzf | Toggle the preview pane. |

Other interactive behavior:

- zsh-autosuggestions displays history-based ghost text.
- zsh-syntax-highlighting distinguishes valid commands, arguments, paths, and errors before execution.
- zsh-completions expands command-specific completion coverage.
- Atuin is configured local-only: automatic sync and update checks are disabled.

---

## 12. Collision-safe short aliases

KTERM always provides the full `k...` command names. It adds the following shorter aliases only when no existing alias, function, builtin, reserved word, or executable already owns that name:

```text
vls       -> kvls          vll       -> kvll
vtree     -> kvtree        vcat      -> kvcat
vgrep     -> kvgrep        vdiff     -> kvdiff
vgit      -> kvgit         yy        -> kyazi
ff        -> kff           fcd       -> kfcd
fbranch   -> kfbranch      fvenv     -> kfvenv
fconda    -> kfconda       fdocker   -> kfdocker
fkill     -> kfkill        mkcd      -> kmkcd
serve     -> kserve        sysinfo   -> ksysinfo
sysmon    -> ksysmon       gputop    -> kgputop
netmon    -> knetmon       pitemp   -> kpitemp
pistatus  -> kpistatus     dashboard -> kdashboard
khelp     -> kterm-help
```

Run `kterm-status` to see names KTERM deliberately left untouched.

---

## 13. Maintenance commands

| Command | Purpose |
|---|---|
| `kterm-help` or `khelp` | In-terminal command/shortcut reference. |
| `kterm-status` | Show active/default modes, prompt/HUD/block settings, versions, and collisions. |
| `kterm-doctor` | Check Zsh, Starship, fzf, zoxide, Terminator, uniform splits, dashboard, Nerd Font, history backend, and integrations. |
| `kterm-update` | Rerun the locally saved installer in update mode. |
| `kterm-repair` | Reapply configuration and restore missing components. |
| `kterm-uninstall` | Remove managed integration and restore snapshots where possible. |
| `kterm-log` | Open the installer log in `$PAGER` or less. |
| `kterm-backups` | Browse timestamped backup files. |
| `kterm-version` | Show installed KTERM version and target. |

`kterm-update` uses the installer copy saved at:

```text
~/.config/karthi-shell/install-kterm.sh
```

To upgrade to a newer KTERM bundle version, download the newer script and run it once; the saved updater is then replaced.

---

## 14. Desktop integration

### Ubuntu/GNOME

The installer uses several independent routes because desktop releases have changed default-terminal mechanisms over time:

- `x-terminal-emulator` is pointed to Terminator when supported.
- XDG terminal preference files receive a reversible managed block.
- A GNOME custom Ctrl+Alt+T binding launches the mode-aware KTERM launcher when the schema exists.
- Older GNOME default-terminal keys are updated when present.
- Plain `terminator` receives the active profile through `~/.config/terminator/config`.
- A bundled user-scope Nautilus extension provides **Open in Terminal** for local folders and selected local files.

### Raspberry Pi

In addition to the routes above when applicable:

- Labwc `Ctrl+Alt+T` is patched in the user `rc.xml` using the compositor's Execute action.
- Legacy Openbox/LXDE terminal keybindings are patched when an Openbox configuration exists.
- A PCManFM directory action is installed where the file manager supports file-manager actions.
- Both configurations are snapshotted for uninstall.

### Uniform Terminator splits

The modern configuration sets:

```text
always_split_with_profile = True
```

and defines the `default` and `modern` profiles with identical visual settings. Therefore new splits remain consistent even if a Terminator version falls back to its default profile name.

---

## 15. Files and safety snapshots

Important locations:

```text
~/.config/karthi-shell/                     managed configuration
~/.config/karthi-shell/modern.zsh           visual shell layer
~/.config/karthi-shell/switcher.zsh         mode and maintenance controls
~/.config/karthi-shell/starship-*.toml      rich/compact prompts
~/.config/karthi-shell/terminator-*.conf    modern and saved classic profiles
~/.config/karthi-shell/dashboard/           dashboard monitor scripts
~/.config/karthi-shell/state/               persistent mode/preferences/original state
~/.config/karthi-shell/backups/             timestamped safety snapshots
~/.config/karthi-shell/install.log          installation/update log
~/.local/share/karthi-shell/plugins/        managed Zsh plugins
~/.local/bin/                               KTERM launchers and portable binaries
~/.local/share/nautilus-python/extensions/  Nautilus user extension
```

The installer is idempotent: its `.zshrc` and XDG changes are bounded by named managed blocks, so rerunning does not append duplicates.

Uninstallation intentionally leaves general apt packages, downloaded visual utilities, fonts, and shell history in place. Removing shared packages automatically could break unrelated applications.

---

## 16. Troubleshooting

### Icons appear as squares

Close all Terminator windows and reopen them. Confirm:

```bash
fc-match 'JetBrainsMono Nerd Font'
kterm-doctor
```

### A split pane has a different background

Run:

```bash
kterm-repair
```

Then close every Terminator process and reopen it. The doctor should report:

```text
[OK] Split panes inherit the active profile
```

### Ctrl+Alt+T still opens another emulator

Run:

```bash
kterm-system modern
kterm-repair
```

Log out/in once. On GNOME, also inspect **Settings → Keyboard → Custom Shortcuts** for competing Ctrl+Alt+T bindings.

### Nautilus right-click opens GNOME Terminal or no menu appears

Run:

```bash
kterm-repair
nautilus -q
```

Reopen Files. The bundled extension supports local filesystem folders. A remote URI that has no local GVFS path may not be offered because Terminator requires a local working directory.

### Atuin reports a GLIBC error

The v3.0.0 installer only chooses MUSL assets and removes a managed Atuin binary that cannot execute. Repair with:

```bash
rm -f ~/.local/bin/atuin
kterm-repair
```

Ctrl+R continues to work through fzf even without Atuin.

### Dashboard right side is blank or stale

```bash
kdashboard --status
kdashboard --reset
```

The corrected layout explicitly targets the right pane before splitting it vertically. If btop exits, that pane opens a shell instead of becoming silently empty.

### A plugin update cannot download

The currently installed plugin is retained when a replacement clone fails. Review:

```bash
kterm-log
```

Then rerun `kterm-update` after network access is restored.

### GitHub API rate limit

Use an optional token for the update run:

```bash
GITHUB_TOKEN=your_token kterm-update
```

Or wait for the unauthenticated rate-limit window to reset. Apt-installed and previously installed tools continue working.

### Emergency recovery

```bash
kterm-safe
```

For all future terminal windows:

```bash
kterm-system classic
```

To remove managed integration:

```bash
kterm-uninstall
```

---

## 17. Installed upstream components

The exact set depends on architecture, apt availability, desktop, and the selected full/minimal profile.

- Terminator — split-pane terminal emulator.
- Zsh — interactive shell.
- Starship — contextual prompt.
- JetBrains Mono Nerd Font — icon-capable terminal font.
- fzf and fzf-tab — fuzzy history, files, directories, and completion.
- zoxide — learned directory navigation.
- Atuin — optional contextual local history interface using compatible MUSL builds only.
- zsh-autosuggestions, zsh-syntax-highlighting, zsh-completions.
- eza, bat, ripgrep, fd — visual/fast file and search tools.
- Yazi — terminal file manager.
- LazyGit and delta — Git UI and highlighted diffs.
- btop, htop/top, nvtop/nvidia-smi/rocm-smi/vcgencmd, nload.
- tmux — resilient workstation dashboard.
- chafa, poppler, ffmpeg/ffprobe, 7-Zip — optional preview backends.

Official references:

- Starship: <https://starship.rs/>
- fzf: <https://github.com/junegunn/fzf>
- zoxide: <https://github.com/ajeetdsouza/zoxide>
- Atuin: <https://github.com/atuinsh/atuin>
- Yazi: <https://yazi-rs.github.io/>
- Nautilus Python: <https://gnome.pages.gitlab.gnome.org/nautilus-python/>
- Labwc configuration: <https://labwc.github.io/getting-started.html>

---

## 18. Verification after installation

Run this sequence after logging in again:

```bash
kterm-version
kterm-status
kterm-doctor
khud now
kvll
kvtree 2
kdashboard --reset
```

Then verify the GUI paths:

1. Press Ctrl+Alt+T.
2. In Terminator press Ctrl+Shift+E and Ctrl+Shift+O.
3. Right-click a local folder in the file manager and open it in a terminal.
4. Switch all future windows to classic and back:

```bash
kterm-system classic
terminator-classic
kterm-system modern
terminator-modern
```

The expected result is a uniform, reversible visual terminal environment without losing the machine's pre-existing shell configuration.
