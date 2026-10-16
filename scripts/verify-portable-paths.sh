#!/usr/bin/env bash
# The checkout can be cloned anywhere, by any user: nothing that runs may name
# a home folder or assume ~/adaptive-desktop (docs: README "Where it lives").
# Then the same checks against a real copy: the path helper finds a checkout
# by its own location, and a template is installed with that path in it.
set -Euo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
failed=0
ok() { echo "OK   $*"; }
bad() { echo "FAIL $*"; failed=1; }

# Code, units and desktop entries; documentation and test fixtures may use
# example paths. The resolver's own last resort and the session wrapper's
# fallback for installs that predate the record are the two allowed mentions.
hits="$(cd "$REPO" && git ls-files -- '*.sh' '*.py' '*.js' '*.service' '*.timer' '*.desktop' '*.ini' \
        ':!:scripts/verify-shell-helpers.js' ':!:scripts/verify-portable-paths.sh' ':!:.local/*' |
    xargs grep -nE '/home/karthi|(\$\{?HOME\}?|~|%h)/adaptive-desktop|Path\.home\(\) */ *"adaptive-desktop' 2>/dev/null |
    grep -vE '^shell/adaptive-shell@local/adaptiveUtil.js:.*(older installs|home \+ "/adaptive-desktop")' |
    grep -vE '^scripts/install-adaptive-session.sh:.*ADAPTIVE_REPO:-\$HOME/adaptive-desktop' |
    grep -vE '^scripts/adaptive-paths.sh:.*nothing assumes' || true)"
if [ -z "$hits" ]; then ok "no code names a home folder or ~/adaptive-desktop"; else bad "fixed paths:"; echo "$hits"; fi

templates="$(cd "$REPO" && grep -lE '^(Exec|ExecStart|WorkingDirectory)=' services/*.service services/*.desktop services/*/*.desktop apps/*/*.desktop)"
for t in $templates; do
    grep -qE '^(Exec|ExecStart|WorkingDirectory)=.*(/home/|%h/adaptive)' "$REPO/$t" && bad "$t names a home path instead of @ADAPTIVE_REPO@"
done
ok "units and desktop entries are templates"

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/some where/../elsewhere/scripts" "$scratch/home"
cp "$REPO/scripts/adaptive-paths.sh" "$scratch/elsewhere/scripts/"
found="$(env -u ADAPTIVE_REPO HOME="$scratch/home" bash -c ". '$scratch/elsewhere/scripts/adaptive-paths.sh'; echo \"\$ADAPTIVE_REPO\"")"
[ "$found" = "$scratch/elsewhere" ] && ok "a checkout anywhere finds itself ($found)" || bad "found '$found', expected $scratch/elsewhere"

ln -s "$scratch/elsewhere/scripts/adaptive-paths.sh" "$scratch/home/linked.sh"
found="$(env -u ADAPTIVE_REPO HOME="$scratch/home" bash -c ". '$scratch/home/linked.sh'; echo \"\$ADAPTIVE_REPO\"")"
[ "$found" = "$scratch/elsewhere" ] && ok "found through a symlink too" || bad "through a symlink: '$found'"

env -u ADAPTIVE_REPO HOME="$scratch/home" XDG_CONFIG_HOME="$scratch/home/.config" bash -c "
    . '$scratch/elsewhere/scripts/adaptive-paths.sh'
    adaptive_render '$REPO/services/adaptive-link.service' '$scratch/home/unit.service'
    adaptive_record_repo"
grep -q "^ExecStart=/usr/bin/python3 $scratch/elsewhere/services/adaptive-link/server.py$" "$scratch/home/unit.service" &&
    ! grep -q '@ADAPTIVE_REPO@' "$scratch/home/unit.service" &&
    ok "a template is installed with the checkout's path" || bad "rendered unit: $(grep ExecStart "$scratch/home/unit.service")"
[ "$(cat "$scratch/home/.config/adaptive-desktop/repo")" = "$scratch/elsewhere" ] &&
    ok "the checkout is recorded for the session and the shell" || bad "record: $(cat "$scratch/home/.config/adaptive-desktop/repo")"

exit "$failed"
