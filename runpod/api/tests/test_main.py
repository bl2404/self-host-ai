import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient

from main import (
    RUNPOD_GPU_CATALOG_URL,
    RUNPOD_OPENAPI_URL,
    RUNPOD_PODS_URL,
    app,
)


class HelloTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    @patch("main.httpx.get")
    def test_openapi_route_returns_runpod_schema(self, get: Mock) -> None:
        get.return_value = Mock(
            content=b'{"openapi":"3.0.3"}',
            status_code=200,
            headers={"content-type": "application/json"},
        )

        response = self.client.get("/runpod/openapi.json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"openapi": "3.0.3"})
        get.assert_called_once_with(RUNPOD_OPENAPI_URL, timeout=10.0)

    @patch("main.httpx.get", side_effect=httpx.ConnectError("offline"))
    def test_openapi_route_reports_upstream_connection_failure(self, get: Mock) -> None:
        response = self.client.get("/runpod/openapi.json")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(), {"detail": "Could not connect to the Runpod API"}
        )
        get.assert_called_once()

    @patch("main.httpx.get")
    def test_cheapest_gpu_obeys_vram_availability_and_cloud_criteria(
        self, get: Mock
    ) -> None:
        get.return_value = Mock(
            json=Mock(
                return_value={
                    "gpus": [
                        {
                            "id": "gpu-none",
                            "memory": 80,
                            "price": {"community": 0.1},
                            "availability": "NONE",
                        },
                        {
                            "id": "gpu-below-threshold",
                            "memory": 32,
                            "price": {"community": 0.2},
                            "availability": "HIGH",
                        },
                        {
                            "id": "gpu-more-expensive",
                            "name": "More expensive GPU",
                            "memory": 48,
                            "price": {"community": 0.8, "secure": 0.5},
                            "availability": "MEDIUM",
                            "dataCenters": [],
                        },
                        {
                            "id": "gpu-cheapest",
                            "name": "Cheapest GPU",
                            "memory": 48,
                            "price": {"community": 0.4, "secure": 0.7},
                            "availability": "LOW",
                            "dataCenters": [
                                {
                                    "id": "US-KS-2",
                                    "name": "US Kansas 2",
                                    "availability": "LOW",
                                }
                            ],
                        },
                    ]
                }
            ),
            status_code=200,
        )

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            with patch("main.RUNPOD_API_KEY_FILE", key_file):
                response = self.client.get(
                    "/runpod/gpus/cheapest?min_vram=32&cloud=COMMUNITY&count=2&max_price=0.5"
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "gpuTypeId": "gpu-cheapest",
                "name": "Cheapest GPU",
                "vramGb": 48,
                "cloud": "COMMUNITY",
                "count": 2,
                "pricePerGpuHour": 0.4,
                "availability": "LOW",
                "dataCenters": [
                    {
                        "id": "US-KS-2",
                        "name": "US Kansas 2",
                        "availability": "LOW",
                    }
                ],
            },
        )
        get.assert_called_once_with(
            RUNPOD_GPU_CATALOG_URL,
            headers={"Authorization": "Bearer test-key"},
            params={
                "include": "AVAILABILITY",
                "product": "POD",
                "cloud": "COMMUNITY",
                "count": 2,
            },
            timeout=10.0,
        )

    @patch("main.httpx.get")
    def test_cheapest_gpu_returns_not_found_when_no_candidate_matches(
        self, get: Mock
    ) -> None:
        get.return_value = Mock(
            json=Mock(
                return_value={
                    "gpus": [
                        {
                            "id": "gpu-over-budget",
                            "memory": 80,
                            "price": {"community": 0.6},
                            "availability": "HIGH",
                        }
                    ]
                }
            ),
            status_code=200,
        )

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            with patch("main.RUNPOD_API_KEY_FILE", key_file):
                response = self.client.get(
                    "/runpod/gpus/cheapest?min_vram=32&max_price=0.5"
                )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "No available GPUs meet the requested VRAM threshold"},
        )

    def test_list_all_pods_route_is_removed(self) -> None:
        response = self.client.get("/runpod/pods")

        self.assertEqual(response.status_code, 405)

    @patch("main.httpx.get")
    def test_get_pod_by_name_returns_exact_match(self, get: Mock) -> None:
        pod = {"id": "pod-1", "name": "training-pod"}
        get.return_value = Mock(json=Mock(return_value=[pod]), status_code=200)

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            with patch("main.RUNPOD_API_KEY_FILE", key_file):
                response = self.client.get("/runpod/pods/training-pod")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), pod)
        get.assert_called_once_with(
            RUNPOD_PODS_URL,
            headers={"Authorization": "Bearer test-key"},
            params={"name": "training-pod"},
            timeout=10.0,
        )

    @patch("main.httpx.get")
    def test_get_pod_by_name_returns_not_found(self, get: Mock) -> None:
        get.return_value = Mock(json=Mock(return_value=[]), status_code=200)

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            with patch("main.RUNPOD_API_KEY_FILE", key_file):
                response = self.client.get("/runpod/pods/missing-pod")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Pod not found"})

    @patch("main.httpx.get")
    def test_get_pod_by_name_rejects_ambiguous_name(self, get: Mock) -> None:
        get.return_value = Mock(
            json=Mock(
                return_value=[
                    {"id": "pod-1", "name": "shared-name"},
                    {"id": "pod-2", "name": "shared-name"},
                ]
            ),
            status_code=200,
        )

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            with patch("main.RUNPOD_API_KEY_FILE", key_file):
                response = self.client.get("/runpod/pods/shared-name")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"detail": "Multiple Pods have this name; use a unique Pod name"},
        )

    @patch("main.httpx.post")
    def test_create_pod_forwards_payload_and_runpod_response(self, post: Mock) -> None:
        post.return_value = Mock(
            content=b'{"id":"pod-created","desiredStatus":"RUNNING"}',
            status_code=201,
            headers={"content-type": "application/json"},
        )
        pod_config = {
            "name": "test-pod",
            "imageName": "runpod/pytorch:latest",
            "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
            "gpuCount": 1,
        }

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            config_file = Path(temp_dir) / "config.json"
            config_file.write_text(
                '{"pod": {}, "gpu_preferences": {}}', encoding="utf-8"
            )
            with (
                patch("main.RUNPOD_API_KEY_FILE", key_file),
                patch("main.CONFIG_FILE", config_file),
            ):
                response = self.client.post("/runpod/pods", json=pod_config)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(), {"id": "pod-created", "desiredStatus": "RUNNING"}
        )
        post.assert_called_once_with(
            RUNPOD_PODS_URL,
            headers={"Authorization": "Bearer test-key"},
            json=pod_config,
            timeout=10.0,
        )

    @patch("main.httpx.post")
    def test_create_pod_injects_ssh_public_key_into_configured_environment(
        self, post: Mock
    ) -> None:
        post.return_value = Mock(
            content=b'{"id":"pod-created"}',
            status_code=201,
            headers={"content-type": "application/json"},
        )

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            public_key_file = Path(temp_dir) / "id_ed25519.pub"
            public_key_file.write_text(
                "ssh-ed25519 AAAATEST key-comment\n", encoding="utf-8"
            )
            config_file = Path(temp_dir) / "config.json"
            config_file.write_text(
                '{"pod":{"name":"configured-pod","gpuTypeIds":'
                '["NVIDIA A40"],"env":["OLLAMA_MODEL=qwen3:8b"]},'
                '"gpu_preferences":{}}',
                encoding="utf-8",
            )
            with (
                patch("main.RUNPOD_API_KEY_FILE", key_file),
                patch("main.RUNPOD_SSH_PUBLIC_KEY_FILE", public_key_file),
                patch("main.CONFIG_FILE", config_file),
            ):
                response = self.client.post("/runpod/pods")

        self.assertEqual(response.status_code, 201)
        post.assert_called_once_with(
            RUNPOD_PODS_URL,
            headers={"Authorization": "Bearer test-key"},
            json={
                "name": "configured-pod",
                "gpuTypeIds": ["NVIDIA A40"],
                "env": [
                    "OLLAMA_MODEL=qwen3:8b",
                    "RUNPOD_SSH_PUBLIC_KEY=ssh-ed25519 AAAATEST key-comment",
                ],
            },
            timeout=10.0,
        )

    @patch("main.httpx.get")
    @patch("main.httpx.post")
    def test_create_pod_uses_explicit_gpu_type_ids_from_config(
        self, post: Mock, get: Mock
    ) -> None:
        post.return_value = Mock(
            content=b'{"id":"pod-created"}',
            status_code=201,
            headers={"content-type": "application/json"},
        )

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            config_file = Path(temp_dir) / "config.json"
            config_file.write_text(
                '{"pod":{"name":"configured-pod","gpuTypeIds":'
                '["NVIDIA A40"]},"gpu_preferences":{"min_vram":64}}',
                encoding="utf-8",
            )
            with (
                patch("main.RUNPOD_API_KEY_FILE", key_file),
                patch("main.CONFIG_FILE", config_file),
            ):
                response = self.client.post("/runpod/pods")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"id": "pod-created"})
        get.assert_not_called()
        post.assert_called_once_with(
            RUNPOD_PODS_URL,
            headers={"Authorization": "Bearer test-key"},
            json={"name": "configured-pod", "gpuTypeIds": ["NVIDIA A40"]},
            timeout=10.0,
        )

    @patch("main.httpx.post")
    @patch("main.httpx.get")
    def test_create_pod_uses_cheapest_gpu_from_config_when_not_specified(
        self, get: Mock, post: Mock
    ) -> None:
        get.return_value = Mock(
            json=Mock(
                return_value={
                    "gpus": [
                        {
                            "id": "gpu-expensive",
                            "name": "Expensive GPU",
                            "memory": 48,
                            "price": {"community": 0.8},
                            "availability": "HIGH",
                        },
                        {
                            "id": "gpu-cheapest",
                            "name": "Cheapest GPU",
                            "memory": 48,
                            "price": {"community": 0.4},
                            "availability": "LOW",
                        },
                    ]
                }
            ),
            status_code=200,
        )
        post.return_value = Mock(
            content=b'{"id":"pod-created"}',
            status_code=201,
            headers={"content-type": "application/json"},
        )

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            config_file = Path(temp_dir) / "config.json"
            config_file.write_text(
                '{"pod":{"name":"configured-pod","computeType":"GPU",'
                '"cloudType":"COMMUNITY","imageName":"test/image",'
                '"containerDiskInGb":30},"gpu_preferences":'
                '{"min_vram":32,"max_price":0.5,"cloud":"COMMUNITY",'
                '"count":1}}',
                encoding="utf-8",
            )
            with (
                patch("main.RUNPOD_API_KEY_FILE", key_file),
                patch("main.CONFIG_FILE", config_file),
            ):
                response = self.client.post("/runpod/pods")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"id": "pod-created"})
        get.assert_called_once_with(
            RUNPOD_GPU_CATALOG_URL,
            headers={"Authorization": "Bearer test-key"},
            params={
                "include": "AVAILABILITY",
                "product": "POD",
                "cloud": "COMMUNITY",
                "count": 1,
            },
            timeout=10.0,
        )
        post.assert_called_once_with(
            RUNPOD_PODS_URL,
            headers={"Authorization": "Bearer test-key"},
            json={
                "name": "configured-pod",
                "computeType": "GPU",
                "cloudType": "COMMUNITY",
                "imageName": "test/image",
                "containerDiskInGb": 30,
                "gpuCount": 1,
                "gpuTypeIds": ["gpu-cheapest"],
            },
            timeout=10.0,
        )

    @patch("main.httpx.delete")
    @patch("main.httpx.get")
    def test_delete_pod_by_name_deletes_only_matching_pod(
        self, get: Mock, delete: Mock
    ) -> None:
        get.return_value = Mock(
            json=Mock(
                return_value=[
                    {"id": "pod-1", "name": "target-pod"},
                    {"id": "pod-2", "name": "other-pod"},
                ]
            ),
            status_code=200,
        )
        delete.return_value = Mock(
            content=b"", status_code=204, headers={"content-type": "application/json"}
        )

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            with patch("main.RUNPOD_API_KEY_FILE", key_file):
                response = self.client.delete("/runpod/pods/target-pod")

        self.assertEqual(response.status_code, 204)
        get.assert_called_once_with(
            RUNPOD_PODS_URL,
            headers={"Authorization": "Bearer test-key"},
            params={"name": "target-pod"},
            timeout=10.0,
        )
        delete.assert_called_once_with(
            f"{RUNPOD_PODS_URL}/pod-1",
            headers={"Authorization": "Bearer test-key"},
            timeout=10.0,
        )

    @patch("main.httpx.post")
    @patch("main.httpx.get")
    def test_start_pod_by_name_starts_matching_pod(self, get: Mock, post: Mock) -> None:
        get.return_value = Mock(
            json=Mock(
                return_value=[
                    {"id": "pod-1", "name": "training-pod"},
                    {"id": "pod-2", "name": "other-pod"},
                ]
            ),
            status_code=200,
        )
        post.return_value = Mock(
            content=b'{"id":"pod-1","desiredStatus":"RUNNING"}',
            status_code=200,
            headers={"content-type": "application/json"},
        )

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            with patch("main.RUNPOD_API_KEY_FILE", key_file):
                response = self.client.post("/runpod/pods/training-pod/start")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": "pod-1", "desiredStatus": "RUNNING"})
        get.assert_called_once_with(
            RUNPOD_PODS_URL,
            headers={"Authorization": "Bearer test-key"},
            params={"name": "training-pod"},
            timeout=10.0,
        )
        post.assert_called_once_with(
            f"{RUNPOD_PODS_URL}/pod-1/start",
            headers={"Authorization": "Bearer test-key"},
            timeout=10.0,
        )

    @patch("main.httpx.post")
    @patch("main.httpx.get")
    def test_start_pod_by_name_returns_not_found_for_missing_name(
        self, get: Mock, post: Mock
    ) -> None:
        get.return_value = Mock(json=Mock(return_value=[]), status_code=200)

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            with patch("main.RUNPOD_API_KEY_FILE", key_file):
                response = self.client.post("/runpod/pods/missing-pod/start")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Pod not found"})
        post.assert_not_called()

    @patch("main.httpx.post")
    @patch("main.httpx.get")
    def test_stop_pod_by_name_stops_matching_pod(self, get: Mock, post: Mock) -> None:
        get.return_value = Mock(
            json=Mock(
                return_value=[
                    {"id": "pod-1", "name": "training-pod"},
                    {"id": "pod-2", "name": "other-pod"},
                ]
            ),
            status_code=200,
        )
        post.return_value = Mock(
            content=b'{"id":"pod-1","desiredStatus":"EXITED"}',
            status_code=200,
            headers={"content-type": "application/json"},
        )

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            with patch("main.RUNPOD_API_KEY_FILE", key_file):
                response = self.client.post("/runpod/pods/training-pod/stop")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": "pod-1", "desiredStatus": "EXITED"})
        get.assert_called_once_with(
            RUNPOD_PODS_URL,
            headers={"Authorization": "Bearer test-key"},
            params={"name": "training-pod"},
            timeout=10.0,
        )
        post.assert_called_once_with(
            f"{RUNPOD_PODS_URL}/pod-1/stop",
            headers={"Authorization": "Bearer test-key"},
            timeout=10.0,
        )

    @patch("main.httpx.post")
    @patch("main.httpx.get")
    def test_stop_pod_by_name_returns_not_found_for_missing_name(
        self, get: Mock, post: Mock
    ) -> None:
        get.return_value = Mock(json=Mock(return_value=[]), status_code=200)

        with TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "runpod_api_key.txt"
            key_file.write_text("test-key", encoding="utf-8")
            with patch("main.RUNPOD_API_KEY_FILE", key_file):
                response = self.client.post("/runpod/pods/missing-pod/stop")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Pod not found"})
        post.assert_not_called()
