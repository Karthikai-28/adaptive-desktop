#!/usr/bin/env bash
# KTERM Futureproof installer 3.0.0
# Target: Raspberry Pi OS or Ubuntu on Raspberry Pi
#
# Standalone, idempotent installer for the selected KTERM setup:
# Terminator + Zsh, reversible classic mode, Starship visual prompt, startup
# HUD, command blocks, fuzzy navigation/history/completion, visual file/Git/
# system tools, uniform Terminator splits, dashboard, desktop shortcuts, and
# file-manager integration where supported.
#
# Run this script as your normal user. Do not use `sudo bash SCRIPT`.

set -Eeuo pipefail
IFS=$'\n\t'
umask 022

KTERM_VERSION="3.0.0"
KTERM_TARGET="raspberry-pi"
MODE="install"
DESKTOP_REQUEST="auto"
INSTALL_PROFILE="full"
CHANGE_SHELL=1
FORCE_TARGET=0
SKIP_APT_UPDATE="${KTERM_SKIP_APT_UPDATE:-0}"

usage() {
  cat <<'EOF'
Usage:
  bash SCRIPT                         install the complete profile
  bash SCRIPT --update                refresh managed tools and configuration
  bash SCRIPT --repair                reapply configuration without apt update
  bash SCRIPT --uninstall             remove managed integration and restore state
  bash SCRIPT --no-desktop            shell/TUI only; suitable for headless systems
  bash SCRIPT --desktop               force Terminator/desktop integration
  bash SCRIPT --minimal               skip larger optional visual utilities
  bash SCRIPT --no-chsh               do not change the account login shell
  bash SCRIPT --force                 bypass target/distribution safety warning
  bash SCRIPT --help

Environment:
  GITHUB_TOKEN=...                    optional GitHub API authentication
  KTERM_SKIP_APT_UPDATE=1             skip apt-get update
EOF
}

for arg in "$@"; do
  case "$arg" in
    --install) MODE="install" ;;
    --update) MODE="update" ;;
    --repair) MODE="repair"; SKIP_APT_UPDATE=1 ;;
    --uninstall) MODE="uninstall" ;;
    --no-desktop) DESKTOP_REQUEST="off" ;;
    --desktop) DESKTOP_REQUEST="on" ;;
    --minimal) INSTALL_PROFILE="minimal" ;;
    --no-chsh) CHANGE_SHELL=0 ;;
    --force) FORCE_TARGET=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n\n' "$arg" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  printf 'Do not run this installer as root. Run it as the normal user; sudo is requested internally.\n' >&2
  exit 1
fi

XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
APP_DIR="$XDG_CONFIG_HOME/karthi-shell"
DATA_DIR="$XDG_DATA_HOME/karthi-shell"
CACHE_DIR="$XDG_CACHE_HOME/karthi-shell"
PLUGIN_DIR="$DATA_DIR/plugins"
BIN_DIR="$HOME/.local/bin"
FONT_DIR="$XDG_DATA_HOME/fonts/JetBrainsMonoNerdFont"
STATE_DIR="$APP_DIR/state"
DASH_DIR="$APP_DIR/dashboard"
BACKUP_DIR="$APP_DIR/backups/$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$APP_DIR/install.log"
ZSHRC="$HOME/.zshrc"
TERMINATOR_CONFIG="$XDG_CONFIG_HOME/terminator/config"
MODERN_TERMINATOR_CONFIG="$APP_DIR/terminator-modern.conf"
CLASSIC_TERMINATOR_CONFIG="$APP_DIR/terminator-classic.conf"
NAUTILUS_EXTENSION="$XDG_DATA_HOME/nautilus-python/extensions/kterm_open_terminal.py"
PCMANFM_ACTION="$XDG_DATA_HOME/file-manager/actions/kterm-open-terminal.desktop"
LOADER_BEGIN="# >>> kterm-futureproof >>>"
LOADER_END="# <<< kterm-futureproof <<<"
XDG_BEGIN="# >>> kterm-default-terminal >>>"
XDG_END="# <<< kterm-default-terminal <<<"
SCRIPT_SOURCE="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")"

mkdir -p "$APP_DIR" "$DATA_DIR" "$CACHE_DIR" "$PLUGIN_DIR" "$BIN_DIR" \
  "$STATE_DIR" "$DASH_DIR" "$BACKUP_DIR"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

info() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

on_error() {
  local rc=$?
  printf '\n\033[1;31mKTERM stopped at line %s (exit %s).\033[0m\n' "${BASH_LINENO[0]:-unknown}" "$rc" >&2
  printf 'Log: %s\n' "$LOG_FILE" >&2
  exit "$rc"
}
trap on_error ERR

strip_block() {
  local file="$1" begin="$2" end="$3" temp
  [[ -e "$file" ]] || return 0
  temp="$(mktemp)"
  awk -v begin="$begin" -v end="$end" '
    $0 == begin {skip=1; next}
    $0 == end {skip=0; next}
    !skip {print}
  ' "$file" > "$temp"
  cat "$temp" > "$file"
  rm -f "$temp"
}

backup_file() {
  local file="$1" rel
  [[ -e "$file" || -L "$file" ]] || return 0
  rel="${file#/}"
  mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
  cp -aL "$file" "$BACKUP_DIR/$rel"
}

save_file_once() {
  local source="$1" destination="$2"
  [[ -e "$destination" ]] && return 0
  [[ -e "$source" || -L "$source" ]] || return 1
  mkdir -p "$(dirname "$destination")"
  cp -aL "$source" "$destination"
}

package_installed() {
  dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q '^install ok installed$'
}

apt_has() {
  apt-cache show "$1" >/dev/null 2>&1
}

apt_install_required() {
  local pkg
  local -a packages=()
  for pkg in "$@"; do
    apt_has "$pkg" || die "Required apt package is unavailable: $pkg"
    packages+=("$pkg")
  done
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
}

apt_install_optional() {
  local pkg
  for pkg in "$@"; do
    if ! apt_has "$pkg"; then
      warn "Optional package unavailable: $pkg"
      continue
    fi
    if ! sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg"; then
      warn "Optional package failed to install: $pkg"
    fi
  done
}

gsettings_has_key() {
  local schema="$1" key="$2"
  command -v gsettings >/dev/null 2>&1 || return 1
  gsettings list-schemas 2>/dev/null | grep -Fxq "$schema" || return 1
  gsettings list-keys "$schema" 2>/dev/null | grep -Fxq "$key"
}

has_graphical_desktop() {
  case "$DESKTOP_REQUEST" in
    on) return 0 ;;
    off) return 1 ;;
  esac
  [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && return 0
  [[ "$(systemctl get-default 2>/dev/null || true)" == graphical.target ]] && return 0
  command -v gnome-shell >/dev/null 2>&1 && return 0
  command -v nautilus >/dev/null 2>&1 && return 0
  command -v pcmanfm >/dev/null 2>&1 && return 0
  command -v pcmanfm-qt >/dev/null 2>&1 && return 0
  command -v labwc >/dev/null 2>&1 && return 0
  command -v openbox >/dev/null 2>&1 && return 0
  return 1
}

remove_gnome_shortcut_path() {
  command -v gsettings >/dev/null 2>&1 || return 0
  gsettings_has_key org.gnome.settings-daemon.plugins.media-keys custom-keybindings || return 0
  local current updated path
  path='/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/kterm/'
  current="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null || printf '[]')"
  updated="$(python3 - "$current" "$path" <<'PY_GSET_REMOVE'
import ast, sys
try:
    values = list(ast.literal_eval(sys.argv[1]))
except Exception:
    values = []
values = [item for item in values if item != sys.argv[2]]
print('[' + ', '.join(repr(item) for item in values) + ']')
PY_GSET_REMOVE
)"
  gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$updated" 2>/dev/null || true
}

restore_uninstall() {
  info "Removing KTERM-managed integration"
  backup_file "$ZSHRC"
  strip_block "$ZSHRC" "$LOADER_BEGIN" "$LOADER_END"

  if [[ -r "$CLASSIC_TERMINATOR_CONFIG" ]]; then
    mkdir -p "$(dirname "$TERMINATOR_CONFIG")"
    cp -f "$CLASSIC_TERMINATOR_CONFIG" "$TERMINATOR_CONFIG"
    chmod 0600 "$TERMINATOR_CONFIG" 2>/dev/null || true
    ok "Restored the saved Terminator configuration"
  fi

  rm -f "$NAUTILUS_EXTENSION" "$PCMANFM_ACTION"
  remove_gnome_shortcut_path
  if [[ -r "$STATE_DIR/gnome-terminal-binding.gvariant" ]] && \
     gsettings_has_key org.gnome.settings-daemon.plugins.media-keys terminal; then
    gsettings set org.gnome.settings-daemon.plugins.media-keys terminal \
      "$(cat "$STATE_DIR/gnome-terminal-binding.gvariant")" 2>/dev/null || true
  fi
  if [[ -r "$STATE_DIR/gnome-default-terminal-exec.gvariant" ]] && \
     gsettings_has_key org.gnome.desktop.default-applications.terminal exec; then
    gsettings set org.gnome.desktop.default-applications.terminal exec \
      "$(cat "$STATE_DIR/gnome-default-terminal-exec.gvariant")" 2>/dev/null || true
  fi
  if [[ -r "$STATE_DIR/gnome-default-terminal-exec-arg.gvariant" ]] && \
     gsettings_has_key org.gnome.desktop.default-applications.terminal exec-arg; then
    gsettings set org.gnome.desktop.default-applications.terminal exec-arg \
      "$(cat "$STATE_DIR/gnome-default-terminal-exec-arg.gvariant")" 2>/dev/null || true
  fi

  local pkg
  for pkg in nautilus-extension-gnome-terminal nautilus-extension-gnome-console; do
    if [[ -e "$STATE_DIR/had-$pkg" ]] && ! package_installed "$pkg" && apt_has "$pkg"; then
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg" || true
    fi
  done

  if [[ -r "$STATE_DIR/x-terminal-emulator.path" ]]; then
    local old_alt
    old_alt="$(cat "$STATE_DIR/x-terminal-emulator.path")"
    if [[ -x "$old_alt" ]] && command -v update-alternatives >/dev/null 2>&1; then
      sudo update-alternatives --set x-terminal-emulator "$old_alt" >/dev/null 2>&1 || true
    fi
  fi

  local xdg_file
  for xdg_file in "$XDG_CONFIG_HOME/xdg-terminals.list" \
                  "$XDG_CONFIG_HOME/ubuntu-xdg-terminals.list" \
                  "$XDG_CONFIG_HOME/gnome-xdg-terminals.list"; do
    strip_block "$xdg_file" "$XDG_BEGIN" "$XDG_END"
  done

  if [[ -r "$STATE_DIR/original-login-shell" ]]; then
    local old_shell
    old_shell="$(cat "$STATE_DIR/original-login-shell")"
    [[ -x "$old_shell" ]] && sudo chsh -s "$old_shell" "$USER" >/dev/null 2>&1 || true
  fi

  if [[ -e "$STATE_DIR/labwc-created" ]]; then
    rm -f "$XDG_CONFIG_HOME/labwc/rc.xml"
  elif [[ -r "$STATE_DIR/labwc-rc.original" ]]; then
    mkdir -p "$XDG_CONFIG_HOME/labwc"
    cp -f "$STATE_DIR/labwc-rc.original" "$XDG_CONFIG_HOME/labwc/rc.xml"
  fi
  if [[ -r "$STATE_DIR/openbox-rc.path" ]]; then
    local ob_path
    ob_path="$(cat "$STATE_DIR/openbox-rc.path")"
    if [[ -e "$STATE_DIR/openbox-created" ]]; then
      rm -f "$ob_path"
    elif [[ -r "$STATE_DIR/openbox-rc.original" ]]; then
      mkdir -p "$(dirname "$ob_path")"
      cp -f "$STATE_DIR/openbox-rc.original" "$ob_path"
    fi
  fi

  rm -f "$BIN_DIR/terminator-modern" "$BIN_DIR/terminator-classic" \
        "$BIN_DIR/kterm-terminal" "$BIN_DIR/kpreview" "$BIN_DIR/karthi-dashboard"
  rm -f "$XDG_DATA_HOME/applications/kterm-terminal.desktop" \
        "$XDG_DATA_HOME/applications/kterm-classic-terminal.desktop"

  command -v nautilus >/dev/null 2>&1 && nautilus -q >/dev/null 2>&1 || true
  command -v labwc >/dev/null 2>&1 && labwc -r >/dev/null 2>&1 || true
  command -v openbox >/dev/null 2>&1 && openbox --reconfigure >/dev/null 2>&1 || true

  printf '\nManaged integration removed. General packages, fonts, tools and history were retained.\n'
  printf 'Safety backup from this run: %s\n' "$BACKUP_DIR"
}

if [[ "$MODE" == uninstall ]]; then
  command -v apt-get >/dev/null 2>&1 || die "apt-get is required for safe restoration."
  sudo -v
  restore_uninstall
  exit 0
fi

[[ -r /etc/os-release ]] || die "Cannot identify this Linux distribution."
# shellcheck disable=SC1091
source /etc/os-release
command -v apt-get >/dev/null 2>&1 || die "This installer requires an apt-based Debian/Ubuntu system."

ARCH="$(uname -m)"
DPKG_ARCH="$(dpkg --print-architecture 2>/dev/null || printf '%s' "$ARCH")"
PI_MODEL=""
if [[ -r /proc/device-tree/model ]]; then PI_MODEL="$(tr -d '\0' </proc/device-tree/model)"; fi
IS_PI=0
[[ "$PI_MODEL" == *"Raspberry Pi"* ]] && IS_PI=1

if [[ "$KTERM_TARGET" == raspberry-pi && "$IS_PI" -ne 1 && "$FORCE_TARGET" -ne 1 ]]; then
  die "Raspberry Pi hardware was not detected. Use the Raspberry Pi script on a Pi, or --force intentionally."
fi
if [[ "$KTERM_TARGET" == ubuntu ]]; then
  case " ${ID:-} ${ID_LIKE:-} " in
    *ubuntu*|*debian*) ;;
    *) [[ "$FORCE_TARGET" -eq 1 ]] || die "This script targets Ubuntu/Debian-family systems. Use --force only when apt-compatible." ;;
  esac
  [[ "$IS_PI" -eq 1 ]] && warn "Raspberry Pi hardware detected; the dedicated Raspberry Pi installer is recommended."
fi

DESKTOP_ENABLED=off
if has_graphical_desktop; then DESKTOP_ENABLED=on; fi
printf '%s\n' "$KTERM_VERSION" > "$STATE_DIR/version"
printf '%s\n' "$KTERM_TARGET" > "$STATE_DIR/platform"
printf '%s\n' "$DESKTOP_ENABLED" > "$STATE_DIR/desktop-enabled"
printf '%s\n' "$INSTALL_PROFILE" > "$STATE_DIR/install-profile"

info "KTERM v$KTERM_VERSION // $KTERM_TARGET"
printf 'System              : %s\n' "${PRETTY_NAME:-unknown}"
printf 'Architecture        : %s (%s)\n' "$ARCH" "$DPKG_ARCH"
printf 'Raspberry Pi model  : %s\n' "${PI_MODEL:-not detected}"
printf 'Desktop integration : %s\n' "$DESKTOP_ENABLED"
printf 'Install profile     : %s\n' "$INSTALL_PROFILE"

info "Creating safety snapshots"
touch "$ZSHRC"
backup_file "$ZSHRC"
backup_file "$TERMINATOR_CONFIG"
if [[ ! -e "$CLASSIC_TERMINATOR_CONFIG" ]]; then
  if [[ -r "$TERMINATOR_CONFIG" ]]; then
    cp -a "$TERMINATOR_CONFIG" "$CLASSIC_TERMINATOR_CONFIG"
  else
    cat > "$CLASSIC_TERMINATOR_CONFIG" <<'CLASSIC_TERM'
[global_config]
[keybindings]
[profiles]
  [[default]]
    use_system_font = True
    scrollback_infinite = True
[layouts]
  [[default]]
    [[[window0]]]
      type = Window
      parent = ""
    [[[terminal1]]]
      type = Terminal
      parent = window0
      profile = default
[plugins]
CLASSIC_TERM
  fi
  chmod 0600 "$CLASSIC_TERMINATOR_CONFIG"
fi
if [[ ! -e "$STATE_DIR/original-login-shell" ]]; then
  getent passwd "$USER" | awk -F: '{print $7}' > "$STATE_DIR/original-login-shell"
fi
if [[ -L /etc/alternatives/x-terminal-emulator && ! -e "$STATE_DIR/x-terminal-emulator.path" ]]; then
  readlink -f /etc/alternatives/x-terminal-emulator > "$STATE_DIR/x-terminal-emulator.path" || true
fi

info "Installing apt prerequisites"
sudo -v
if [[ "$SKIP_APT_UPDATE" != 1 ]]; then sudo apt-get update; fi
apt_install_required ca-certificates curl git zsh python3 tmux tar gzip unzip xz-utils \
  fontconfig file less procps findutils coreutils util-linux sed grep gawk
if [[ "$DESKTOP_ENABLED" == on ]]; then apt_install_required terminator; fi
apt_install_optional jq ripgrep fzf bat fd-find btop htop tree fastfetch poppler-utils \
  ffmpeg p7zip-full imagemagick chafa xclip wl-clipboard duf nload net-tools \
  iproute2 lsof rsync gettext libglib2.0-bin desktop-file-utils
if [[ "$KTERM_TARGET" == ubuntu ]]; then apt_install_optional nvtop; fi
if [[ "$KTERM_TARGET" == raspberry-pi ]]; then
  if ! command -v vcgencmd >/dev/null 2>&1; then
    apt_install_optional raspi-utils libraspberrypi-bin
  fi
fi
if [[ "$DESKTOP_ENABLED" == on ]] && command -v nautilus >/dev/null 2>&1; then
  apt_install_optional python3-nautilus python3-gi
fi

if ! command -v bat >/dev/null 2>&1 && command -v batcat >/dev/null 2>&1; then
  ln -sfn "$(command -v batcat)" "$BIN_DIR/bat"
fi
if ! command -v fd >/dev/null 2>&1 && command -v fdfind >/dev/null 2>&1; then
  ln -sfn "$(command -v fdfind)" "$BIN_DIR/fd"
fi

case "$DPKG_ARCH" in
  amd64)
    RUST_MUSL="x86_64-unknown-linux-musl"; RUST_GNU="x86_64-unknown-linux-gnu"
    FZF_ARCH="amd64"; LAZYGIT_ARCH="x86_64"
    ;;
  arm64)
    RUST_MUSL="aarch64-unknown-linux-musl"; RUST_GNU="aarch64-unknown-linux-gnu"
    FZF_ARCH="arm64"; LAZYGIT_ARCH="arm64"
    ;;
  armhf)
    RUST_MUSL=""; RUST_GNU="arm-unknown-linux-gnueabihf"
    FZF_ARCH="armv7"; LAZYGIT_ARCH="armv6"
    ;;
  armel)
    RUST_MUSL=""; RUST_GNU="arm-unknown-linux-gnueabihf"
    FZF_ARCH="armv6"; LAZYGIT_ARCH="armv6"
    ;;
  i386)
    RUST_MUSL=""; RUST_GNU=""; FZF_ARCH="386"; LAZYGIT_ARCH="32-bit"
    ;;
  *)
    RUST_MUSL=""; RUST_GNU=""; FZF_ARCH=""; LAZYGIT_ARCH=""
    warn "No portable-binary map for $DPKG_ARCH; apt tools and fallbacks remain usable."
    ;;
esac

GITHUB_HEADERS=(-H 'Accept: application/vnd.github+json')
[[ -n "${GITHUB_TOKEN:-}" ]] && GITHUB_HEADERS+=(-H "Authorization: Bearer $GITHUB_TOKEN")

download_latest_asset() {
  local repo="$1" regex="$2" output="$3" json url
  json="$(mktemp)"
  if ! curl --proto '=https' --tlsv1.2 -fsSL --retry 3 --retry-delay 2 \
      "${GITHUB_HEADERS[@]}" "https://api.github.com/repos/$repo/releases/latest" -o "$json"; then
    rm -f "$json"
    return 1
  fi
  url="$(python3 - "$json" "$regex" <<'PY_ASSET'
import json, re, sys
with open(sys.argv[1], encoding='utf-8') as handle:
    data = json.load(handle)
pattern = re.compile(sys.argv[2], re.I)
for asset in data.get('assets', []):
    if pattern.search(asset.get('name', '')):
        print(asset.get('browser_download_url', ''))
        break
PY_ASSET
)"
  rm -f "$json"
  [[ -n "$url" ]] || return 1
  curl --proto '=https' --tlsv1.2 -fL --retry 3 --retry-delay 2 "$url" -o "$output"
  printf '%s\n' "$url"
}

extract_archive() {
  local archive="$1" url="$2" destination="$3"
  mkdir -p "$destination"
  case "$url" in
    *.tar.gz|*.tgz) tar -xzf "$archive" -C "$destination" ;;
    *.tar.xz) tar -xJf "$archive" -C "$destination" ;;
    *.zip) unzip -q "$archive" -d "$destination" ;;
    *) return 1 ;;
  esac
}

install_release_binary() {
  local repo="$1" regex="$2" binary="$3" destination="${4:-$3}"
  local temp archive extracted url candidate
  temp="$(mktemp -d)"; archive="$temp/asset"; extracted="$temp/extracted"
  if ! url="$(download_latest_asset "$repo" "$regex" "$archive")"; then
    rm -rf "$temp"
    warn "No matching release asset from $repo for $DPKG_ARCH"
    return 1
  fi
  if ! extract_archive "$archive" "$url" "$extracted"; then
    rm -rf "$temp"
    warn "Could not extract $repo release asset"
    return 1
  fi
  candidate="$(find "$extracted" -type f -name "$binary" -print -quit)"
  if [[ -z "$candidate" ]]; then
    rm -rf "$temp"
    warn "Binary $binary was not present in the $repo asset"
    return 1
  fi
  install -m 0755 "$candidate" "$BIN_DIR/$destination"
  rm -rf "$temp"
  ok "Installed $destination from $repo"
}

should_refresh() {
  local binary="$1"
  [[ "$MODE" == update ]] && return 0
  command -v "$binary" >/dev/null 2>&1 || return 0
  timeout 8 "$binary" --version >/dev/null 2>&1 || return 0
  return 1
}

install_starship() {
  if should_refresh starship && [[ -n "$RUST_MUSL" ]]; then
    install_release_binary starship/starship "^starship-${RUST_MUSL}\\.tar\\.gz$" starship || true
  fi
  if ! command -v starship >/dev/null 2>&1; then
    local temp
    temp="$(mktemp)"
    if curl --proto '=https' --tlsv1.2 -fsSL --retry 3 https://starship.rs/install.sh -o "$temp"; then
      sh "$temp" -y -b "$BIN_DIR" || true
    fi
    rm -f "$temp"
  fi
}

install_zoxide() {
  if should_refresh zoxide && [[ -n "$RUST_MUSL" ]]; then
    install_release_binary ajeetdsouza/zoxide "zoxide-[0-9.]+-${RUST_MUSL}\\.tar\\.gz$" zoxide || true
  fi
  if ! command -v zoxide >/dev/null 2>&1; then
    local temp
    temp="$(mktemp)"
    if curl --proto '=https' --tlsv1.2 -fsSL --retry 3 \
        https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh -o "$temp"; then
      sh "$temp" || true
    fi
    rm -f "$temp"
  fi
}

info "Installing current portable terminal utilities"
install_starship
if should_refresh fzf && [[ -n "$FZF_ARCH" ]]; then
  install_release_binary junegunn/fzf "linux_${FZF_ARCH}\\.tar\\.gz$" fzf || true
fi
install_zoxide

if [[ "$INSTALL_PROFILE" == full ]]; then
  if [[ -n "$RUST_MUSL" ]]; then
    if should_refresh atuin; then
      install_release_binary atuinsh/atuin "^atuin-${RUST_MUSL}\\.tar\\.gz$" atuin || true
    fi
    if [[ -x "$BIN_DIR/atuin" ]] && ! timeout 8 "$BIN_DIR/atuin" --version >/dev/null 2>&1; then
      warn "Removing an incompatible Atuin binary; Ctrl+R will safely use fzf."
      rm -f "$BIN_DIR/atuin"
    fi
  fi
  if should_refresh eza && [[ -n "$RUST_GNU" ]]; then
    install_release_binary eza-community/eza "eza_?${RUST_GNU}\\.tar\\.gz$" eza || true
  fi
  if should_refresh delta && [[ -n "$RUST_MUSL" ]]; then
    install_release_binary dandavison/delta "(git-)?delta-[0-9.]+-(${RUST_MUSL}|${RUST_GNU})\\.tar\\.gz$" delta || true
  fi
  if should_refresh lazygit && [[ -n "$LAZYGIT_ARCH" ]]; then
    install_release_binary jesseduffield/lazygit "_Linux_${LAZYGIT_ARCH}\\.tar\\.gz$" lazygit || true
  fi
  if should_refresh yazi && [[ -n "$RUST_GNU" ]]; then
    temp_yazi="$(mktemp -d)"
    if yazi_url="$(download_latest_asset sxyazi/yazi "^yazi-(${RUST_GNU}|${RUST_MUSL})\\.zip$" "$temp_yazi/asset")" && \
       extract_archive "$temp_yazi/asset" "$yazi_url" "$temp_yazi/extracted"; then
      for yazi_binary in yazi ya; do
        yazi_candidate="$(find "$temp_yazi/extracted" -type f -name "$yazi_binary" -print -quit)"
        [[ -n "$yazi_candidate" ]] && install -m 0755 "$yazi_candidate" "$BIN_DIR/$yazi_binary"
      done
      [[ -x "$BIN_DIR/yazi" ]] && ok "Installed Yazi"
    else
      warn "Yazi release asset unavailable for $DPKG_ARCH; other tools remain active."
    fi
    rm -rf "$temp_yazi"
  fi
fi

