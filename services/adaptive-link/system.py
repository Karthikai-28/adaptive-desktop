"""Adaptive Link - the machine itself, and the desktop's own features.

What the phone's Tasks, Devices, Network and Desktop screens show and do:

  tasks     what is running, how busy the machine is, and stopping a process
            or making it less important
  devices   what is plugged in over USB, and the drives: mounting, unmounting
            and safely removing a drive, switching a USB device off and on
  network   how the machine is connected and how much is going through;
            Wi-Fi on and off, joining a network, connecting and disconnecting
  desktop   the things Adaptive Desktop adds - projects, focus, window
            placement, quick notes - through the same command-line tools the
            desktop's own keys and palette use (scripts/*-cli.py)

Everything here is done with the owner's own permissions: a process can be
stopped only if it is the owner's, exactly as in a terminal, and the network
and the drives are changed through NetworkManager and UDisks, which allow the
person at the computer what they would allow from its own settings.

A change that could cut the phone off from the computer - turning Wi-Fi off,
leaving a network, switching a USB device off - comes back with how to undo
it. The daemon undoes it unless the phone says, over the link, that it can
still reach the computer (server.py, /v1/keep).
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
PRIORITIES = {"normal": 0, "low": 10, "lowest": 19}
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
            ["ps", "-eo", "pid=,user:20=,pcpu=,pmem=,rss=,etimes=,ni=,s=,comm:32=,args=", f"--sort={order}"],
            capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    me = _user()
    wanted = query.strip().lower()
    found = []
    for line in out.splitlines():
        parts = line.split(None, 9)
        if len(parts) < 9:
            continue
        try:
            entry = {"pid": int(parts[0]), "user": parts[1], "cpu": float(parts[2]), "memory": float(parts[3]),
                     "rss": int(parts[4]) * 1024, "elapsed": int(parts[5]),
                     "nice": int(parts[6]) if parts[6].lstrip("-").isdigit() else 0,   # "-" for a realtime one
                     "paused": parts[7] in ("T", "t"), "name": parts[8],
                     "command": (parts[9] if len(parts) > 9 else parts[8])[:300]}
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


def _started_by(pid):
    """The processes a process started, and the ones those started."""
    try:
        out = subprocess.run(["ps", "-eo", "pid=,ppid="], capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    children = {}
    for line in out.split("\n"):
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, queue = [], [pid]
    while queue:
        for child in children.get(queue.pop(), []):
            if child not in found:
                found.append(child)
                queue.append(child)
    return found


def signal_process(pid, action, tree=False):
    """Stop, kill, pause or resume one of the owner's processes, or change
    how important it is; with `tree`, the processes it started as well.
    Returns (done, why not)."""
    if action not in SIGNALS and action not in PRIORITIES:
        return False, "unknown action"
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return False, "not a process"
    ours = (os.getpid(), os.getppid())
    if pid in ours:
        return False, "that is Adaptive Link itself; turn it off from the computer"

    def one(target):
        if action in SIGNALS:
            os.kill(target, SIGNALS[action])
        else:
            os.setpriority(os.PRIO_PROCESS, target, PRIORITIES[action])

    # The ones it started first, so that none is left behind without it.
    for child in reversed(_started_by(pid)) if tree else ():
        if child not in ours:
            try:
                one(child)
            except OSError:
                pass   # ended in the meantime, or not the owner's
    try:
        one(pid)
    except ProcessLookupError:
        return False, "it has already ended"
    except PermissionError:
        if action in PRIORITIES and _owner(pid) == os.getuid():
            return False, "only the system can make a process more important again"
        return False, "it belongs to another user or to the system"
    return True, ""


def _owner(pid):
    try:
        return os.stat(f"/proc/{pid}").st_uid
    except OSError:
        return -1


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
        switch = device / "authorized"
        found.append({
            "on": _read(switch) != "0",
            # The switch is the system's unless install-link-usb.sh handed it to the owner.
            "switchable": os.access(switch, os.W_OK),
            "name": _read(device / "product") or named.get(f"{vendor}:{product}") or f"USB device {vendor}:{product}",
            "maker": _read(device / "manufacturer"),
            "id": f"{vendor}:{product}",
            "kind": _usb_kind(device),
            "speed": f"{speed} Mb/s" if speed else "",
            "port": device.name,
        })
    return found


def usb_switch(port, on, root=USB_ROOT):
    """Switch a USB device off (as if unplugged) or on again.
    Returns (done, what to say, how to undo it)."""
    if not any(device["port"] == port for device in usb_devices(root)):
        return False, "no such device", None
    try:
        (root / port / "authorized").write_text("1" if on else "0")
    except PermissionError:
        return False, "the computer has not been set up for this: run scripts/install-link-usb.sh on it once", None
    except OSError as error:
        return False, str(error), None
    return True, "", None if on else ("usb", port)


def _system_mount(mount):
    """A place the system or the owner's own files live: never unmounted from the phone."""
    if not mount:
        return False
    if mount == "/" or mount.startswith(("/boot", "/usr", "/var", "/etc", "/snap")):
        return True
    return any(str(place).startswith(mount.rstrip("/") + "/") or str(place) == mount
               for place in (Path.home(), REPO))


