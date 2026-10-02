"""Adaptive Link - the machine itself, and the desktop's own features.

What the phone's Tasks, Devices, Network and Desktop screens show and do:

  tasks     what is running, how busy the machine is, and stopping a process
  devices   what is plugged in over USB, and the drives
  network   how the machine is connected, and how much is going through
  desktop   the things Adaptive Desktop adds - projects, focus, window
            placement, quick notes - through the same command-line tools the
            desktop's own keys and palette use (scripts/*-cli.py)

Everything here is read with the owner's own permissions: a process can be
stopped only if it is the owner's, exactly as in a terminal.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("ADAPTIVE_REPO", Path(__file__).resolve().parent.parent.parent))
SCRIPTS = REPO / "scripts"
USB_ROOT = Path("/sys/bus/usb/devices")

USB_CLASSES = {
    "01": "Audio", "02": "Communications", "03": "Keyboard or mouse", "05": "Physical",
    "06": "Camera or scanner", "07": "Printer", "08": "Storage", "09": "Hub", "0a": "Data",
    "0b": "Smart card", "0e": "Camera", "e0": "Wireless", "ef": "Composite", "ff": "Other",
}
SIGNALS = {"stop": signal.SIGTERM, "kill": signal.SIGKILL, "pause": signal.SIGSTOP, "resume": signal.SIGCONT}
PROCESS_LIMIT = 80


# ------------------------------------------------------------------- tasks

def summary():
    """How busy the machine is, in a few numbers."""
    memory = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                memory[key] = int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    disks = []
    for mount in dict.fromkeys(("/", str(Path.home()))):
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        if not any(d["total"] == usage.total and d["free"] == usage.free for d in disks):
            disks.append({"mount": mount, "total": usage.total, "free": usage.free})
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        uptime = 0
    return {
        "load": [round(value, 2) for value in os.getloadavg()],
        "cpus": os.cpu_count() or 1,
        "memory": {"total": memory.get("MemTotal", 0), "available": memory.get("MemAvailable", 0),
                   "swap_total": memory.get("SwapTotal", 0), "swap_free": memory.get("SwapFree", 0)},
        "disks": disks,
        "uptime": int(uptime),
    }


def processes(sort="cpu", query=""):
    """The busiest processes, or the ones matching a word."""
    order = "-rss" if sort == "memory" else "-pcpu"
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid=,user:20=,pcpu=,pmem=,rss=,etimes=,comm:32=,args=", f"--sort={order}"],
            capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    me = _user()
    wanted = query.strip().lower()
    found = []
    for line in out.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 7:
            continue
        try:
            entry = {"pid": int(parts[0]), "user": parts[1], "cpu": float(parts[2]), "memory": float(parts[3]),
                     "rss": int(parts[4]) * 1024, "elapsed": int(parts[5]), "name": parts[6],
                     "command": (parts[7] if len(parts) > 7 else parts[6])[:300]}
        except ValueError:
            continue
        if entry["pid"] == os.getpid() or entry["name"] == "ps":
            continue
        if wanted and wanted not in entry["command"].lower() and wanted != str(entry["pid"]):
            continue
        entry["mine"] = entry["user"] == me
        found.append(entry)
        if len(found) >= PROCESS_LIMIT:
            break
    return found


def _user():
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name


def signal_process(pid, action):
    """Stop, kill, pause or resume one of the owner's processes.
    Returns (done, why not)."""
    if action not in SIGNALS:
        return False, "unknown action"
    if not isinstance(pid, int) or pid <= 1:
        return False, "not a process"
    if pid in (os.getpid(), os.getppid()):
        return False, "that is Adaptive Link itself; turn it off from the computer"
    try:
        os.kill(pid, SIGNALS[action])
    except ProcessLookupError:
        return False, "it has already ended"
    except PermissionError:
        return False, "it belongs to another user or to the system"
    return True, ""


# ----------------------------------------------------------------- devices

def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _usb_kind(device):
    """What a device is, from its own class or from what its parts are."""
    classes = [_read(device / "bDeviceClass")]
    classes += [_read(part / "bInterfaceClass") for part in sorted(device.glob(f"{device.name}:*"))]
    for code in classes:
        if code and code not in ("00", "ef") and code in USB_CLASSES:
            return USB_CLASSES[code]
    return "Device"


def _usb_names():
    """What lsusb calls each device, for the ones that do not name themselves."""
    try:
        out = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    names = {}
    for line in out.splitlines():
        match = re.search(r"ID ([0-9a-f]{4}:[0-9a-f]{4})\s+(.+)$", line)
        if match and match.group(2).strip():
            names[match.group(1)] = match.group(2).strip()
    return names


def usb_devices(root=USB_ROOT):
    """What is plugged in over USB (and built in, like a webcam): no hubs."""
    found = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found
    named = _usb_names() if root == USB_ROOT else {}
    for device in entries:
        if ":" in device.name or not (device / "idVendor").exists():
            continue
        if _read(device / "bDeviceClass") == "09":
            continue   # hubs and the machine's own ports
        vendor, product = _read(device / "idVendor"), _read(device / "idProduct")
        speed = _read(device / "speed")
        found.append({
            "name": _read(device / "product") or named.get(f"{vendor}:{product}") or f"USB device {vendor}:{product}",
            "maker": _read(device / "manufacturer"),
            "id": f"{vendor}:{product}",
            "kind": _usb_kind(device),
            "speed": f"{speed} Mb/s" if speed else "",
            "port": device.name,
        })
    return found


def drives():
    """The disks and what is mounted from them. Removable ones are marked."""
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,LABEL,SIZE,TYPE,MOUNTPOINT,RM,HOTPLUG,TRAN,MODEL,FSTYPE"],
            capture_output=True, text=True, timeout=10, check=False).stdout
        tree = json.loads(out).get("blockdevices", [])
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    found = []

    def walk(node, parent):
        if node.get("type") in ("loop", "rom") and not node.get("mountpoint"):
            return
        if node.get("type") == "loop":
            return
        removable = any(bool(item.get(key)) for item in (node, parent or {}) for key in ("rm", "hotplug")) \
            or (parent or node).get("tran") == "usb"
        children = node.get("children") or []
        if node.get("type") in ("part", "crypt", "lvm") or not children:
            mount = node.get("mountpoint") or ""
            if mount.startswith(("/boot", "/snap", "[SWAP]")):
                return
            entry = {"name": node.get("label") or (parent or node).get("model") or node.get("name") or "",
                     "device": "/dev/" + str(node.get("name")), "size": int(node.get("size") or 0),
                     "mount": mount, "removable": removable, "format": node.get("fstype") or "",
                     "over": (parent or node).get("tran") or ""}
            if mount:
                try:
                    entry["free"] = shutil.disk_usage(mount).free
                except OSError:
                    pass
            found.append(entry)
        for child in children:
            walk(child, node if node.get("type") == "disk" else parent)

    for device in tree:
        walk(device, None)
    return found


# ----------------------------------------------------------------- network

NET_ROOT = Path("/sys/class/net")


def _json_from(*command):
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def _wifi():
    """The Wi-Fi network in use, as NetworkManager knows it."""
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SIGNAL,FREQ,RATE,SECURITY,SSID", "dev", "wifi", "list", "--rescan", "no"],
            capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        # The name comes last because it is the one part that may hold a colon.
        parts = line.split(":", 5)
        if len(parts) == 6 and parts[0] == "yes":
            return {"name": parts[5].replace("\\:", ":"), "signal": int(parts[1]) if parts[1].isdigit() else 0,
                    "frequency": parts[2], "rate": parts[3], "security": parts[4]}
    return None


def _dns():
    servers = []
    try:
        out = subprocess.run(["resolvectl", "dns"], capture_output=True, text=True, timeout=5, check=False).stdout
        for line in out.splitlines():
            servers += line.partition(":")[2].split()
    except (OSError, subprocess.SubprocessError):
        pass
    if not servers:
        for line in _read(Path("/etc/resolv.conf")).splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "nameserver":
                servers.append(parts[1])
    return list(dict.fromkeys(servers))[:6]


def _net_kind(name, root):
    if (root / name / "wireless").exists():
        return "Wi-Fi"
    if (root / name / "device").exists():
        return "Ethernet"
    if name.startswith(("tun", "tap", "wg", "tailscale", "ppp", "vpn")):
        return "VPN"
    return "Virtual"


def _count(path):
    text = _read(path)
    return int(text) if text.isdigit() else 0


def network(root=NET_ROOT):
    """How the machine is connected: each interface with its addresses and
    how much it has carried. The phone works the speed out from two readings,
    so `time` says when this one was taken."""
    gateways = {route.get("dev"): route.get("gateway", "") for route in reversed(_json_from("ip", "-j", "route", "show", "default"))}
    wifi = _wifi()
    found = []
    for link in _json_from("ip", "-j", "addr"):
        name = link.get("ifname", "")
        if not name or link.get("link_type") == "loopback":
            continue
        kind = _net_kind(name, root)
        addresses = [f"{a.get('local')}/{a.get('prefixlen')}" for a in link.get("addr_info", [])
                     if a.get("local") and a.get("scope") != "link"]
        up = "LOWER_UP" in link.get("flags", [])
        if kind in ("VPN", "Virtual") and not (up and addresses):
            continue   # bridges and tunnels nothing is using
        speed = _count(root / name / "speed") if kind == "Ethernet" and up else 0
        entry = {
            "name": name, "kind": kind, "up": up, "addresses": addresses,
            "mac": link.get("address", "") if kind in ("Wi-Fi", "Ethernet") else "",
            "gateway": gateways.get(name, ""), "default": name in gateways,
            "speed": f"{speed} Mb/s" if speed else "",
            "received": _count(root / name / "statistics/rx_bytes"),
            "sent": _count(root / name / "statistics/tx_bytes"),
        }
        if kind == "Wi-Fi" and up and wifi:
            entry["wifi"] = wifi
        found.append(entry)
    # The one the machine reaches the internet through first, then the rest that are up.
    found.sort(key=lambda entry: (not entry["default"], not entry["up"], entry["name"]))
    return {"interfaces": found, "dns": _dns(), "time": round(time.monotonic(), 3)}


# ----------------------------------------------------------------- desktop

def _cli(name, *args, timeout=15):
    """Run one of the desktop's command-line tools. Returns (ok, its words)."""
    try:
        done = subprocess.run([sys.executable, str(SCRIPTS / name), *args],
                              capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    text = (done.stdout + done.stderr).strip()
    if done.returncode != 0 and "Traceback" in text:
        # The tool itself failed: its last line says why, the rest is noise.
        text = text.splitlines()[-1]
    return done.returncode == 0, text[-4000:]


PROJECT_LINE = re.compile(r"^(\*| ) (.+) \[([0-9a-f]+)\] -> (.+)$")


def projects():
    ok, text = _cli("project-cli.py", "list")
    found = []
    if ok:
        for line in text.splitlines():
            match = PROJECT_LINE.match(line)
            if match:
                found.append({"active": match.group(1) == "*", "name": match.group(2),
                              "id": match.group(3), "path": match.group(4)})
    return found


def desktop_state():
    """What the Desktop screen opens with."""
    _ok, focus = _cli("focus-cli.py", "status")
    _ok, appearance = _cli("appearance-cli.py", "status")
    return {
        "projects": projects(),
        "focus": "on" in focus.lower().split(":")[-1],
        "dark": "dark" in appearance.lower().split("color-scheme")[-1],
    }


# What the phone may ask for, and the command each one is. The value, where
# there is one, is checked against what that command accepts.
TILES = ("left", "right", "center", "maximize", "smart")
REPORTS = {"git": ("project-cli.py", "git"), "time": ("project-cli.py", "time"),
           "tasks": ("project-cli.py", "tasks"), "session": ("session-cli.py", "status"),
           "monitors": ("window-cli.py", "monitors")}
LAUNCHERS = {"palette": "adaptive-command-launch.sh", "projects": "adaptive-projects-launch.sh",
             "settings": "adaptive-settings-launch.sh"}


def desktop_report(name):
    if name not in REPORTS:
        return False, "unknown report"
    script, *args = REPORTS[name]
    return _cli(script, *args, timeout=30)


def desktop_action(action, value=""):
    """Do one thing on the desktop. Returns (done, what it said)."""
    value = value if isinstance(value, str) else ""
    if action == "project":
        if not any(value == p["id"] for p in projects()):
            return False, "no such project"
        return _cli("project-cli.py", "switch", value)
    if action == "project-clear":
        return _cli("project-cli.py", "clear")
    if action == "focus":
        if value in ("on", "off"):
            return _cli("focus-cli.py", value)
        if value.isdigit() and 1 <= int(value) <= 600:
            return _cli("focus-cli.py", "timer", value)
        return False, "focus is on, off, or a number of minutes"
    if action == "tile":
        return _cli("window-cli.py", "tile", value) if value in TILES else (False, "unknown placement")
    if action == "fullscreen":
        return _cli("window-cli.py", "fullscreen")
    if action == "scheme":
        return _cli("appearance-cli.py", "scheme", value) if value in ("dark", "light") else (False, "dark or light")
    if action == "session-save":
        return _cli("session-cli.py", "save", timeout=30)
    if action == "task-done":
        return _cli("project-cli.py", "tasks", "--done", value) if value.isdigit() else (False, "which task?")
    if action == "note":
        return note(value)
    if action == "open":
        script = LAUNCHERS.get(value)
        if not script:
            return False, "unknown window"
        try:
            subprocess.Popen([str(SCRIPTS / script)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as error:
            return False, str(error)
        return True, ""
    return False, "unknown action"


def note(text):
    """A line into the active project's inbox, as the quick-note key does."""
    text = " ".join((text or "").split())[:2000]
    if not text:
        return False, "nothing to note"
    active = next((p["name"] for p in projects() if p["active"]), "")
    safe = re.sub(r"[^\w.-]", "_", active or "General")
    path = Path.home() / ".local/share/adaptive-desktop/notes" / safe / "Inbox.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = "" if path.exists() else f"# {path.parent.name} inbox\n\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(header + f"- {time.strftime('%Y-%m-%d %H:%M')}  {text}\n")
    except OSError as error:
        return False, str(error)
    return True, f"Noted in {active or 'General'}"
