import json
import os
import shlex
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse

RUNPOD_OPENAPI_URL = "https://api.runpod.io/v2/openapi.json"
RUNPOD_PODS_URL = "https://rest.runpod.io/v1/pods"
RUNPOD_GPU_CATALOG_URL = "https://api.runpod.io/v2/catalog/gpus"
CONFIG_FILE = Path(__file__).with_name("config.json")
RUNPOD_API_KEY_FILE = Path(
    os.environ.get(
        "RUNPOD_API_KEY_FILE", Path(__file__).with_name("runpod_api_key.txt")
    )
)
RUNPOD_SSH_PUBLIC_KEY_FILE = (
    Path(os.environ["RUNPOD_SSH_PUBLIC_KEY_FILE"])
    if os.environ.get("RUNPOD_SSH_PUBLIC_KEY_FILE")
    else None
)

app = FastAPI(title="Runpod API bridge")


def _get_runpod_api_key() -> str:
    try:
        api_key = RUNPOD_API_KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HTTPException(
            status_code=503, detail="Runpod API key is not configured"
        ) from exc

    if not api_key:
        raise HTTPException(status_code=503, detail="Runpod API key is not configured")

    return api_key


def _get_runpod_ssh_public_key() -> str | None:
    if RUNPOD_SSH_PUBLIC_KEY_FILE is None:
        return None

    try:
        public_key = RUNPOD_SSH_PUBLIC_KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HTTPException(
            status_code=503, detail="Runpod SSH public key is not configured"
        ) from exc

    key_parts = public_key.split()
    if len(key_parts) < 2 or not key_parts[0].startswith(("ssh-", "ecdsa-")):
        raise HTTPException(status_code=503, detail="Runpod SSH public key is invalid")

    return public_key


def _proxy_response(upstream: httpx.Response) -> Response:
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={
            "content-type": upstream.headers.get("content-type", "application/json")
        },
    )


def _load_app_config() -> tuple[dict[str, Any], dict[str, Any], str]:
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail="Application config is unavailable"
        ) from exc

    if not isinstance(config, dict):
        raise HTTPException(status_code=500, detail="Application config is invalid")

    pod_config = config.get("pod")
    gpu_preferences = config.get("gpu_preferences", {})
    startup_script_url = config.get("pod_startup_script_url")
    if (
        not isinstance(pod_config, dict)
        or not isinstance(gpu_preferences, dict)
        or not isinstance(startup_script_url, str)
    ):
        raise HTTPException(status_code=500, detail="Application config is invalid")

    parsed_startup_url = urlsplit(startup_script_url)
    if (
        parsed_startup_url.scheme != "https"
        or not parsed_startup_url.netloc
        or any(
            placeholder in parsed_startup_url.path.split("/")
            for placeholder in ("OWNER", "REPOSITORY", "COMMIT")
        )
    ):
        raise HTTPException(status_code=500, detail="Pod startup script URL is invalid")

    return pod_config.copy(), gpu_preferences, startup_script_url


def _pod_start_command(script_url: str) -> list[str]:
    shell_command = (
        "set -euo pipefail; "
        f"curl -fsSL {shlex.quote(script_url)} -o /tmp/pod-startup.sh; "
        "chmod 0700 /tmp/pod-startup.sh; "
        "exec bash /tmp/pod-startup.sh"
    )
    return ["bash", "-lc", shell_command]


def _fetch_gpu_catalog(cloud: str, count: int) -> dict[str, Any] | Response:
    try:
        upstream = httpx.get(
            RUNPOD_GPU_CATALOG_URL,
            headers={"Authorization": f"Bearer {_get_runpod_api_key()}"},
            params={
                "include": "AVAILABILITY",
                "product": "POD",
                "cloud": cloud,
                "count": count,
            },
            timeout=10.0,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the Runpod API",
        ) from exc

    if not 200 <= upstream.status_code < 300:
        return _proxy_response(upstream)

    try:
        catalog = upstream.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502, detail="Runpod API returned an invalid GPU catalog"
        ) from exc

    if not isinstance(catalog, dict) or not isinstance(catalog.get("gpus"), list):
        raise HTTPException(
            status_code=502, detail="Runpod API returned an invalid GPU catalog"
        )

    return catalog