def _udisks(*args):
    try:
        done = subprocess.run(["udisksctl", *args, "--no-user-interaction"],
                              capture_output=True, text=True, timeout=40, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    text = (done.stdout + done.stderr).strip()
    # "Error unmounting /dev/sdb1: GDBus.Error:...: target is busy" - the last part is the reason.
    return done.returncode == 0, text.rsplit(": ", 1)[-1][:300]


def drive_action(device, action):
    """Mount or unmount a drive, or make a removable one safe to pull out.
    Returns (done, what to say)."""
    known = drives()
    drive = next((d for d in known if d["device"] == device), None)
    if drive is None:
        return False, "no such drive"
    if action == "mount":
        if drive["mount"]:
            return True, f"Already at {drive['mount']}"
        done, text = _udisks("mount", "-b", device)
        return done, (f"Mounted at {text.rsplit(' at ', 1)[-1].rstrip('.')}" if done and " at " in text else text)
    if action == "unmount":
        if not drive["mount"]:
            return True, "It is not mounted"
        if _system_mount(drive["mount"]):
            return False, "the computer is running from that drive"
        done, text = _udisks("unmount", "-b", device)
        return done, ("Unmounted" if done else text)
    if action == "eject":
        if not drive["removable"]:
            return False, "that drive is built in"
        parts = [d for d in known if d["disk"] == drive["disk"]]
        if any(_system_mount(part["mount"]) for part in parts):
            return False, "the computer is running from that drive"
        for part in parts:
            if part["mount"]:
                done, text = _udisks("unmount", "-b", part["device"])
                if not done:
                    return False, text
        done, text = _udisks("power-off", "-b", drive["disk"])
        return done, ("It is safe to pull out" if done else text)
    return False, "unknown action"


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
                     "disk": "/dev/" + str((parent or node).get("name")),
                     "mount": mount, "removable": removable, "format": node.get("fstype") or "",
                     "system": _system_mount(mount),
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
WIFI_LIMIT = 30


def _json_from(*command):
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def _nmcli(*args, wait=0, feed=None):
    """Ask NetworkManager. Returns (ok, its words)."""
    command = ["nmcli", *(("--wait", str(wait)) if wait else ()), *args]
    try:
        done = subprocess.run(command, capture_output=True, text=True, input=feed,
                              timeout=wait + 10 if wait else 8, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return done.returncode == 0, (done.stdout if done.returncode == 0 else done.stderr or done.stdout).strip()


def _fields(line):
    """One line of nmcli's terse output: fields apart at ':', which a name
    that holds one has as '\\:'."""
    return [part.replace("\\:", ":").replace("\\\\", "\\") for part in re.split(r"(?<!\\):", line)]


def _rows(*args, width):
    ok, out = _nmcli("-t", *args)
    return [row for row in map(_fields, out.splitlines()) if len(row) == width] if ok else []


def _saved():
    """The connections NetworkManager remembers: (name, kind, in use)."""
    return _rows("-f", "NAME,TYPE,ACTIVE", "con", "show", width=3)


def wifi_networks(saved=None):
    """The Wi-Fi networks in range, strongest first, one line per name."""
    known = {name for name, kind, _active in (_saved() if saved is None else saved) if kind == "802-11-wireless"}
    best = {}
    for used, name, strength, frequency, rate, security in _rows(
            "-f", "IN-USE,SSID,SIGNAL,FREQ,RATE,SECURITY", "dev", "wifi", "list", "--rescan", "no", width=6):
        if not name:
            continue   # a hidden one has no name to join it by
        entry = {"name": name, "signal": int(strength) if strength.isdigit() else 0, "frequency": frequency,
                 "rate": rate, "security": "" if security in ("", "--") else security,
                 "active": used.strip() == "*", "known": name in known}
        kept = best.get(name)
        if kept is None or (entry["active"], entry["signal"]) > (kept["active"], kept["signal"]):
            best[name] = entry
    return sorted(best.values(), key=lambda n: (not n["active"], -n["signal"], n["name"]))[:WIFI_LIMIT]


def _nm_devices():
    """What NetworkManager says of each interface it looks after."""
    return {device: {"state": state.split(" ")[0], "connection": connection}
            for device, state, connection in _rows("-f", "DEVICE,STATE,CONNECTION", "dev", width=3)
            if state != "unmanaged"}


def _tunnels(saved=None):
    """The saved VPNs, which can be brought up and down."""
    return [{"name": name, "kind": "WireGuard" if kind == "wireguard" else "VPN", "active": active == "yes"}
            for name, kind, active in (_saved() if saved is None else saved) if kind in ("vpn", "wireguard")]


def network_action(action, value="", secret=""):
    """Change how the machine is connected.
    Returns (done, what to say, how to undo it): the last is None where the
    change cannot cut the phone off."""
    value = value if isinstance(value, str) else ""
    if not shutil.which("nmcli"):
        return False, "the computer's network is not run by NetworkManager", None
    if action == "wifi":
        if value not in ("on", "off"):
            return False, "on or off", None
        done, text = _nmcli("radio", "wifi", value)
        return done, text, ("wifi", "on") if done and value == "off" else None
    if action == "scan":
        done, text = _nmcli("dev", "wifi", "rescan")
        # Asked twice in a few seconds it says so; the list is fresh either way.
        return done or "not allowed" in text, "" if done else text, None
    if action == "join":
        seen = next((n for n in wifi_networks() if n["name"] == value), None)
        if seen is None:
            return False, "that network is not in range", None
        before = next((n["name"] for n in wifi_networks() if n["active"]), "")
        if seen["known"]:
            done, text = _nmcli("con", "up", "id", value, wait=20)
        elif not seen["security"]:
            done, text = _nmcli("dev", "wifi", "connect", value, wait=20)
        elif not isinstance(secret, str) or not 8 <= len(secret) <= 63:
            return False, "it needs its password (8 to 63 characters)", None
        else:
            # Typed in rather than given as an argument, where every program
            # on the computer could read it.
            done, text = _nmcli("--ask", "dev", "wifi", "connect", value, wait=20, feed=secret + "\n")
            if not done:
                _nmcli("con", "delete", "id", value)   # the half-made one would never connect
                text = "it did not accept that password" if "ecret" in text or "assword" in text else text
        if not done:
            return False, _last_line(text), None
        if before == value:
            return True, f"Already on {value}", None
        return True, f"Connected to {value}", ("join", before) if before else ("wifi-leave", value)
    if action in ("connect", "disconnect"):
        if value not in _nm_devices():
            return False, "no such connection", None
        done, text = _nmcli("dev", action, value, wait=20)
        return done, "" if done else _last_line(text), ("connect", value) if done and action == "disconnect" else None
    if action in ("up", "down"):
        if not any(tunnel["name"] == value for tunnel in _tunnels()):
            return False, "no such VPN", None
        done, text = _nmcli("con", action, "id", value, wait=20)
        # A VPN that does not carry the link cuts the phone off when it comes up.
        return done, "" if done else _last_line(text), ("down", value) if done and action == "up" else None
    return False, "unknown action", None


def _last_line(text):
    return (text.strip().splitlines() or [""])[-1][:300]


def undo(change):
    """Take back a change the phone did not come back from. `change` is what
    network_action or usb_switch returned. Returns what was done, in words."""
    kind, value = change
    if kind == "wifi":
        _nmcli("radio", "wifi", value)
        return "Wi-Fi turned back on"
    if kind == "join":
        _nmcli("con", "up", "id", value, wait=20)
        return f"back on {value}"
    if kind == "wifi-leave":
        _nmcli("con", "down", "id", value, wait=20)
        return f"left {value}"
    if kind == "connect":
        _nmcli("dev", "connect", value, wait=20)
        return f"{value} connected again"
    if kind == "down":
        _nmcli("con", "down", "id", value, wait=20)
        return f"{value} brought down again"
    if kind == "usb":
        usb_switch(value, True)
        return f"USB device {value} switched back on"
    return ""


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
    saved = _saved()
    networks = wifi_networks(saved)
    wifi = next((n for n in networks if n["active"]), None)
    managed = _nm_devices()
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
            # Whether it is NetworkManager's to connect and disconnect, and what it is on.
            "managed": name in managed, "connection": managed.get(name, {}).get("connection", ""),
        }
        if kind == "Wi-Fi" and up and wifi:
            entry["wifi"] = wifi
        found.append(entry)
    # The one the machine reaches the internet through first, then the rest that are up.
    found.sort(key=lambda entry: (not entry["default"], not entry["up"], entry["name"]))
    radio = _nmcli("radio", "wifi")
    return {"interfaces": found, "dns": _dns(), "time": round(time.monotonic(), 3),
            "control": bool(managed), "wifi_on": radio[0] and radio[1] == "enabled",
            "networks": networks, "vpns": _tunnels(saved)}


# -------------------------------------------------------------------- wake

# The setting NetworkManager keeps for each kind of connection, and the
# value that means "wake when the magic packet arrives".
WAKE_SETTING = {"802-3-ethernet": ("802-3-ethernet.wake-on-lan", "magic"),
                "802-11-wireless": ("802-11-wireless.wake-on-wlan", "magic")}


def wake_addresses(root=NET_ROOT):
    """Where a magic packet has to be sent to wake this computer: the
    hardware address of each real interface that is connected, and the
    broadcast address of its network."""
    found = []
    for link in _json_from("ip", "-j", "addr"):
        name, mac = link.get("ifname", ""), link.get("address", "")
        if _net_kind(name, root) not in ("Wi-Fi", "Ethernet") or not re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
            continue
        for address in link.get("addr_info", []):
            if address.get("family") == "inet" and address.get("broadcast"):
                found.append({"mac": mac, "broadcast": address["broadcast"],
                              "kind": _net_kind(name, root)})
    return found


def _wake_connections():
    """[(connection, setting, value wanted, value now)] for the connections in use."""
    found = []
    for name, kind, active in _saved():
        if active != "yes" or kind not in WAKE_SETTING:
            continue
        setting, wanted = WAKE_SETTING[kind]
        ok, now = _nmcli("-g", setting, "con", "show", "id", name)
        found.append((name, setting, wanted, now.strip() if ok else ""))
    return found


def wake_state():
    """Whether the connections in use are set to wake the computer."""
    connections = _wake_connections()
    return {"connections": [{"name": name, "on": wanted in now.split(",")} for name, _setting, wanted, now in connections],
            "on": bool(connections) and all(wanted in now.split(",") for _n, _s, wanted, now in connections)}


def wake_enable(on):
    """Set the connections in use to wake the computer on a magic packet, or
    not to. Returns (done, what to say)."""
    connections = _wake_connections()
    if not connections:
        return False, "no network connection that could wake the computer is in use"
    for name, setting, wanted, _now in connections:
        done, text = _nmcli("con", "modify", "id", name, setting, wanted if on else "default")
        if not done:
            return False, _last_line(text)
    return True, ("The computer will wake for the phone" if on else "The computer will no longer wake for the phone") \
        + " once each connection has been made again (or after a restart)."


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
