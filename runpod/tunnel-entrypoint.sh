#!/bin/sh
set -eu

: "${RUNPOD_SSH_HOST:?RUNPOD_SSH_HOST is required}"
: "${RUNPOD_SSH_PORT:=22036}"
: "${RUNPOD_SSH_USER:=root}"

if [ ! -f /runpod/id_ed25519 ] || [ ! -r /runpod/id_ed25519 ]; then
  echo "SSH private key is missing, unreadable, or not a regular file at /runpod/id_ed25519" >&2
  exit 1
fi

key_file=/tmp/runpod_id_ed25519
cp /runpod/id_ed25519 "$key_file"
chmod 600 "$key_file"

AUTOSSH_GATETIME=0 autossh -M 0 \
  -i "$key_file" \
  -p "$RUNPOD_SSH_PORT" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ConnectTimeout=15 \
  -N -L 127.0.0.1:11434:127.0.0.1:11434 \
  "$RUNPOD_SSH_USER@$RUNPOD_SSH_HOST" &
tunnel_pid=$!

"$@" &
app_pid=$!

cleanup() {
  kill "$app_pid" "$tunnel_pid" 2>/dev/null || true
  wait "$app_pid" 2>/dev/null || true
  wait "$tunnel_pid" 2>/dev/null || true
  rm -f "$key_file"
}
trap cleanup INT TERM

if wait "$app_pid"; then
  status=0
else
  status=$?
fi
cleanup
exit "$status"