info "Installing JetBrainsMono Nerd Font"
if [[ "$DESKTOP_ENABLED" == on || "$KTERM_TARGET" == ubuntu ]]; then
  font_temp="$(mktemp -d)"
  if curl --proto '=https' --tlsv1.2 -fL --retry 3 \
      https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.zip \
      -o "$font_temp/font.zip"; then
    unzip -q "$font_temp/font.zip" -d "$font_temp/extracted"
    rm -rf "$FONT_DIR"; mkdir -p "$FONT_DIR"
    while IFS= read -r -d '' font; do
      install -m 0644 "$font" "$FONT_DIR/$(basename "$font")"
    done < <(find "$font_temp/extracted" -type f \( -iname '*.ttf' -o -iname '*.otf' \) -print0)
    fc-cache -f "$FONT_DIR" >/dev/null 2>&1 || fc-cache -f >/dev/null 2>&1 || true
    ok "Nerd Font installed"
  else
    warn "Font download failed; the terminal works, but icons may appear as boxes."
  fi
  rm -rf "$font_temp"
fi

clone_managed_plugin() {
  local url="$1" destination="$2" name="$3" temp
  if [[ "$MODE" != update && -d "$destination/.git" ]]; then
    ok "$name already installed"
    return 0
  fi
  temp="$(mktemp -d)"
  if git clone --depth=1 --quiet "$url" "$temp/repo"; then
    rm -rf "$destination"
    mv "$temp/repo" "$destination"
    ok "Installed/updated $name"
  else
    warn "Could not download $name; retaining any existing copy."
  fi
  rm -rf "$temp"
}

info "Installing Zsh visual plugins"
clone_managed_plugin https://github.com/zsh-users/zsh-autosuggestions.git \
  "$PLUGIN_DIR/zsh-autosuggestions" zsh-autosuggestions
clone_managed_plugin https://github.com/zsh-users/zsh-syntax-highlighting.git \
  "$PLUGIN_DIR/zsh-syntax-highlighting" zsh-syntax-highlighting
clone_managed_plugin https://github.com/zsh-users/zsh-completions.git \
  "$PLUGIN_DIR/zsh-completions" zsh-completions
clone_managed_plugin https://github.com/Aloxaf/fzf-tab.git \
  "$PLUGIN_DIR/fzf-tab" fzf-tab

info "Writing KTERM configuration and helpers"
mkdir -p "$APP_DIR/atuin" "$DASH_DIR" "$(dirname "$NAUTILUS_EXTENSION")"
base64 -d > "$APP_DIR/starship-rich.toml" <<'KTERM_B64_RICH'
YWRkX25ld2xpbmUgPSB0cnVlCmNvbW1hbmRfdGltZW91dCA9IDEyMDAKc2Nhbl90aW1lb3V0ID0g
MzAKcGFsZXR0ZSA9ICJjYXRwcHVjY2luX21vY2hhIgoKZm9ybWF0ID0gIiIiClvila3ilIBdKGJv
bGQgYmx1ZSkkb3MkdXNlcm5hbWUkaG9zdG5hbWUkZGlyZWN0b3J5JGdpdF9icmFuY2gkZ2l0X3N0
YXR1cyRnaXRfc3RhdGUkZ2l0X21ldHJpY3MkcHl0aG9uJGNvbmRhJGRvY2tlcl9jb250ZXh0JGt1
YmVybmV0ZXMkYyRjcHAkY21ha2Ukbm9kZWpzJHJ1c3QkZ29sYW5nJHBhY2thZ2UKW+KVsOKUgF0o
Ym9sZCBibHVlKSRjaGFyYWN0ZXIiIiIKCnJpZ2h0X2Zvcm1hdCA9ICIkY21kX2R1cmF0aW9uJGpv
YnMkc3RhdHVzJG1lbW9yeV91c2FnZSRiYXR0ZXJ5JHRpbWUiCmNvbnRpbnVhdGlvbl9wcm9tcHQg
PSAiW+KImSBdKGJvbGQgb3ZlcmxheTEpIgoKW3BhbGV0dGVzLmNhdHBwdWNjaW5fbW9jaGFdCnJv
c2V3YXRlciA9ICIjZjVlMGRjIgpmbGFtaW5nbyA9ICIjZjJjZGNkIgpwaW5rID0gIiNmNWMyZTci
Cm1hdXZlID0gIiNjYmE2ZjciCnJlZCA9ICIjZjM4YmE4IgptYXJvb24gPSAiI2ViYTBhYyIKcGVh
Y2ggPSAiI2ZhYjM4NyIKeWVsbG93ID0gIiNmOWUyYWYiCmdyZWVuID0gIiNhNmUzYTEiCnRlYWwg
PSAiIzk0ZTJkNSIKc2t5ID0gIiM4OWRjZWIiCnNhcHBoaXJlID0gIiM3NGM3ZWMiCmJsdWUgPSAi
Izg5YjRmYSIKbGF2ZW5kZXIgPSAiI2I0YmVmZSIKdGV4dCA9ICIjY2RkNmY0IgpzdWJ0ZXh0MSA9
ICIjYmFjMmRlIgpzdWJ0ZXh0MCA9ICIjYTZhZGM4IgpvdmVybGF5MiA9ICIjOTM5OWIyIgpvdmVy
bGF5MSA9ICIjN2Y4NDljIgpvdmVybGF5MCA9ICIjNmM3MDg2IgpzdXJmYWNlMiA9ICIjNTg1Yjcw
IgpzdXJmYWNlMSA9ICIjNDU0NzVhIgpzdXJmYWNlMCA9ICIjMzEzMjQ0IgpiYXNlID0gIiMxZTFl
MmUiCm1hbnRsZSA9ICIjMTgxODI1IgpjcnVzdCA9ICIjMTExMTFiIgoKW29zXQpkaXNhYmxlZCA9
IGZhbHNlCmZvcm1hdCA9ICJbJHN5bWJvbF0oJHN0eWxlKSIKc3R5bGUgPSAiYm9sZCBibHVlIgoK
W29zLnN5bWJvbHNdClVidW50dSA9ICLvjJsgIgpEZWJpYW4gPSAi74yGICIKTGludXggPSAi74W8
ICIKV2luZG93cyA9ICLzsI2yICIKTWFjb3MgPSAi74W5ICIKClt1c2VybmFtZV0Kc2hvd19hbHdh
eXMgPSB0cnVlCmZvcm1hdCA9ICJbJHVzZXJdKCRzdHlsZSkiCnN0eWxlX3VzZXIgPSAiYm9sZCBs
YXZlbmRlciIKc3R5bGVfcm9vdCA9ICJib2xkIHJlZCIKCltob3N0bmFtZV0Kc3NoX29ubHkgPSBm
YWxzZQpmb3JtYXQgPSAiW0AkaG9zdG5hbWVdKCRzdHlsZSkgIgpzdHlsZSA9ICJib2xkIHNhcHBo
aXJlIgp0cmltX2F0ID0gIi4iCgpbZGlyZWN0b3J5XQpmb3JtYXQgPSAiW++BvCAgJHBhdGhdKCRz
dHlsZSlbJHJlYWRfb25seV0oJHJlYWRfb25seV9zdHlsZSkgIgpzdHlsZSA9ICJib2xkIGJsdWUi
CnJlYWRfb25seSA9ICIg74CjIgpyZWFkX29ubHlfc3R5bGUgPSAiYm9sZCByZWQiCnRydW5jYXRp
b25fbGVuZ3RoID0gNQp0cnVuY2F0ZV90b19yZXBvID0gZmFsc2UKaG9tZV9zeW1ib2wgPSAi74CV
IH4iCgpbZGlyZWN0b3J5LnN1YnN0aXR1dGlvbnNdCkRvY3VtZW50cyA9ICLzsIiZIERvY3VtZW50
cyIKRG93bmxvYWRzID0gIu+AmSBEb3dubG9hZHMiCk11c2ljID0gIu+AgSBNdXNpYyIKUGljdHVy
ZXMgPSAi74C+IFBpY3R1cmVzIgpQcm9qZWN0cyA9ICLzsLKLIFByb2plY3RzIgpEZXZlbG9wZXIg
PSAi87CyiyBEZXZlbG9wZXIiCgpbZ2l0X2JyYW5jaF0Kc3ltYm9sID0gIu+QmCAiCmZvcm1hdCA9
ICJbJHN5bWJvbCRicmFuY2goOiRyZW1vdGVfYnJhbmNoKV0oJHN0eWxlKSAiCnN0eWxlID0gImJv
bGQgbWF1dmUiCnRydW5jYXRpb25fbGVuZ3RoID0gMzIKCltnaXRfc3RhdHVzXQpmb3JtYXQgPSAi
KFskYWxsX3N0YXR1cyRhaGVhZF9iZWhpbmRdKCRzdHlsZSkgKSIKc3R5bGUgPSAiYm9sZCBwZWFj
aCIKY29uZmxpY3RlZCA9ICI9JHtjb3VudH0gIgphaGVhZCA9ICLih6Eke2NvdW50fSAiCmJlaGlu
ZCA9ICLih6Mke2NvdW50fSAiCmRpdmVyZ2VkID0gIuKHleKHoSR7YWhlYWRfY291bnR94oejJHti
ZWhpbmRfY291bnR9ICIKdW50cmFja2VkID0gIj8ke2NvdW50fSAiCnN0YXNoZWQgPSAi87CPlyR7
Y291bnR9ICIKbW9kaWZpZWQgPSAiISR7Y291bnR9ICIKc3RhZ2VkID0gIiske2NvdW50fSAiCnJl
bmFtZWQgPSAiwrske2NvdW50fSAiCmRlbGV0ZWQgPSAi4pyYJHtjb3VudH0gIgoKW2dpdF9zdGF0
ZV0KZm9ybWF0ID0gIlskc3RhdGUoICRwcm9ncmVzc19jdXJyZW50LyRwcm9ncmVzc190b3RhbCld
KCRzdHlsZSkgIgpzdHlsZSA9ICJib2xkIHllbGxvdyIKCltnaXRfbWV0cmljc10KZGlzYWJsZWQg
PSBmYWxzZQphZGRlZF9zdHlsZSA9ICJib2xkIGdyZWVuIgpkZWxldGVkX3N0eWxlID0gImJvbGQg
cmVkIgpmb3JtYXQgPSAiKFsrJGFkZGVkXSgkYWRkZWRfc3R5bGUpICkoWy0kZGVsZXRlZF0oJGRl
bGV0ZWRfc3R5bGUpICkiCgpbY2hhcmFjdGVyXQpzdWNjZXNzX3N5bWJvbCA9ICJb4p2vXShib2xk
IGdyZWVuKSIKZXJyb3Jfc3ltYm9sID0gIlvina9dKGJvbGQgcmVkKSIKdmltY21kX3N5bWJvbCA9
ICJb4p2uXShib2xkIGdyZWVuKSIKdmltY21kX3JlcGxhY2Vfb25lX3N5bWJvbCA9ICJb4p2uXShi
b2xkIG1hdXZlKSIKdmltY21kX3JlcGxhY2Vfc3ltYm9sID0gIlvina5dKGJvbGQgbWF1dmUpIgp2
aW1jbWRfdmlzdWFsX3N5bWJvbCA9ICJb4p2uXShib2xkIHllbGxvdykiCgpbY21kX2R1cmF0aW9u
XQptaW5fdGltZSA9IDUwMApzaG93X21pbGxpc2Vjb25kcyA9IHRydWUKZm9ybWF0ID0gIlvzsY6r
ICRkdXJhdGlvbl0oJHN0eWxlKSAiCnN0eWxlID0gImJvbGQgeWVsbG93IgpzaG93X25vdGlmaWNh
dGlvbnMgPSBmYWxzZQoKW2pvYnNdCnN5bWJvbCA9ICLzsJyOICIKZm9ybWF0ID0gIlskc3ltYm9s
JG51bWJlcl0oJHN0eWxlKSAiCnN0eWxlID0gImJvbGQgYmx1ZSIKbnVtYmVyX3RocmVzaG9sZCA9
IDEKCltzdGF0dXNdCmRpc2FibGVkID0gZmFsc2UKc3ltYm9sID0gIuKcmCIKc3VjY2Vzc19zeW1i
b2wgPSAiIgpub3RfZXhlY3V0YWJsZV9zeW1ib2wgPSAi87CCrSIKbm90X2ZvdW5kX3N5bWJvbCA9
ICLzsI2JIgpzaWdpbnRfc3ltYm9sID0gIvOwmowiCnNpZ25hbF9zeW1ib2wgPSAi87GQiyIKZm9y
bWF0ID0gIlskc3ltYm9sJHN0YXR1c10oJHN0eWxlKSAiCnN0eWxlID0gImJvbGQgcmVkIgptYXBf
c3ltYm9sID0gdHJ1ZQoKW21lbW9yeV91c2FnZV0KZGlzYWJsZWQgPSBmYWxzZQp0aHJlc2hvbGQg
PSA3NQpzeW1ib2wgPSAi87CNmyAiCmZvcm1hdCA9ICJbJHN5bWJvbCR7cmFtX3BjdH1dKCRzdHls
ZSkgIgpzdHlsZSA9ICJib2xkIHBlYWNoIgoKW2JhdHRlcnldCmRpc2FibGVkID0gZmFsc2UKZm9y
bWF0ID0gIlskc3ltYm9sJHBlcmNlbnRhZ2VdKCRzdHlsZSkgIgpmdWxsX3N5bWJvbCA9ICLzsIG5
ICIKY2hhcmdpbmdfc3ltYm9sID0gIvOwgoQgIgpkaXNjaGFyZ2luZ19zeW1ib2wgPSAi87CCgyAi
CnVua25vd25fc3ltYm9sID0gIvOwgpEgIgplbXB0eV9zeW1ib2wgPSAi87CCjiAiCgpbW2JhdHRl
cnkuZGlzcGxheV1dCnRocmVzaG9sZCA9IDIwCnN0eWxlID0gImJvbGQgcmVkIgoKW1tiYXR0ZXJ5
LmRpc3BsYXldXQp0aHJlc2hvbGQgPSA1MApzdHlsZSA9ICJib2xkIHllbGxvdyIKClt0aW1lXQpk
aXNhYmxlZCA9IGZhbHNlCnRpbWVfZm9ybWF0ID0gIiVIOiVNOiVTIgpmb3JtYXQgPSAiW++AlyAk
dGltZV0oJHN0eWxlKSIKc3R5bGUgPSAiYm9sZCBzdWJ0ZXh0MCIKCltweXRob25dCnN5bWJvbCA9
ICLunLwgIgpmb3JtYXQgPSAiWyRzeW1ib2wke3B5ZW52X3ByZWZpeH0ke3ZlcnNpb259KCBcXCgk
dmlydHVhbGVudlxcKSldKCRzdHlsZSkgIgpzdHlsZSA9ICJib2xkIHllbGxvdyIKCltjb25kYV0K
c3ltYm9sID0gIvOxlI4gIgpmb3JtYXQgPSAiWyRzeW1ib2wkZW52aXJvbm1lbnRdKCRzdHlsZSkg
IgpzdHlsZSA9ICJib2xkIGdyZWVuIgppZ25vcmVfYmFzZSA9IGZhbHNlCgpbZG9ja2VyX2NvbnRl
eHRdCnN5bWJvbCA9ICLvjIggIgpmb3JtYXQgPSAiWyRzeW1ib2wkY29udGV4dF0oJHN0eWxlKSAi
CnN0eWxlID0gImJvbGQgYmx1ZSIKb25seV93aXRoX2ZpbGVzID0gdHJ1ZQoKW2t1YmVybmV0ZXNd
CmRpc2FibGVkID0gZmFsc2UKc3ltYm9sID0gIvOxg74gIgpmb3JtYXQgPSAiWyRzeW1ib2wkY29u
dGV4dCg6OiRuYW1lc3BhY2UpXSgkc3R5bGUpICIKc3R5bGUgPSAiYm9sZCBzYXBwaGlyZSIKCltj
XQpzeW1ib2wgPSAi7pieICIKZm9ybWF0ID0gIlskc3ltYm9sKCR2ZXJzaW9uKC0kbmFtZSkpXSgk
c3R5bGUpICIKc3R5bGUgPSAiYm9sZCBibHVlIgoKW2NwcF0Kc3ltYm9sID0gIu6YnSAiCmZvcm1h
dCA9ICJbJHN5bWJvbCgkdmVyc2lvbigtJG5hbWUpKV0oJHN0eWxlKSAiCnN0eWxlID0gImJvbGQg
Ymx1ZSIKCltjbWFrZV0Kc3ltYm9sID0gIu6elCAiCmZvcm1hdCA9ICJbJHN5bWJvbCgkdmVyc2lv
bildKCRzdHlsZSkgIgpzdHlsZSA9ICJib2xkIGJsdWUiCgpbbm9kZWpzXQpzeW1ib2wgPSAi7pyY
ICIKZm9ybWF0ID0gIlskc3ltYm9sKCR2ZXJzaW9uKV0oJHN0eWxlKSAiCnN0eWxlID0gImJvbGQg
Z3JlZW4iCgpbcnVzdF0Kc3ltYm9sID0gIu6eqCAiCmZvcm1hdCA9ICJbJHN5bWJvbCgkdmVyc2lv
bildKCRzdHlsZSkgIgpzdHlsZSA9ICJib2xkIHBlYWNoIgoKW2dvbGFuZ10Kc3ltYm9sID0gIu6Y
pyAiCmZvcm1hdCA9ICJbJHN5bWJvbCgkdmVyc2lvbildKCRzdHlsZSkgIgpzdHlsZSA9ICJib2xk
IHNreSIKCltwYWNrYWdlXQpzeW1ib2wgPSAi87CPlyAiCmZvcm1hdCA9ICJbJHN5bWJvbCR2ZXJz
aW9uXSgkc3R5bGUpICIKc3R5bGUgPSAiYm9sZCBwaW5rIgo=
KTERM_B64_RICH

base64 -d > "$APP_DIR/starship-compact.toml" <<'KTERM_B64_COMPACT'
YWRkX25ld2xpbmUgPSBmYWxzZQpjb21tYW5kX3RpbWVvdXQgPSAxMDAwCnNjYW5fdGltZW91dCA9
IDIwCnBhbGV0dGUgPSAiY2F0cHB1Y2Npbl9tb2NoYSIKZm9ybWF0ID0gIiRkaXJlY3RvcnkkZ2l0
X2JyYW5jaCRnaXRfc3RhdHVzJHB5dGhvbiRjb25kYSRjaGFyYWN0ZXIiCnJpZ2h0X2Zvcm1hdCA9
ICIkY21kX2R1cmF0aW9uJHN0YXR1cyR0aW1lIgoKW3BhbGV0dGVzLmNhdHBwdWNjaW5fbW9jaGFd
CnJlZCA9ICIjZjM4YmE4IgpwZWFjaCA9ICIjZmFiMzg3Igp5ZWxsb3cgPSAiI2Y5ZTJhZiIKZ3Jl
ZW4gPSAiI2E2ZTNhMSIKYmx1ZSA9ICIjODliNGZhIgptYXV2ZSA9ICIjY2JhNmY3Igp0ZXh0ID0g
IiNjZGQ2ZjQiCnN1YnRleHQwID0gIiNhNmFkYzgiCgpbZGlyZWN0b3J5XQpmb3JtYXQgPSAiW++B
vCAkcGF0aF0oJHN0eWxlKSAiCnN0eWxlID0gImJvbGQgYmx1ZSIKdHJ1bmNhdGlvbl9sZW5ndGgg
PSAzCnRydW5jYXRlX3RvX3JlcG8gPSBmYWxzZQoKW2dpdF9icmFuY2hdCnN5bWJvbCA9ICLvkJgg
Igpmb3JtYXQgPSAiWyRzeW1ib2wkYnJhbmNoXSgkc3R5bGUpICIKc3R5bGUgPSAiYm9sZCBtYXV2
ZSIKCltnaXRfc3RhdHVzXQpmb3JtYXQgPSAiKFskYWxsX3N0YXR1cyRhaGVhZF9iZWhpbmRdKCRz
dHlsZSkgKSIKc3R5bGUgPSAiYm9sZCBwZWFjaCIKCltweXRob25dCnN5bWJvbCA9ICLunLwgIgpm
b3JtYXQgPSAiWyRzeW1ib2woXFwoJHZpcnR1YWxlbnZcXCkpXSgkc3R5bGUpICIKc3R5bGUgPSAi
Ym9sZCB5ZWxsb3ciCgpbY29uZGFdCnN5bWJvbCA9ICLzsZSOICIKZm9ybWF0ID0gIlskc3ltYm9s
JGVudmlyb25tZW50XSgkc3R5bGUpICIKc3R5bGUgPSAiYm9sZCBncmVlbiIKaWdub3JlX2Jhc2Ug
PSBmYWxzZQoKW2NoYXJhY3Rlcl0Kc3VjY2Vzc19zeW1ib2wgPSAiW+Kdr10oYm9sZCBncmVlbikg
IgplcnJvcl9zeW1ib2wgPSAiW+Kdr10oYm9sZCByZWQpICIKCltjbWRfZHVyYXRpb25dCm1pbl90
aW1lID0gNzUwCmZvcm1hdCA9ICJb87GOqyAkZHVyYXRpb25dKCRzdHlsZSkgIgpzdHlsZSA9ICJi
b2xkIHllbGxvdyIKCltzdGF0dXNdCmRpc2FibGVkID0gZmFsc2UKc3ltYm9sID0gIuKcmCIKc3Vj
Y2Vzc19zeW1ib2wgPSAiIgpmb3JtYXQgPSAiWyRzeW1ib2wkc3RhdHVzXSgkc3R5bGUpICIKc3R5
bGUgPSAiYm9sZCByZWQiCgpbdGltZV0KZGlzYWJsZWQgPSBmYWxzZQp0aW1lX2Zvcm1hdCA9ICIl
SDolTSIKZm9ybWF0ID0gIlvvgJcgJHRpbWVdKCRzdHlsZSkiCnN0eWxlID0gImJvbGQgc3VidGV4
dDAiCg==
KTERM_B64_COMPACT

