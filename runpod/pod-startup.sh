#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  printf 'Run this script as root.\n' >&2
  exit 1
fi

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:8b}"
OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
OLLAMA_MODELS="${OLLAMA_MODELS:-/workspace/ollama}"
OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:--1}"
OLLAMA_LOG="${OLLAMA_LOG:-/workspace/ollama.log}"

if [[ -n "${RUNPOD_SSH_PUBLIC_KEY:-}" ]]; then
  case "$RUNPOD_SSH_PUBLIC_KEY" in
    ssh-*\ *|ecdsa-*\ *) ;;
    *)
      printf 'RUNPOD_SSH_PUBLIC_KEY must contain one OpenSSH public key.\n' >&2
      exit 1
      ;;
  esac

  install -d -m 0700 /root/.ssh
  touch /root/.ssh/authorized_keys
  chmod 0600 /root/.ssh/authorized_keys
  if ! grep -Fqx -- "$RUNPOD_SSH_PUBLIC_KEY" /root/.ssh/authorized_keys; then
    printf '%s\n' "$RUNPOD_SSH_PUBLIC_KEY" >> /root/.ssh/authorized_keys
  fi
fi

if ! command -v sshd >/dev/null 2>&1; then
  if ! command -v apt-get >/dev/null 2>&1; then
    printf 'sshd is required, and this image has no apt-get package manager.\n' >&2
    exit 1
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends openssh-server
fi

install -d -m 0755 /run/sshd
ssh-keygen -A
if ! pgrep -x sshd >/dev/null 2>&1; then
  /usr/sbin/sshd
fi

if ! command -v curl >/dev/null 2>&1; then
  if ! command -v apt-get >/dev/null 2>&1; then
    printf 'curl is required, and this image has no apt-get package manager.\n' >&2
    exit 1
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl
fi

if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

export OLLAMA_HOST OLLAMA_MODELS OLLAMA_KEEP_ALIVE
mkdir -p "$OLLAMA_MODELS" "$(dirname "$OLLAMA_LOG")"

ollama serve >"$OLLAMA_LOG" 2>&1 &
ollama_pid=$!

cleanup() {
  if kill -0 "$ollama_pid" 2>/dev/null; then
    kill "$ollama_pid" 2>/dev/null || true
    wait "$ollama_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 0' INT TERM

ready=false
for attempt in {1..120}; do
  if curl -fsS "http://127.0.0.1:11434/api/tags" >/dev/null; then
    ready=true
    break
  fi
  if ! kill -0 "$ollama_pid" 2>/dev/null; then
    printf 'Ollama exited before becoming ready; see %s.\n' "$OLLAMA_LOG" >&2
    exit 1
  fi
  sleep 5
done

if [[ "$ready" != true ]]; then
  printf 'Ollama did not become ready within 10 minutes; see %s.\n' "$OLLAMA_LOG" >&2
  exit 1
fi

ollama pull "$OLLAMA_MODEL"
curl -fsS http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$OLLAMA_MODEL\",\"prompt\":\"\",\"stream\":false,\"think\":false,\"keep_alive\":-1,\"options\":{\"num_predict\":1}}" \
  >/dev/null
printf 'Ollama is ready with model %s.\n' "$OLLAMA_MODEL"
wait "$ollama_pid"