def _find_cheapest_available_gpu(
    catalog: dict[str, Any],
    min_vram: int,
    cloud: str,
    max_price: float | None,
) -> dict[str, Any] | None:
    price_field = cloud.lower()
    candidates = []
    for gpu in catalog["gpus"]:
        if not isinstance(gpu, dict):
            continue

        memory = gpu.get("memory")
        availability = gpu.get("availability")
        prices = gpu.get("price")
        price = prices.get(price_field) if isinstance(prices, dict) else None
        if (
            isinstance(memory, int)
            and not isinstance(memory, bool)
            and memory > min_vram
            and availability in {"LOW", "MEDIUM", "HIGH"}
            and isinstance(price, (int, float))
            and not isinstance(price, bool)
            and (max_price is None or price <= max_price)
            and isinstance(gpu.get("id"), str)
        ):
            candidates.append((price, gpu))

    if not candidates:
        return None

    return min(candidates, key=lambda candidate: candidate[0])[1]


@app.get("/runpod/openapi.json")
def get_runpod_openapi() -> Response:
    try:
        upstream = httpx.get(RUNPOD_OPENAPI_URL, timeout=10.0)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the Runpod API",
        ) from exc

    return _proxy_response(upstream)


@app.get("/runpod/gpus/cheapest")
def get_cheapest_available_gpu(
    min_vram: int = Query(ge=0),
    cloud: Literal["COMMUNITY", "SECURE"] = "COMMUNITY",
    count: int = Query(default=1, ge=1),
    max_price: float | None = Query(default=None, ge=0),
) -> Response:
    catalog = _fetch_gpu_catalog(cloud, count)
    if isinstance(catalog, Response):
        return catalog

    gpu = _find_cheapest_available_gpu(catalog, min_vram, cloud, max_price)
    if gpu is None:
        raise HTTPException(
            status_code=404,
            detail="No available GPUs meet the requested VRAM threshold",
        )

    price = gpu["price"][cloud.lower()]
    return JSONResponse(
        content={
            "gpuTypeId": gpu["id"],
            "name": gpu.get("name"),
            "vramGb": gpu["memory"],
            "cloud": cloud,
            "count": count,
            "pricePerGpuHour": price,
            "availability": gpu["availability"],
            "dataCenters": gpu.get("dataCenters", []),
        }
    )


def _find_runpod_pod_by_name(pod_name: str) -> dict[str, Any] | Response:
    headers = {"Authorization": f"Bearer {_get_runpod_api_key()}"}
    try:
        upstream = httpx.get(
            RUNPOD_PODS_URL,
            headers=headers,
            params={"name": pod_name},
            timeout=10.0,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the Runpod API",
        ) from exc

    if not 200 <= upstream.status_code < 300:
        return _proxy_response(upstream)

    try:
        pods = upstream.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502, detail="Runpod API returned an invalid pod list"
        ) from exc

    if not isinstance(pods, list) or any(not isinstance(pod, dict) for pod in pods):
        raise HTTPException(
            status_code=502, detail="Runpod API returned an invalid pod list"
        )

    matches = [pod for pod in pods if pod.get("name") == pod_name]
    if not matches:
        raise HTTPException(status_code=404, detail="Pod not found")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple Pods have this name; use a unique Pod name",
        )

    pod = matches[0]
    if not isinstance(pod.get("id"), str):
        raise HTTPException(status_code=502, detail="Pod response is missing its ID")
    return pod


@app.get("/runpod/pods/{pod_name}")
def get_pod(pod_name: str) -> Response:
    pod = _find_runpod_pod_by_name(pod_name)
    if isinstance(pod, Response):
        return pod
    return JSONResponse(content=pod)