base64 -d > "$APP_DIR/switcher.zsh" <<'KTERM_B64_SWITCHER'
IyBLVEVSTSBjb3JlIGNvbnRyb2xzLiBMb2FkZWQgaW4gY2xhc3NpYyBhbmQgbW9kZXJuIG1vZGVz
LgpbWyAtbyBpbnRlcmFjdGl2ZSBdXSB8fCByZXR1cm4gMApleHBvcnQgS0FSVEhJX1NIRUxMX0hP
TUU9IiR7WERHX0NPTkZJR19IT01FOi0kSE9NRS8uY29uZmlnfS9rYXJ0aGktc2hlbGwiCmV4cG9y
dCBLQVJUSElfU0hFTExfREFUQT0iJHtYREdfREFUQV9IT01FOi0kSE9NRS8ubG9jYWwvc2hhcmV9
L2thcnRoaS1zaGVsbCIKZXhwb3J0IFBBVEg9IiRIT01FLy5sb2NhbC9iaW46JFBBVEgiCnR5cGVz
ZXQgLWdhIEtBUlRISV9TS0lQUEVEX0FMSUFTRVMKCl9rdGVybV9yZWFkX3N0YXRlKCkgewogIGxv
Y2FsIGZpbGU9IiQxIiBmYWxsYmFjaz0iJDIiIHZhbHVlCiAgaWYgW1sgLXIgIiRLQVJUSElfU0hF
TExfSE9NRS9zdGF0ZS8kZmlsZSIgXV07IHRoZW4KICAgIElGUz0gcmVhZCAtciB2YWx1ZSA8ICIk
S0FSVEhJX1NIRUxMX0hPTUUvc3RhdGUvJGZpbGUiCiAgICBwcmludCAtciAtLSAiJHt2YWx1ZTot
JGZhbGxiYWNrfSIKICBlbHNlCiAgICBwcmludCAtciAtLSAiJGZhbGxiYWNrIgogIGZpCn0KCl9r
dGVybV9pbnN0YWxsZXIoKSB7CiAgcHJpbnQgLXIgLS0gIiRLQVJUSElfU0hFTExfSE9NRS9pbnN0
YWxsLWt0ZXJtLnNoIgp9Cgpfa3Rlcm1fcmVzdGFydF9zaGVsbCgpIHsKICB1bnNldCBLQVJUSElf
TU9ERVJOX0xPQURFRCBLQVJUSElfSFVEX1NIT1dOIEtBUlRISV9CTE9DS19BQ1RJVkUgS0FSVEhJ
X0JMT0NLX1NUQVJUCiAgZXhlYyB6c2ggLWlsCn0KCmt0ZXJtLW1vZGVybigpIHsKICBleHBvcnQg
S0FSVEhJX1NIRUxMX01PREU9bW9kZXJuCiAgX2t0ZXJtX3Jlc3RhcnRfc2hlbGwKfQoKa3Rlcm0t
Y2xhc3NpYygpIHsKICBleHBvcnQgS0FSVEhJX1NIRUxMX01PREU9Y2xhc3NpYwogIF9rdGVybV9y
ZXN0YXJ0X3NoZWxsCn0KCmt0ZXJtLXNhZmUoKSB7CiAgdW5zZXQgS0FSVEhJX1NIRUxMX01PREUg
S0FSVEhJX01PREVSTl9MT0FERUQgS0FSVEhJX0hVRF9TSE9XTgogIGV4ZWMgenNoIC1kZgp9Cgpr
dGVybS1yZWxvYWQoKSB7CiAgZXhwb3J0IEtBUlRISV9TSEVMTF9NT0RFPSIke0tBUlRISV9TSEVM
TF9NT0RFOi0kKF9rdGVybV9yZWFkX3N0YXRlIGRlZmF1bHQtbW9kZSBtb2Rlcm4pfSIKICBfa3Rl
cm1fcmVzdGFydF9zaGVsbAp9Cgpfa3Rlcm1fYXBwbHlfcHJvZmlsZSgpIHsKICBsb2NhbCBtb2Rl
PSIkMSIgc291cmNlIHRhcmdldAogIHRhcmdldD0iJHtYREdfQ09ORklHX0hPTUU6LSRIT01FLy5j
b25maWd9L3Rlcm1pbmF0b3IvY29uZmlnIgogIGNhc2UgIiRtb2RlIiBpbgogICAgbW9kZXJuKSBz
b3VyY2U9IiRLQVJUSElfU0hFTExfSE9NRS90ZXJtaW5hdG9yLW1vZGVybi5jb25mIiA7OwogICAg
Y2xhc3NpYykgc291cmNlPSIkS0FSVEhJX1NIRUxMX0hPTUUvdGVybWluYXRvci1jbGFzc2ljLmNv
bmYiIDs7CiAgICAqKSByZXR1cm4gMiA7OwogIGVzYWMKICBta2RpciAtcCAiJEtBUlRISV9TSEVM
TF9IT01FL3N0YXRlIgogIHByaW50IC1yIC0tICIkbW9kZSIgPiAiJEtBUlRISV9TSEVMTF9IT01F
L3N0YXRlL2RlZmF1bHQtbW9kZSIKICBpZiBbWyAtciAiJHNvdXJjZSIgXV07IHRoZW4KICAgIG1r
ZGlyIC1wICIke3RhcmdldDpofSIKICAgIGNwIC1mIC0tICIkc291cmNlIiAiJHRhcmdldCIgfHwg
cmV0dXJuIDEKICAgIGNobW9kIDA2MDAgIiR0YXJnZXQiIDI+L2Rldi9udWxsIHx8IHRydWUKICBm
aQp9CgprdGVybS1zeXN0ZW0oKSB7CiAgY2FzZSAiJHsxOi1zdGF0dXN9IiBpbgogICAgbW9kZXJu
fGNsYXNzaWMpCiAgICAgIF9rdGVybV9hcHBseV9wcm9maWxlICIkMSIgfHwgcmV0dXJuICQ/CiAg
ICAgIHByaW50ICJGdXR1cmUgQ3RybCtBbHQrVCwgcmlnaHQtY2xpY2sgdGVybWluYWxzIGFuZCBw
bGFpbiBUZXJtaW5hdG9yIHVzZTogJDEiCiAgICAgIHByaW50ICJSdW4ga3Rlcm0tJDEgdG8gc3dp
dGNoIHRoaXMgY3VycmVudCBzaGVsbCBhcyB3ZWxsLiIKICAgICAgOzsKICAgIHN0YXR1cykgcHJp
bnQgIkRlc2t0b3AvZGVmYXVsdCBtb2RlOiAkKF9rdGVybV9yZWFkX3N0YXRlIGRlZmF1bHQtbW9k
ZSBtb2Rlcm4pIiA7OwogICAgKikgcHJpbnQgIlVzYWdlOiBrdGVybS1zeXN0ZW0gbW9kZXJufGNs
YXNzaWN8c3RhdHVzIiA+JjI7IHJldHVybiAyIDs7CiAgZXNhYwp9CgprdGVybS1kZWZhdWx0KCkg
ewogIGNhc2UgIiR7MTotfSIgaW4KICAgIG1vZGVybnxjbGFzc2ljKSBrdGVybS1zeXN0ZW0gIiQx
IiA7OwogICAgKikgcHJpbnQgIlVzYWdlOiBrdGVybS1kZWZhdWx0IG1vZGVybnxjbGFzc2ljIiA+
JjI7IHJldHVybiAyIDs7CiAgZXNhYwp9CgprcHJvbXB0KCkgewogIGNhc2UgIiR7MTotfSIgaW4K
ICAgIHJpY2h8Y29tcGFjdCkKICAgICAgbWtkaXIgLXAgIiRLQVJUSElfU0hFTExfSE9NRS9zdGF0
ZSIKICAgICAgcHJpbnQgLXIgLS0gIiQxIiA+ICIkS0FSVEhJX1NIRUxMX0hPTUUvc3RhdGUvcHJv
bXB0LXN0eWxlIgogICAgICBwcmludCAiUHJvbXB0IHN0eWxlIHNldCB0bzogJDEiCiAgICAgIFtb
ICIke0tBUlRISV9TSEVMTF9NT0RFOi19IiA9PSBtb2Rlcm4gXV0gJiYga3Rlcm0tbW9kZXJuCiAg
ICAgIDs7CiAgICAqKSBwcmludCAiVXNhZ2U6IGtwcm9tcHQgcmljaHxjb21wYWN0IiA+JjI7IHJl
dHVybiAyIDs7CiAgZXNhYwp9CgprYmxvY2tzKCkgewogIGNhc2UgIiR7MTotc3RhdHVzfSIgaW4K
ICAgIG9ufG9mZikKICAgICAgbWtkaXIgLXAgIiRLQVJUSElfU0hFTExfSE9NRS9zdGF0ZSIKICAg
ICAgZXhwb3J0IEtBUlRISV9CTE9DS1M9IiQxIgogICAgICBwcmludCAtciAtLSAiJDEiID4gIiRL
QVJUSElfU0hFTExfSE9NRS9zdGF0ZS9ibG9ja3MiCiAgICAgIHByaW50ICJWaXN1YWwgY29tbWFu
ZCBibG9ja3M6ICQxIgogICAgICA7OwogICAgc3RhdHVzKSBwcmludCAiVmlzdWFsIGNvbW1hbmQg
YmxvY2tzOiAke0tBUlRISV9CTE9DS1M6LSQoX2t0ZXJtX3JlYWRfc3RhdGUgYmxvY2tzIG9uKX0i
IDs7CiAgICAqKSBwcmludCAiVXNhZ2U6IGtibG9ja3Mgb258b2ZmfHN0YXR1cyIgPiYyOyByZXR1
cm4gMiA7OwogIGVzYWMKfQoKa2h1ZCgpIHsKICBjYXNlICIkezE6LXN0YXR1c30iIGluCiAgICBv
bnxvZmYpCiAgICAgIG1rZGlyIC1wICIkS0FSVEhJX1NIRUxMX0hPTUUvc3RhdGUiCiAgICAgIGV4
cG9ydCBLQVJUSElfSFVEPSIkMSIKICAgICAgcHJpbnQgLXIgLS0gIiQxIiA+ICIkS0FSVEhJX1NI
RUxMX0hPTUUvc3RhdGUvaHVkIgogICAgICBwcmludCAiU3RhcnR1cCBIVUQ6ICQxIgogICAgICA7
OwogICAgbm93KQogICAgICBpZiAoKCAkeytmdW5jdGlvbnNbX2thcnRoaV9yZW5kZXJfaHVkXX0g
KSk7IHRoZW4KICAgICAgICBfa2FydGhpX3JlbmRlcl9odWQKICAgICAgZWxzZQogICAgICAgIHBy
aW50ICJIVUQgcmVuZGVyaW5nIGlzIGF2YWlsYWJsZSBpbiBtb2Rlcm4gbW9kZS4iCiAgICAgIGZp
CiAgICAgIDs7CiAgICBzdGF0dXMpIHByaW50ICJTdGFydHVwIEhVRDogJHtLQVJUSElfSFVEOi0k
KF9rdGVybV9yZWFkX3N0YXRlIGh1ZCBvbil9IiA7OwogICAgKikgcHJpbnQgIlVzYWdlOiBraHVk
IG9ufG9mZnxub3d8c3RhdHVzIiA+JjI7IHJldHVybiAyIDs7CiAgZXNhYwp9CgprdGVybS1zdGF0
dXMoKSB7CiAgbG9jYWwgZGVmYXVsdF9tb2RlIHByb21wdF9zdHlsZSBibG9ja3MgaHVkIHBsYXRm
b3JtCiAgZGVmYXVsdF9tb2RlPSIkKF9rdGVybV9yZWFkX3N0YXRlIGRlZmF1bHQtbW9kZSBtb2Rl
cm4pIgogIHByb21wdF9zdHlsZT0iJChfa3Rlcm1fcmVhZF9zdGF0ZSBwcm9tcHQtc3R5bGUgcmlj
aCkiCiAgYmxvY2tzPSIkKF9rdGVybV9yZWFkX3N0YXRlIGJsb2NrcyBvbikiCiAgaHVkPSIkKF9r
dGVybV9yZWFkX3N0YXRlIGh1ZCBvbikiCiAgcGxhdGZvcm09IiQoX2t0ZXJtX3JlYWRfc3RhdGUg
cGxhdGZvcm0gdW5rbm93bikiCiAgcHJpbnQgIktURVJNICAgICAgIDogdiQoX2t0ZXJtX3JlYWRf
c3RhdGUgdmVyc2lvbiB1bmtub3duKSIKICBwcmludCAiUGxhdGZvcm0gICAgOiAkcGxhdGZvcm0i
CiAgcHJpbnQgIkFjdGl2ZSBtb2RlIDogJHtLQVJUSElfU0hFTExfTU9ERTotJGRlZmF1bHRfbW9k
ZX0iCiAgcHJpbnQgIkRlZmF1bHQgbW9kZTogJGRlZmF1bHRfbW9kZSIKICBwcmludCAiUHJvbXB0
ICAgICAgOiAkcHJvbXB0X3N0eWxlIgogIHByaW50ICJDbWQgYmxvY2tzICA6ICRibG9ja3MiCiAg
cHJpbnQgIlN0YXJ0dXAgSFVEIDogJGh1ZCIKICBwcmludCAiQ29uZmlnIHJvb3QgOiAkS0FSVEhJ
X1NIRUxMX0hPTUUiCiAgcHJpbnQgIlpzaCAgICAgICAgIDogJHtaU0hfVkVSU0lPTjotdW5rbm93
bn0iCiAgY29tbWFuZCAtdiBzdGFyc2hpcCA+L2Rldi9udWxsIDI+JjEgJiYgcHJpbnQgIlN0YXJz
aGlwICAgIDogJChzdGFyc2hpcCAtLXZlcnNpb24gMj4vZGV2L251bGwgfCBoZWFkIC1uMSkiCiAg
Y29tbWFuZCAtdiBmemYgPi9kZXYvbnVsbCAyPiYxICYmIHByaW50ICJmemYgICAgICAgICA6ICQo
ZnpmIC0tdmVyc2lvbiAyPi9kZXYvbnVsbCB8IGhlYWQgLW4xKSIKICBjb21tYW5kIC12IHpveGlk
ZSA+L2Rldi9udWxsIDI+JjEgJiYgcHJpbnQgInpveGlkZSAgICAgIDogJCh6b3hpZGUgLS12ZXJz
aW9uIDI+L2Rldi9udWxsIHwgaGVhZCAtbjEpIgogIGlmIGNvbW1hbmQgLXYgYXR1aW4gPi9kZXYv
bnVsbCAyPiYxICYmIGF0dWluIC0tdmVyc2lvbiA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICAgIHBy
aW50ICJBdHVpbiAgICAgICA6ICQoYXR1aW4gLS12ZXJzaW9uIDI+L2Rldi9udWxsIHwgaGVhZCAt
bjEpIgogIGVsc2UKICAgIHByaW50ICJBdHVpbiAgICAgICA6IHVuYXZhaWxhYmxlOyBDdHJsK1Ig
dXNlcyBmemYgaGlzdG9yeSIKICBmaQogIGlmICgoICR7I0tBUlRISV9TS0lQUEVEX0FMSUFTRVNb
QF19ICkpOyB0aGVuCiAgICBwcmludCAiS2VwdCBuYW1lcyAgOiAke0tBUlRISV9TS0lQUEVEX0FM
SUFTRVNbKl19IgogIGZpCn0KCmt0ZXJtLWRvY3RvcigpIHsKICBsb2NhbCByYz0wIG1vZGUgZXhw
ZWN0ZWQgYWN0dWFsIHNoZWxsX25vdwogIG1vZGU9IiQoX2t0ZXJtX3JlYWRfc3RhdGUgZGVmYXVs
dC1tb2RlIG1vZGVybikiCiAgZXhwZWN0ZWQ9IiRLQVJUSElfU0hFTExfSE9NRS90ZXJtaW5hdG9y
LSR7bW9kZX0uY29uZiIKICBhY3R1YWw9IiR7WERHX0NPTkZJR19IT01FOi0kSE9NRS8uY29uZmln
fS90ZXJtaW5hdG9yL2NvbmZpZyIKICBwcmludCAiS1RFUk0gZG9jdG9yIgogIHByaW50ICItLS0t
LS0tLS0tLS0iCgogIHNoZWxsX25vdz0iJChnZXRlbnQgcGFzc3dkICIkVVNFUiIgMj4vZGV2L251
bGwgfCBhd2sgLUY6ICd7cHJpbnQgJDd9JykiCiAgaWYgW1sgIiRzaGVsbF9ub3ciID09ICovenNo
IF1dOyB0aGVuIHByaW50ICJbT0tdIExvZ2luIHNoZWxsIGlzIFpzaCI7IGVsc2UgcHJpbnQgIltX
QVJOXSBMb2dpbiBzaGVsbDogJHtzaGVsbF9ub3c6LXVua25vd259IjsgcmM9MTsgZmkKCiAgaWYg
Y29tbWFuZCAtdiBzdGFyc2hpcCA+L2Rldi9udWxsIDI+JjE7IHRoZW4gcHJpbnQgIltPS10gU3Rh
cnNoaXAiOyBlbHNlIHByaW50ICJbV0FSTl0gU3RhcnNoaXAgbWlzc2luZyI7IHJjPTE7IGZpCiAg
aWYgY29tbWFuZCAtdiBmemYgPi9kZXYvbnVsbCAyPiYxOyB0aGVuIHByaW50ICJbT0tdIGZ6ZiI7
IGVsc2UgcHJpbnQgIltXQVJOXSBmemYgbWlzc2luZyI7IHJjPTE7IGZpCiAgaWYgY29tbWFuZCAt
diB6b3hpZGUgPi9kZXYvbnVsbCAyPiYxOyB0aGVuIHByaW50ICJbT0tdIHpveGlkZSI7IGVsc2Ug
cHJpbnQgIltXQVJOXSB6b3hpZGUgbWlzc2luZyI7IHJjPTE7IGZpCiAgaWYgW1sgLXggIiRIT01F
Ly5sb2NhbC9iaW4va2FydGhpLWRhc2hib2FyZCIgXV07IHRoZW4gcHJpbnQgIltPS10gRGFzaGJv
YXJkIGhlbHBlciI7IGVsc2UgcHJpbnQgIltXQVJOXSBEYXNoYm9hcmQgaGVscGVyIG1pc3Npbmci
OyByYz0xOyBmaQoKICBpZiBbWyAiJChfa3Rlcm1fcmVhZF9zdGF0ZSBkZXNrdG9wLWVuYWJsZWQg
b24pIiA9PSBvbiBdXTsgdGhlbgogICAgaWYgY29tbWFuZCAtdiB0ZXJtaW5hdG9yID4vZGV2L251
bGwgMj4mMTsgdGhlbiBwcmludCAiW09LXSBUZXJtaW5hdG9yIjsgZWxzZSBwcmludCAiW1dBUk5d
IFRlcm1pbmF0b3IgbWlzc2luZyI7IHJjPTE7IGZpCiAgICBpZiBbWyAtciAiJGFjdHVhbCIgXV0g
JiYgZ3JlcCAtRXEgJ2Fsd2F5c19zcGxpdF93aXRoX3Byb2ZpbGVbWzpzcGFjZTpdXSo9W1s6c3Bh
Y2U6XV0qVHJ1ZScgIiRhY3R1YWwiOyB0aGVuCiAgICAgIHByaW50ICJbT0tdIFNwbGl0IHBhbmVz
IGluaGVyaXQgdGhlIGFjdGl2ZSBwcm9maWxlIgogICAgZWxzZQogICAgICBwcmludCAiW1dBUk5d
IFVuaWZvcm0gc3BsaXQgc2V0dGluZyBtaXNzaW5nIgogICAgICByYz0xCiAgICBmaQogICAgaWYg
W1sgLXIgIiRleHBlY3RlZCIgJiYgLXIgIiRhY3R1YWwiIF1dICYmIGNtcCAtcyAtLSAiJGV4cGVj
dGVkIiAiJGFjdHVhbCI7IHRoZW4KICAgICAgcHJpbnQgIltPS10gTGl2ZSBUZXJtaW5hdG9yIHBy
b2ZpbGUgbWF0Y2hlcyAkbW9kZSBtb2RlIgogICAgZWxzZQogICAgICBwcmludCAiW0lORk9dIExp
dmUgVGVybWluYXRvciBwcm9maWxlIGRpZmZlcnMgZnJvbSBzdG9yZWQgJG1vZGUgcHJvZmlsZSIK
ICAgIGZpCiAgICBpZiBbWyAtTCAvZXRjL2FsdGVybmF0aXZlcy94LXRlcm1pbmFsLWVtdWxhdG9y
IF1dICYmIFtbICIkKHJlYWRsaW5rIC1mIC9ldGMvYWx0ZXJuYXRpdmVzL3gtdGVybWluYWwtZW11
bGF0b3IgMj4vZGV2L251bGwpIiA9PSAqL3Rlcm1pbmF0b3IgXV07IHRoZW4KICAgICAgcHJpbnQg
IltPS10geC10ZXJtaW5hbC1lbXVsYXRvciAtPiBUZXJtaW5hdG9yIgogICAgZWxzZQogICAgICBw
cmludCAiW0lORk9dIHgtdGVybWluYWwtZW11bGF0b3IgaXMgbm90IFRlcm1pbmF0b3IiCiAgICBm
aQogICAgaWYgW1sgLXIgIiR7WERHX0RBVEFfSE9NRTotJEhPTUUvLmxvY2FsL3NoYXJlfS9uYXV0
aWx1cy1weXRob24vZXh0ZW5zaW9ucy9rdGVybV9vcGVuX3Rlcm1pbmFsLnB5IiBdXTsgdGhlbgog
ICAgICBwcmludCAiW09LXSBOYXV0aWx1cyBLVEVSTSBleHRlbnNpb24gaW5zdGFsbGVkIgogICAg
ZWxpZiBjb21tYW5kIC12IG5hdXRpbHVzID4vZGV2L251bGwgMj4mMTsgdGhlbgogICAgICBwcmlu
dCAiW0lORk9dIE5hdXRpbHVzIGlzIHByZXNlbnQgYnV0IGl0cyBLVEVSTSBleHRlbnNpb24gaXMg
bm90IGFjdGl2ZSIKICAgIGZpCiAgICBpZiBjb21tYW5kIC12IGZjLW1hdGNoID4vZGV2L251bGwg
Mj4mMSAmJiBmYy1tYXRjaCAnSmV0QnJhaW5zTW9ubyBOZXJkIEZvbnQnIDI+L2Rldi9udWxsIHwg
Z3JlcCAtcWkgJ0pldEJyYWlucyc7IHRoZW4KICAgICAgcHJpbnQgIltPS10gSmV0QnJhaW5zTW9u
byBOZXJkIEZvbnQiCiAgICBlbHNlCiAgICAgIHByaW50ICJbV0FSTl0gTmVyZCBGb250IG1pc3Np
bmc7IGljb25zIGNhbiByZW5kZXIgYXMgYm94ZXMiCiAgICAgIHJjPTEKICAgIGZpCiAgZmkKCiAg
aWYgY29tbWFuZCAtdiBhdHVpbiA+L2Rldi9udWxsIDI+JjEgJiYgISBhdHVpbiAtLXZlcnNpb24g
Pi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgICBwcmludCAiW1dBUk5dIEF0dWluIGV4aXN0cyBidXQg
aXMgbm90IHJ1bm5hYmxlOyBmemYgZmFsbGJhY2sgcmVtYWlucyBzYWZlIgogIGVsc2UKICAgIHBy
aW50ICJbT0tdIEhpc3Rvcnkgc2VhcmNoIGhhcyBhIHdvcmtpbmcgYmFja2VuZCIKICBmaQoKICBp
ZiBjb21tYW5kIC12IHRtdXggPi9kZXYvbnVsbCAyPiYxOyB0aGVuIHByaW50ICJbT0tdIHRtdXgg
ZGFzaGJvYXJkIGJhY2tlbmQiOyBlbHNlIHByaW50ICJbV0FSTl0gdG11eCBtaXNzaW5nIjsgcmM9
MTsgZmkKICBwcmludCAiLS0tLS0tLS0tLS0tIgogICgoIHJjID09IDAgKSkgJiYgcHJpbnQgIktU
RVJNIGlzIGhlYWx0aHkuIiB8fCBwcmludCAiT25lIG9yIG1vcmUgb3B0aW9uYWwvZGVza3RvcCBj
aGVja3MgbmVlZCBhdHRlbnRpb24uIFJ1bjoga3Rlcm0tcmVwYWlyIgogIHJldHVybiAiJHJjIgp9
Cgpfa3Rlcm1fcnVuX2luc3RhbGxlcigpIHsKICBsb2NhbCBhY3Rpb249IiQxIiBpbnN0YWxsZXIK
ICBsb2NhbCAtYSBhcmdzCiAgaW5zdGFsbGVyPSIkKF9rdGVybV9pbnN0YWxsZXIpIgogIFtbIC1y
ICIkaW5zdGFsbGVyIiBdXSB8fCB7IHByaW50ICJJbnN0YWxsZXIgY29weSBtaXNzaW5nOiAkaW5z
dGFsbGVyIiA+JjI7IHJldHVybiAxOyB9CiAgYXJncz0oIi0tJGFjdGlvbiIpCiAgW1sgIiQoX2t0
ZXJtX3JlYWRfc3RhdGUgZGVza3RvcC1lbmFibGVkIG9uKSIgPT0gb2ZmIF1dICYmIGFyZ3MrPSgt
LW5vLWRlc2t0b3ApCiAgW1sgIiQoX2t0ZXJtX3JlYWRfc3RhdGUgaW5zdGFsbC1wcm9maWxlIGZ1
bGwpIiA9PSBtaW5pbWFsIF1dICYmIGFyZ3MrPSgtLW1pbmltYWwpCiAgYmFzaCAiJGluc3RhbGxl
ciIgIiR7YXJnc1tAXX0iCn0KCmt0ZXJtLXVwZGF0ZSgpIHsgX2t0ZXJtX3J1bl9pbnN0YWxsZXIg
dXBkYXRlOyB9Cmt0ZXJtLXJlcGFpcigpIHsgX2t0ZXJtX3J1bl9pbnN0YWxsZXIgcmVwYWlyOyB9
Cmt0ZXJtLXVuaW5zdGFsbCgpIHsgX2t0ZXJtX3J1bl9pbnN0YWxsZXIgdW5pbnN0YWxsOyB9Cmt0
ZXJtLWxvZygpIHsKICBsb2NhbCBwYWdlcj0iJHtQQUdFUjotbGVzc30iCiAgJHs9cGFnZXJ9ICIk
S0FSVEhJX1NIRUxMX0hPTUUvaW5zdGFsbC5sb2ciCn0Ka3Rlcm0tYmFja3VwcygpIHsKICBsb2Nh
bCBwYWdlcj0iJHtQQUdFUjotbGVzc30iCiAgY29tbWFuZCBmaW5kICIkS0FSVEhJX1NIRUxMX0hP
TUUvYmFja3VwcyIgLW1heGRlcHRoIDQgLXR5cGUgZiAtcHJpbnRmICclVFktJVRtLSVUZCAlVEg6
JVRNICAlcFxuJyAyPi9kZXYvbnVsbCB8IHNvcnQgLXIgfCAkez1wYWdlcn0KfQprdGVybS12ZXJz
aW9uKCkgeyBwcmludCAiS1RFUk0gdiQoX2t0ZXJtX3JlYWRfc3RhdGUgdmVyc2lvbiB1bmtub3du
KSAoJChfa3Rlcm1fcmVhZF9zdGF0ZSBwbGF0Zm9ybSB1bmtub3duKSkiOyB9CgprdGVybS1oZWxw
KCkgewogIGNhdCA8PCdIRUxQJwpLVEVSTSBtb2RlIGFuZCByZWNvdmVyeQogIGt0ZXJtLW1vZGVy
biAvIGt0ZXJtLWNsYXNzaWMgICAgICAgc3dpdGNoIHRoaXMgc2hlbGwgaW1tZWRpYXRlbHkKICBr
dGVybS1zeXN0ZW0gbW9kZXJufGNsYXNzaWMgICAgICAgIGNoYW5nZSBhbGwgZnV0dXJlIGRlc2t0
b3AgdGVybWluYWxzCiAga3Rlcm0tZGVmYXVsdCBtb2Rlcm58Y2xhc3NpYyAgICAgICBhbGlhcyBv
ZiBrdGVybS1zeXN0ZW0KICBrdGVybS1zYWZlICAgICAgICAgICAgICAgICAgICAgICAgIGNsZWFu
IFpzaCB3aXRob3V0IHN0YXJ0dXAgZmlsZXMKICBrdGVybS1yZWxvYWQgICAgICAgICAgICAgICAg
ICAgICAgIHJlbG9hZCB0aGUgY3VycmVudCBzZWxlY3RlZCBtb2RlCiAga3Byb21wdCByaWNofGNv
bXBhY3QgICAgICAgICAgICAgICBzZWxlY3QgcHJvbXB0IGRlbnNpdHkKICBrYmxvY2tzIG9ufG9m
ZnxzdGF0dXMgICAgICAgICAgICAgIHZpc3VhbCBjb21tYW5kIGJvdW5kYXJpZXMKICBraHVkIG9u
fG9mZnxub3d8c3RhdHVzICAgICAgICAgICAgIHN0YXJ0dXAgZGV2ZWxvcGVyIEhVRAoKTWFpbnRl
bmFuY2UKICBrdGVybS1zdGF0dXMgICAgICAgICAgICAgICAgICAgICAgIGFjdGl2ZSBtb2RlIGFu
ZCB0b29sIHZlcnNpb25zCiAga3Rlcm0tZG9jdG9yICAgICAgICAgICAgICAgICAgICAgICB2ZXJp
Znkgc2hlbGwsIGRlc2t0b3AsIHNwbGl0cyBhbmQgdG9vbHMKICBrdGVybS11cGRhdGUgICAgICAg
ICAgICAgICAgICAgICAgIHVwZGF0ZSBwYWNrYWdlcy90b29scy9jb25maWd1cmF0aW9uCiAga3Rl
cm0tcmVwYWlyICAgICAgICAgICAgICAgICAgICAgICByZWFwcGx5IG1hbmFnZWQgY29uZmlndXJh
dGlvbgogIGt0ZXJtLXVuaW5zdGFsbCAgICAgICAgICAgICAgICAgICAgcmVzdG9yZSBtYW5hZ2Vk
IGRlc2t0b3Avc2hlbGwgaW50ZWdyYXRpb24KICBrdGVybS1sb2cgLyBrdGVybS1iYWNrdXBzICAg
ICAgICAgIGluc3BlY3QgbG9ncyBhbmQgc2FmZXR5IHNuYXBzaG90cwogIGt0ZXJtLXZlcnNpb24g
ICAgICAgICAgICAgICAgICAgICAgaW5zdGFsbGVkIGJ1bmRsZSB2ZXJzaW9uCgpWaXN1YWwgY29t
bWFuZHMgKG1vZGVybiBtb2RlKQogIGt2bHMgLyBrdmxsIC8ga3Z0cmVlIFtkZXB0aF0gICAgICAg
aWNvbi1hd2FyZSBsaXN0aW5ncyBhbmQgdHJlZQogIGt2Y2F0IEZJTEUgICAgICAgICAgICAgICAg
ICAgICAgICAgaGlnaGxpZ2h0ZWQgY29kZS9maWxlIHZpZXdlcgogIGt2Z3JlcCBRVUVSWSBbUEFU
SF0gICAgICAgICAgICAgICAgZmFzdCByZWN1cnNpdmUgc2VhcmNoCiAga3ZkaWZmIFthcmdzXSAv
IGt2Z2l0ICAgICAgICAgICAgICBoaWdobGlnaHRlZCBHaXQgZGlmZiAvIExhenlHaXQKICBreWF6
aSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRlcm1pbmFsIGZpbGUgbWFuYWdlcgogIGtm
ZiAvIGtmY2QgICAgICAgICAgICAgICAgICAgICAgICAgZnV6enkgZmlsZSBlZGl0b3IgLyBkaXJl
Y3RvcnkgY2hvb3NlcgogIGtmYnJhbmNoICAgICAgICAgICAgICAgICAgICAgICAgICAgZnV6enkg
R2l0IGJyYW5jaCBzZWxlY3RvcgogIGtmdmVudiAvIGtmY29uZGEgICAgICAgICAgICAgICAgICAg
UHl0aG9uL0NvbmRhIGVudmlyb25tZW50IHNlbGVjdG9yCiAga2Zkb2NrZXIgLyBrZmtpbGwgICAg
ICAgICAgICAgICAgICBjb250YWluZXIgc2hlbGwgLyBwcm9jZXNzIHNlbGVjdG9yCiAga21rY2Qg
RElSIC8ga3NlcnZlIFtQT1JUXSBbQklORF0gIGNyZWF0ZStlbnRlciBkaXJlY3RvcnkgLyBsb2Nh
bCB3ZWIgc2VydmVyCiAga3N5c2luZm8gLyBrc3lzbW9uICAgICAgICAgICAgICAgICBzeXN0ZW0g
c3VtbWFyeSAvIGJ0b3AgbW9uaXRvcgogIGtncHV0b3AgLyBrbmV0bW9uICAgICAgICAgICAgICAg
ICAgR1BVL1NvQyAvIG5ldHdvcmsgbW9uaXRvcgogIGtkYXNoYm9hcmQgW29wdGlvbnNdICAgICAg
ICAgICAgICAgdGhyZWUtcGFuZSB0bXV4IHdvcmtzdGF0aW9uCgpMYXVuY2hlcnMKICB0ZXJtaW5h
dG9yLW1vZGVybiAgICAgICAgICAgICAgICAgIGV4cGxpY2l0IGZ1dHVyaXN0aWMgVGVybWluYXRv
cgogIHRlcm1pbmF0b3ItY2xhc3NpYyAgICAgICAgICAgICAgICAgc2F2ZWQgcHJlLUtURVJNIFRl
cm1pbmF0b3IKICBrdGVybS10ZXJtaW5hbCAgICAgICAgICAgICAgICAgICAgIG1vZGUtYXdhcmUg
ZGVza3RvcCBsYXVuY2hlcgoKS2V5cwogIEN0cmwrUiAgICAgQXR1aW4gaGlzdG9yeSB3aGVuIGNv
bXBhdGlibGU7IG90aGVyd2lzZSBmemYgaGlzdG9yeQogIEFsdCtSICAgICAgb3JpZ2luYWwgaW5j
cmVtZW50YWwgWnNoIGhpc3Rvcnkgc2VhcmNoCiAgQ3RybCtUICAgICBmdXp6eSBmaWxlIGluc2Vy
dGlvbgogIEFsdCtDICAgICAgZnV6enkgZGlyZWN0b3J5IGNoYW5nZQogIFRhYiAgICAgICAgdmlz
dWFsIGZ1enp5IGNvbXBsZXRpb24KICBSaWdodCAgICAgIGFjY2VwdCBhdXRvc3VnZ2VzdGlvbgog
IEN0cmwrLyAgICAgdG9nZ2xlIHByZXZpZXcgd2hpbGUgaW5zaWRlIGZ6ZgogIEN0cmwrU2hpZnQr
RSAvIEN0cmwrU2hpZnQrTyAgICAgICAgVGVybWluYXRvciB2ZXJ0aWNhbC9ob3Jpem9udGFsIHNw
bGl0CkhFTFAKfQoKaWYgKCggISAkeythbGlhc2VzW2toZWxwXX0gJiYgISAkeytmdW5jdGlvbnNb
a2hlbHBdfSAmJiAhICR7K2NvbW1hbmRzW2toZWxwXX0gKSk7IHRoZW4KICBhbGlhcyBraGVscD1r
dGVybS1oZWxwCmZpCg==
KTERM_B64_SWITCHER

