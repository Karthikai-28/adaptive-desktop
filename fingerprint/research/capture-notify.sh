#!/usr/bin/env bash
# Runs as the desktop user: turns the capture tool's status file into notifications.
status="$1/status"; last=""
pretty() { echo "${1//-/ }"; }
while sleep 0.3; do
  [ -r "$status" ] || continue
  cur=$(cat "$status" 2>/dev/null); [ "$cur" = "$last" ] && continue; last=$cur
  set -- $cur
  case "$1" in
    switch)   notify-send -u critical -h string:x-canonical-private-synchronous:fp -i fingerprint "Fingerprint test: use your $(pretty "$2")" "Get ready. $4 touches, lift fully between touches." ;;
    touch)    notify-send -h string:x-canonical-private-synchronous:fp -i fingerprint "Touch: $(pretty "$2") ($3 of $4)" "Press flat and still on the reader" ;;
    captured) canberra-gtk-play -i message 2>/dev/null & notify-send -h string:x-canonical-private-synchronous:fp -i fingerprint "Got it ($3 of $4)" "Lift your finger" ;;
    retry)    notify-send -h string:x-canonical-private-synchronous:fp "Scan $3 again" "${*:5}" ;;
    done)     notify-send -u critical -h string:x-canonical-private-synchronous:fp "Fingerprint test finished" "Thank you - you can stop now"; exit 0 ;;
    error)    notify-send -u critical "Fingerprint test failed" "${*:2}"; exit 1 ;;
  esac
done
