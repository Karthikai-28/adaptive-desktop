"""Adaptive Link - who the laptop is, and which phones it trusts.

No networking here, so scripts/verify-link.py checks all of it directly.

The laptop has a TLS certificate of its own, made on first run. The phone has
one too, made on the phone with its private key held in the phone's hardware
keystore, where it cannot be copied out. Pairing gives each side the other's
certificate. From then on every connection is mutual TLS: the laptop will not
finish a handshake with anything that does not hold the paired phone's key, so
an unpaired device never reaches a single line of the server's code.

A few devices can be paired - a phone and a tablet, say - each with its own
certificate, and each can be allowed less than the others (PHONE_SWITCHES).
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
MAX_PHONES = 5
# What one device can be denied while the others keep it. A device is never
# allowed more than the owner's switches for all of them (DEFAULT_CONFIG).
PHONE_SWITCHES = ("allow_input", "allow_exec", "allow_files", "allow_power")

DEFAULT_CONFIG = {
    "enabled": True,
    "port": DEFAULT_PORT,
    # Connections are taken only from private addresses. A
    # router port-forward straight from the internet is refused unless this
    # is turned on by hand.
    "allow_public": False,
    # Pointer, keyboard and launching apps. Off, the phone can watch the
    # screen but not act on it. (With this on, turning allow_exec off only
    # removes the Run screen: a keyboard can still type into a terminal.)
    "allow_input": True,
    "allow_exec": True,
    "allow_files": True,
    "allow_power": True,
    "notify_on_connect": True,
    # The desktop's own notifications are told to a phone that asks for them.
    # Alerts about the machine itself (a full disk, a low battery) always are.
    "send_notifications": True,
    # What is copied on the computer is told to a phone that asks, as it is
    # copied. Off until the owner wants it: a clipboard holds passwords.
    "sync_clipboard": False,
    # Lock the computer when the paired phone leaves its network.
    "proximity_lock": False,
    # A device signed in to the same Google account as this computer may ask
    # to connect without a pairing code. It still has to be approved here,
    # once, unless auto_approve_account is on.
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


# ------------------------------------------------------------------- relay

def clean_relay(data):
    """A relay as the owner gave it, checked: {"url", "username",
    "credential"}, or None. Only a TURN server's address is one."""
    if not isinstance(data, dict):
        return None
    url = str(data.get("url", "")).strip()
    rest = url.split(":", 1)[1] if ":" in url else ""
    if url.split(":", 1)[0] not in ("turn", "turns") or not rest or len(url) > 200 \
            or not all(ch.isalnum() or ch in ".-:[]?=_" for ch in rest):
        return None
    username, credential = str(data.get("username", ""))[:200], str(data.get("credential", ""))[:200]
    if any(not ch.isprintable() for ch in username + credential):
        return None
    return {"url": url, "username": username, "credential": credential}


