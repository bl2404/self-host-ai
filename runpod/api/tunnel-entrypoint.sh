#!/bin/sh
set -eu

: "${RUNPOD_SSH_HOST:?RUNPOD_SSH_HOST is required}"
: "${RUNPOD_SSH_PORT:=22036}"
: "${RUNPOD_SSH_USER:=root}"
: "${RUNPOD_SSH_KEY_FILE:=/runpod/id_ed25519}"

if [ ! -f "$RUNPOD_SSH_KEY_FILE" ] || [ ! -r "$RUNPOD_SSH_KEY_FILE" ]; then
  echo "SSH private key is missing or unreadable: $RUNPOD_SSH_KEY_FILE" >&2
  exit 1
fi

key_file="$(mktemp /tmp/runpod_id_ed25519.XXXXXX)"
cp "$RUNPOD_SSH_KEY_FILE" "$key_file"
chmod 0600 "$key_file"

cleanup() {
  if [ -n "${tunnel_pid:-}" ]; then
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
  fi
  rm -f "$key_file"
}
trap cleanup EXIT
trap 'exit 0' INT TERM

AUTOSSH_GATETIME=0 autossh -M 0 \
  -i "$key_file" \
  -p "$RUNPOD_SSH_PORT" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ConnectTimeout=15 \
  -N -L "0.0.0.0:11434:127.0.0.1:11434" \
  "$RUNPOD_SSH_USER@$RUNPOD_SSH_HOST" &
tunnel_pid=$!
wait "$tunnel_pid"