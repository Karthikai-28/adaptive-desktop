"""Adaptive Link - who the laptop is, and which one phone it trusts.

No networking here, so scripts/verify-link.py checks all of it directly.

The laptop has a TLS certificate of its own, made on first run. The phone has
one too, made on the phone with its private key held in the phone's hardware
keystore, where it cannot be copied out. Pairing gives each side the other's
certificate. From then on every connection is mutual TLS: the laptop will not
finish a handshake with anything that does not hold the paired phone's key, so
an unpaired device never reaches a single line of the server's code.

One phone at a time. Pairing another replaces it.
"""

import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import ssl
import time
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

LINK_DIR = Path.home() / ".config" / "adaptive-desktop" / "link"
STATE_DIR = Path.home() / ".local" / "state" / "adaptive-desktop"
DEFAULT_PORT = 47823
PAIRING_PORT = 47824
PAIRING_WINDOW_S = 120
PAIRING_WINDOW_MAX_S = 600
PAIRING_MAX_ATTEMPTS = 5
MAX_CERT_BYTES = 8192

DEFAULT_CONFIG = {
    "enabled": True,
    "port": DEFAULT_PORT,
    # Connections are taken only from private and Tailscale addresses. A
    # router port-forward straight from the internet is refused unless this
    # is turned on by hand.
    "allow_public": False,
    "allow_exec": True,
    "allow_files": True,
    "allow_power": True,
    "notify_on_connect": True,
    # A device signed in to the same account as this computer (on the link's
    # Tailscale network) may ask to connect without a pairing code. It still
    # has to be approved here, once, unless auto_approve_account is on.
    "account_enroll": True,
    "auto_approve_account": False,
}


# ------------------------------------------------------------------ files

def _private_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _write_private(path, data):
    """Write bytes so the file is never readable by anyone else, even briefly."""
    _private_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)