def load_relay(link_dir=None):
    """The owner's own relay for when a direct connection cannot be made, or None."""
    try:
        return clean_relay(json.loads(((link_dir or LINK_DIR) / "relay.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save_relay(relay, link_dir=None):
    """Keep the relay, or forget it (None). Returns what is kept now."""
    path = (link_dir or LINK_DIR) / "relay.json"
    relay = clean_relay(relay)
    if relay is None:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    # Its password is in here: private, like the keys.
    _write_private(path, (json.dumps(relay, indent=2) + "\n").encode())
    return relay


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


# -------------------------------------------------------------- the phones

class TooManyPhones(ValueError):
    pass


def _record(data):
    """One stored device, checked: {name, cert_pem, fingerprint, paired_at,
    deny}, or None if it is not to be trusted."""
    try:
        _pem, _der, digest = check_phone_certificate(data["cert_pem"])
    except (ValueError, KeyError, TypeError):
        return None
    if digest != data.get("fingerprint"):
        return None  # the file was edited; do not trust it
    deny = data.get("deny") if isinstance(data.get("deny"), list) else []
    try:
        paired_at = int(data.get("paired_at", 0))
    except (TypeError, ValueError):
        paired_at = 0
    return {"name": str(data.get("name", "Phone"))[:60], "cert_pem": data["cert_pem"], "fingerprint": digest,
            "paired_at": paired_at, "deny": [switch for switch in PHONE_SWITCHES if switch in deny]}


def load_phones(link_dir=None):
    """The paired devices, oldest first. One paired before several could be
    is found where it was kept then (phone.json) and carried over."""
    link_dir = link_dir or LINK_DIR
    try:
        data = json.loads((link_dir / "phones.json").read_text(encoding="utf-8"))
        listed = data["phones"] if isinstance(data, dict) else []
    except (OSError, ValueError, KeyError):
        try:
            listed = [json.loads((link_dir / "phone.json").read_text(encoding="utf-8"))]
        except (OSError, ValueError):
            listed = []
    found = []
    for entry in listed if isinstance(listed, list) else []:
        record = _record(entry) if isinstance(entry, dict) else None
        if record and all(record["fingerprint"] != other["fingerprint"] for other in found):
            found.append(record)
    return found[:MAX_PHONES]


def _save_phones(phones, link_dir):
    _write_private(link_dir / "phones.json", (json.dumps({"phones": phones}, indent=2) + "\n").encode())
    try:
        (link_dir / "phone.json").unlink()   # where one phone was kept, before there could be several
    except OSError:
        pass


def save_phone(name, cert_pem, link_dir=None, now=None):
    """Trust a device. One already trusted (the same certificate) is renamed
    and keeps what it was denied. Returns its record."""
    link_dir = link_dir or LINK_DIR
    pem, _der, digest = check_phone_certificate(cert_pem)
    phones = load_phones(link_dir)
    known = next((phone for phone in phones if phone["fingerprint"] == digest), None)
    if known is None and len(phones) >= MAX_PHONES:
        raise TooManyPhones(f"{MAX_PHONES} devices are paired already; unpair one first")
    record = {"name": clean_name(name), "cert_pem": pem.decode(), "fingerprint": digest,
              "paired_at": int(now if now is not None else time.time()),
              "deny": known["deny"] if known else []}
    _save_phones([phone for phone in phones if phone["fingerprint"] != digest] + [record], link_dir)
    return record


def forget_phone(link_dir=None, fingerprint=None):
    """Stop trusting one device, or all of them. Returns how many were forgotten."""
    link_dir = link_dir or LINK_DIR
    phones = load_phones(link_dir)
    kept = [phone for phone in phones if fingerprint is not None and phone["fingerprint"] != fingerprint]
    if len(kept) != len(phones):
        _save_phones(kept, link_dir)
    return len(phones) - len(kept)


def deny_phone(fingerprint, switch, denied, link_dir=None):
    """Keep one device from something the others may do, or let it again."""
    link_dir = link_dir or LINK_DIR
    phones = load_phones(link_dir)
    phone = next((phone for phone in phones if phone["fingerprint"] == fingerprint), None)
    if phone is None or switch not in PHONE_SWITCHES:
        return False
    phone["deny"] = [name for name in PHONE_SWITCHES if (name in phone["deny"] and name != switch) or (name == switch and denied)]
    _save_phones(phones, link_dir)
    return True


def find_phone(phones, text):
    """The device the owner means by a name, or by the start of its fingerprint."""
    wanted = str(text or "").strip().casefold()
    if not wanted:
        return None
    named = [phone for phone in phones if phone["name"].casefold() == wanted]
    if len(named) == 1:
        return named[0]
    marked = [phone for phone in phones if len(wanted) >= 6 and phone["fingerprint"].startswith(wanted)]
    return marked[0] if len(marked) == 1 else None


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


def link_context(key_path, cert_path, phone_certs_pem):
    """TLS for the link itself: a handshake completes only with a paired
    device's certificate; those are the whole of the trust store."""
    context = _base_context(key_path, cert_path)
    context.verify_mode = ssl.CERT_REQUIRED
    # The phone's certificate is self-signed and is its own trust anchor; the
    # strict profile would refuse an anchor that is not marked as a CA.
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    # Each paired certificate is trusted as itself. Phones name their
    # certificates alike, and without this the one presented would be checked
    # against whichever of that name comes first - and refused if it is
    # another device's.
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    if isinstance(phone_certs_pem, (str, bytes)):
        phone_certs_pem = [phone_certs_pem]
    context.load_verify_locations(cadata="\n".join(
        pem.decode() if isinstance(pem, bytes) else pem for pem in phone_certs_pem))
    return context


# ------------------------------------------------------------------ network

_ALLOWED_NETWORKS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "::1/128", "fe80::/10", "fc00::/7",   # loopback, link-local, unique local
)]


def peer_allowed(address, allow_public=False):
    """Whether a connection from this address is taken at all.

    Home and office networks, and this machine itself (which is where the
    direct tunnel from the phone arrives). Mutual TLS would refuse a stranger
    anyway; this keeps the port from even answering the internet if a router
    ever forwards it by mistake.
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


def is_loopback(address):
    try:
        return ipaddress.ip_address(str(address).split("%")[0]).is_loopback
    except ValueError:
        return False


def local_addresses():
    """[(address, kind)] this machine can be reached at on its own network."""
    found = []
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
        # Bridges and tunnels of other software are not where a phone finds us.
        if interface.startswith(("docker", "br-", "veth", "virbr", "tailscale", "tun", "wg")):
            continue
        found.append((address, "lan"))
    return found