base64 -d > "$APP_DIR/modern.zsh" <<'KTERM_B64_MODERN'
IyBNYW5hZ2VkIG1vZGVybiBwcm9maWxlLiBUaGUgdXNlcidzIG9yaWdpbmFsIH4vLnpzaHJjIGhh
cyBhbHJlYWR5IHJ1bi4KW1sgLW8gaW50ZXJhY3RpdmUgXV0gfHwgcmV0dXJuIDAKW1sgIiR7VEVS
TTotfSIgPT0gZHVtYiBdXSAmJiByZXR1cm4gMApbWyAtbiAiJHtLQVJUSElfTU9ERVJOX0xPQURF
RDotfSIgXV0gJiYgcmV0dXJuIDAKZXhwb3J0IEtBUlRISV9NT0RFUk5fTE9BREVEPTEKZXhwb3J0
IEtBUlRISV9TSEVMTF9NT0RFPW1vZGVybgpleHBvcnQgS0FSVEhJX1NIRUxMX0hPTUU9IiR7WERH
X0NPTkZJR19IT01FOi0kSE9NRS8uY29uZmlnfS9rYXJ0aGktc2hlbGwiCmV4cG9ydCBLQVJUSElf
U0hFTExfREFUQT0iJHtYREdfREFUQV9IT01FOi0kSE9NRS8ubG9jYWwvc2hhcmV9L2thcnRoaS1z
aGVsbCIKZXhwb3J0IEtBUlRISV9TSEVMTF9DQUNIRT0iJHtYREdfQ0FDSEVfSE9NRTotJEhPTUUv
LmNhY2hlfS9rYXJ0aGktc2hlbGwiCmV4cG9ydCBQQVRIPSIkSE9NRS8ubG9jYWwvYmluOiRIT01F
Ly5hdHVpbi9iaW46JFBBVEgiCm1rZGlyIC1wICIkS0FSVEhJX1NIRUxMX0NBQ0hFIiAiJEtBUlRI
SV9TSEVMTF9IT01FL3N0YXRlIgoKX2tyZWFkKCkgewogIGxvY2FsIGZpbGU9IiQxIiBmYWxsYmFj
az0iJDIiIHZhbHVlCiAgaWYgW1sgLXIgIiRLQVJUSElfU0hFTExfSE9NRS9zdGF0ZS8kZmlsZSIg
XV07IHRoZW4KICAgIElGUz0gcmVhZCAtciB2YWx1ZSA8ICIkS0FSVEhJX1NIRUxMX0hPTUUvc3Rh
dGUvJGZpbGUiCiAgICBwcmludCAtciAtLSAiJHt2YWx1ZTotJGZhbGxiYWNrfSIKICBlbHNlCiAg
ICBwcmludCAtciAtLSAiJGZhbGxiYWNrIgogIGZpCn0KCmV4cG9ydCBLQVJUSElfQkxPQ0tTPSIk
e0tBUlRISV9CTE9DS1M6LSQoX2tyZWFkIGJsb2NrcyBvbil9Igp0eXBlc2V0IF9rcHJvbXB0X3N0
eWxlPSIkKF9rcmVhZCBwcm9tcHQtc3R5bGUgcmljaCkiCmNhc2UgIiRfa3Byb21wdF9zdHlsZSIg
aW4KICBjb21wYWN0KSBleHBvcnQgU1RBUlNISVBfQ09ORklHPSIkS0FSVEhJX1NIRUxMX0hPTUUv
c3RhcnNoaXAtY29tcGFjdC50b21sIiA7OwogICopICAgICAgIGV4cG9ydCBTVEFSU0hJUF9DT05G
SUc9IiRLQVJUSElfU0hFTExfSE9NRS9zdGFyc2hpcC1yaWNoLnRvbWwiIDs7CmVzYWMKZXhwb3J0
IFNUQVJTSElQX0NBQ0hFPSIkS0FSVEhJX1NIRUxMX0NBQ0hFL3N0YXJzaGlwIgpleHBvcnQgQVRV
SU5fQ09ORklHX0RJUj0iJEtBUlRISV9TSEVMTF9IT01FL2F0dWluIgpleHBvcnQgS0FSVEhJX0hV
RD0iJHtLQVJUSElfSFVEOi0kKF9rcmVhZCBodWQgb24pfSIKCmZ1bmN0aW9uIF9rYXJ0aGlfcmVu
ZGVyX2h1ZCgpIHsKICBsb2NhbCBjd2QgaG9zdCBnaXRfaW5mbyBweV9pbmZvIGdwdV9pbmZvIG5v
dyBicmFuY2ggcHl2ZXIKICBjd2Q9IiR7UFdELyMkSE9NRS9+fSIKICBob3N0PSIke0hPU1QlJS4q
fSIKICBub3c9IiQoZGF0ZSArJUg6JU0pIgogIGdpdF9pbmZvPSIiCiAgcHlfaW5mbz0iIgogIGdw
dV9pbmZvPSIiCgogIGlmIGNvbW1hbmQgZ2l0IHJldi1wYXJzZSAtLWlzLWluc2lkZS13b3JrLXRy
ZWUgPi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgICBicmFuY2g9IiQoY29tbWFuZCBnaXQgYnJhbmNo
IC0tc2hvdy1jdXJyZW50IDI+L2Rldi9udWxsKSIKICAgIFtbIC1uICIkYnJhbmNoIiBdXSB8fCBi
cmFuY2g9IiQoY29tbWFuZCBnaXQgcmV2LXBhcnNlIC0tc2hvcnQgSEVBRCAyPi9kZXYvbnVsbCki
CiAgICBbWyAtbiAiJGJyYW5jaCIgXV0gJiYgZ2l0X2luZm89ImdpdDokYnJhbmNoIgogIGZpCgog
IGlmIFtbIC1uICIke0NPTkRBX0RFRkFVTFRfRU5WOi19IiBdXTsgdGhlbgogICAgcHlfaW5mbz0i
Y29uZGE6JHtDT05EQV9ERUZBVUxUX0VOVn0iCiAgZWxpZiBbWyAtbiAiJHtWSVJUVUFMX0VOVjot
fSIgXV07IHRoZW4KICAgIHB5X2luZm89InZlbnY6JHtWSVJUVUFMX0VOVjp0fSIKICBlbGlmIGNv
bW1hbmQgLXYgcHl0aG9uMyA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICAgIHB5dmVyPSIkKHB5dGhv
bjMgLVYgMj4vZGV2L251bGwgfCBhd2sgJ3twcmludCAkMn0nKSIKICAgIFtbIC1uICIkcHl2ZXIi
IF1dICYmIHB5X2luZm89InB5OiRweXZlciIKICBmaQoKICBpZiBjb21tYW5kIC12IG52aWRpYS1z
bWkgPi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgICBncHVfaW5mbz0iJChudmlkaWEtc21pIC0tcXVl
cnktZ3B1PW5hbWUsbWVtb3J5LnRvdGFsIC0tZm9ybWF0PWNzdixub2hlYWRlciAyPi9kZXYvbnVs
bCB8IGhlYWQgLW4xKSIKICBmaQoKICBjd2Q9IiR7Y3dkLy9cJS8lJX0iOyBob3N0PSIke2hvc3Qv
L1wlLyUlfSI7IGdpdF9pbmZvPSIke2dpdF9pbmZvLy9cJS8lJX0iCiAgcHlfaW5mbz0iJHtweV9p
bmZvLy9cJS8lJX0iOyBncHVfaW5mbz0iJHtncHVfaW5mby8vXCUvJSV9IgogIHByaW50IC1yUCAt
LSAiJUZ7IzZjNzA4Nn3ila3ilIAlZiAlQiVGeyM4OWI0ZmF94peiIEtURVJNIC8vIFZJU1VBTCBE
RVYgQ09OU09MRSDil6MlZiViICVGeyM2YzcwODZ94pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA
4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAJWYiCiAgcHJpbnQg
LXJQIC0tICIlRnsjNmM3MDg2feKUgiVmICVGeyM5NGUyZDV9VVNFUiVmICR7VVNFUn1AJHtob3N0
fSAgICVGeyM5NGUyZDV9VElNRSVmICR7bm93fSIKICBwcmludCAtclAgLS0gIiVGeyM2YzcwODZ9
4pSCJWYgJUZ7Izk0ZTJkNX1QQVRIJWYgJHtjd2R9IgogIFtbIC1uICIkZ2l0X2luZm8kcHlfaW5m
byIgXV0gJiYgcHJpbnQgLXJQIC0tICIlRnsjNmM3MDg2feKUgiVmICVGeyM5NGUyZDV9REVWICVm
ICR7Z2l0X2luZm99ICR7cHlfaW5mb30iCiAgW1sgLW4gIiRncHVfaW5mbyIgXV0gJiYgcHJpbnQg
LXJQIC0tICIlRnsjNmM3MDg2feKUgiVmICVGeyM5NGUyZDV9R1BVICVmICR7Z3B1X2luZm99Igog
IHByaW50IC1yUCAtLSAiJUZ7IzZjNzA4Nn3ilbDilIAlZiAlRnsjN2Y4NDljfUN0cmwrUiBoaXN0
b3J5ICDigKIgIFRhYiBmdXp6eS1jb21wbGV0ZSAg4oCiICBrdGVybS1oZWxwJWYiCn0KCmZ1bmN0
aW9uIGtodWQoKSB7CiAgY2FzZSAiJHsxOi1zdGF0dXN9IiBpbgogICAgb258b2ZmKQogICAgICBt
a2RpciAtcCAiJEtBUlRISV9TSEVMTF9IT01FL3N0YXRlIgogICAgICBleHBvcnQgS0FSVEhJX0hV
RD0iJDEiCiAgICAgIHByaW50IC1yIC0tICIkMSIgPiAiJEtBUlRISV9TSEVMTF9IT01FL3N0YXRl
L2h1ZCIKICAgICAgcHJpbnQgIlN0YXJ0dXAgSFVEOiAkMSIKICAgICAgOzsKICAgIG5vdykgX2th
cnRoaV9yZW5kZXJfaHVkIDs7CiAgICBzdGF0dXMpIHByaW50ICJTdGFydHVwIEhVRDogJHtLQVJU
SElfSFVEOi1vbn0iIDs7CiAgICAqKSBwcmludCAiVXNhZ2U6IGtodWQgb258b2ZmfG5vd3xzdGF0
dXMiID4mMjsgcmV0dXJuIDIgOzsKICBlc2FjCn0KCiMgUmljaCBmdXp6eS1maW5kZXIgYXBwZWFy
YW5jZS4gQ3RybCsvIHRvZ2dsZXMgcHJldmlld3MuCmV4cG9ydCBGWkZfREVGQVVMVF9PUFRTPSIk
e0ZaRl9ERUZBVUxUX09QVFM6LX0gXAotLWhlaWdodD03MiUgLS1sYXlvdXQ9cmV2ZXJzZSAtLWJv
cmRlcj1yb3VuZGVkIC0taW5mbz1pbmxpbmUgXAotLXByb21wdD0nICDvgIIgICcgLS1wb2ludGVy
PSfilrYnIC0tbWFya2VyPSfinJMnIFwKLS1wcmV2aWV3LXdpbmRvdz0ncmlnaHQsNjAlLGJvcmRl
ci1sZWZ0JyBcCi0tYmluZD0nY3RybC0vOnRvZ2dsZS1wcmV2aWV3JyBcCi0tY29sb3I9J2ZnOiNj
ZGQ2ZjQsYmc6IzFlMWUyZSxobDojZjM4YmE4LGZnKzojY2RkNmY0LGJnKzojMzEzMjQ0LGhsKzoj
ZjM4YmE4LGluZm86I2NiYTZmNyxwcm9tcHQ6Izg5YjRmYSxwb2ludGVyOiNmNWUwZGMsbWFya2Vy
OiNhNmUzYTEsc3Bpbm5lcjojZjllMmFmLGhlYWRlcjojOTRlMmQ1LGJvcmRlcjojNmM3MDg2LGxh
YmVsOiNjZGQ2ZjQscXVlcnk6I2NkZDZmNCciCmV4cG9ydCBGWkZfQ1RSTF9UX09QVFM9Ii0tcHJl
dmlldyAna3ByZXZpZXcge30nIC0tcHJldmlldy13aW5kb3c9J3JpZ2h0LDY1JSciCmV4cG9ydCBG
WkZfQUxUX0NfT1BUUz0iLS1wcmV2aWV3ICdjb21tYW5kIGV6YSAtLXRyZWUgLS1sZXZlbD0yIC0t
aWNvbnM9YWx3YXlzIC0tY29sb3I9YWx3YXlzIHt9IDI+L2Rldi9udWxsIHx8IGNvbW1hbmQgZXhh
IC0tdHJlZSAtLWxldmVsPTIgLS1pY29ucyAtLWNvbG9yPWFsd2F5cyB7fSAyPi9kZXYvbnVsbCB8
fCBjb21tYW5kIGxzIC1sYSAtLWNvbG9yPWFsd2F5cyB7fSciCgojIENvbXBsZXRpb24gc3lzdGVt
IGFuZCB2aXN1YWwgdGFiIGNvbXBsZXRpb24uCmZwYXRoPSgiJEtBUlRISV9TSEVMTF9EQVRBL3Bs
dWdpbnMvenNoLWNvbXBsZXRpb25zL3NyYyIgJGZwYXRoKQphdXRvbG9hZCAtVXogY29tcGluaXQK
Y29tcGluaXQgLUMgLWQgIiRLQVJUSElfU0hFTExfQ0FDSEUvemNvbXBkdW1wLSR7WlNIX1ZFUlNJ
T059IiAyPi9kZXYvbnVsbAp6c3R5bGUgJzpjb21wbGV0aW9uOionIG1lbnUgc2VsZWN0CnpzdHls
ZSAnOmNvbXBsZXRpb246KicgbWF0Y2hlci1saXN0ICdtOnthLXp9PXtBLVphLXp9JyAncjp8Wy5f
LV09KiByOnw9KicKenN0eWxlICc6Y29tcGxldGlvbjoqOmRlc2NyaXB0aW9ucycgZm9ybWF0ICcl
RntibHVlfS0tICVkIC0tJWYnCnpzdHlsZSAnOmNvbXBsZXRpb246Kjp3YXJuaW5ncycgZm9ybWF0
ICclRntyZWR9bm8gbWF0Y2hlcyVmJwp6c3R5bGUgJzpjb21wbGV0aW9uOionIGdyb3VwLW5hbWUg
JycKCmlmIFtbIC1yICIkS0FSVEhJX1NIRUxMX0RBVEEvcGx1Z2lucy9memYtdGFiL2Z6Zi10YWIu
cGx1Z2luLnpzaCIgXV07IHRoZW4KICBzb3VyY2UgIiRLQVJUSElfU0hFTExfREFUQS9wbHVnaW5z
L2Z6Zi10YWIvZnpmLXRhYi5wbHVnaW4uenNoIgogIHpzdHlsZSAnOmZ6Zi10YWI6KicgZnpmLWZs
YWdzIC0taGVpZ2h0PTY1JSAtLWxheW91dD1yZXZlcnNlIC0tYm9yZGVyPXJvdW5kZWQKICB6c3R5
bGUgJzpmemYtdGFiOmNvbXBsZXRlOmNkOionIGZ6Zi1wcmV2aWV3ICdjb21tYW5kIGV6YSAtLXRy
ZWUgLS1sZXZlbD0yIC0taWNvbnM9YWx3YXlzIC0tY29sb3I9YWx3YXlzIC0tICIkcmVhbHBhdGgi
IDI+L2Rldi9udWxsIHx8IGNvbW1hbmQgZXhhIC0tdHJlZSAtLWxldmVsPTIgLS1pY29ucyAtLWNv
bG9yPWFsd2F5cyAtLSAiJHJlYWxwYXRoIiAyPi9kZXYvbnVsbCB8fCBjb21tYW5kIGxzIC1sYSAt
LWNvbG9yPWFsd2F5cyAtLSAiJHJlYWxwYXRoIicKICB6c3R5bGUgJzpmemYtdGFiOmNvbXBsZXRl
Oio6KicgZnpmLXByZXZpZXcgJ2twcmV2aWV3ICIkcmVhbHBhdGgiJwpmaQoKIyBOYXRpdmUgZnpm
IGludGVncmF0aW9uLiBOZXcgZnpmIHZlcnNpb25zIGV4cG9zZSBgZnpmIC0tenNoYDsgb2xkZXIK
IyBVYnVudHUvRGViaWFuIHBhY2thZ2VzIHNoaXAgaW50ZWdyYXRpb24gc2NyaXB0cyBpbnN0ZWFk
LgppZiBjb21tYW5kIC12IGZ6ZiA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICBpZiBmemYgLS16c2gg
Pi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgICBzb3VyY2UgPChmemYgLS16c2gpCiAgZWxzZQogICAg
Zm9yIF9rZnpmX2ZpbGUgaW4gICAgICAgL3Vzci9zaGFyZS9kb2MvZnpmL2V4YW1wbGVzL2tleS1i
aW5kaW5ncy56c2ggICAgICAgL3Vzci9zaGFyZS9memYva2V5LWJpbmRpbmdzLnpzaCAgICAgICAi
JEhPTUUvLmZ6Zi9zaGVsbC9rZXktYmluZGluZ3MuenNoIjsgZG8KICAgICAgW1sgLXIgIiRfa2Z6
Zl9maWxlIiBdXSAmJiBzb3VyY2UgIiRfa2Z6Zl9maWxlIiAmJiBicmVhawogICAgZG9uZQogICAg
Zm9yIF9rZnpmX2ZpbGUgaW4gICAgICAgL3Vzci9zaGFyZS9kb2MvZnpmL2V4YW1wbGVzL2NvbXBs
ZXRpb24uenNoICAgICAgIC91c3Ivc2hhcmUvZnpmL2NvbXBsZXRpb24uenNoICAgICAgICIkSE9N
RS8uZnpmL3NoZWxsL2NvbXBsZXRpb24uenNoIjsgZG8KICAgICAgW1sgLXIgIiRfa2Z6Zl9maWxl
IiBdXSAmJiBzb3VyY2UgIiRfa2Z6Zl9maWxlIiAmJiBicmVhawogICAgZG9uZQogICAgdW5zZXQg
X2tmemZfZmlsZQogIGZpCgogICMgR3VhcmFudGVlZCB2aXN1YWwgaGlzdG9yeSBmYWxsYmFjay4g
QXR1aW4gcmVwbGFjZXMgdGhpcyBiaW5kaW5nIG9ubHkgd2hlbgogICMgaXRzIGV4ZWN1dGFibGUg
YW5kIFpMRSB3aWRnZXQgYXJlIGJvdGggaGVhbHRoeS4KICBmdW5jdGlvbiBfa3Rlcm1fZnpmX2hp
c3Rvcnlfd2lkZ2V0KCkgewogICAgbG9jYWwgc2VsZWN0ZWQKICAgIHNlbGVjdGVkPSIkKGZjIC1y
bCAxIHwgc2VkIC1FICdzL15bWzpzcGFjZTpdXSpbMC05XStbWzpzcGFjZTpdXSsvLycgfCBhd2sg
JyFzZWVuWyQwXSsrJyB8IGZ6ZiAtLW5vLXNvcnQgLS10YWMgLS1xdWVyeT0iJExCVUZGRVIiKSIg
fHwgcmV0dXJuCiAgICBCVUZGRVI9IiRzZWxlY3RlZCIKICAgIENVUlNPUj0keyNCVUZGRVJ9CiAg
ICB6bGUgcmVkaXNwbGF5CiAgfQogIHpsZSAtTiBfa3Rlcm1fZnpmX2hpc3Rvcnlfd2lkZ2V0CiAg
YmluZGtleSAnXlInIF9rdGVybV9memZfaGlzdG9yeV93aWRnZXQKZmkKCiMgU21hcnQgZGlyZWN0
b3J5IGp1bXBpbmc6IHogPHBhcnRpYWwtbmFtZT4sIHppIGZvciBhbiBpbnRlcmFjdGl2ZSBwaWNr
ZXIuCmlmIGNvbW1hbmQgLXYgem94aWRlID4vZGV2L251bGwgMj4mMTsgdGhlbgogIGV2YWwgIiQo
em94aWRlIGluaXQgenNoKSIKZmkKCiMgSGlzdG9yeSBVSSBvbiBDdHJsK1Igb25seS4gZnpmIGFs
cmVhZHkgb3ducyBDdHJsK1IgYXMgdGhlIHJlbGlhYmxlCiMgZmFsbGJhY2suIEF0dWluIHJlcGxh
Y2VzIGl0IG9ubHkgYWZ0ZXIgaXRzIGJpbmFyeSBydW5zLCBpbml0aWFsaXphdGlvbgojIHN1Y2Nl
ZWRzLCBhbmQgdGhlIGF0dWluLXNlYXJjaCBaTEUgd2lkZ2V0IGlzIGNvbmZpcm1lZCB0byBleGlz
dC4KYmluZGtleSAnXltyJyBoaXN0b3J5LWluY3JlbWVudGFsLXNlYXJjaC1iYWNrd2FyZAppZiBj
b21tYW5kIC12IGF0dWluID4vZGV2L251bGwgMj4mMSAmJiBhdHVpbiAtLXZlcnNpb24gPi9kZXYv
bnVsbCAyPiYxOyB0aGVuCiAgZXhwb3J0IEFUVUlOX05PQklORD10cnVlCiAgdHlwZXNldCBfa2Fy
dGhpX2F0dWluX2luaXQ9JycKICBpZiBfa2FydGhpX2F0dWluX2luaXQ9IiQoYXR1aW4gaW5pdCB6
c2ggMj4vZGV2L251bGwpIiBcCiAgICAgJiYgW1sgLW4gIiRfa2FydGhpX2F0dWluX2luaXQiIF1d
OyB0aGVuCiAgICBldmFsICIkX2thcnRoaV9hdHVpbl9pbml0IgogICAgIyB6bGVwYXJhbWV0ZXIg
cmVwb3J0cyBhIG51bGwgdmFsdWUgZm9yIGEgd2lkZ2V0IHRoYXQgZXhpc3RzIG9ubHkgYXMgYW4K
ICAgICMgaW5jb21wbGV0ZSBiaW5kaW5nLiBCaW5kIEN0cmwrUiBvbmx5IHRvIGEgZnVsbHkgZGVm
aW5lZCB3aWRnZXQuCiAgICBpZiB6bW9kbG9hZCB6c2gvemxlcGFyYW1ldGVyIDI+L2Rldi9udWxs
IFwKICAgICAgICYmIFtbIC1uICIke3dpZGdldHNbYXR1aW4tc2VhcmNoXS19IiBdXTsgdGhlbgog
ICAgICBiaW5ka2V5ICdeUicgYXR1aW4tc2VhcmNoCiAgICBmaQogIGZpCiAgdW5zZXQgX2thcnRo
aV9hdHVpbl9pbml0CmZpCgojIFN1Z2dlc3Rpb25zIGFyZSBkZWxpYmVyYXRlbHkgbG9hZGVkIGFm
dGVyIGV4aXN0aW5nIGNvbmZpZyBzbyB0aGV5IGF1Z21lbnQgaXQuCmlmIFtbIC1yICIkS0FSVEhJ
X1NIRUxMX0RBVEEvcGx1Z2lucy96c2gtYXV0b3N1Z2dlc3Rpb25zL3pzaC1hdXRvc3VnZ2VzdGlv
bnMuenNoIiBdXSBcCiAgICYmICgoICEgJHsrZnVuY3Rpb25zW196c2hfYXV0b3N1Z2dlc3Rfc3Rh
cnRdfSApKTsgdGhlbgogIFpTSF9BVVRPU1VHR0VTVF9ISUdITElHSFRfU1RZTEU9J2ZnPSM2Yzcw
ODYnCiAgWlNIX0FVVE9TVUdHRVNUX1NUUkFURUdZPShoaXN0b3J5KQogIHNvdXJjZSAiJEtBUlRI
SV9TSEVMTF9EQVRBL3BsdWdpbnMvenNoLWF1dG9zdWdnZXN0aW9ucy96c2gtYXV0b3N1Z2dlc3Rp
b25zLnpzaCIKZmkKCiMgRG8gbm90IHJlcGxhY2Ugc3RhbmRhcmQgY29tbWFuZHMgZ2xvYmFsbHku
IFZpc3VhbCBhbHRlcm5hdGl2ZXMgdXNlIGV4cGxpY2l0IG5hbWVzLgpmdW5jdGlvbiBrdmxzKCkg
ewogIGlmIGNvbW1hbmQgLXYgZXphID4vZGV2L251bGwgMj4mMTsgdGhlbgogICAgY29tbWFuZCBl
emEgLS1pY29ucz1hbHdheXMgLS1ncm91cC1kaXJlY3Rvcmllcy1maXJzdCAtLWNvbG9yPWFsd2F5
cyAiJEAiCiAgZWxpZiBjb21tYW5kIC12IGV4YSA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICAgIGNv
bW1hbmQgZXhhIC0taWNvbnMgLS1ncm91cC1kaXJlY3Rvcmllcy1maXJzdCAtLWNvbG9yPWFsd2F5
cyAiJEAiCiAgZWxzZQogICAgY29tbWFuZCBscyAtLWNvbG9yPWFsd2F5cyAiJEAiCiAgZmkKfQoK
ZnVuY3Rpb24ga3ZsbCgpIHsKICBpZiBjb21tYW5kIC12IGV6YSA+L2Rldi9udWxsIDI+JjE7IHRo
ZW4KICAgIGNvbW1hbmQgZXphIC1sYWggLS1pY29ucz1hbHdheXMgLS1naXQgLS1ncm91cC1kaXJl
Y3Rvcmllcy1maXJzdCAtLXRpbWUtc3R5bGU9bG9uZy1pc28gIiRAIgogIGVsaWYgY29tbWFuZCAt
diBleGEgPi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgICBjb21tYW5kIGV4YSAtbGFoIC0taWNvbnMg
LS1naXQgLS1ncm91cC1kaXJlY3Rvcmllcy1maXJzdCAiJEAiCiAgZWxzZQogICAgY29tbWFuZCBs
cyAtbGFoIC0tY29sb3I9YWx3YXlzICIkQCIKICBmaQp9CgpmdW5jdGlvbiBrdnRyZWUoKSB7CiAg
bG9jYWwgZGVwdGg9IiR7MTotM30iCiAgaWYgW1sgIiRkZXB0aCIgPT0gPC0+IF1dOyB0aGVuIHNo
aWZ0OyBlbHNlIGRlcHRoPTM7IGZpCiAgaWYgY29tbWFuZCAtdiBlemEgPi9kZXYvbnVsbCAyPiYx
OyB0aGVuCiAgICBjb21tYW5kIGV6YSAtLXRyZWUgLS1sZXZlbD0iJGRlcHRoIiAtLWljb25zPWFs
d2F5cyAtLWdpdC1pZ25vcmUgLS1ncm91cC1kaXJlY3Rvcmllcy1maXJzdCAiJEAiCiAgZWxpZiBj
b21tYW5kIC12IGV4YSA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICAgIGNvbW1hbmQgZXhhIC0tdHJl
ZSAtLWxldmVsPSIkZGVwdGgiIC0taWNvbnMgLS1naXQtaWdub3JlIC0tZ3JvdXAtZGlyZWN0b3Jp
ZXMtZmlyc3QgIiRAIgogIGVsaWYgY29tbWFuZCAtdiB0cmVlID4vZGV2L251bGwgMj4mMTsgdGhl
bgogICAgY29tbWFuZCB0cmVlIC1MICIkZGVwdGgiICIkQCIKICBlbHNlCiAgICBsb2NhbCAtYSBy
b290cwogICAgcm9vdHM9KCIkQCIpCiAgICAoKCAkeyNyb290c1tAXX0gKSkgfHwgcm9vdHM9KC4p
CiAgICBjb21tYW5kIGZpbmQgIiR7cm9vdHNbQF19IiAtbWF4ZGVwdGggIiRkZXB0aCIgLXByaW50
CiAgZmkKfQoKZnVuY3Rpb24ga3ZjYXQoKSB7CiAgaWYgY29tbWFuZCAtdiBiYXQgPi9kZXYvbnVs
bCAyPiYxOyB0aGVuCiAgICBjb21tYW5kIGJhdCAtLXN0eWxlPW51bWJlcnMsY2hhbmdlcyxoZWFk
ZXIgLS1wYWdpbmc9YXV0byAiJEAiCiAgZWxzZQogICAgY29tbWFuZCBjYXQgIiRAIgogIGZpCn0K
CmZ1bmN0aW9uIGt2Z3JlcCgpIHsKICBpZiBjb21tYW5kIC12IHJnID4vZGV2L251bGwgMj4mMTsg
dGhlbgogICAgY29tbWFuZCByZyAtLWhpZGRlbiAtLWdsb2IgJyEuZ2l0JyAtLXNtYXJ0LWNhc2Ug
LS1saW5lLW51bWJlciAtLWNvbHVtbiAtLWNvbG9yPWFsd2F5cyAiJEAiCiAgZWxzZQogICAgY29t
bWFuZCBncmVwIC1SSW4gLS1jb2xvcj1hbHdheXMgIiRAIgogIGZpCn0KCmZ1bmN0aW9uIGt2ZGlm
ZigpIHsKICBpZiBjb21tYW5kIC12IGRlbHRhID4vZGV2L251bGwgMj4mMTsgdGhlbgogICAgY29t
bWFuZCBnaXQgLWMgY29sb3IudWk9YWx3YXlzIGRpZmYgIiRAIiB8IGNvbW1hbmQgZGVsdGEKICBl
bHNlCiAgICBjb21tYW5kIGdpdCBkaWZmIC0tY29sb3I9YWx3YXlzICIkQCIgfCBsZXNzIC1SCiAg
ZmkKfQoKZnVuY3Rpb24ga3ZnaXQoKSB7CiAgaWYgY29tbWFuZCAtdiBsYXp5Z2l0ID4vZGV2L251
bGwgMj4mMTsgdGhlbgogICAgY29tbWFuZCBsYXp5Z2l0ICIkQCIKICBlbHNlCiAgICBjb21tYW5k
IGdpdCBzdGF0dXMgLS1zaG9ydCAtLWJyYW5jaAogIGZpCn0KCmZ1bmN0aW9uIGt5YXppKCkgewog
IGlmICEgY29tbWFuZCAtdiB5YXppID4vZGV2L251bGwgMj4mMTsgdGhlbgogICAgcHJpbnQgIllh
emkgaXMgbm90IGluc3RhbGxlZC4iID4mMgogICAgcmV0dXJuIDEyNwogIGZpCiAgbG9jYWwgdG1w
IGN3ZAogIHRtcD0iJChta3RlbXAgLXQgeWF6aS1jd2QuWFhYWFhYKSIgfHwgcmV0dXJuCiAgY29t
bWFuZCB5YXppICIkQCIgLS1jd2QtZmlsZT0iJHRtcCIKICBJRlM9IHJlYWQgLXIgY3dkIDwgIiR0
bXAiCiAgW1sgLW4gIiRjd2QiICYmICIkY3dkIiAhPSAiJFBXRCIgJiYgLWQgIiRjd2QiIF1dICYm
IGJ1aWx0aW4gY2QgLS0gIiRjd2QiCiAgY29tbWFuZCBybSAtZiAtLSAiJHRtcCIKfQoKZnVuY3Rp
b24gX2t0ZXJtX3JlcXVpcmVfZnpmKCkgewogIGNvbW1hbmQgLXYgZnpmID4vZGV2L251bGwgMj4m
MSB8fCB7IHByaW50ICJmemYgaXMgbm90IGluc3RhbGxlZC4gUnVuIGt0ZXJtLXJlcGFpciB3aGVu
IG9ubGluZS4iID4mMjsgcmV0dXJuIDEyNzsgfQp9CgpmdW5jdGlvbiBrZmYoKSB7CiAgX2t0ZXJt
X3JlcXVpcmVfZnpmIHx8IHJldHVybgogIGxvY2FsIHNlbGVjdGVkCiAgaWYgY29tbWFuZCAtdiBm
ZCA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICAgIHNlbGVjdGVkPSIkKGNvbW1hbmQgZmQgLS10eXBl
IGYgLS1oaWRkZW4gLS1mb2xsb3cgLS1leGNsdWRlIC5naXQgLiAyPi9kZXYvbnVsbCB8IGZ6ZiAt
LXByZXZpZXcgJ2twcmV2aWV3IHt9JykiIHx8IHJldHVybgogIGVsc2UKICAgIHNlbGVjdGVkPSIk
KGNvbW1hbmQgZmluZCAuIC10eXBlIGYgLW5vdCAtcGF0aCAnKi8uZ2l0LyonIDI+L2Rldi9udWxs
IHwgZnpmIC0tcHJldmlldyAna3ByZXZpZXcge30nKSIgfHwgcmV0dXJuCiAgZmkKICBsb2NhbCBl
ZGl0b3JfY29tbWFuZD0iJHtWSVNVQUw6LSR7RURJVE9SOi1uYW5vfX0iCiAgJHs9ZWRpdG9yX2Nv
bW1hbmR9IC0tICIkc2VsZWN0ZWQiCn0KCmZ1bmN0aW9uIGtmY2QoKSB7CiAgX2t0ZXJtX3JlcXVp
cmVfZnpmIHx8IHJldHVybgogIGxvY2FsIHNlbGVjdGVkCiAgaWYgY29tbWFuZCAtdiBmZCA+L2Rl
di9udWxsIDI+JjE7IHRoZW4KICAgIHNlbGVjdGVkPSIkKGNvbW1hbmQgZmQgLS10eXBlIGQgLS1o
aWRkZW4gLS1mb2xsb3cgLS1leGNsdWRlIC5naXQgLiAyPi9kZXYvbnVsbCB8IGZ6ZiAtLXByZXZp
ZXcgJ2NvbW1hbmQgZXphIC0tdHJlZSAtLWxldmVsPTIgLS1pY29ucz1hbHdheXMgLS1jb2xvcj1h
bHdheXMge30gMj4vZGV2L251bGwgfHwgY29tbWFuZCBleGEgLS10cmVlIC0tbGV2ZWw9MiAtLWlj
b25zIC0tY29sb3I9YWx3YXlzIHt9IDI+L2Rldi9udWxsIHx8IGNvbW1hbmQgbHMgLWxhIC0tY29s
b3I9YWx3YXlzIHt9JykiIHx8IHJldHVybgogIGVsc2UKICAgIHNlbGVjdGVkPSIkKGNvbW1hbmQg
ZmluZCAuIC10eXBlIGQgLW5vdCAtcGF0aCAnKi8uZ2l0LyonIDI+L2Rldi9udWxsIHwgZnpmKSIg
fHwgcmV0dXJuCiAgZmkKICBidWlsdGluIGNkIC0tICIkc2VsZWN0ZWQiCn0KCmZ1bmN0aW9uIGtm
a2lsbCgpIHsKICBfa3Rlcm1fcmVxdWlyZV9memYgfHwgcmV0dXJuCiAgbG9jYWwgcGlkCiAgcGlk
PSIkKGNvbW1hbmQgcHMgLWVvIHBpZCx1c2VyLCVjcHUsJW1lbSxldGltZSxjb21tIC0tc29ydD0t
JWNwdSB8IHNlZCAxZCB8IGZ6ZiAtLWhlYWRlcj0nU2VsZWN0IGEgcHJvY2VzczsgRW50ZXIgc2Vu
ZHMgU0lHVEVSTScgfCBhd2sgJ3twcmludCAkMX0nKSIgfHwgcmV0dXJuCiAgW1sgLW4gIiRwaWQi
IF1dICYmIGNvbW1hbmQga2lsbCAtVEVSTSAiJHBpZCIKfQoKZnVuY3Rpb24ga2ZicmFuY2goKSB7
CiAgX2t0ZXJtX3JlcXVpcmVfZnpmIHx8IHJldHVybgogIGNvbW1hbmQgZ2l0IHJldi1wYXJzZSAt
LWdpdC1kaXIgPi9kZXYvbnVsbCAyPiYxIHx8IHsgcHJpbnQgIk5vdCBpbnNpZGUgYSBHaXQgcmVw
b3NpdG9yeS4iID4mMjsgcmV0dXJuIDE7IH0KICBsb2NhbCBicmFuY2gKICBicmFuY2g9IiQoY29t
bWFuZCBnaXQgZm9yLWVhY2gtcmVmIC0tZm9ybWF0PSclKHJlZm5hbWU6c2hvcnQpJyByZWZzL2hl
YWRzLyB8IGZ6ZiAtLXByZXZpZXcgJ2dpdCBsb2cgLS1jb2xvcj1hbHdheXMgLS1vbmVsaW5lIC0t
ZGVjb3JhdGUgLTIwIHt9JykiIHx8IHJldHVybgogIFtbIC1uICIkYnJhbmNoIiBdXSAmJiBjb21t
YW5kIGdpdCBzd2l0Y2ggIiRicmFuY2giCn0KCmZ1bmN0aW9uIGtmdmVudigpIHsKICBfa3Rlcm1f
cmVxdWlyZV9memYgfHwgcmV0dXJuCiAgbG9jYWwgYWN0aXZhdGUKICBhY3RpdmF0ZT0iJChjb21t
YW5kIGZpbmQgLiAtbWF4ZGVwdGggNSAtdHlwZSBmIC1wYXRoICcqL2Jpbi9hY3RpdmF0ZScgLW5v
dCAtcGF0aCAnKi9ub2RlX21vZHVsZXMvKicgMj4vZGV2L251bGwgfCBmemYgLS1wcmV2aWV3ICdk
aXJuYW1lIHt9JykiIHx8IHJldHVybgogIFtbIC1uICIkYWN0aXZhdGUiIF1dICYmIHNvdXJjZSAi
JGFjdGl2YXRlIgp9CgpmdW5jdGlvbiBrZmNvbmRhKCkgewogIF9rdGVybV9yZXF1aXJlX2Z6ZiB8
fCByZXR1cm4KICAoKCAkeytjb21tYW5kc1tjb25kYV19IHx8ICR7K2Z1bmN0aW9uc1tjb25kYV19
ICkpIHx8IHsgcHJpbnQgIkNvbmRhIGlzIG5vdCBhdmFpbGFibGUuIiA+JjI7IHJldHVybiAxMjc7
IH0KICBsb2NhbCBlbnZfcGF0aAogIGVudl9wYXRoPSIkKGNvbmRhIGVudiBsaXN0IC0tanNvbiAy
Pi9kZXYvbnVsbCB8IGpxIC1yICcuZW52c1tdJyB8IGZ6ZikiIHx8IHJldHVybgogIGNvbmRhIGFj
dGl2YXRlICIkZW52X3BhdGgiCn0KCmZ1bmN0aW9uIGtmZG9ja2VyKCkgewogIF9rdGVybV9yZXF1
aXJlX2Z6ZiB8fCByZXR1cm4KICBjb21tYW5kIC12IGRvY2tlciA+L2Rldi9udWxsIDI+JjEgfHwg
eyBwcmludCAiRG9ja2VyIGlzIG5vdCBpbnN0YWxsZWQuIiA+JjI7IHJldHVybiAxMjc7IH0KICBs
b2NhbCBjb250YWluZXIKICBjb250YWluZXI9IiQoY29tbWFuZCBkb2NrZXIgcHMgLS1mb3JtYXQg
J3t7Lk5hbWVzfX1cdHt7LkltYWdlfX1cdHt7LlN0YXR1c319JyB8IGZ6ZiAtLWhlYWRlcj0nY29u
dGFpbmVyICBpbWFnZSAgc3RhdHVzJyB8IGN1dCAtZjEpIiB8fCByZXR1cm4KICBbWyAtbiAiJGNv
bnRhaW5lciIgXV0gfHwgcmV0dXJuCiAgY29tbWFuZCBkb2NrZXIgZXhlYyAtaXQgIiRjb250YWlu
ZXIiIHNoIC1sYyAnaWYgY29tbWFuZCAtdiB6c2ggPi9kZXYvbnVsbCAyPiYxOyB0aGVuIGV4ZWMg
enNoOyBlbGlmIGNvbW1hbmQgLXYgYmFzaCA+L2Rldi9udWxsIDI+JjE7IHRoZW4gZXhlYyBiYXNo
OyBlbHNlIGV4ZWMgc2g7IGZpJwp9CgpmdW5jdGlvbiBrbWtjZCgpIHsKICBbWyAtbiAiJHsxOi19
IiBdXSB8fCB7IHByaW50ICJVc2FnZToga21rY2QgRElSRUNUT1JZIiA+JjI7IHJldHVybiAyOyB9
CiAgY29tbWFuZCBta2RpciAtcCAtLSAiJDEiICYmIGJ1aWx0aW4gY2QgLS0gIiQxIgp9CgpmdW5j
dGlvbiBrc2VydmUoKSB7CiAgbG9jYWwgcG9ydD0iJHsxOi04MDAwfSIgYmluZF9hZGRyZXNzPSIk
ezI6LTEyNy4wLjAuMX0iCiAgY29tbWFuZCBweXRob24zIC1tIGh0dHAuc2VydmVyICIkcG9ydCIg
LS1iaW5kICIkYmluZF9hZGRyZXNzIgp9CgpmdW5jdGlvbiBrc3lzaW5mbygpIHsKICBpZiBjb21t
YW5kIC12IGZhc3RmZXRjaCA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICAgIGNvbW1hbmQgZmFzdGZl
dGNoCiAgZWxpZiBjb21tYW5kIC12IG5lb2ZldGNoID4vZGV2L251bGwgMj4mMTsgdGhlbgogICAg
Y29tbWFuZCBuZW9mZXRjaAogIGVsc2UKICAgIHByaW50IC1QICIlRntibHVlfVN5c3RlbSVmICAk
KHVuYW1lIC1zcm1vKSIKICAgIGlmIFtbIC1yIC9wcm9jL2RldmljZS10cmVlL21vZGVsIF1dOyB0
aGVuCiAgICAgIHByaW50ICJNb2RlbCAgICQodHIgLWQgJ1wwJyA8L3Byb2MvZGV2aWNlLXRyZWUv
bW9kZWwpIgogICAgZmkKICAgIGNvbW1hbmQgbHNjcHUgfCBzZWQgLW4gJ3MvXk1vZGVsIG5hbWU6
W1s6c3BhY2U6XV0qL0NQVSAgICAgL3AnIHwgaGVhZCAtbjEKICAgIGNvbW1hbmQgZnJlZSAtaCB8
IGF3ayAnTlI9PTIge3ByaW50ICJNZW1vcnkgICIkMyIgLyAiJDJ9JwogICAgY29tbWFuZCBkZiAt
aCAvIHwgYXdrICdOUj09MiB7cHJpbnQgIlJvb3QgICAgIiQzIiAvICIkMiIgKCIkNSIpIn0nCiAg
ZmkKfQoKZnVuY3Rpb24ga3N5c21vbigpIHsKICBpZiBjb21tYW5kIC12IGJ0b3AgPi9kZXYvbnVs
bCAyPiYxOyB0aGVuIGNvbW1hbmQgYnRvcAogIGVsaWYgY29tbWFuZCAtdiBodG9wID4vZGV2L251
bGwgMj4mMTsgdGhlbiBjb21tYW5kIGh0b3AKICBlbHNlIGNvbW1hbmQgdG9wCiAgZmkKfQoKZnVu
Y3Rpb24ga2dwdXRvcCgpIHsKICBpZiBjb21tYW5kIC12IG52dG9wID4vZGV2L251bGwgMj4mMTsg
dGhlbgogICAgY29tbWFuZCBudnRvcAogIGVsaWYgY29tbWFuZCAtdiBudmlkaWEtc21pID4vZGV2
L251bGwgMj4mMTsgdGhlbgogICAgY29tbWFuZCB3YXRjaCAtbiAxIG52aWRpYS1zbWkKICBlbGlm
IGNvbW1hbmQgLXYgcm9jbS1zbWkgPi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgICBjb21tYW5kIHdh
dGNoIC1uIDIgcm9jbS1zbWkKICBlbGlmIGNvbW1hbmQgLXYgdmNnZW5jbWQgPi9kZXYvbnVsbCAy
PiYxOyB0aGVuCiAgICBjb21tYW5kIHdhdGNoIC1uIDIgJ3ZjZ2VuY21kIG1lYXN1cmVfdGVtcDsg
dmNnZW5jbWQgZ2V0X3Rocm90dGxlZDsgdmNnZW5jbWQgbWVhc3VyZV9jbG9jayBhcm07IHZjZ2Vu
Y21kIG1lYXN1cmVfdm9sdHMgY29yZScKICBlbGlmIFtbIC1yIC9zeXMvY2xhc3MvdGhlcm1hbC90
aGVybWFsX3pvbmUwL3RlbXAgXV07IHRoZW4KICAgIGNvbW1hbmQgd2F0Y2ggLW4gMiAnYXdrICJ7
cHJpbnRmIFwiU29DIHRlbXBlcmF0dXJlOiAlLjFmIENcXG5cIiwgXCQxLzEwMDB9IiAvc3lzL2Ns
YXNzL3RoZXJtYWwvdGhlcm1hbF96b25lMC90ZW1wJwogIGVsc2UKICAgIHByaW50ICJObyBzdXBw
b3J0ZWQgR1BVIG9yIFNvQyBtb25pdG9yIHdhcyBmb3VuZC4iID4mMgogICAgcmV0dXJuIDEyNwog
IGZpCn0KCmZ1bmN0aW9uIGtwaXRlbXAoKSB7CiAgaWYgY29tbWFuZCAtdiB2Y2dlbmNtZCA+L2Rl
di9udWxsIDI+JjE7IHRoZW4KICAgIGNvbW1hbmQgdmNnZW5jbWQgbWVhc3VyZV90ZW1wCiAgZWxp
ZiBbWyAtciAvc3lzL2NsYXNzL3RoZXJtYWwvdGhlcm1hbF96b25lMC90ZW1wIF1dOyB0aGVuCiAg
ICBhd2sgJ3twcmludGYgIlNvQyB0ZW1wZXJhdHVyZTogJS4xZiBDXG4iLCAkMS8xMDAwfScgL3N5
cy9jbGFzcy90aGVybWFsL3RoZXJtYWxfem9uZTAvdGVtcAogIGVsc2UKICAgIHByaW50ICJObyBT
b0MgdGVtcGVyYXR1cmUgaW50ZXJmYWNlIHdhcyBmb3VuZC4iID4mMgogICAgcmV0dXJuIDEKICBm
aQp9CgpmdW5jdGlvbiBrcGlzdGF0dXMoKSB7CiAgcHJpbnQgLVAgIiVCJUZ7Y3lhbn1SYXNwYmVy
cnkgUGkgLyBTQkMgc3RhdHVzJWYlYiIKICBbWyAtciAvcHJvYy9kZXZpY2UtdHJlZS9tb2RlbCBd
XSAmJiBwcmludCAiTW9kZWwgICAgICA6ICQodHIgLWQgJ1wwJyA8L3Byb2MvZGV2aWNlLXRyZWUv
bW9kZWwpIgogIHByaW50IC1uICJUZW1wZXJhdHVyZTogIjsga3BpdGVtcCAyPi9kZXYvbnVsbCB8
fCBwcmludCAidW5hdmFpbGFibGUiCiAgaWYgY29tbWFuZCAtdiB2Y2dlbmNtZCA+L2Rldi9udWxs
IDI+JjE7IHRoZW4KICAgIHByaW50ICJUaHJvdHRsZSAgIDogJCh2Y2dlbmNtZCBnZXRfdGhyb3R0
bGVkIDI+L2Rldi9udWxsKSIKICAgIHByaW50ICJBUk0gY2xvY2sgIDogJCh2Y2dlbmNtZCBtZWFz
dXJlX2Nsb2NrIGFybSAyPi9kZXYvbnVsbCkiCiAgICBwcmludCAiQ29yZSB2b2x0cyA6ICQodmNn
ZW5jbWQgbWVhc3VyZV92b2x0cyBjb3JlIDI+L2Rldi9udWxsKSIKICBmaQogIGNvbW1hbmQgZnJl
ZSAtaCB8IGF3ayAnTlI9PTIge3ByaW50ICJNZW1vcnkgICAgIDogIiQzIiAvICIkMn0nCiAgY29t
bWFuZCBkZiAtaCAvIHwgYXdrICdOUj09MiB7cHJpbnQgIlJvb3QgZGlzayAgOiAiJDMiIC8gIiQy
IiAoIiQ1IikifScKICBjb21tYW5kIHVwdGltZQp9CgpmdW5jdGlvbiBrbmV0bW9uKCkgewogIGlm
IGNvbW1hbmQgLXYgbmxvYWQgPi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgICBjb21tYW5kIG5sb2Fk
CiAgZWxzZQogICAgY29tbWFuZCB3YXRjaCAtbiAyICdpcCAtcyBsaW5rJwogIGZpCn0KCmZ1bmN0
aW9uIGtkYXNoYm9hcmQoKSB7CiAgY29tbWFuZCBrYXJ0aGktZGFzaGJvYXJkICIkQCIKfQoKZnVu
Y3Rpb24ga3Rlcm0taGVscCgpIHsKICBjYXQgPDwnSEVMUCcKS1RFUk0gcHJvZmlsZSBhbmQgcmVj
b3ZlcnkKICBrdGVybS1tb2Rlcm4gLyBrdGVybS1jbGFzc2ljICAgICAgIHN3aXRjaCB0aGUgY3Vy
cmVudCBzaGVsbCBpbW1lZGlhdGVseQogIGt0ZXJtLXN5c3RlbSBtb2Rlcm58Y2xhc3NpYyAgICAg
ICAgY2hvb3NlIHRoZSBwcm9maWxlIGZvciBmdXR1cmUgZGVza3RvcCB0ZXJtaW5hbHMKICBrdGVy
bS1kZWZhdWx0IG1vZGVybnxjbGFzc2ljICAgICAgIGFsaWFzIG9mIGt0ZXJtLXN5c3RlbQogIGt0
ZXJtLXNhZmUgICAgICAgICAgICAgICAgICAgICAgICAgb3BlbiBjbGVhbiBac2ggd2l0aG91dCBz
dGFydHVwIGZpbGVzCiAga3Rlcm0tcmVsb2FkICAgICAgICAgICAgICAgICAgICAgICByZWxvYWQg
dGhlIHNlbGVjdGVkIHByb2ZpbGUKICBrcHJvbXB0IHJpY2h8Y29tcGFjdCAgICAgICAgICAgICAg
IHN3aXRjaCBwcm9tcHQgZGVuc2l0eQogIGtibG9ja3Mgb258b2ZmfHN0YXR1cyAgICAgICAgICAg
ICAgY29udHJvbCBXYXJwLWxpa2UgY29tbWFuZCBzZXBhcmF0b3JzCiAga2h1ZCBvbnxvZmZ8bm93
fHN0YXR1cyAgICAgICAgICAgICBjb250cm9sIHRoZSBzdGFydHVwIGluZm9ybWF0aW9uIEhVRAog
IGt0ZXJtLXN0YXR1cyAgICAgICAgICAgICAgICAgICAgICAgZGlzcGxheSBpbnN0YWxsZWQgbW9k
ZSwgdmVyc2lvbnMgYW5kIGZhbGxiYWNrcwogIGt0ZXJtLWRvY3RvciAgICAgICAgICAgICAgICAg
ICAgICAgdmVyaWZ5IHNoZWxsLCB0b29scywgZm9udCBhbmQgZGVza3RvcCByb3V0aW5nCiAga3Rl
cm0tdXBkYXRlIC8ga3Rlcm0tcmVwYWlyICAgICAgICByZXJ1biB0aGUgc2F2ZWQgaW5zdGFsbGVy
IGlkZW1wb3RlbnRseQogIGt0ZXJtLWxvZyAgICAgICAgICAgICAgICAgICAgICAgICAgZm9sbG93
IHRoZSBpbnN0YWxsZXIgbG9nCiAga3Rlcm0tYmFja3VwcyAgICAgICAgICAgICAgICAgICAgICBs
aXN0IHNhZmV0eS1iYWNrdXAgZGlyZWN0b3JpZXMKICBrdGVybS11bmluc3RhbGwgICAgICAgICAg
ICAgICAgICAgIHJlbW92ZSBtYW5hZ2VkIGludGVncmF0aW9uIGFuZCByZXN0b3JlIGJhY2t1cHMK
ICB0ZXJtaW5hdG9yLW1vZGVybiAvIC1jbGFzc2ljICAgICAgIGxhdW5jaCBhIHNwZWNpZmljIHNh
dmVkIFRlcm1pbmF0b3IgcHJvZmlsZQoKVmlzdWFsIGZpbGVzLCBjb2RlIGFuZCBuYXZpZ2F0aW9u
CiAga3ZscyBbUEFUSF0gICAgICAgICAgICAgICAgICAgICAgICBpY29uLWF3YXJlIGxpc3RpbmcK
ICBrdmxsIFtQQVRIXSAgICAgICAgICAgICAgICAgICAgICAgIGRldGFpbGVkIGljb24vR2l0LWF3
YXJlIGxpc3RpbmcKICBrdnRyZWUgW0RFUFRIXSBbUEFUSF0gICAgICAgICAgICAgIHZpc3VhbCBk
aXJlY3RvcnkgdHJlZQogIGt2Y2F0IEZJTEUgICAgICAgICAgICAgICAgICAgICAgICAgc3ludGF4
LWhpZ2hsaWdodGVkIGZpbGUgdmlld2VyCiAga3ZncmVwIFFVRVJZIFtQQVRIXSAgICAgICAgICAg
ICAgICBmYXN0IHJlY3Vyc2l2ZSBzbWFydCBzZWFyY2gKICBrcHJldmlldyBQQVRIICAgICAgICAg
ICAgICAgICAgICAgIHByZXZpZXcgY29kZSwgaW1hZ2VzLCBQREYsIEpTT04sIGFyY2hpdmVzIGFu
ZCBtZWRpYQogIGtmZiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZnV6enktc2VsZWN0
IGEgZmlsZSBhbmQgb3BlbiBpdCBpbiAkVklTVUFMLyRFRElUT1IKICBrZmNkICAgICAgICAgICAg
ICAgICAgICAgICAgICAgICAgIGZ1enp5LXNlbGVjdCBhbmQgZW50ZXIgYSBkaXJlY3RvcnkKICB6
IE5BTUUgLyB6aSAgICAgICAgICAgICAgICAgICAgICAgIGxlYXJuZWQgZGlyZWN0b3J5IGp1bXAg
LyB2aXN1YWwgZGlyZWN0b3J5IHBpY2tlcgogIGt5YXppICAgICAgICAgICAgICAgICAgICAgICAg
ICAgICAgdGVybWluYWwgZmlsZSBtYW5hZ2VyOyBleGl0cyBpbnRvIGNob3NlbiBkaXJlY3RvcnkK
CkdpdCwgUHl0aG9uLCBjb250YWluZXJzIGFuZCBwcm9jZXNzZXMKICBrdmRpZmYgW2dpdCBkaWZm
IG9wdGlvbnNdICAgICAgICAgIGhpZ2hsaWdodGVkIEdpdCBkaWZmCiAga3ZnaXQgICAgICAgICAg
ICAgICAgICAgICAgICAgICAgICBMYXp5R2l0IFVJLCB3aXRoIGdpdC1zdGF0dXMgZmFsbGJhY2sK
ICBrZmJyYW5jaCAgICAgICAgICAgICAgICAgICAgICAgICAgIGZ1enp5IGxvY2FsIEdpdCBicmFu
Y2ggc3dpdGNoZXIKICBrZnZlbnYgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZ1enp5IFB5
dGhvbiB2aXJ0dWFsLWVudmlyb25tZW50IGFjdGl2YXRvcgogIGtmY29uZGEgICAgICAgICAgICAg
ICAgICAgICAgICAgICAgZnV6enkgQ29uZGEgZW52aXJvbm1lbnQgYWN0aXZhdG9yCiAga2Zkb2Nr
ZXIgICAgICAgICAgICAgICAgICAgICAgICAgICBmdXp6eSBydW5uaW5nLWNvbnRhaW5lciBzaGVs
bAogIGtma2lsbCAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZnV6enkgcHJvY2VzcyBzZWxl
Y3Rvcjsgc2VuZHMgU0lHVEVSTQogIGtta2NkIERJUiAgICAgICAgICAgICAgICAgICAgICAgICAg
Y3JlYXRlIGFuZCBlbnRlciBhIGRpcmVjdG9yeQogIGtzZXJ2ZSBbUE9SVF0gW0JJTkRdICAgICAg
ICAgICAgICAgbG9jYWwgUHl0aG9uIGZpbGUgc2VydmVyOyBkZWZhdWx0IDEyNy4wLjAuMTo4MDAw
CgpTeXN0ZW0gYW5kIGRhc2hib2FyZHMKICBrc3lzaW5mbyAgICAgICAgICAgICAgICAgICAgICAg
ICAgIHZpc3VhbCBtYWNoaW5lIHN1bW1hcnkKICBrc3lzbW9uICAgICAgICAgICAgICAgICAgICAg
ICAgICAgIGJ0b3AsIGh0b3Agb3IgdG9wCiAga2dwdXRvcCAgICAgICAgICAgICAgICAgICAgICAg
ICAgICBOVklESUEsIEFNRCBvciBSYXNwYmVycnkgUGkvU29DIG1vbml0b3IKICBrbmV0bW9uICAg
ICAgICAgICAgICAgICAgICAgICAgICAgIG5sb2FkIG9yIGxpdmUgaXAtbGluayBzdGF0aXN0aWNz
CiAga3BpdGVtcCAvIGtwaXN0YXR1cyAgICAgICAgICAgICAgICBSYXNwYmVycnkgUGkvU0JDIHRo
ZXJtYWwgYW5kIGhlYWx0aCBzdW1tYXJ5CiAga2Rhc2hib2FyZCAgICAgICAgICAgICAgICAgICAg
ICAgICAzLXBhbmUgdG11eCB3b3Jrc3RhdGlvbiBkYXNoYm9hcmQKICBrZGFzaGJvYXJkIC0tcmVz
ZXR8LS1zdGF0dXN8LS1raWxsIHJlYnVpbGQsIGluc3BlY3Qgb3IgY2xvc2UgaXRzIHRtdXggc2Vz
c2lvbgoKS2V5Ym9hcmQgc2hvcnRjdXRzCiAgQ3RybCtSICAgICAgICAgICAgICAgICAgICAgICAg
ICAgICBBdHVpbiBoaXN0b3J5IFVJIG9yIGd1YXJhbnRlZWQgZnpmIGZhbGxiYWNrCiAgQWx0K1Ig
ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBvcmlnaW5hbCBpbmNyZW1lbnRhbCBac2ggaGlz
dG9yeSBzZWFyY2gKICBDdHJsK1QgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZ1enp5IGZp
bGUgaW5zZXJ0aW9uCiAgQWx0K0MgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmdXp6eSBk
aXJlY3RvcnkgY2hhbmdlCiAgVGFiICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB2aXN1
YWwgY29tcGxldGlvbiBtZW51CiAgUmlnaHQgQXJyb3cgICAgICAgICAgICAgICAgICAgICAgICBh
Y2NlcHQgYW4gYXV0b3N1Z2dlc3Rpb24KICBDdHJsKy8gaW5zaWRlIGZ6ZiAgICAgICAgICAgICAg
ICAgIHRvZ2dsZSB0aGUgcHJldmlldyBwYW5lCiAgQ3RybCtTaGlmdCtFIC8gQ3RybCtTaGlmdCtP
ICAgICAgICBUZXJtaW5hdG9yIHZlcnRpY2FsIC8gaG9yaXpvbnRhbCBzcGxpdAogIEN0cmwrU2hp
ZnQrVCAgICAgICAgICAgICAgICAgICAgICAgbmV3IFRlcm1pbmF0b3IgdGFiCgpTaG9ydCBhbGlh
c2VzIHN1Y2ggYXMgdmxsLCB2dHJlZSwgdmNhdCwgdmdyZXAsIHZnaXQsIHl5LCBmZiwgZmNkLCBz
eXNtb24sCmdwdXRvcCBhbmQgZGFzaGJvYXJkIGFyZSBhZGRlZCBvbmx5IHdoZW4gdGhlIG5hbWUg
d2FzIHByZXZpb3VzbHkgdW51c2VkLgpFeGlzdGluZyBhbGlhc2VzLCBmdW5jdGlvbnMsIFBBVEgg
c2V0dGluZ3MgYW5kIGNvbW1hbmRzIGFyZSBuZXZlciByZXBsYWNlZC4KSEVMUAp9CgojIFByZXNl
cnZlIGV2ZXJ5IHVzZXItZGVmaW5lZCBuYW1lLiBTaG9ydCBjb252ZW5pZW5jZSBhbGlhc2VzIGFy
ZSBpbnN0YWxsZWQKIyBvbmx5IHdoZW4gbm8gYWxpYXMsIGZ1bmN0aW9uLCBidWlsdGluLCByZXNl
cnZlZCB3b3JkLCBvciBleGVjdXRhYmxlIG93bnMgaXQuCnR5cGVzZXQgLWdhIEtBUlRISV9TS0lQ
UEVEX0FMSUFTRVMKS0FSVEhJX1NLSVBQRURfQUxJQVNFUz0oKQoKX2t0ZXJtX2FsaWFzX2lmX2Zy
ZWUoKSB7CiAgbG9jYWwgc2hvcnRfbmFtZT0iJDEiIHRhcmdldF9uYW1lPSIkMiIKICBpZiAoKCAk
eythbGlhc2VzWyRzaG9ydF9uYW1lXX0gfHwgJHsrZnVuY3Rpb25zWyRzaG9ydF9uYW1lXX0gfHwK
ICAgICAgICAkeytidWlsdGluc1skc2hvcnRfbmFtZV19IHx8ICR7K3Jlc3dvcmRzWyRzaG9ydF9u
YW1lXX0gfHwKICAgICAgICAkeytjb21tYW5kc1skc2hvcnRfbmFtZV19ICkpOyB0aGVuCiAgICBL
QVJUSElfU0tJUFBFRF9BTElBU0VTKz0oIiRzaG9ydF9uYW1lIikKICAgIHJldHVybiAwCiAgZmkK
ICBhbGlhcyAiJHNob3J0X25hbWU9JHRhcmdldF9uYW1lIgp9Cgpfa3Rlcm1fYWxpYXNfaWZfZnJl
ZSB2bHMga3Zscwpfa3Rlcm1fYWxpYXNfaWZfZnJlZSB2bGwga3ZsbApfa3Rlcm1fYWxpYXNfaWZf
ZnJlZSB2dHJlZSBrdnRyZWUKX2t0ZXJtX2FsaWFzX2lmX2ZyZWUgdmNhdCBrdmNhdApfa3Rlcm1f
YWxpYXNfaWZfZnJlZSB2Z3JlcCBrdmdyZXAKX2t0ZXJtX2FsaWFzX2lmX2ZyZWUgdmRpZmYga3Zk
aWZmCl9rdGVybV9hbGlhc19pZl9mcmVlIHZnaXQga3ZnaXQKX2t0ZXJtX2FsaWFzX2lmX2ZyZWUg
eXkga3lhemkKX2t0ZXJtX2FsaWFzX2lmX2ZyZWUgZmYga2ZmCl9rdGVybV9hbGlhc19pZl9mcmVl
IGZjZCBrZmNkCl9rdGVybV9hbGlhc19pZl9mcmVlIGZraWxsIGtma2lsbApfa3Rlcm1fYWxpYXNf
aWZfZnJlZSBmYnJhbmNoIGtmYnJhbmNoCl9rdGVybV9hbGlhc19pZl9mcmVlIGZ2ZW52IGtmdmVu
dgpfa3Rlcm1fYWxpYXNfaWZfZnJlZSBmY29uZGEga2Zjb25kYQpfa3Rlcm1fYWxpYXNfaWZfZnJl
ZSBmZG9ja2VyIGtmZG9ja2VyCl9rdGVybV9hbGlhc19pZl9mcmVlIG1rY2Qga21rY2QKX2t0ZXJt
X2FsaWFzX2lmX2ZyZWUgc2VydmUga3NlcnZlCl9rdGVybV9hbGlhc19pZl9mcmVlIHN5c2luZm8g
a3N5c2luZm8KX2t0ZXJtX2FsaWFzX2lmX2ZyZWUgc3lzbW9uIGtzeXNtb24KX2t0ZXJtX2FsaWFz
X2lmX2ZyZWUgZ3B1dG9wIGtncHV0b3AKX2t0ZXJtX2FsaWFzX2lmX2ZyZWUgbmV0bW9uIGtuZXRt
b24KX2t0ZXJtX2FsaWFzX2lmX2ZyZWUgcGl0ZW1wIGtwaXRlbXAKX2t0ZXJtX2FsaWFzX2lmX2Zy
ZWUgcGlzdGF0dXMga3Bpc3RhdHVzCl9rdGVybV9hbGlhc19pZl9mcmVlIGRhc2hib2FyZCBrZGFz
aGJvYXJkCl9rdGVybV9hbGlhc19pZl9mcmVlIGtoZWxwIGt0ZXJtLWhlbHAKdW5mdW5jdGlvbiBf
a3Rlcm1fYWxpYXNfaWZfZnJlZQoKaWYgW1sgIiR7S0FSVEhJX0hVRDotb259IiA9PSBvbiAmJiAt
eiAiJHtLQVJUSElfSFVEX1NIT1dOOi19IiBdXTsgdGhlbgogIGV4cG9ydCBLQVJUSElfSFVEX1NI
T1dOPTEKICBfa2FydGhpX3JlbmRlcl9odWQKZmkKCiMgVmlzdWFsIGNvbW1hbmQgYm91bmRhcmll
cy4gUmV0dXJuIHRoZSBwcmV2aW91cyBzdGF0dXMgc28gbGF0ZXIgaG9va3Mgc3VjaCBhcwojIEF0
dWluIGFuZCBTdGFyc2hpcCBzdGlsbCByZWNlaXZlIHRoZSByZWFsIGNvbW1hbmQgcmVzdWx0Lgp6
bW9kbG9hZCB6c2gvZGF0ZXRpbWUgMj4vZGV2L251bGwgfHwgdHJ1ZQpmdW5jdGlvbiBfa2FydGhp
X3ByZWV4ZWMoKSB7CiAgW1sgIiR7S0FSVEhJX0JMT0NLUzotb259IiA9PSBvbiBdXSB8fCByZXR1
cm4gMAogIGxvY2FsIGNvbW1hbmRfdGV4dD0iJHsxLy8kJ1xuJy8gfSIKICAoKCAkeyNjb21tYW5k
X3RleHR9ID4gMTIwICkpICYmIGNvbW1hbmRfdGV4dD0iJHtjb21tYW5kX3RleHRbMSwxMTddfS4u
LiIKICBjb21tYW5kX3RleHQ9IiR7Y29tbWFuZF90ZXh0Ly9cJS8lJX0iCiAgdHlwZXNldCAtZ0Yg
S0FSVEhJX0JMT0NLX1NUQVJUPSIkRVBPQ0hSRUFMVElNRSIKICB0eXBlc2V0IC1nIEtBUlRISV9C
TE9DS19BQ1RJVkU9MQogIHByaW50IC1yUCAtLSAiJUZ7IzZjNzA4Nn3ila3ilIAlZiAlRnsjODli
NGZhfVJVTiVmICVGeyM3Zjg0OWN9JChkYXRlICslSDolTTolUyklZiAgJUZ7I2JhYzJkZX0ke2Nv
bW1hbmRfdGV4dH0lZiIKICByZXR1cm4gMAp9CgpmdW5jdGlvbiBfa2FydGhpX3ByZWNtZCgpIHsK
ICBsb2NhbCByYz0kPwogIGlmIFtbICIke0tBUlRISV9CTE9DS1M6LW9ufSIgPT0gb24gJiYgLW4g
IiR7S0FSVEhJX0JMT0NLX0FDVElWRTotfSIgXV07IHRoZW4KICAgIGxvY2FsIGVsYXBzZWQ9IjAu
MDAiCiAgICBpZiBbWyAtbiAiJHtLQVJUSElfQkxPQ0tfU1RBUlQ6LX0iIF1dOyB0aGVuCiAgICAg
IGVsYXBzZWQ9IiQocHJpbnRmICclLjJmJyAiJCgoIEVQT0NIUkVBTFRJTUUgLSBLQVJUSElfQkxP
Q0tfU1RBUlQgKSkiKSIKICAgIGZpCiAgICBpZiAoKCByYyA9PSAwICkpOyB0aGVuCiAgICAgIHBy
aW50IC1yUCAtLSAiJUZ7IzZjNzA4Nn3ilbDilIAlZiAlRnsjYTZlM2ExfU9LJWYgICVGeyM3Zjg0
OWN9JHtlbGFwc2VkfXMlZiIKICAgIGVsc2UKICAgICAgcHJpbnQgLXJQIC0tICIlRnsjNmM3MDg2
feKVsOKUgCVmICVGeyNmMzhiYTh9RVJSICR7cmN9JWYgICVGeyM3Zjg0OWN9JHtlbGFwc2VkfXMl
ZiIKICAgIGZpCiAgICB1bnNldCBLQVJUSElfQkxPQ0tfQUNUSVZFIEtBUlRISV9CTE9DS19TVEFS
VAogIGZpCiAgcmV0dXJuICIkcmMiCn0KCnR5cGVzZXQgLWdhIHByZWV4ZWNfZnVuY3Rpb25zIHBy
ZWNtZF9mdW5jdGlvbnMKcHJlZXhlY19mdW5jdGlvbnM9KF9rYXJ0aGlfcHJlZXhlYyAke3ByZWV4
ZWNfZnVuY3Rpb25zOiNfa2FydGhpX3ByZWV4ZWN9KQpwcmVjbWRfZnVuY3Rpb25zPShfa2FydGhp
X3ByZWNtZCAke3ByZWNtZF9mdW5jdGlvbnM6I19rYXJ0aGlfcHJlY21kfSkKCmlmIGNvbW1hbmQg
LXYgc3RhcnNoaXAgPi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgZXZhbCAiJChzdGFyc2hpcCBpbml0
IHpzaCkiCmZpCgojIFN5bnRheCBoaWdobGlnaHRpbmcgbXVzdCBiZSB0aGUgbGFzdCBaTEUgcGx1
Z2luIGxvYWRlZC4KaWYgW1sgLXIgIiRLQVJUSElfU0hFTExfREFUQS9wbHVnaW5zL3pzaC1zeW50
YXgtaGlnaGxpZ2h0aW5nL3pzaC1zeW50YXgtaGlnaGxpZ2h0aW5nLnpzaCIgXV0gXAogICAmJiBb
WyAteiAiJHtaU0hfSElHSExJR0hUX1ZFUlNJT046LX0iIF1dOyB0aGVuCiAgWlNIX0hJR0hMSUdI
VF9ISUdITElHSFRFUlM9KG1haW4gYnJhY2tldHMpCiAgWlNIX0hJR0hMSUdIVF9QQVRURVJOUys9
KCdybSAtcmYgKicgJ2ZnPXdoaXRlLGJvbGQsYmc9cmVkJykKICBzb3VyY2UgIiRLQVJUSElfU0hF
TExfREFUQS9wbHVnaW5zL3pzaC1zeW50YXgtaGlnaGxpZ2h0aW5nL3pzaC1zeW50YXgtaGlnaGxp
Z2h0aW5nLnpzaCIKZmkKCnVuc2V0IF9rcHJvbXB0X3N0eWxlCg==
KTERM_B64_MODERN

