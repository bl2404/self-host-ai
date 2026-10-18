# Requirements
- one-click pod on/off
- no charge / little charge when gpu pod is not running
- llm can be used in vscode github copilot
- llm can be used as a chat via open-webUI


# Diagram 
```
Client (Mobile / Browser / vscode agent) -> Cloudflare tunnel -> Local Fedora Server -> runpod pod

```

# To do
- [x] api cerating, starting, stoping container
- [x] startup script for newly started pod
- [x] script for local ssh tunnel for copilot
- [ ] integration to vscode
- [ ] frontend/integration to HA
- [ ] integration to alabamalab compose
- [ ] no activity auto-off


https://chatgpt.com/c/6aca3f7b-8ef0-83eb-a099-c65d5b29bbc3


# gpu pod
Configure the pod with these environment variables and settings:

- `OLLAMA_MODEL=qwen3:8b`
- `OLLAMA_MODELS=/workspace/ollama` (mount a network volume at `/workspace` to
    retain models when the pod is replaced)
- `OLLAMA_HOST=127.0.0.1:11434` (the SSH tunnel reaches the pod's loopback)
- Optional: `RUNPOD_SSH_PUBLIC_KEY=<contents of ~/.ssh/runpod.pub>`
- Configure SSH access and expose its TCP port if the selected image does not
    already provide Runpod SSH access. Do not expose `11434/http`; Ollama has no
    built-in authentication and is intended to be reached through the SSH tunnel.

Set this as the container start command, replacing the placeholders with the
public repository and an immutable commit SHA:

```bash
bash -lc 'curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<commit>/runpod/pod-startup.sh | bash'
```

The script installs Ollama if needed, adds the optional public key to
`/root/.ssh/authorized_keys`, starts Ollama, waits for its API, pulls the model,
and keeps the server running. The container image must already provide a working
SSH server if you rely on that key; adding `authorized_keys` alone does not start
or configure `sshd`. Prefer Runpod's registered SSH key support when available.

**Better long-term:** bake Ollama and this startup script into a pinned custom
Docker image, then use a network volume for `/workspace/ollama`. Downloading and
executing a mutable remote script at every boot adds a network dependency and a
supply-chain risk; pin the raw URL to a commit even for this bootstrap approach.


# local
- Generate key-pair
    `ssh-keygen -t ed25519 -C "bruleb24@gmail.com" -f ~/.ssh/runpod`

- _now setup pod_

- turn on ssh tunnl
    `ssh root@194.68.245.106 -f -N -p 22036 -i ~/.ssh/id_ed25519 -L 11434:127.0.0.1:11434`

- test
    `curl http://127.0.0.1:11434/api/tags`

- close ssh tunnel
    `pgrep -af 'ssh.*11434'`
    `kill <PID>`


# startup order
- py api receives (private, call from HA)
- py api sends start command to pod
- py api polls until pod is running
- py api creates ssh tunnel
- py api polls until model is loaded an ollama is runing (everything is ready)
- open ui is accessable because ssh tunnel is separate container and can be use by both py api and open webUI. 
- py api receives stop request
- pod stops, ssh tunnel terminates

```
I’ll sanity-check this against Runpod’s pod lifecycle guidance, then map the startup flow to your local API, pod, and tunnel responsibilities.

The key design question is whether the “pod” should report readiness back to the API or whether the local side can discover readiness itself. I’m checking Runpod’s lifecycle and networking details because that affects restart handling and whether the tunnel needs a poller.

Runpod confirms two important constraints: “pod running” is not app-ready, and public HTTP proxy URLs are unauthenticated. I’ll compare that with your current API/compose setup so the suggestions fit what you’ve already built.

One concrete integration detail surfaced: the compose file currently points Open WebUI at `127.0.0.1:11434`, which only works if the tunnel shares that exact network namespace. I’m checking the tunnel launcher before recommending whether it should live inside the UI container or beside it.

The shape is good, but I’d simplify it to **one local controller that owns the lifecycle**. The pod shouldn’t need to call back to your API: the controller already has the Runpod API key and can poll pod state, then test the actual service through the tunnel.

**Suggested flow**

1. An authenticated start request reaches the local API.
2. The API checks the desired state. If the pod is stopped, it asks Runpod to start it; if it’s already running, that’s a no-op.
3. The API waits for Runpod’s pod state, then refreshes the SSH connection details.
4. It starts or reconnects the tunnel and checks Ollama’s health endpoint through it. Report “ready” only after that check passes; a pod marked `RUNNING` isn’t necessarily serving yet.
5. On stop, stop the pod and mark the service unavailable. Make start and stop idempotent so retries are safe.

The main thing to account for is **changed SSH connection details after a reset**. `autossh` reconnects to its configured host and port, but it won’t discover a new mapping. Your current tunnel configuration is fixed in `compose.yml`; a local controller/reconciler should refresh those values and restart the tunnel when they change. The tunnel launcher already uses `autossh` and keepalives in `tunnel-entrypoint.sh`, which is a solid base.

A few important omissions to plan for:

- **Readiness and failure states:** starting, waiting for capacity, connecting, ready, stopping, and failed, with timeouts and useful logs.
- **Access control:** “simple auth” still needs to protect every lifecycle endpoint. Also, the current pod-list route in `main.py` has no caller authentication; don’t expose it publicly without a guard. Cloudflare Access or a strong bearer token would be a better boundary.
- **Idle shutdown:** stopping a pod releases GPU billing, but storage can still cost money. If you add auto-off, track in-flight requests and start the idle timer after they finish, so you don’t stop during generation.
- **Tunnel/UI separation:** your current tunnel and Open WebUI share a container, so `127.0.0.1:11434` works. If you split them into separate containers later, that address won’t; use a shared network namespace or connect to the tunnel service by name.

So: **no pod callback, no pod-side poller**. Keep the controller local, let it reconcile Runpod state and tunnel state, and treat a successful Ollama health check as the definition of ready.
```