def load_config(link_dir=None):
    config = dict(DEFAULT_CONFIG)
    try:
        data = json.loads(((link_dir or LINK_DIR) / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return config
    if isinstance(data, dict):
        for key, default in DEFAULT_CONFIG.items():
            if key in data and type(data[key]) is type(default):
                config[key] = data[key]
    if not 1024 <= config["port"] <= 65535:
        config["port"] = DEFAULT_PORT
    return config


def save_config(config, link_dir=None):
    known = {k: config[k] for k in DEFAULT_CONFIG if k in config}
    _write_private((link_dir or LINK_DIR) / "config.json",
                   (json.dumps(known, indent=2, sort_keys=True) + "\n").encode())


# ------------------------------------------------------------ certificates

def fingerprint(cert_der):
    """SHA-256 of the DER certificate, as lowercase hex."""
    return hashlib.sha256(cert_der).hexdigest()


def format_fingerprint(hex_digest):
    return ":".join(hex_digest[i:i + 2] for i in range(0, len(hex_digest), 2)).upper()


def make_certificate(common_name, days=3650):
    """(key_pem, cert_pem) for a new self-signed EC P-256 certificate."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name[:60] or "adaptive")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=days))
            .sign(key, hashes.SHA256()))
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    return key_pem, cert.public_bytes(serialization.Encoding.PEM)


def server_identity(link_dir=None):
    """(key_path, cert_path, fingerprint_hex); made on first use, then kept.

    The phone pins this certificate, so it must not change: a new one means
    pairing again.
    """
    link_dir = link_dir or LINK_DIR
    key_path, cert_path = link_dir / "server.key", link_dir / "server.crt"
    if not (key_path.exists() and cert_path.exists()):
        key_pem, cert_pem = make_certificate(f"Adaptive Link {socket.gethostname()}")
        _write_private(key_path, key_pem)
        _write_private(cert_path, cert_pem)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return key_path, cert_path, fingerprint(cert.public_bytes(serialization.Encoding.DER))


class BadCertificate(ValueError):
    pass


def check_phone_certificate(cert_pem):
    """(clean_pem, der, fingerprint_hex) for a certificate a phone offers.

    It is input from an unpaired device, so it is checked before it is ever
    trusted: one certificate, of a sane size, in date, with a key strong
    enough to be worth pinning.
    """
    if isinstance(cert_pem, str):
        cert_pem = cert_pem.encode()
    if not isinstance(cert_pem, bytes) or len(cert_pem) > MAX_CERT_BYTES:
        raise BadCertificate("certificate missing or too large")
    if cert_pem.count(b"BEGIN CERTIFICATE") != 1:
        raise BadCertificate("exactly one certificate is expected")
    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
    except ValueError as error:
        raise BadCertificate(f"not a certificate: {error}") from None

    key = cert.public_key()
    if isinstance(key, ec.EllipticCurvePublicKey):
        if key.curve.key_size < 256:
            raise BadCertificate("elliptic curve key is too small")
    elif isinstance(key, rsa.RSAPublicKey):
        if key.key_size < 2048:
            raise BadCertificate("RSA key is too small")
    else:
        raise BadCertificate("unsupported key type")

    now = datetime.datetime.now(datetime.timezone.utc)
    expires = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(
        tzinfo=datetime.timezone.utc)
    if expires < now:
        raise BadCertificate("certificate has expired")

    der = cert.public_bytes(serialization.Encoding.DER)
    return cert.public_bytes(serialization.Encoding.PEM), der, fingerprint(der)


# --------------------------------------------------------------- the phone

def load_phone(link_dir=None):
    """The paired phone: {name, cert_pem, fingerprint, paired_at}, or None."""
    try:
        data = json.loads(((link_dir or LINK_DIR) / "phone.json").read_text(encoding="utf-8"))
        _pem, _der, digest = check_phone_certificate(data["cert_pem"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if digest != data.get("fingerprint"):
        return None  # the file was edited; do not trust it
    return {"name": str(data.get("name", "Phone"))[:60], "cert_pem": data["cert_pem"],
            "fingerprint": digest, "paired_at": int(data.get("paired_at", 0))}


def save_phone(name, cert_pem, link_dir=None, now=None):
    pem, _der, digest = check_phone_certificate(cert_pem)
    record = {"name": clean_name(name), "cert_pem": pem.decode(), "fingerprint": digest,
              "paired_at": int(now if now is not None else time.time())}
    _write_private((link_dir or LINK_DIR) / "phone.json",
                   (json.dumps(record, indent=2) + "\n").encode())
    return record


def forget_phone(link_dir=None):
    try:
        ((link_dir or LINK_DIR) / "phone.json").unlink()
        return True
    except FileNotFoundError:
        return False


def clean_name(name):
    """A device name fit to show in a dialog: printable, one line, bounded."""
    text = "".join(ch for ch in str(name or "") if ch.isprintable()).strip()
    return text[:40] or "Phone"


# ----------------------------------------------------------------- pairing

def new_pairing_token():
    return secrets.token_urlsafe(32)


def tokens_match(offered, expected):
    if not isinstance(offered, str) or not expected:
        return False
    return hmac.compare_digest(offered.encode(), expected.encode())


def pairing_code(server_fingerprint, phone_fingerprint):
    """Six digits both screens show, derived from both certificates.

    If something sat between the phone and the laptop during pairing, the two
    would be looking at different certificates and so different codes.
    """
    digest = hashlib.sha256(f"{server_fingerprint}|{phone_fingerprint}".encode()).digest()
    number = int.from_bytes(digest[:8], "big") % 1_000_000
    return f"{number:06d}"


def pairing_payload(name, hosts, port, pairing_port, server_fingerprint, token):
    """What the QR code holds. Short keys keep the code small enough to scan."""
    return json.dumps({"v": 1, "n": name, "h": hosts, "p": port, "pp": pairing_port,
                       "f": server_fingerprint, "t": token}, separators=(",", ":"))


PAIRING_TEXT_PREFIX = "ALINK1."


def pairing_text(payload):
    """The QR code's contents as one line of text, for when the code cannot
    be scanned (the phone's camera is busy or broken, or the two are not in
    the same room). It carries exactly what the QR does, the one-time code
    included, so it is as short-lived and as private as the QR."""
    import base64
    return PAIRING_TEXT_PREFIX + base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


# --------------------------------------------------------------------- TLS

def _base_context(key_path, cert_path):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


def pairing_context(key_path, cert_path):
    """TLS for the pairing window: the laptop proves itself, the phone cannot yet."""
    return _base_context(key_path, cert_path)


def link_context(key_path, cert_path, phone_cert_pem):
    """TLS for the link itself: a handshake completes only with the paired
    phone's certificate, which is the whole of the trust store."""
    context = _base_context(key_path, cert_path)
    context.verify_mode = ssl.CERT_REQUIRED
    # The phone's certificate is self-signed and is its own trust anchor; the
    # strict profile would refuse an anchor that is not marked as a CA.
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    pem = phone_cert_pem.decode() if isinstance(phone_cert_pem, bytes) else phone_cert_pem
    context.load_verify_locations(cadata=pem)
    return context


# ------------------------------------------------------------------ network

_ALLOWED_NETWORKS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "100.64.0.0/10",              # carrier-grade NAT range: Tailscale's addresses
    "::1/128", "fe80::/10", "fc00::/7",   # loopback, link-local, unique local (Tailscale's fd7a:)
)]