base64 -d > "$BIN_DIR/kpreview" <<'KTERM_B64_PREVIEW'
IyEvdXNyL2Jpbi9lbnYgYmFzaApzZXQgLXUKCnRhcmdldD0iJHsxOi19IgpbWyAtbiAiJHRhcmdl
dCIgXV0gfHwgZXhpdCAwCltbIC1lICIkdGFyZ2V0IiB8fCAtTCAiJHRhcmdldCIgXV0gfHwgeyBw
cmludGYgJ05vdCBmb3VuZDogJXNcbicgIiR0YXJnZXQiOyBleGl0IDA7IH0KCndpZHRoPSIke0Za
Rl9QUkVWSUVXX0NPTFVNTlM6LTEwMH0iCmhlaWdodD0iJHtGWkZfUFJFVklFV19MSU5FUzotNDB9
IgoKaWYgW1sgLWQgIiR0YXJnZXQiIF1dOyB0aGVuCiAgaWYgY29tbWFuZCAtdiBlemEgPi9kZXYv
bnVsbCAyPiYxOyB0aGVuCiAgICBleGVjIGV6YSAtLXRyZWUgLS1sZXZlbD0zIC0taWNvbnM9YWx3
YXlzIC0tZ2l0IC0tZ3JvdXAtZGlyZWN0b3JpZXMtZmlyc3QgLS1jb2xvcj1hbHdheXMgLS0gIiR0
YXJnZXQiCiAgZWxpZiBjb21tYW5kIC12IGV4YSA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICAgIGV4
ZWMgZXhhIC0tdHJlZSAtLWxldmVsPTMgLS1pY29ucyAtLWdpdCAtLWdyb3VwLWRpcmVjdG9yaWVz
LWZpcnN0IC0tY29sb3I9YWx3YXlzIC0tICIkdGFyZ2V0IgogIGZpCiAgZXhlYyBscyAtbGFoIC0t
Y29sb3I9YWx3YXlzIC0tICIkdGFyZ2V0IgpmaQoKbWltZT0iJChmaWxlIC1MYiAtLW1pbWUtdHlw
ZSAtLSAiJHRhcmdldCIgMj4vZGV2L251bGwgfHwgcHJpbnRmIGFwcGxpY2F0aW9uL29jdGV0LXN0
cmVhbSkiCmNhc2UgIiRtaW1lIiBpbgogIGltYWdlLyopCiAgICBpZiBjb21tYW5kIC12IGNoYWZh
ID4vZGV2L251bGwgMj4mMTsgdGhlbgogICAgICBjaGFmYSAtLWZvcm1hdD1zeW1ib2xzIC0tc2l6
ZT0iJHt3aWR0aH14JHtoZWlnaHR9IiAtLSAiJHRhcmdldCIKICAgIGVsc2UKICAgICAgZmlsZSAt
LSAiJHRhcmdldCIKICAgIGZpCiAgICA7OwogIGFwcGxpY2F0aW9uL3BkZikKICAgIGlmIGNvbW1h
bmQgLXYgcGRmdG90ZXh0ID4vZGV2L251bGwgMj4mMTsgdGhlbgogICAgICBpZiBjb21tYW5kIC12
IGJhdCA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICAgICAgICBwZGZ0b3RleHQgLWYgMSAtbCA1IC1s
YXlvdXQgLS0gIiR0YXJnZXQiIC0gMj4vZGV2L251bGwgfCBiYXQgLS1jb2xvcj1hbHdheXMgLS1z
dHlsZT1wbGFpbiAtLWxhbmd1YWdlPXR4dAogICAgICBlbHNlCiAgICAgICAgcGRmdG90ZXh0IC1m
IDEgLWwgNSAtbGF5b3V0IC0tICIkdGFyZ2V0IiAtIDI+L2Rldi9udWxsIHwgaGVhZCAtbiAiJGhl
aWdodCIKICAgICAgZmkKICAgIGVsc2UKICAgICAgZmlsZSAtLSAiJHRhcmdldCIKICAgIGZpCiAg
ICA7OwogIGFwcGxpY2F0aW9uL2pzb258YXBwbGljYXRpb24vKitqc29uKQogICAgaWYgY29tbWFu
ZCAtdiBqcSA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICAgICAganEgLS1jb2xvci1vdXRwdXQgLiAt
LSAiJHRhcmdldCIgMj4vZGV2L251bGwgfCBoZWFkIC1uICIkKChoZWlnaHQgKiAzKSkiCiAgICBl
bHNlCiAgICAgIGNhdCAtLSAiJHRhcmdldCIKICAgIGZpCiAgICA7OwogIGFwcGxpY2F0aW9uL3pp
cHxhcHBsaWNhdGlvbi94LTd6LWNvbXByZXNzZWR8YXBwbGljYXRpb24veC1yYXJ8YXBwbGljYXRp
b24vZ3ppcHxhcHBsaWNhdGlvbi94LXh6fGFwcGxpY2F0aW9uL3gtdGFyKQogICAgaWYgY29tbWFu
ZCAtdiA3eiA+L2Rldi9udWxsIDI+JjE7IHRoZW4gN3ogbCAtLSAiJHRhcmdldCIgfCBoZWFkIC1u
ICIkaGVpZ2h0IjsgZWxzZSBmaWxlIC0tICIkdGFyZ2V0IjsgZmkKICAgIDs7CiAgdmlkZW8vKnxh
dWRpby8qKQogICAgaWYgY29tbWFuZCAtdiBmZnByb2JlID4vZGV2L251bGwgMj4mMTsgdGhlbgog
ICAgICBmZnByb2JlIC1oaWRlX2Jhbm5lciAtLSAiJHRhcmdldCIgMj4mMSB8IGhlYWQgLW4gIiRo
ZWlnaHQiCiAgICBlbHNlCiAgICAgIGZpbGUgLS0gIiR0YXJnZXQiCiAgICBmaQogICAgOzsKICB0
ZXh0Lyp8YXBwbGljYXRpb24veG1sfGFwcGxpY2F0aW9uL3gtc2hlbGxzY3JpcHR8YXBwbGljYXRp
b24vamF2YXNjcmlwdHxhcHBsaWNhdGlvbi94LXB5dGhvbiopCiAgICBpZiBjb21tYW5kIC12IGJh
dCA+L2Rldi9udWxsIDI+JjE7IHRoZW4KICAgICAgYmF0IC0tY29sb3I9YWx3YXlzIC0tc3R5bGU9
bnVtYmVycyxjaGFuZ2VzIC0tbGluZS1yYW5nZT0iOiQoKGhlaWdodCAqIDMpKSIgLS0gIiR0YXJn
ZXQiCiAgICBlbHNlCiAgICAgIHNlZCAtbiAiMSwke2hlaWdodH1wIiAtLSAiJHRhcmdldCIKICAg
IGZpCiAgICA7OwogICopCiAgICBmaWxlIC0tICIkdGFyZ2V0IgogICAgcHJpbnRmICdcbicKICAg
IHN0YXQgLS0gIiR0YXJnZXQiIDI+L2Rldi9udWxsIHwgaGVhZCAtbiAxMgogICAgOzsKZXNhYwo=
KTERM_B64_PREVIEW