# Runpod API docs: https://docs.runpod.io/api-reference/pods/POST/pods
@app.post("/runpod/pods")
def create_runpod_pod(
    pod_overrides: dict[str, Any] | None = None,
) -> Response:
    pod_config, gpu_preferences, startup_script_url = _load_app_config()
    if pod_overrides:
        pod_config.update(pod_overrides)

    pod_environment = pod_config.get("env", {})
    if not isinstance(pod_environment, dict) or any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in pod_environment.items()
    ):
        raise HTTPException(status_code=500, detail="Pod environment config is invalid")
    public_key = _get_runpod_ssh_public_key()
    if public_key is not None:
        pod_environment = pod_environment.copy()
        pod_environment["RUNPOD_SSH_PUBLIC_KEY"] = public_key
        pod_config["env"] = pod_environment

    pod_config["dockerStartCmd"] = _pod_start_command(startup_script_url)

    if "gpuTypeIds" not in pod_config and pod_config.get("computeType", "GPU") == "GPU":
        cloud = pod_config.get("cloudType", gpu_preferences.get("cloud", "COMMUNITY"))
        count = pod_config.get("gpuCount", gpu_preferences.get("count", 1))
        min_vram = gpu_preferences.get("min_vram", 0)
        max_price = gpu_preferences.get("max_price")

        if cloud not in {"COMMUNITY", "SECURE"}:
            raise HTTPException(
                status_code=500, detail="GPU preference cloud is invalid"
            )
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise HTTPException(
                status_code=500, detail="GPU preference count is invalid"
            )
        if not isinstance(min_vram, int) or isinstance(min_vram, bool) or min_vram < 0:
            raise HTTPException(
                status_code=500, detail="GPU preference min_vram is invalid"
            )
        if max_price is not None and (
            not isinstance(max_price, (int, float))
            or isinstance(max_price, bool)
            or max_price < 0
        ):
            raise HTTPException(
                status_code=500, detail="GPU preference max_price is invalid"
            )

        catalog = _fetch_gpu_catalog(cloud, count)
        if isinstance(catalog, Response):
            return catalog

        gpu = _find_cheapest_available_gpu(catalog, min_vram, cloud, max_price)
        if gpu is None:
            raise HTTPException(
                status_code=404,
                detail="No available GPUs meet the configured preferences",
            )

        pod_config["gpuTypeIds"] = [gpu["id"]]
        pod_config.setdefault("gpuCount", count)
        pod_config.setdefault("cloudType", cloud)

    try:
        upstream = httpx.post(
            RUNPOD_PODS_URL,
            headers={"Authorization": f"Bearer {_get_runpod_api_key()}"},
            json=pod_config,
            timeout=10.0,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the Runpod API",
        ) from exc

    return _proxy_response(upstream)


@app.delete("/runpod/pods/{pod_name}")
def delete_runpod_pod(pod_name: str) -> Response:
    pod = _find_runpod_pod_by_name(pod_name)
    if isinstance(pod, Response):
        return pod

    headers = {"Authorization": f"Bearer {_get_runpod_api_key()}"}
    pod_url = f"{RUNPOD_PODS_URL}/{quote(pod['id'], safe='')}"
    try:
        upstream = httpx.delete(pod_url, headers=headers, timeout=10.0)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the Runpod API",
        ) from exc

    return _proxy_response(upstream)


def _runpod_pod_action(pod_name: str, action: str) -> Response:
    pod = _find_runpod_pod_by_name(pod_name)
    if isinstance(pod, Response):
        return pod

    headers = {"Authorization": f"Bearer {_get_runpod_api_key()}"}
    action_url = f"{RUNPOD_PODS_URL}/{quote(pod['id'], safe='')}/{action}"
    try:
        upstream = httpx.post(action_url, headers=headers, timeout=10.0)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the Runpod API",
        ) from exc

    return _proxy_response(upstream)


@app.post("/runpod/pods/{pod_name}/start")
def start_runpod_pod(pod_name: str) -> Response:
    return _runpod_pod_action(pod_name, "start")


@app.post("/runpod/pods/{pod_name}/stop")
def stop_runpod_pod(pod_name: str) -> Response:
    return _runpod_pod_action(pod_name, "stop")