def peer_allowed(address, allow_public=False):
    """Whether a connection from this address is taken at all.

    Home and office networks and Tailscale, by default. Mutual TLS would
    refuse a stranger anyway; this keeps the port from even answering the
    internet if a router ever forwards it by mistake.
    """
    try:
        ip = ipaddress.ip_address(str(address).split("%")[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if allow_public:
        return True
    return any(ip in network for network in _ALLOWED_NETWORKS)


def is_tailscale(address):
    try:
        ip = ipaddress.ip_address(str(address).split("%")[0])
    except ValueError:
        return False
    return ip in ipaddress.ip_network("100.64.0.0/10") or ip in ipaddress.ip_network("fd7a:115c:a1e0::/48")


def tailnet_socket():
    """The socket of the link's own Tailscale node (scripts/install-link-tailnet.sh)."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "adaptive-tailnet.sock"


def parse_tailnet_status(text):
    """(name, address) from `tailscale status --json`, or None unless it is
    signed in and running. The name is the stable one: it stays the same
    whatever network either device is on."""
    try:
        status = json.loads(text)
    except ValueError:
        return None
    if not isinstance(status, dict) or status.get("BackendState") != "Running":
        return None
    me = status.get("Self") or {}
    name = str(me.get("DNSName") or "").rstrip(".")
    addresses = [a for a in me.get("TailscaleIPs") or [] if ":" not in str(a)]
    if not name and not addresses:
        return None
    return name, (addresses[0] if addresses else "")


def tailnet():
    """(name, address) of the link's own Tailscale node, or None."""
    socket_path = tailnet_socket()
    if not socket_path.exists():
        return None
    try:
        import subprocess
        out = subprocess.run(["tailscale", f"--socket={socket_path}", "status", "--json"],
                             capture_output=True, text=True, timeout=4).stdout
    except (OSError, ValueError):
        return None
    return parse_tailnet_status(out)


# For verify-link.py only: a file naming the account this computer and its
# peers are signed in with, in place of asking Tailscale. Whoever can set the
# daemon's environment already is the user, so this opens nothing.
_TEST_ACCOUNTS = "ADAPTIVE_LINK_TEST_ACCOUNTS"


def _test_accounts():
    path = os.environ.get(_TEST_ACCOUNTS)
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _tailscale_json(*args):
    socket_path = tailnet_socket()
    if not socket_path.exists():
        return None
    try:
        import subprocess
        done = subprocess.run(["tailscale", f"--socket={socket_path}", *args],
                              capture_output=True, text=True, timeout=4)
        return json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, ValueError):
        return None


def own_account():
    """The account this computer is signed in with (an email address), or ""."""
    fake = _test_accounts()
    if fake is not None:
        return str(fake.get("own", ""))
    status = _tailscale_json("status", "--json")
    if not isinstance(status, dict) or status.get("BackendState") != "Running":
        return ""
    user = (status.get("User") or {}).get(str((status.get("Self") or {}).get("UserID")), {})
    return str(user.get("LoginName") or "")


def parse_whois(data):
    """{"account", "device"} from `tailscale whois --json`, or None."""
    if not isinstance(data, dict):
        return None
    account = str((data.get("UserProfile") or {}).get("LoginName") or "")
    node = data.get("Node") or {}
    device = str(node.get("ComputedName") or node.get("Name") or "").split(".")[0]
    return {"account": account, "device": clean_name(device)} if account else None


def whois(address, port):
    """Who is on the other end of a connection: {"account", "device"} if it
    is a device on this computer's Tailscale network, otherwise None.

    This is Tailscale's own answer, tied to the keys that device signed in
    with, not anything the device says about itself. The link's node hands
    connections on from this machine, so they are looked up by the local
    address and port they arrived from.
    """
    fake = _test_accounts()
    if fake is not None:
        account = str(fake.get("peer", ""))
        return {"account": account, "device": str(fake.get("device", "Test device"))} if account else None
    return parse_whois(_tailscale_json("whois", "--json", f"{address}:{port}")) or \
        (parse_whois(_tailscale_json("whois", "--json", str(address))) if is_tailscale(address) else None)


def same_account(peer, own):
    """Whether a peer is signed in to this computer's own account."""
    return bool(own) and bool(peer) and peer.get("account", "").casefold() == own.casefold()


def local_addresses():
    """[(address, kind)] this machine can be reached at: "lan" or "tailscale".

    The Tailscale name comes first. It identifies this computer rather than
    where it is, so it keeps working when either device changes network; the
    numeric addresses after it are the fallbacks.
    """
    found = []
    own = tailnet()
    if own:
        found.extend((value, "tailscale") for value in own if value)
    try:
        import subprocess
        out = subprocess.run(["ip", "-o", "-4", "addr", "show", "scope", "global"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, ValueError):
        return found
    for line in out.splitlines():
        parts = line.split()
        if "inet" not in parts:
            continue
        interface = parts[1]
        address = parts[parts.index("inet") + 1].split("/")[0]
        if interface.startswith(("docker", "br-", "veth", "virbr")):
            continue
        if not any(address == known for known, _kind in found):
            found.append((address, "tailscale" if is_tailscale(address) else "lan"))
    # Tailscale first: it is the address that works from anywhere.
    found.sort(key=lambda item: item[1] != "tailscale")
    return found


def came_by_tailnet(host_header, peer):
    """Whether a request arrived over Tailscale: by the address it was sent
    to (the link's own node hands connections on from this machine, so the
    peer address alone does not say) or by where it came from."""
    host = str(host_header or "").rsplit(":", 1)[0].strip("[]").lower()
    return host.endswith(".ts.net") or is_tailscale(host) or is_tailscale(peer)