base64 -d > "$DASH_DIR/system-monitor.sh" <<'KTERM_B64_SYSTEM_MON'
IyEvdXNyL2Jpbi9lbnYgYmFzaApzZXQgK2UKY2xlYXIKcHJpbnRmICdcMDMzWzE7MzZtS1RFUk0g
Ly8gU1lTVEVNIE1PTklUT1JcMDMzWzBtXG4nCnByaW50ZiAnSG9zdDogJXMgICBTdGFydGVkOiAl
c1xuXG4nICIkKGhvc3RuYW1lKSIgIiQoZGF0ZSAnKyVGICVUJykiCgppZiBjb21tYW5kIC12IGJ0
b3AgPi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgYnRvcAplbGlmIGNvbW1hbmQgLXYgaHRvcCA+L2Rl
di9udWxsIDI+JjE7IHRoZW4KICBodG9wCmVsc2UKICB0b3AKZmkKCnJjPSQ/CnByaW50ZiAnXG5N
b25pdG9yIGV4aXRlZCB3aXRoIHN0YXR1cyAlcy4gQSBzaGVsbCBpcyBvcGVuaW5nIGluIHRoaXMg
cGFuZS5cbicgIiRyYyIKZXhlYyAiJHtTSEVMTDotL2Jpbi96c2h9IiAtbAo=
KTERM_B64_SYSTEM_MON

