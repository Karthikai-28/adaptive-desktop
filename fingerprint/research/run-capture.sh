#!/usr/bin/env bash
# Usage: run-capture.sh OUTDIR finger:count ...   (asks for admin once)
here="$(cd "$(dirname "$0")" && pwd)"; tools="$here/../../.local/fingerprint-driver/research"; out="$1"; shift
mkdir -p "$out"; rm -f "$out/status"
"$here/capture-notify.sh" "$out" & nt=$!
pkexec /bin/sh -c 'pkill -x vfs-capture; systemctl stop fprintd 2>/dev/null; umask 022; G_MESSAGES_DEBUG=all timeout 1200 "$0" "$@" 2>"$1/driver.log"; rc=$?; chown -R '"$(id -u):$(id -g)"' "$1"; exit $rc' "$(readlink -f "$tools/vfs-capture")" "$out" 12 "$@"
rc=$?; sleep 1; kill $nt 2>/dev/null; exit $rc
