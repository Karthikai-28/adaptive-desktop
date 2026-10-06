#!/usr/bin/env bash
# Let the paired phone's fingerprint stand in for the password in sudo.
#
# sudo asks the phone first. A yes on the phone - its fingerprint, then a
# signature made by the key in its secure hardware - is accepted; no answer,
# or a no, and sudo asks for the password as it always did. So the password
# still works, and a phone that is not there costs nothing.
#
# What this trusts, it copies to where only root can change it:
#   /usr/local/lib/adaptive-link/link-approve   the program sudo runs
#   /etc/adaptive-link/approvers/USER/*.pem     the public keys of the phones paired now
# A phone paired later is not trusted for sudo until this is run again; one
# unpaired later is trusted no longer at once (link-approve also checks that
# a key is one of the phones paired now).
#
#   install-link-sudo.sh            install
#   install-link-sudo.sh --remove   take it out again
#
# Think before installing it: anyone who can unlock your phone and reach
# this computer's network can then become root here.
set -Eeuo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER=/usr/local/lib/adaptive-link/link-approve
KEYS="/etc/adaptive-link/approvers/${USER:?}"
PAM=/etc/pam.d/sudo
LINE="auth sufficient pam_exec.so quiet $HELPER"

if [ "${1:-}" = "--remove" ]; then
    sudo sed -i "\|pam_exec.so quiet $HELPER|d" "$PAM"
    sudo rm -f /usr/local/lib/adaptive-link/link-approve
    sudo find "${KEYS:?}" -maxdepth 1 -name '*.pem' -delete 2>/dev/null || true
    echo "Removed. sudo asks for the password only."
    exit 0
fi

PHONES="${ADAPTIVE_LINK_DIR:-$HOME/.config/adaptive-desktop/link}/phones.json"
if [ ! -s "$PHONES" ]; then
    echo "No phone is paired yet (scripts/link-cli.py pair)." >&2
    exit 1
fi

scratch="$(mktemp -d)"
trap 'find "${scratch:?}" -type f -delete; rmdir "${scratch:?}"' EXIT
python3 - "$PHONES" "$scratch" <<'PY'
import json, subprocess, sys
phones = json.load(open(sys.argv[1]))["phones"]
for phone in phones:
    key = subprocess.run(["openssl", "x509", "-pubkey", "-noout"], input=phone["cert_pem"].encode(),
                         capture_output=True, check=True).stdout
    open(f"{sys.argv[2]}/{phone['fingerprint'][:16]}.pem", "wb").write(key)
    print(f"  {phone['name']} ({phone['fingerprint'][:8]})")
PY

sudo install -d -m 0755 "$(dirname "$HELPER")" "$KEYS"
sudo install -m 0755 -o root -g root "$REPO/scripts/link-approve.py" "$HELPER"
# Only the phones paired now: one unpaired since is trusted no longer.
sudo find "${KEYS:?}" -maxdepth 1 -name '*.pem' -delete
sudo install -m 0644 -o root -g root "$scratch"/*.pem "$KEYS/"
if ! sudo grep -qF "$LINE" "$PAM"; then
    # First, so that the phone is asked before the password is.
    sudo sed -i "0,/^[^#]/s||$LINE\n&|" "$PAM"
fi
echo "sudo now asks the phones listed above first, then the password."
echo "Turn on \"Approve with this phone\" in the app's More screen."
