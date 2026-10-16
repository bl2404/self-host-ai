# Runpod API Bridge

A minimal FastAPI service that fetches Runpod's public REST API OpenAPI schema.

## Run

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Fetch the schema from `http://127.0.0.1:8000/runpod/openapi.json`. This first
endpoint reads `https://rest.runpod.io/v1/openapi.json` and does not require an
API key.

The schema endpoint reads the public schema at
`https://api.runpod.io/v2/openapi.json`. Put your Runpod API key in
`runpod_api_key.txt` in the project directory; this file is ignored by Git.
Set `RUNPOD_API_KEY_FILE` to use a different secret file. The bridge adds the
required bearer authorization when calling Runpod.

Get the cheapest currently available GPU above a VRAM threshold with
`GET http://127.0.0.1:8000/runpod/gpus/cheapest?min_vram=32`. The threshold is
strict (`memory > min_vram`). Optional `cloud` (`COMMUNITY` or `SECURE`) and
`count` parameters scope the price and availability lookup; both default to
`COMMUNITY` and `1`. Add `max_price` to set an inclusive price ceiling in USD
per GPU per hour; for example, `&max_price=0.50`.

Get a Pod by its name with
`GET http://127.0.0.1:8000/runpod/pods/{pod_name}`. Pod names are not unique,
so this returns `409` if multiple Pods have that name.

Create a Pod by sending a JSON body to
`POST http://127.0.0.1:8000/runpod/pods`. The payload is forwarded to Runpod's
Create Pod API. This operation can incur charges; protect the bridge from
untrusted access. The [config.json](config.json) file holds the default `pod`
payload and `gpu_preferences`. If `pod.gpuTypeIds` is omitted, the bridge selects
the lowest-priced available GPU matching those preferences. Any explicitly
supplied `gpuTypeIds` is forwarded unchanged. A request body is optional; when
supplied, its Pod fields override the configured defaults. See
[pod_config.example.json](pod_config.example.json) for a sample request payload.
Create from config defaults with:

```bash
curl -X POST http://127.0.0.1:8000/runpod/pods
```

Or override the defaults with a JSON request body:

```bash
curl -X POST http://127.0.0.1:8000/runpod/pods \
	-H 'Content-Type: application/json' \
	--data-binary @pod_config.example.json
```

The example requests a community NVIDIA A40 Pod without spot pricing;
availability and pricing are determined by Runpod.

Start a Pod by name with
`POST http://127.0.0.1:8000/runpod/pods/{pod_name}/start`.

Stop a Pod by name with
`POST http://127.0.0.1:8000/runpod/pods/{pod_name}/stop`.

Delete a Pod by name with
`DELETE http://127.0.0.1:8000/runpod/pods/{pod_name}`. This is destructive;
keep the bridge inaccessible to untrusted clients.

## Test

```bash
python -m unittest discover -s tests -p 'test_*.py'
```
