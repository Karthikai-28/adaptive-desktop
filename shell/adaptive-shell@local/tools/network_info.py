#!/usr/bin/env python3
"""Network facts and a local device scan, as JSON for the shell's Network panel.

    network_info.py info     this computer: addresses, router, DNS, Wi-Fi...
    network_info.py scan     every device answering on the local /24
    network_info.py public   the public IP (asks one outside service)

The scan sends a single UDP packet to each address on the local network. That
makes the kernel resolve every address with ARP, and ARP is answered even by
devices that ignore ping - it is how arp-scan finds them, without needing
root. The neighbour table then lists who answered. Names come from mDNS
(Avahi), the router's reverse DNS and NetBIOS; makers from the IEEE OUI list.

Nothing leaves the local network except `public`, which the panel only runs
when asked.
"""

import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time

OUI_FILES = ("/usr/share/ieee-data/oui.txt", "/var/lib/ieee-data/oui.txt")


def run(argv, timeout=4):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def ip_json(*args):
    try:
        return json.loads(run(["/usr/bin/ip", "-j", *args]) or "[]")
    except ValueError:
        return []


def primary_route():
    for route in ip_json("-4", "route", "show", "default"):
        return route.get("dev"), route.get("gateway")
    return None, None


def addresses(dev):
    v4, v6 = [], []
    for link in ip_json("addr", "show", "dev", dev):
        for addr in link.get("addr_info", []):
            if addr.get("family") == "inet":
                v4.append(f"{addr['local']}/{addr['prefixlen']}")
            elif addr.get("family") == "inet6" and addr.get("scope") == "global":
                v6.append(addr["local"])
    return v4, v6


def mac_of(dev):
    try:
        with open(f"/sys/class/net/{dev}/address") as handle:
            return handle.read().strip()
    except OSError:
        return None


def dns_servers(dev):
    servers = []
    out = run(["resolvectl", "dns", dev])
    for token in out.split(":", 1)[-1].split():
        if re.match(r"^[0-9a-fA-F:.]+$", token):
            servers.append(token)
    if not servers:
        try:
            with open("/etc/resolv.conf") as handle:
                servers = re.findall(r"^nameserver\s+(\S+)", handle.read(), re.M)
        except OSError:
            pass
    return servers


def wifi_details(dev):
    out = run(["nmcli", "-t", "-e", "no", "-f", "ACTIVE,SSID,SIGNAL,FREQ,RATE,SECURITY,CHAN",
               "dev", "wifi", "list", "ifname", dev, "--rescan", "no"])
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 7 and parts[0] == "yes":
            return {
                "ssid": parts[1],
                "signal": int(parts[2] or 0),
                "frequency": parts[3],
                "rate": parts[4],
                "security": parts[5] or "Open",
                "channel": parts[6],
            }
    return None


def link_speed(dev):
    try:
        with open(f"/sys/class/net/{dev}/speed") as handle:
            speed = int(handle.read().strip())
            return f"{speed} Mb/s" if speed > 0 else None
    except (OSError, ValueError):
        return None


def gateway_latency(gateway):
    if not gateway:
        return None
    out = run(["ping", "-c", "3", "-i", "0.2", "-W", "1", "-q", gateway], timeout=5)
    found = re.search(r"= [\d.]+/([\d.]+)/", out)
    return float(found.group(1)) if found else None


def info():
    dev, gateway = primary_route()
    if dev is None:
        return {"connected": False}
    v4, v6 = addresses(dev)
    kind = "wifi" if os.path.isdir(f"/sys/class/net/{dev}/wireless") else "ethernet"
    result = {
        "connected": True,
        "device": dev,
        "kind": kind,
        "ipv4": v4,
        "ipv6": v6,
        "gateway": gateway,
        "dns": dns_servers(dev),
        "mac": mac_of(dev),
        "hostname": socket.gethostname(),
        "connectivity": run(["nmcli", "networking", "connectivity"]).strip() or "unknown",
        "gateway_ms": gateway_latency(gateway),
    }
    if kind == "wifi":
        result["wifi"] = wifi_details(dev)
    else:
        result["speed"] = link_speed(dev)

    # VPNs worth knowing about: Tailscale, WireGuard, OpenVPN tunnels.
    tunnels = []
    for link in ip_json("addr"):
        name = link.get("ifname", "")
        if name.startswith(("tailscale", "wg", "tun", "tap")) and link.get("operstate") != "DOWN":
            for addr in link.get("addr_info", []):
                if addr.get("family") == "inet":
                    tunnels.append({"name": name, "address": addr["local"]})
    result["tunnels"] = tunnels
    return result


# ------------------------------------------------------------------ scan


