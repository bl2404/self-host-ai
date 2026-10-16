1. Install the Docker Model Runner plugin:
	`sudo dnf install docker-model-plugin`
2. Install the `llama.cpp` backend:
	`docker model install-runner --backend llama.cpp`
	If the Runner is already running without this backend, use
	`docker model reinstall-runner --backend llama.cpp` instead.
3. Start the stack from this directory:
	`docker compose up -d --remove-orphans`
4. Open http://localhost:3000 and select `docker.io/ai/smollm2:latest`.

Check backend availability with `docker model status`; `llama.cpp` should show
`Running`. Docker Model Runner exposes the model list through its OpenAI API at
`http://host.docker.internal:12434/engines/v1/models` from the WebUI container.


# notes
1. `docker compose up -d` will fail if docker model runner is not running, Runnig `docker model ps` will pull and run the model-runner container. Run it before compose. Otherwise following error can be displayed:
```
bruno@dell:~/playground/localai/local$ docker compose up -d
[+] up 3/4
 ✔ Network local_default    Created                                                                                                                                                                                                                       0.2s
 ✘ smollm2-runner           Error exit status 1                                                                                                                                                                                                           0.1s
 ✘ provider:smollm2-runner  failed to create service provider: exit status 1                                                                                                                                                                              0.0s
 ⠋ Container local-ai-webui Creating                                                                                                                                                                                                                      0.0s
failed to create service provider: exit status 1
```