base64 -d > "$DASH_DIR/hardware-monitor.sh" <<'KTERM_B64_HARDWARE_MON'
IyEvdXNyL2Jpbi9lbnYgYmFzaApzZXQgK2UKCm9wZW5fc2hlbGwoKSB7CiAgcHJpbnRmICdcbkhh
cmR3YXJlIG1vbml0b3Igc3RvcHBlZC4gQSBzaGVsbCBpcyBvcGVuaW5nIGluIHRoaXMgcGFuZS5c
bicKICBleGVjICIke1NIRUxMOi0vYmluL3pzaH0iIC1sCn0KdHJhcCBvcGVuX3NoZWxsIElOVCBU
RVJNCgp3aGlsZSB0cnVlOyBkbwogIGNsZWFyCiAgcHJpbnRmICdcMDMzWzE7MzVtS1RFUk0gLy8g
SEFSRFdBUkUgKyBORVRXT1JLXDAzM1swbVxuJwogIHByaW50ZiAnSG9zdDogJXMgICAlc1xuJyAi
JChob3N0bmFtZSkiICIkKGRhdGUgJyslRiAlVCcpIgogIHByaW50ZiAnJXNcblxuJyAn4pSA4pSA
4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA
4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA
JwoKICBpZiBjb21tYW5kIC12IG52aWRpYS1zbWkgPi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgICBw
cmludGYgJ1wwMzNbMTszNm1HUFVcMDMzWzBtXG4nCiAgICBudmlkaWEtc21pIC0tcXVlcnktZ3B1
PW5hbWUsdGVtcGVyYXR1cmUuZ3B1LHV0aWxpemF0aW9uLmdwdSxtZW1vcnkudXNlZCxtZW1vcnku
dG90YWwscG93ZXIuZHJhdyBcCiAgICAgIC0tZm9ybWF0PWNzdixub2hlYWRlciAyPi9kZXYvbnVs
bCB8fCBudmlkaWEtc21pIDI+L2Rldi9udWxsCiAgZWxpZiBjb21tYW5kIC12IHJvY20tc21pID4v
ZGV2L251bGwgMj4mMTsgdGhlbgogICAgcHJpbnRmICdcMDMzWzE7MzZtR1BVXDAzM1swbVxuJwog
ICAgcm9jbS1zbWkgLS1zaG93cHJvZHVjdG5hbWUgLS1zaG93dGVtcCAtLXNob3d1c2UgLS1zaG93
bWVtdXNlIDI+L2Rldi9udWxsIHwgaGVhZCAtMjAKICBlbGlmIGNvbW1hbmQgLXYgdmNnZW5jbWQg
Pi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgICBwcmludGYgJ1wwMzNbMTszNm1SQVNQQkVSUlkgUEkg
U09DXDAzM1swbVxuJwogICAgdmNnZW5jbWQgbWVhc3VyZV90ZW1wIDI+L2Rldi9udWxsCiAgICB2
Y2dlbmNtZCBnZXRfdGhyb3R0bGVkIDI+L2Rldi9udWxsCiAgICB2Y2dlbmNtZCBtZWFzdXJlX2Ns
b2NrIGFybSAyPi9kZXYvbnVsbAogICAgdmNnZW5jbWQgbWVhc3VyZV92b2x0cyBjb3JlIDI+L2Rl
di9udWxsCiAgZWxpZiBbWyAtciAvc3lzL2NsYXNzL3RoZXJtYWwvdGhlcm1hbF96b25lMC90ZW1w
IF1dOyB0aGVuCiAgICBwcmludGYgJ1wwMzNbMTszNm1TT0NcMDMzWzBtXG4nCiAgICBhd2sgJ3tw
cmludGYgIlRlbXBlcmF0dXJlOiAlLjFmIENcbiIsICQxLzEwMDB9JyAvc3lzL2NsYXNzL3RoZXJt
YWwvdGhlcm1hbF96b25lMC90ZW1wCiAgZWxzZQogICAgcHJpbnRmICdcMDMzWzE7MzZtR1BVIC8g
U09DXDAzM1swbVxuTm8gc3VwcG9ydGVkIHRlbGVtZXRyeSBjb21tYW5kIHdhcyBkZXRlY3RlZC5c
bicKICBmaQoKICBwcmludGYgJ1xuXDAzM1sxOzM2bU1FTU9SWVwwMzNbMG1cbicKICBmcmVlIC1o
IDI+L2Rldi9udWxsIHwgc2VkIC1uICcxLDNwJwogIHByaW50ZiAnXG5cMDMzWzE7MzZtTE9BRFww
MzNbMG1cbicKICB1cHRpbWUgMj4vZGV2L251bGwKICBwcmludGYgJ1xuXDAzM1sxOzM2bURJU0sg
L1wwMzNbMG1cbicKICBkZiAtaCAvIDI+L2Rldi9udWxsIHwgc2VkIC1uICcxLDJwJwogIHByaW50
ZiAnXG5cMDMzWzE7MzZtTkVUV09SS1wwMzNbMG1cbicKICBpcCAtYnJpZWYgYWRkcmVzcyAyPi9k
ZXYvbnVsbCB8IGF3ayAnJDEgIT0gImxvIiB7cHJpbnR9JyB8IGhlYWQgLTgKICBwcmludGYgJ1xu
XDAzM1sybVJlZnJlc2g6IDIgcyDigKIgQ3RybCtDIG9wZW5zIGEgc2hlbGwgaW4gdGhpcyBwYW5l
XDAzM1swbVxuJwogIHNsZWVwIDIKZG9uZQo=
KTERM_B64_HARDWARE_MON

base64 -d > "$BIN_DIR/karthi-dashboard" <<'KTERM_B64_DASHBOARD'
IyEvdXNyL2Jpbi9lbnYgYmFzaApzZXQgLUVldW8gcGlwZWZhaWwKClNFU1NJT049ImthcnRoaS1k
YXNoYm9hcmQiCldPUktESVI9IiRQV0QiCktURVJNX0RJUj0iJHtYREdfQ09ORklHX0hPTUU6LSRI
T01FLy5jb25maWd9L2thcnRoaS1zaGVsbCIKU1lTVEVNX01PTj0iJEtURVJNX0RJUi9kYXNoYm9h
cmQvc3lzdGVtLW1vbml0b3Iuc2giCkhBUkRXQVJFX01PTj0iJEtURVJNX0RJUi9kYXNoYm9hcmQv
aGFyZHdhcmUtbW9uaXRvci5zaCIKCnVzYWdlKCkgewogIGNhdCA8PCdUWFQnClVzYWdlOgogIGtk
YXNoYm9hcmQgICAgICAgICAgICAgb3BlbiBvciBhdHRhY2ggdGhlIEtURVJNIGRhc2hib2FyZAog
IGtkYXNoYm9hcmQgLS1yZXNldCAgICAgZGVzdHJveSBhbmQgcmVidWlsZCBhbGwgcGFuZXMKICBr
ZGFzaGJvYXJkIC0tc3RhdHVzICAgIHNob3cgcGFuZSB0aXRsZXMgYW5kIHJ1bm5pbmcgY29tbWFu
ZHMKICBrZGFzaGJvYXJkIC0ta2lsbCAgICAgIGNsb3NlIHRoZSBkYXNoYm9hcmQgc2Vzc2lvbgpU
WFQKfQoKY29tbWFuZCAtdiB0bXV4ID4vZGV2L251bGwgMj4mMSB8fCB7CiAgcHJpbnRmICdrZGFz
aGJvYXJkOiB0bXV4IGlzIG5vdCBpbnN0YWxsZWQuIFJ1biBrdGVybS1yZXBhaXIuXG4nID4mMgog
IGV4aXQgMTI3Cn0KCmNhc2UgIiR7MTotfSIgaW4KICAtaHwtLWhlbHApIHVzYWdlOyBleGl0IDAg
OzsKICAtLWtpbGwpCiAgICB0bXV4IGtpbGwtc2Vzc2lvbiAtdCAiJFNFU1NJT04iIDI+L2Rldi9u
dWxsIHx8IHRydWUKICAgIHByaW50ZiAnS1RFUk0gZGFzaGJvYXJkIHNlc3Npb24gY2xvc2VkLlxu
JwogICAgZXhpdCAwCiAgICA7OwogIC0tc3RhdHVzKQogICAgdG11eCBoYXMtc2Vzc2lvbiAtdCAi
JFNFU1NJT04iIDI+L2Rldi9udWxsIHx8IHsKICAgICAgcHJpbnRmICdLVEVSTSBkYXNoYm9hcmQg
aXMgbm90IHJ1bm5pbmcuXG4nCiAgICAgIGV4aXQgMQogICAgfQogICAgdG11eCBsaXN0LXBhbmVz
IC10ICIkU0VTU0lPTjp3b3Jrc3RhdGlvbiIgXAogICAgICAtRiAnI3twYW5lX2luZGV4fSB8ICN7
cGFuZV90aXRsZX0gfCBhY3RpdmU9I3twYW5lX2FjdGl2ZX0gfCBkZWFkPSN7cGFuZV9kZWFkfSB8
IHBpZD0je3BhbmVfcGlkfSB8IGNtZD0je3BhbmVfY3VycmVudF9jb21tYW5kfScKICAgIGV4aXQg
MAogICAgOzsKICAtLXJlc2V0KSB0bXV4IGtpbGwtc2Vzc2lvbiAtdCAiJFNFU1NJT04iIDI+L2Rl
di9udWxsIHx8IHRydWUgOzsKICAiIikgOzsKICAqKSBwcmludGYgJ1Vua25vd24gb3B0aW9uOiAl
c1xuXG4nICIkMSIgPiYyOyB1c2FnZSA+JjI7IGV4aXQgMiA7Owplc2FjCgppZiB0bXV4IGhhcy1z
ZXNzaW9uIC10ICIkU0VTU0lPTiIgMj4vZGV2L251bGw7IHRoZW4KICBpZiBbWyAtbiAiJHtUTVVY
Oi19IiBdXTsgdGhlbgogICAgZXhlYyB0bXV4IHN3aXRjaC1jbGllbnQgLXQgIiRTRVNTSU9OIgog
IGVsc2UKICAgIGV4ZWMgdG11eCBhdHRhY2gtc2Vzc2lvbiAtdCAiJFNFU1NJT04iCiAgZmkKZmkK
CnRtdXggbmV3LXNlc3Npb24gLWQgLXMgIiRTRVNTSU9OIiAtbiB3b3Jrc3RhdGlvbiAtYyAiJFdP
UktESVIiCnRtdXggc2V0LW9wdGlvbiAtdCAiJFNFU1NJT04iIHN0YXR1cyBvbgp0bXV4IHNldC1v
cHRpb24gLXQgIiRTRVNTSU9OIiBtb3VzZSBvbgp0bXV4IHNldC1vcHRpb24gLXQgIiRTRVNTSU9O
IiBzdGF0dXMtaW50ZXJ2YWwgMgp0bXV4IHNldC1vcHRpb24gLXQgIiRTRVNTSU9OIiBzdGF0dXMt
bGVmdC1sZW5ndGggNDAKdG11eCBzZXQtb3B0aW9uIC10ICIkU0VTU0lPTiIgc3RhdHVzLXJpZ2h0
LWxlbmd0aCA4MAp0bXV4IHNldC1vcHRpb24gLXQgIiRTRVNTSU9OIiBzdGF0dXMtbGVmdCAnIEtU
RVJNIERBU0hCT0FSRCAnCnRtdXggc2V0LW9wdGlvbiAtdCAiJFNFU1NJT04iIHN0YXR1cy1yaWdo
dCAnICN7P2NsaWVudF9wcmVmaXgsUFJFRklYICx9IyhkYXRlICIrJUg6JU06JVMiKSAnCnRtdXgg
c2V0LW9wdGlvbiAtdCAiJFNFU1NJT04iIHBhbmUtYm9yZGVyLXN0YXR1cyB0b3AKdG11eCBzZXQt
b3B0aW9uIC10ICIkU0VTU0lPTiIgcGFuZS1ib3JkZXItZm9ybWF0ICcgI1tib2xkXSAje3BhbmVf
dGl0bGV9ICNbZGVmYXVsdF0gJwp0bXV4IHNldC13aW5kb3ctb3B0aW9uIC10ICIkU0VTU0lPTjp3
b3Jrc3RhdGlvbiIgcmVtYWluLW9uLWV4aXQgb24KCnRtdXggc2VsZWN0LXBhbmUgLXQgIiRTRVNT
SU9OOndvcmtzdGF0aW9uLjAiIC1UICdERVYgU0hFTEwnClJJR0hUX1BBTkU9IiQodG11eCBzcGxp
dC13aW5kb3cgLWggLXAgNDAgLVAgLUYgJyN7cGFuZV9pZH0nIFwKICAtdCAiJFNFU1NJT046d29y
a3N0YXRpb24uMCIgLWMgIiRXT1JLRElSIiAiJFNZU1RFTV9NT04iKSIKdG11eCBzZWxlY3QtcGFu
ZSAtdCAiJFJJR0hUX1BBTkUiIC1UICdTWVNURU0gLy8gYnRvcCcKSEFSRFdBUkVfUEFORT0iJCh0
bXV4IHNwbGl0LXdpbmRvdyAtdiAtcCA0OCAtUCAtRiAnI3twYW5lX2lkfScgXAogIC10ICIkUklH
SFRfUEFORSIgLWMgIiRXT1JLRElSIiAiJEhBUkRXQVJFX01PTiIpIgp0bXV4IHNlbGVjdC1wYW5l
IC10ICIkSEFSRFdBUkVfUEFORSIgLVQgJ0hBUkRXQVJFIC8vIEdQVSArIE5FVCcKdG11eCBzZWxl
Y3QtcGFuZSAtdCAiJFNFU1NJT046d29ya3N0YXRpb24uMCIKCmlmIFtbIC1uICIke1RNVVg6LX0i
IF1dOyB0aGVuCiAgZXhlYyB0bXV4IHN3aXRjaC1jbGllbnQgLXQgIiRTRVNTSU9OIgplbHNlCiAg
ZXhlYyB0bXV4IGF0dGFjaC1zZXNzaW9uIC10ICIkU0VTU0lPTiIKZmkK
KTERM_B64_DASHBOARD

base64 -d > "$NAUTILUS_EXTENSION" <<'KTERM_B64_NAUTILUS'
IyBLVEVSTSBOYXV0aWx1cyBleHRlbnNpb24gZm9yIE5hdXRpbHVzIEFQSSAzLnggYW5kIDQueC4K
IyBJbnN0YWxsZWQgaW4gdGhlIGRvY3VtZW50ZWQgdXNlciBleHRlbnNpb24gcGF0aCB1bmRlciBY
REdfREFUQV9IT01FLgppbXBvcnQgb3MKaW1wb3J0IHN1YnByb2Nlc3MKZnJvbSBwYXRobGliIGlt
cG9ydCBQYXRoCmZyb20gdXJsbGliLnBhcnNlIGltcG9ydCB1bnF1b3RlLCB1cmxwYXJzZQoKaW1w
b3J0IGdpCgp0cnk6CiAgICBnaS5yZXF1aXJlX3ZlcnNpb24oIk5hdXRpbHVzIiwgIjQuMCIpCmV4
Y2VwdCBWYWx1ZUVycm9yOgogICAgdHJ5OgogICAgICAgIGdpLnJlcXVpcmVfdmVyc2lvbigiTmF1
dGlsdXMiLCAiMy4wIikKICAgIGV4Y2VwdCBWYWx1ZUVycm9yOgogICAgICAgIHBhc3MKCmZyb20g
Z2kucmVwb3NpdG9yeSBpbXBvcnQgR09iamVjdCwgTmF1dGlsdXMKCkxBVU5DSEVSID0gb3MucGF0
aC5leHBhbmR1c2VyKCJ+Ly5sb2NhbC9iaW4va3Rlcm0tdGVybWluYWwiKQoKCmRlZiBfbG9jYWxf
cGF0aChpbmZvKToKICAgIGlmIGluZm8gaXMgTm9uZToKICAgICAgICByZXR1cm4gTm9uZQogICAg
dHJ5OgogICAgICAgIGxvY2F0aW9uID0gaW5mby5nZXRfbG9jYXRpb24oKQogICAgICAgIGlmIGxv
Y2F0aW9uIGlzIG5vdCBOb25lOgogICAgICAgICAgICBwYXRoID0gbG9jYXRpb24uZ2V0X3BhdGgo
KQogICAgICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICAgICAgcmV0dXJuIHBhdGgKICAgIGV4
Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwogICAgdHJ5OgogICAgICAgIHVyaSA9IGluZm8u
Z2V0X3VyaSgpCiAgICAgICAgaWYgdXJpIGFuZCB1cmkuc3RhcnRzd2l0aCgiZmlsZTovLyIpOgog
ICAgICAgICAgICByZXR1cm4gdW5xdW90ZSh1cmxwYXJzZSh1cmkpLnBhdGgpCiAgICBleGNlcHQg
RXhjZXB0aW9uOgogICAgICAgIHBhc3MKICAgIHJldHVybiBOb25lCgoKY2xhc3MgS1Rlcm1PcGVu
VGVybWluYWwoR09iamVjdC5HT2JqZWN0LCBOYXV0aWx1cy5NZW51UHJvdmlkZXIpOgogICAgZGVm
IF9sYXVuY2goc2VsZiwgX21lbnUsIHBhdGgpOgogICAgICAgIHRyeToKICAgICAgICAgICAgc3Vi
cHJvY2Vzcy5Qb3BlbigKICAgICAgICAgICAgICAgIFtMQVVOQ0hFUiwgIi0td29ya2luZy1kaXJl
Y3RvcnkiLCBwYXRoXSwKICAgICAgICAgICAgICAgIHN0YXJ0X25ld19zZXNzaW9uPVRydWUsCiAg
ICAgICAgICAgICAgICBjbG9zZV9mZHM9VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgIGV4Y2Vw
dCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICBkZWYgX21ha2VfbWVudShzZWxmLCBw
YXRoKToKICAgICAgICBpZiBub3QgcGF0aCBvciBub3Qgb3MucGF0aC5pc2RpcihwYXRoKSBvciBu
b3Qgb3MucGF0aC5pc2ZpbGUoTEFVTkNIRVIpOgogICAgICAgICAgICByZXR1cm4gW10KICAgICAg
ICBpdGVtID0gTmF1dGlsdXMuTWVudUl0ZW0oCiAgICAgICAgICAgIG5hbWU9IktUZXJtOjpPcGVu
VGVybWluYWwiLAogICAgICAgICAgICBsYWJlbD0iT3BlbiBpbiBUZXJtaW5hbCIsCiAgICAgICAg
ICAgIHRpcD0iT3BlbiB0aGlzIGZvbGRlciB3aXRoIHRoZSBhY3RpdmUgS1RFUk0gVGVybWluYXRv
ciBwcm9maWxlIiwKICAgICAgICAgICAgaWNvbj0idXRpbGl0aWVzLXRlcm1pbmFsIiwKICAgICAg
ICApCiAgICAgICAgaXRlbS5jb25uZWN0KCJhY3RpdmF0ZSIsIHNlbGYuX2xhdW5jaCwgcGF0aCkK
ICAgICAgICByZXR1cm4gW2l0ZW1dCgogICAgIyBWYXJpYWRpYyBhcmd1bWVudHMga2VlcCB0aGUg
ZXh0ZW5zaW9uIGNvbXBhdGlibGUgd2l0aCBOYXV0aWx1cyBBUEkgMy54CiAgICAjICh3aW5kb3cs
IGZpbGVzL2ZvbGRlcikgYW5kIEFQSSA0LnggKGZpbGVzL2ZvbGRlciBvbmx5KS4KICAgIGRlZiBn
ZXRfYmFja2dyb3VuZF9pdGVtcyhzZWxmLCAqYXJncyk6CiAgICAgICAgZm9sZGVyID0gYXJnc1st
MV0gaWYgYXJncyBlbHNlIE5vbmUKICAgICAgICByZXR1cm4gc2VsZi5fbWFrZV9tZW51KF9sb2Nh
bF9wYXRoKGZvbGRlcikpCgogICAgZGVmIGdldF9maWxlX2l0ZW1zKHNlbGYsICphcmdzKToKICAg
ICAgICBmaWxlcyA9IGFyZ3NbLTFdIGlmIGFyZ3MgZWxzZSBbXQogICAgICAgIGlmIG5vdCBmaWxl
cyBvciBsZW4oZmlsZXMpICE9IDE6CiAgICAgICAgICAgIHJldHVybiBbXQogICAgICAgIGluZm8g
PSBmaWxlc1swXQogICAgICAgIHBhdGggPSBfbG9jYWxfcGF0aChpbmZvKQogICAgICAgIGlmIG5v
dCBwYXRoOgogICAgICAgICAgICByZXR1cm4gW10KICAgICAgICB0cnk6CiAgICAgICAgICAgIGlz
X2RpciA9IGluZm8uaXNfZGlyZWN0b3J5KCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg
ICAgICAgICBpc19kaXIgPSBvcy5wYXRoLmlzZGlyKHBhdGgpCiAgICAgICAgcmV0dXJuIHNlbGYu
X21ha2VfbWVudShwYXRoIGlmIGlzX2RpciBlbHNlIHN0cihQYXRoKHBhdGgpLnBhcmVudCkpCg==
KTERM_B64_NAUTILUS