def load_vendors(prefixes):
    """Maker per MAC prefix, from whichever of the IEEE, Wireshark and nmap
    lists knows it. All three are only as new as their packages; a maker
    registered since is simply not named."""
    wanted = {p.upper() for p in prefixes}
    vendors = {}
    for path in OUI_FILES:
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if "(hex)" in line:
                        prefix, _, name = line.partition("(hex)")
                        key = prefix.strip().replace("-", ":").upper()
                        if key in wanted:
                            vendors[key] = name.strip()
            break
    missing = wanted - set(vendors)
    if missing and os.path.exists("/usr/share/wireshark/manuf"):
        with open("/usr/share/wireshark/manuf", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].upper() in missing:
                    vendors[parts[0].upper()] = (parts[2] if len(parts) > 2 else parts[1]).strip()
    missing = wanted - set(vendors)
    if missing and os.path.exists("/usr/share/nmap/nmap-mac-prefixes"):
        compact = {m.replace(":", ""): m for m in missing}
        with open("/usr/share/nmap/nmap-mac-prefixes", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                key, _, name = line.strip().partition(" ")
                if key.upper() in compact:
                    vendors[compact[key.upper()]] = name
    return vendors


def tidy(name):
    for suffix in (".lan", ".local", ".home", ".localdomain"):
        if name and name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name


def neighbours(dev):
    found = {}
    try:
        with open("/proc/net/arp") as handle:
            next(handle)
            for line in handle:
                parts = line.split()
                if len(parts) >= 6 and parts[5] == dev and parts[2] == "0x2":
                    found[parts[0]] = parts[3].lower()
    except OSError:
        pass
    return found


def nudge(hosts):
    """One UDP packet to the discard port of every host: the kernel has to
    ARP for each, and the neighbour table fills with whoever answers."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    for host in hosts:
        try:
            sock.sendto(b"", (str(host), 9))
        except OSError:
            pass
    sock.close()


def name_for(address):
    out = run(["avahi-resolve-address", address], timeout=2)
    parts = out.split()
    if len(parts) >= 2:
        return tidy(parts[1])
    try:
        name = socket.gethostbyaddr(address)[0]
        if name and name != address:
            return tidy(name)
    except OSError:
        pass
    out = run(["nmblookup", "-A", address], timeout=3)
    found = re.search(r"^\s+(\S+)\s+<00>\s+-\s+[^<]*<ACTIVE>", out, re.M)
    return found.group(1) if found else None


def classify(vendor, name, is_gateway, private_mac):
    text = f"{vendor or ''} {name or ''}".lower()
    if is_gateway:
        return "router"
    if any(k in text for k in ("iphone", "ipad", "android", "galaxy", "pixel", "oneplus",
                               "redmi", "xiaomi communications", "oppo", "vivo", "realme")):
        return "phone"
    if any(k in text for k in ("printer", "epson", "canon", "brother", "hewlett", " hp ")):
        return "printer"
    if any(k in text for k in ("tv", "roku", "chromecast", "fire", "bravia", "webos",
                               "settop", "set-top", "stb")):
        return "tv"
    if any(k in text for k in ("espressif", "tuya", "shelly", "sonoff", "tp-link smart", "philips lighting")):
        return "smart"
    if "raspberry" in text:
        return "board"
    if any(k in text for k in ("macbook", "imac", "desktop", "laptop", "intel", "liteon", "dell",
                               "lenovo", "asus", "micro-star", "gigabyte", "hon hai")):
        return "computer"
    if private_mac:
        return "phone"
    return "device"


def scan():
    dev, gateway = primary_route()
    if dev is None:
        return {"connected": False, "devices": []}
    v4, _ = addresses(dev)
    if not v4:
        return {"connected": True, "devices": []}
    own = v4[0].split("/")[0]
    network = ipaddress.ip_interface(v4[0]).network
    # Never sweep more than the /24 around this computer.
    if network.prefixlen < 24:
        network = ipaddress.ip_interface(f"{own}/24").network
    hosts = [h for h in network.hosts() if str(h) != own]

    started = time.monotonic()
    nudge(hosts)
    time.sleep(1.2)
    nudge([h for h in hosts if str(h) not in neighbours(dev)])
    time.sleep(1.3)

    table = neighbours(dev)
    table[own] = (mac_of(dev) or "").lower()

    vendors = load_vendors({mac[:8] for mac in table.values() if mac})
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        names = dict(zip(table, pool.map(name_for, table)))

    devices = []
    for address, mac in table.items():
        first = int(mac[:2], 16) if mac else 0
        private_mac = bool(first & 0x02)
        vendor = vendors.get(mac[:8].upper()) if mac else None
        name = socket.gethostname() if address == own else names.get(address)
        devices.append({
            "ip": address,
            "mac": mac,
            "vendor": vendor or ("Private Wi-Fi address" if private_mac else None),
            "name": name,
            "self": address == own,
            "gateway": address == gateway,
            "kind": "computer" if address == own else classify(vendor, name, address == gateway, private_mac),
        })

    devices.sort(key=lambda d: (not d["gateway"], not d["self"], ipaddress.ip_address(d["ip"])))
    return {
        "connected": True,
        "network": str(network),
        "seconds": round(time.monotonic() - started, 1),
        "devices": devices,
    }


def public():
    out = run(["curl", "-s", "-m", "5", "https://api.ipify.org"], timeout=7).strip()
    return {"public": out if re.match(r"^[0-9a-fA-F:.]+$", out) else None}


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "info"
    handler = {"info": info, "scan": scan, "public": public}.get(command)
    if handler is None:
        sys.exit(f"unknown command {command}")
    print(json.dumps(handler()))