base64 -d > "$APP_DIR/atuin/config.toml" <<'KTERM_B64_ATUIN'
YXV0b19zeW5jID0gZmFsc2UKdXBkYXRlX2NoZWNrID0gZmFsc2UKc2VhcmNoX21vZGUgPSAiZnV6
enkiCmZpbHRlcl9tb2RlID0gImdsb2JhbCIKd29ya3NwYWNlcyA9IHRydWUKc3R5bGUgPSAiY29t
cGFjdCIKaW5saW5lX2hlaWdodCA9IDM1CnNob3dfcHJldmlldyA9IHRydWUKbWF4X3ByZXZpZXdf
aGVpZ2h0ID0gNgpzaG93X2hlbHAgPSB0cnVlCnNob3dfdGFicyA9IHRydWUKZW50ZXJfYWNjZXB0
ID0gZmFsc2UKa2V5bWFwX21vZGUgPSAiYXV0byIK
KTERM_B64_ATUIN
chmod 0700 "$APP_DIR/atuin"
chmod 0600 "$APP_DIR/atuin/config.toml"
chmod 0755 "$BIN_DIR/kpreview" "$BIN_DIR/karthi-dashboard" \
  "$DASH_DIR/system-monitor.sh" "$DASH_DIR/hardware-monitor.sh"
chmod 0644 "$NAUTILUS_EXTENSION"

[[ -e "$STATE_DIR/default-mode" ]] || printf 'modern\n' > "$STATE_DIR/default-mode"
[[ -e "$STATE_DIR/prompt-style" ]] || printf 'rich\n' > "$STATE_DIR/prompt-style"
[[ -e "$STATE_DIR/blocks" ]] || printf 'on\n' > "$STATE_DIR/blocks"
[[ -e "$STATE_DIR/hud" ]] || printf 'on\n' > "$STATE_DIR/hud"

ZSH_PATH="$(command -v zsh)"
cat > "$MODERN_TERMINATOR_CONFIG" <<EOF_MODERN_TERM
[global_config]
  always_split_with_profile = True
  suppress_multiple_term_dialog = True
  title_transmit_bg_color = "#313244"
  title_receive_bg_color = "#45475a"
[keybindings]
[profiles]
  [[default]]
    background_color = "#11111b"
    background_darkness = 1.0
    background_type = solid
    bold_is_bright = True
    copy_on_selection = True
    cursor_blink = True
    cursor_color = "#f5e0dc"
    cursor_shape = ibeam
    font = JetBrainsMono Nerd Font 11
    foreground_color = "#cdd6f4"
    icon_bell = False
    login_shell = False
    palette = "#45475a:#f38ba8:#a6e3a1:#f9e2af:#89b4fa:#f5c2e7:#94e2d5:#bac2de:#585b70:#f38ba8:#a6e3a1:#f9e2af:#89b4fa:#f5c2e7:#94e2d5:#a6adc8"
    scrollbar_position = hidden
    scroll_on_keystroke = True
    scroll_on_output = False
    scrollback_infinite = True
    show_titlebar = False
    use_custom_command = True
    custom_command = env -u KARTHI_HUD_SHOWN -u KARTHI_MODERN_LOADED KARTHI_SHELL_MODE=modern $ZSH_PATH -l
    use_system_font = False
    use_theme_colors = False
    visible_bell = False
  [[modern]]
    background_color = "#11111b"
    background_darkness = 1.0
    background_type = solid
    bold_is_bright = True
    copy_on_selection = True
    cursor_blink = True
    cursor_color = "#f5e0dc"
    cursor_shape = ibeam
    font = JetBrainsMono Nerd Font 11
    foreground_color = "#cdd6f4"
    icon_bell = False
    login_shell = False
    palette = "#45475a:#f38ba8:#a6e3a1:#f9e2af:#89b4fa:#f5c2e7:#94e2d5:#bac2de:#585b70:#f38ba8:#a6e3a1:#f9e2af:#89b4fa:#f5c2e7:#94e2d5:#a6adc8"
    scrollbar_position = hidden
    scroll_on_keystroke = True
    scroll_on_output = False
    scrollback_infinite = True
    show_titlebar = False
    use_custom_command = True
    custom_command = env -u KARTHI_HUD_SHOWN -u KARTHI_MODERN_LOADED KARTHI_SHELL_MODE=modern $ZSH_PATH -l
    use_system_font = False
    use_theme_colors = False
    visible_bell = False
[layouts]
  [[default]]
    [[[window0]]]
      type = Window
      parent = ""
      size = 1200, 760
    [[[terminal1]]]
      type = Terminal
      parent = window0
      profile = modern
[plugins]
EOF_MODERN_TERM
chmod 0600 "$MODERN_TERMINATOR_CONFIG" "$CLASSIC_TERMINATOR_CONFIG"

cat > "$BIN_DIR/terminator-modern" <<EOF_TERM_MODERN
#!/usr/bin/env bash
set -e
command -v terminator >/dev/null 2>&1 || { printf 'Terminator is not installed. Run kterm-repair.\n' >&2; exit 127; }
exec terminator --no-dbus --config "$MODERN_TERMINATOR_CONFIG" --profile modern "\$@"
EOF_TERM_MODERN

cat > "$BIN_DIR/terminator-classic" <<EOF_TERM_CLASSIC
#!/usr/bin/env bash
set -e
command -v terminator >/dev/null 2>&1 || { printf 'Terminator is not installed. Run kterm-repair.\n' >&2; exit 127; }
export KARTHI_SHELL_MODE=classic
unset KARTHI_MODERN_LOADED KARTHI_HUD_SHOWN
exec terminator --no-dbus --config "$CLASSIC_TERMINATOR_CONFIG" "\$@"
EOF_TERM_CLASSIC

cat > "$BIN_DIR/kterm-terminal" <<EOF_KTERM_LAUNCHER
#!/usr/bin/env bash
set -e
mode=modern
[[ -r "$STATE_DIR/default-mode" ]] && IFS= read -r mode < "$STATE_DIR/default-mode"
if [[ "\$mode" == classic ]]; then
  exec "$BIN_DIR/terminator-classic" "\$@"
fi
exec "$BIN_DIR/terminator-modern" "\$@"
EOF_KTERM_LAUNCHER
chmod 0755 "$BIN_DIR/terminator-modern" "$BIN_DIR/terminator-classic" "$BIN_DIR/kterm-terminal"

write_desktop_launchers() {
  mkdir -p "$XDG_DATA_HOME/applications"
  cat > "$XDG_DATA_HOME/applications/kterm-terminal.desktop" <<EOF_KTERM_DESKTOP
[Desktop Entry]
Type=Application
Name=KTERM Futuristic Terminal
Comment=Terminator and Zsh visual developer console
Exec=$BIN_DIR/kterm-terminal
Icon=utilities-terminal
Terminal=false
Categories=System;TerminalEmulator;
StartupNotify=true
EOF_KTERM_DESKTOP
  cat > "$XDG_DATA_HOME/applications/kterm-classic-terminal.desktop" <<EOF_CLASSIC_DESKTOP
[Desktop Entry]
Type=Application
Name=KTERM Classic Terminal
Comment=Saved pre-KTERM Terminator profile
Exec=$BIN_DIR/terminator-classic
Icon=utilities-terminal
Terminal=false
Categories=System;TerminalEmulator;
StartupNotify=true
EOF_CLASSIC_DESKTOP
  chmod 0644 "$XDG_DATA_HOME/applications/kterm-terminal.desktop" \
    "$XDG_DATA_HOME/applications/kterm-classic-terminal.desktop"
  command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$XDG_DATA_HOME/applications" >/dev/null 2>&1 || true
}

configure_xdg_terminal_file() {
  local file="$1" temp
  mkdir -p "$(dirname "$file")"
  touch "$file"
  strip_block "$file" "$XDG_BEGIN" "$XDG_END"
  temp="$(mktemp)"
  {
    printf '%s\n' "$XDG_BEGIN"
    printf 'terminator.desktop\n'
    printf '%s\n' "$XDG_END"
    cat "$file"
  } > "$temp"
  cat "$temp" > "$file"
  rm -f "$temp"
}

configure_gnome_shortcut() {
  gsettings_has_key org.gnome.settings-daemon.plugins.media-keys custom-keybindings || return 0
  if gsettings_has_key org.gnome.settings-daemon.plugins.media-keys terminal && \
     [[ ! -e "$STATE_DIR/gnome-terminal-binding.gvariant" ]]; then
    gsettings get org.gnome.settings-daemon.plugins.media-keys terminal \
      > "$STATE_DIR/gnome-terminal-binding.gvariant" 2>/dev/null || true
  fi

  local path current updated schema
  path='/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/kterm/'
  current="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null || printf '[]')"
  updated="$(python3 - "$current" "$path" <<'PY_GSET_ADD'
import ast, sys
try:
    values = list(ast.literal_eval(sys.argv[1]))
except Exception:
    values = []
if sys.argv[2] not in values:
    values.append(sys.argv[2])
print('[' + ', '.join(repr(item) for item in values) + ']')
PY_GSET_ADD
)"
  gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$updated" 2>/dev/null || return 0
  schema="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$path"
  gsettings set "$schema" name 'KTERM Futuristic Terminal' 2>/dev/null || true
  gsettings set "$schema" command "$BIN_DIR/kterm-terminal" 2>/dev/null || true
  gsettings set "$schema" binding '<Primary><Alt>t' 2>/dev/null || true
  if gsettings_has_key org.gnome.settings-daemon.plugins.media-keys terminal; then
    gsettings set org.gnome.settings-daemon.plugins.media-keys terminal '[]' 2>/dev/null || true
  fi
  ok "Configured GNOME Ctrl+Alt+T"
}

configure_old_gnome_default() {
  if gsettings_has_key org.gnome.desktop.default-applications.terminal exec; then
    if [[ ! -e "$STATE_DIR/gnome-default-terminal-exec.gvariant" ]]; then
      gsettings get org.gnome.desktop.default-applications.terminal exec > "$STATE_DIR/gnome-default-terminal-exec.gvariant" 2>/dev/null || true
    fi
    gsettings set org.gnome.desktop.default-applications.terminal exec 'terminator' 2>/dev/null || true
  fi
  if gsettings_has_key org.gnome.desktop.default-applications.terminal exec-arg; then
    if [[ ! -e "$STATE_DIR/gnome-default-terminal-exec-arg.gvariant" ]]; then
      gsettings get org.gnome.desktop.default-applications.terminal exec-arg > "$STATE_DIR/gnome-default-terminal-exec-arg.gvariant" 2>/dev/null || true
    fi
    gsettings set org.gnome.desktop.default-applications.terminal exec-arg '-x' 2>/dev/null || true
  fi
}

validate_nautilus_extension() {
  python3 - "$NAUTILUS_EXTENSION" <<'PY_NAUTILUS_CHECK'
from pathlib import Path
import runpy
import sys
path = Path(sys.argv[1])
source = path.read_text(encoding='utf-8')
compile(source, str(path), 'exec')
runpy.run_path(str(path), run_name='kterm_nautilus_validation')
PY_NAUTILUS_CHECK
}

configure_nautilus() {
  command -v nautilus >/dev/null 2>&1 || return 0
  python3 -c 'import gi' >/dev/null 2>&1 || { warn "PyGObject unavailable; skipping Nautilus context-menu integration."; return 0; }
  if ! validate_nautilus_extension >/dev/null 2>&1; then
    warn "Nautilus extension validation failed; keeping the native provider."
    return 0
  fi

  local pkg
  for pkg in nautilus-extension-gnome-terminal nautilus-extension-gnome-console; do
    if package_installed "$pkg"; then
      touch "$STATE_DIR/had-$pkg"
      if ! sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y "$pkg"; then
        warn "Could not remove competing Nautilus provider: $pkg"
      fi
    fi
  done
  nautilus -q >/dev/null 2>&1 || true
  ok "Installed a Nautilus API 3/4-compatible Open in Terminal extension"
}

configure_pcmanfm_action() {
  command -v pcmanfm >/dev/null 2>&1 || command -v pcmanfm-qt >/dev/null 2>&1 || return 0
  mkdir -p "$(dirname "$PCMANFM_ACTION")"
  cat > "$PCMANFM_ACTION" <<EOF_PCMANFM
[Desktop Entry]
Type=Action
Name=Open in KTERM
Icon=utilities-terminal
Profiles=profile-zero;

[X-Action-Profile profile-zero]
MimeTypes=inode/directory;
Exec=$BIN_DIR/kterm-terminal --working-directory %f
Name=Open in KTERM
EOF_PCMANFM
  chmod 0644 "$PCMANFM_ACTION"
  ok "Installed PCManFM directory action"
}

patch_keybind_xml() {
  local file="$1" flavor="$2" launcher="$3"
  python3 - "$file" "$flavor" "$launcher" <<'PY_XML_BIND'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

path = Path(sys.argv[1])
flavor = sys.argv[2]
launcher = sys.argv[3]

tree = ET.parse(path)
root = tree.getroot()
namespace = ''
if root.tag.startswith('{'):
    namespace = root.tag.split('}', 1)[0] + '}'
    ET.register_namespace('', namespace[1:-1])

def local(tag):
    return tag.split('}', 1)[-1]

def tag(name):
    return namespace + name

keyboard = next((node for node in root.iter() if local(node.tag) == 'keyboard'), None)
if keyboard is None:
    keyboard = ET.SubElement(root, tag('keyboard'))

for child in list(keyboard):
    if local(child.tag) == 'keybind' and child.attrib.get('key') in {'C-A-t', 'A-C-t'}:
        keyboard.remove(child)

keybind = ET.SubElement(keyboard, tag('keybind'), {'key': 'C-A-t'})
action = ET.SubElement(keybind, tag('action'), {'name': 'Execute'})
if flavor == 'labwc':
    action.set('command', launcher)
else:
    command = ET.SubElement(action, tag('command'))
    command.text = launcher

try:
    ET.indent(tree, space='  ')
except AttributeError:
    pass
tree.write(path, encoding='UTF-8', xml_declaration=True)
PY_XML_BIND
}

configure_labwc() {
  [[ "$KTERM_TARGET" == raspberry-pi ]] || return 0
  command -v labwc >/dev/null 2>&1 || [[ -r /etc/xdg/labwc/rc.xml ]] || return 0
  local file="$XDG_CONFIG_HOME/labwc/rc.xml"
  mkdir -p "$(dirname "$file")"
  if [[ ! -e "$STATE_DIR/labwc-rc.original" && ! -e "$STATE_DIR/labwc-created" ]]; then
    if [[ -r "$file" ]]; then
      cp -a "$file" "$STATE_DIR/labwc-rc.original"
    elif [[ -r /etc/xdg/labwc/rc.xml ]]; then
      cp -a /etc/xdg/labwc/rc.xml "$file"
      touch "$STATE_DIR/labwc-created"
    else
      cat > "$file" <<'EOF_LABWC'
<?xml version="1.0"?>
<labwc_config><keyboard><default /></keyboard></labwc_config>
EOF_LABWC
      touch "$STATE_DIR/labwc-created"
    fi
  fi
  patch_keybind_xml "$file" labwc "$BIN_DIR/kterm-terminal"
  command -v labwc >/dev/null 2>&1 && labwc -r >/dev/null 2>&1 || true
  ok "Configured Labwc Ctrl+Alt+T"
}

configure_openbox() {
  [[ "$KTERM_TARGET" == raspberry-pi ]] || return 0
  local file="" candidate user_config_existed=0
  for candidate in \
    "$XDG_CONFIG_HOME/openbox/lxde-pi-rc.xml" \
    "$XDG_CONFIG_HOME/openbox/lxde-rc.xml" \
    "$XDG_CONFIG_HOME/openbox/rc.xml"; do
    if [[ -r "$candidate" ]]; then
      file="$candidate"
      user_config_existed=1
      break
    fi
  done
  if [[ -z "$file" ]] && command -v openbox >/dev/null 2>&1; then
    file="$XDG_CONFIG_HOME/openbox/lxde-pi-rc.xml"
    mkdir -p "$(dirname "$file")"
    if [[ -r /etc/xdg/openbox/lxde-pi-rc.xml ]]; then
      cp -a /etc/xdg/openbox/lxde-pi-rc.xml "$file"
    elif [[ -r /etc/xdg/openbox/rc.xml ]]; then
      cp -a /etc/xdg/openbox/rc.xml "$file"
    else
      cat > "$file" <<'EOF_OPENBOX'
<?xml version="1.0"?>
<openbox_config xmlns="http://openbox.org/3.4/rc"><keyboard /></openbox_config>
EOF_OPENBOX
    fi
  fi
  [[ -n "$file" && -r "$file" ]] || return 0
  if [[ ! -e "$STATE_DIR/openbox-rc.path" ]]; then
    printf '%s\n' "$file" > "$STATE_DIR/openbox-rc.path"
    if [[ "$user_config_existed" -eq 1 ]]; then
      cp -a "$file" "$STATE_DIR/openbox-rc.original"
    else
      touch "$STATE_DIR/openbox-created"
    fi
  fi
  patch_keybind_xml "$file" openbox "$BIN_DIR/kterm-terminal"
  command -v openbox >/dev/null 2>&1 && openbox --reconfigure >/dev/null 2>&1 || true
  ok "Configured Openbox Ctrl+Alt+T"
}

configure_desktop_integration() {
  [[ "$DESKTOP_ENABLED" == on ]] || return 0
  write_desktop_launchers
  mkdir -p "$(dirname "$TERMINATOR_CONFIG")"
  cp -f "$MODERN_TERMINATOR_CONFIG" "$TERMINATOR_CONFIG"
  chmod 0600 "$TERMINATOR_CONFIG"

  local terminator_path
  terminator_path="$(command -v terminator)"
  if command -v update-alternatives >/dev/null 2>&1; then
    if sudo update-alternatives --list x-terminal-emulator 2>/dev/null | grep -Fxq "$terminator_path"; then
      sudo update-alternatives --set x-terminal-emulator "$terminator_path" >/dev/null 2>&1 || true
    fi
  fi

  configure_xdg_terminal_file "$XDG_CONFIG_HOME/xdg-terminals.list"
  configure_xdg_terminal_file "$XDG_CONFIG_HOME/ubuntu-xdg-terminals.list"
  configure_xdg_terminal_file "$XDG_CONFIG_HOME/gnome-xdg-terminals.list"
  configure_gnome_shortcut
  configure_old_gnome_default
  configure_nautilus
  configure_pcmanfm_action
  configure_labwc
  configure_openbox
}

configure_desktop_integration

info "Installing the reversible Zsh loader"
strip_block "$ZSHRC" "$LOADER_BEGIN" "$LOADER_END"
cat >> "$ZSHRC" <<EOF_ZSH_LOADER

$LOADER_BEGIN
# Existing ~/.zshrc configuration runs first. KTERM augments it afterwards.
export PATH="\$HOME/.local/bin:\$PATH"
export KARTHI_SHELL_HOME="\${XDG_CONFIG_HOME:-\$HOME/.config}/karthi-shell"
if [[ -r "\$KARTHI_SHELL_HOME/switcher.zsh" ]]; then
  source "\$KARTHI_SHELL_HOME/switcher.zsh"
fi
_kterm_loader_mode="\${KARTHI_SHELL_MODE:-}"
if [[ -z "\$_kterm_loader_mode" && -r "\$KARTHI_SHELL_HOME/state/default-mode" ]]; then
  IFS= read -r _kterm_loader_mode < "\$KARTHI_SHELL_HOME/state/default-mode"
fi
_kterm_loader_mode="\${_kterm_loader_mode:-modern}"
if [[ "\$_kterm_loader_mode" == modern && -r "\$KARTHI_SHELL_HOME/modern.zsh" ]]; then
  source "\$KARTHI_SHELL_HOME/modern.zsh"
else
  export KARTHI_SHELL_MODE=classic
fi
unset _kterm_loader_mode
$LOADER_END
EOF_ZSH_LOADER

if [[ "$CHANGE_SHELL" -eq 1 ]]; then
  if ! grep -Fxq "$ZSH_PATH" /etc/shells; then
    printf '%s\n' "$ZSH_PATH" | sudo tee -a /etc/shells >/dev/null
  fi
  current_login_shell="$(getent passwd "$USER" | awk -F: '{print $7}')"
  if [[ "$current_login_shell" != "$ZSH_PATH" ]]; then
    sudo chsh -s "$ZSH_PATH" "$USER"
    ok "Set Zsh as the account login shell"
  fi
fi

if [[ -r "$SCRIPT_SOURCE" ]]; then
  cp -f "$SCRIPT_SOURCE" "$APP_DIR/install-kterm.sh"
  chmod 0755 "$APP_DIR/install-kterm.sh"
else
  warn "Could not save a reusable installer copy; kterm-update will need the original script."
fi

info "Validating the generated setup"
bash -n "$BIN_DIR/kpreview"
bash -n "$BIN_DIR/karthi-dashboard"
bash -n "$DASH_DIR/system-monitor.sh"
bash -n "$DASH_DIR/hardware-monitor.sh"
zsh -n "$APP_DIR/switcher.zsh"
zsh -n "$APP_DIR/modern.zsh"
python3 - "$NAUTILUS_EXTENSION" <<'PY_FINAL_COMPILE'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text(encoding='utf-8')
compile(source, sys.argv[1], 'exec')
PY_FINAL_COMPILE

grep -Eq 'always_split_with_profile[[:space:]]*=[[:space:]]*True' "$MODERN_TERMINATOR_CONFIG" || \
  die "Uniform Terminator split setting was not written."
grep -q '^  \[\[default\]\]' "$MODERN_TERMINATOR_CONFIG" || die "Modern default profile missing."
grep -q '^  \[\[modern\]\]' "$MODERN_TERMINATOR_CONFIG" || die "Modern named profile missing."
if command -v starship >/dev/null 2>&1; then
  STARSHIP_CONFIG="$APP_DIR/starship-rich.toml" starship prompt >/dev/null 2>&1 || \
    warn "Starship could not render the rich prompt during validation."
fi

# Remove a stale dashboard session so the next launch uses the new layout.
tmux kill-session -t karthi-dashboard 2>/dev/null || true

printf '\n\033[1;32mKTERM v%s installation is complete.\033[0m\n' "$KTERM_VERSION"
printf 'Log     : %s\n' "$LOG_FILE"
printf 'Backups : %s\n' "$BACKUP_DIR"
printf '\nNext steps:\n'
printf '  1. Close all Terminator windows and log out/in once.\n'
printf '  2. Open Ctrl+Alt+T and run: kterm-doctor\n'
printf '  3. Test split colors: Ctrl+Shift+E and Ctrl+Shift+O\n'
printf '  4. Test the workstation view: kdashboard --reset\n'
printf '\nClassic recovery remains available with:\n'
printf '  kterm-system classic\n  kterm-classic\n'
