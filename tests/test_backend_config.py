import importlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
COMFYUI_ROOT = REPO_ROOT.parent.parent
if str(COMFYUI_ROOT) not in sys.path:
    sys.path.insert(0, str(COMFYUI_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

seedance_package = importlib.import_module("py")
seedance_nodes = importlib.import_module("py.nodes")
client_module = importlib.import_module("py.api.client")
upload_module = importlib.import_module("py.api.upload")
video_api = importlib.import_module("py.api.video")
asset_api = importlib.import_module("py.api.asset")


ENV_KEYS = {
    "ARK_API_KEY": "",
    "SEEDANCE_API_KEY": "",
    "SEEDANCE_BASE_URL": "",
    "SEEDANCE_POLL_INTERVAL": "",
    "SEEDANCE_REQUEST_TIMEOUT": "",
    "SEEDANCE_UPLOAD_TIMEOUT": "",
    "ARK_ACCESS_KEY_ID": "",
    "VOLCENGINE_ACCESS_KEY_ID": "",
    "VOLC_ACCESS_KEY_ID": "",
    "ARK_SECRET_ACCESS_KEY": "",
    "VOLCENGINE_SECRET_ACCESS_KEY": "",
    "VOLC_SECRET_ACCESS_KEY": "",
    "SEEDANCE_ASSET_BASE_URL": "",
    "ARK_ASSET_BASE_URL": "",
    "SEEDANCE_ASSET_POLL_INTERVAL": "",
    "ARK_ASSET_POLL_INTERVAL": "",
    "SEEDANCE_ASSET_TIMEOUT": "",
    "ARK_ASSET_TIMEOUT": "",
    "SEEDANCE_ASSET_PROJECT_NAME": "",
    "ARK_PROJECT_NAME": "",
}


class FakeResolvedClient:
    def __init__(self, api_key, timeout=60, base_url=None, poll_interval=15.0):
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = base_url
        self.poll_interval = poll_interval

    def absolute_url(self, path):
        if isinstance(path, str) and path.startswith(("http://", "https://")):
            return path
        return f"{self.base_url}{path}"

    def download_to_file(self, path, file_path):
        with open(file_path, "wb") as handle:
            handle.write(b"video-bytes")

    def close(self):
        pass


class FakeVideoClient(FakeResolvedClient):
    def __init__(self, responses, base_url="https://ark.cn-beijing.volces.com/api/v3"):
        super().__init__("fake-key", timeout=60, base_url=base_url, poll_interval=0.0)
        self._responses = list(responses)
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._responses.pop(0)


class FakeAssetClient:
    def __init__(self, access_key_id, secret_access_key, base_url=None, timeout=60, poll_interval=5.0):
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.base_url = base_url
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.created_assets = []
        self.closed = False

    def create_asset(self, group_id, source_url, asset_type="Image", project_name="default", name=""):
        self.created_assets.append(
            {
                "group_id": group_id,
                "source_url": source_url,
                "asset_type": asset_type,
                "project_name": project_name,
                "name": name,
            }
        )
        return {"Id": "asset-202606250001-test", "Status": "Processing"}

    def wait_for_asset_active(self, asset_id, project_name="default"):
        return {
            "Id": asset_id,
            "ProjectName": project_name,
            "Status": "Active",
            "URL": "https://example.com/asset.png",
        }

    def close(self):
        self.closed = True


class FakeVideoReference:
    def __init__(self):
        self.saved_paths = []

    def save_to(self, path):
        self.saved_paths.append(path)
        Path(path).write_bytes(b"video-bytes")


class BackendConfigTests(unittest.TestCase):
    def test_node_mapping_contains_all_generation_and_preview_nodes(self):
        self.assertEqual(len(seedance_package.NODE_CLASS_MAPPINGS), 7)
        self.assertIn("ComfyUI-Seedance Text-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance First-Frame-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance First-Last-Frame-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Asset Model-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Upload Image Asset", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Multimodal-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Preview Video", seedance_package.NODE_CLASS_MAPPINGS)

    def test_model_options_include_seedance_models(self):
        self.assertEqual(
            video_api.MODEL_OPTIONS,
            [
                "doubao-seedance-2-0-260128",
                "doubao-seedance-2-0-fast-260128",
                "doubao-seedance-2-0-mini-260615",
            ],
        )

    def test_resolution_ratio_and_duration_options_match_plan(self):
        self.assertEqual(video_api.RESOLUTION_OPTIONS, ["480p", "720p", "1080p", "4k"])
        self.assertEqual(video_api.RATIO_OPTIONS, ["adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"])
        self.assertEqual(video_api.DURATION_OPTIONS, ["-1"] + [str(value) for value in range(4, 16)])
        self.assertEqual(video_api.NODE_DURATION_OPTIONS, [str(value) for value in range(4, 16)])

    def test_node_duration_dropdown_hides_auto_mode(self):
        input_types = seedance_nodes.SeedanceTextNode.INPUT_TYPES()
        self.assertEqual(input_types["required"]["duration"][0], [str(value) for value in range(4, 16)])

    def test_runtime_client_prefers_config_local_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            json_path = tmpdir_path / "config.local.json"

            json_path.write_text(
                json.dumps(
                    {
                        "api_key": "json-key",
                        "base_url": "https://json.example.com/api/v3/",
                        "poll_interval": 12.5,
                        "request_timeout": 90,
                        "upload_timeout": 140,
                        "access_key_id": "json-ak",
                        "secret_access_key": "json-sk",
                        "asset_base_url": "https://json.example.com",
                        "asset_project_name": "json-project",
                        "asset_poll_interval": 6.5,
                        "asset_timeout": 95,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {**ENV_KEYS, "ARK_API_KEY": "env-key", "SEEDANCE_BASE_URL": "https://env.example.com/api/v3"},
                clear=False,
            ):
                with mock.patch.object(seedance_nodes, "CONFIG_JSON_PATH", json_path):
                    with mock.patch.object(seedance_nodes, "Client", FakeResolvedClient):
                        with mock.patch.object(seedance_nodes, "AssetClient", FakeAssetClient):
                            client = seedance_nodes._create_runtime_client()
                            upload_timeout = seedance_nodes._create_upload_timeout()
                            asset_client = seedance_nodes._create_asset_client()
                            asset_project_name = seedance_nodes._create_asset_project_name()

            self.assertEqual(client.api_key, "json-key")
            self.assertEqual(client.timeout, 90)
            self.assertEqual(client.base_url, "https://json.example.com/api/v3")
            self.assertEqual(client.poll_interval, 12.5)
            self.assertEqual(upload_timeout, 140)
            self.assertEqual(asset_client.access_key_id, "json-ak")
            self.assertEqual(asset_client.secret_access_key, "json-sk")
            self.assertEqual(asset_client.base_url, "https://json.example.com")
            self.assertEqual(asset_client.timeout, 95)
            self.assertEqual(asset_client.poll_interval, 6.5)
            self.assertEqual(asset_project_name, "json-project")

    def test_runtime_client_uses_env_when_json_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "config.local.json"

            with mock.patch.dict(
                os.environ,
                {
                    **ENV_KEYS,
                    "ARK_API_KEY": "env-key",
                    "SEEDANCE_BASE_URL": "https://env.example.com/api/v3/",
                    "SEEDANCE_POLL_INTERVAL": "20",
                    "SEEDANCE_REQUEST_TIMEOUT": "75",
                    "SEEDANCE_UPLOAD_TIMEOUT": "150",
                    "ARK_ACCESS_KEY_ID": "env-ak",
                    "ARK_SECRET_ACCESS_KEY": "env-sk",
                    "SEEDANCE_ASSET_BASE_URL": "https://asset-env.example.com/",
                    "SEEDANCE_ASSET_POLL_INTERVAL": "7",
                    "SEEDANCE_ASSET_TIMEOUT": "80",
                    "SEEDANCE_ASSET_PROJECT_NAME": "env-project",
                },
                clear=False,
            ):
                with mock.patch.object(seedance_nodes, "CONFIG_JSON_PATH", json_path):
                    with mock.patch.object(seedance_nodes, "Client", FakeResolvedClient):
                        with mock.patch.object(seedance_nodes, "AssetClient", FakeAssetClient):
                            client = seedance_nodes._create_runtime_client()
                            upload_timeout = seedance_nodes._create_upload_timeout()
                            asset_client = seedance_nodes._create_asset_client()
                            asset_project_name = seedance_nodes._create_asset_project_name()

            self.assertEqual(client.api_key, "env-key")
            self.assertEqual(client.timeout, 75)
            self.assertEqual(client.base_url, "https://env.example.com/api/v3")
            self.assertEqual(client.poll_interval, 20.0)
            self.assertEqual(upload_timeout, 150)
            self.assertEqual(asset_client.access_key_id, "env-ak")
            self.assertEqual(asset_client.secret_access_key, "env-sk")
            self.assertEqual(asset_client.base_url, "https://asset-env.example.com")
            self.assertEqual(asset_client.timeout, 80)
            self.assertEqual(asset_client.poll_interval, 7.0)
            self.assertEqual(asset_project_name, "env-project")

    def test_tmpfiles_url_is_converted_to_direct_download(self):
        self.assertEqual(
            upload_module._normalize_tmpfiles_download_url("http://tmpfiles.org/123/example.jpg"),
            "https://tmpfiles.org/dl/123/example.jpg",
        )

    def test_client_normalizes_base_url(self):
        client = client_module.Client("test-key", base_url="https://ark.cn-beijing.volces.com/api/v3/")
        try:
            self.assertEqual(client.base_url, "https://ark.cn-beijing.volces.com/api/v3")
        finally:
            client.close()

    def test_asset_client_posts_signed_create_asset_request(self):
        seen_requests = []

        def handler(request):
            seen_requests.append(request)
            return httpx.Response(200, json={"Result": {"Id": "asset-123"}})

        client = asset_api.AssetClient(
            "ak-test",
            "sk-test",
            base_url="https://ark.cn-beijing.volcengineapi.com/",
            poll_interval=0.0,
            transport=httpx.MockTransport(handler),
        )
        try:
            result = client.create_asset(
                "group-123",
                "https://example.com/source.png",
                project_name="default",
            )
        finally:
            client.close()

        self.assertEqual(result["Id"], "asset-123")
        self.assertEqual(str(seen_requests[0].url), "https://ark.cn-beijing.volcengineapi.com/?Action=CreateAsset&Version=2024-01-01")
        self.assertIn("HMAC-SHA256 Credential=ak-test/", seen_requests[0].headers["Authorization"])
        self.assertEqual(json.loads(seen_requests[0].content.decode("utf-8"))["AssetType"], "Image")

    def test_asset_failure_message_explains_face_mismatch(self):
        message = asset_api.describe_asset_failure(
            "asset-20260625190628-sz626",
            {
                "Status": "Failed",
                "Error": {
                    "Code": "FaceMismatch",
                    "Message": "Face consistency verification failed.",
                },
            },
        )
        self.assertIn("FaceMismatch", message)
        self.assertIn("does not match the verified person", message)
        self.assertIn("backgrounds/products as normal reference images", message)

    def test_text_payload_contains_expected_fields(self):
        payload = video_api.build_generation_payload(
            "doubao-seedance-2-0-260128",
            "A calm coastal scene.",
            "720p",
            "5",
            "adaptive",
            True,
            False,
        )
        self.assertEqual(payload["model"], "doubao-seedance-2-0-260128")
        self.assertEqual(payload["content"], [{"type": "text", "text": "A calm coastal scene."}])
        self.assertEqual(payload["resolution"], "720p")
        self.assertEqual(payload["duration"], 5)
        self.assertEqual(payload["ratio"], "adaptive")
        self.assertEqual(payload["generate_audio"], True)
        self.assertEqual(payload["watermark"], False)
        self.assertNotIn("prompt", payload)
        self.assertNotIn("extra_body", payload)

    def test_non_text_payload_allows_empty_prompt(self):
        payload = video_api.build_generation_payload(
            "doubao-seedance-2-0-fast-260128",
            "",
            "720p",
            "5",
            "3:4",
            True,
            False,
            content=[video_api.build_first_frame_payload("https://example.com/first.png")],
            prompt_required=False,
        )
        self.assertNotIn("prompt", payload)
        self.assertEqual(payload["content"][0]["role"], "first_frame")

    def test_first_frame_payload_contains_first_frame_role(self):
        payload = video_api.build_generation_payload(
            "doubao-seedance-2-0-fast-260128",
            "",
            "480p",
            "-1",
            "16:9",
            False,
            True,
            content=[video_api.build_first_frame_payload("https://example.com/first.jpg")],
            prompt_required=False,
        )
        part = payload["content"][0]
        self.assertEqual(part["type"], "image_url")
        self.assertEqual(part["role"], "first_frame")
        self.assertEqual(part["image_url"]["url"], "https://example.com/first.jpg")
        self.assertEqual(payload["duration"], -1)

    def test_first_last_frame_payload_contains_expected_roles(self):
        payload = video_api.build_generation_payload(
            "doubao-seedance-2-0-fast-260128",
            "Animate from first to last frame.",
            "720p",
            "5",
            "9:16",
            True,
            False,
            content=[
                video_api.build_first_frame_payload("https://example.com/first.jpg"),
                video_api.build_last_frame_payload("https://example.com/last.jpg"),
            ],
        )
        self.assertEqual(payload["content"][0], {"type": "text", "text": "Animate from first to last frame."})
        self.assertEqual(
            [item["role"] for item in payload["content"][1:]],
            ["first_frame", "last_frame"],
        )

    def test_multimodal_reference_payload_contains_reference_roles(self):
        payload = video_api.build_generation_payload(
            "doubao-seedance-2-0-fast-260128",
            "Blend all references into one ad.",
            "720p",
            "11",
            "16:9",
            True,
            False,
            content=[
                video_api.build_image_reference_payload("https://example.com/ref.jpg"),
                video_api.build_video_reference_payload("https://example.com/ref.mp4"),
                video_api.build_audio_reference_payload("https://example.com/ref.mp3"),
            ],
        )
        self.assertEqual(payload["content"][0], {"type": "text", "text": "Blend all references into one ad."})
        self.assertEqual(
            [item["role"] for item in payload["content"][1:]],
            ["reference_image", "reference_video", "reference_audio"],
        )

    def test_standard_model_allows_native_high_resolutions(self):
        for resolution in ["1080p", "4k"]:
            payload = video_api.build_generation_payload(
                "doubao-seedance-2-0-260128",
                "A calm coastal scene.",
                resolution,
                "5",
                "16:9",
                False,
                False,
            )
            self.assertEqual(payload["resolution"], resolution)

    def test_fast_and_mini_reject_native_high_resolutions(self):
        for model in ["doubao-seedance-2-0-fast-260128", "doubao-seedance-2-0-mini-260615"]:
            for resolution in ["1080p", "4k"]:
                with self.subTest(model=model, resolution=resolution):
                    with self.assertRaisesRegex(ValueError, "does not support resolution"):
                        video_api.build_generation_payload(
                            model,
                            "A calm coastal scene.",
                            resolution,
                            "5",
                            "16:9",
                            False,
                            False,
                        )

    def test_image_reference_rejects_non_url_non_data_input(self):
        with self.assertRaisesRegex(ValueError, "image_url must be a valid http or https URL."):
            video_api.build_image_reference_payload("ZmFrZQ==")

    def test_image_reference_accepts_data_url(self):
        payload = video_api.build_image_reference_payload("data:image/jpeg;base64,ZmFrZQ==")
        self.assertEqual(payload["image_url"]["url"], "data:image/jpeg;base64,ZmFrZQ==")

    def test_image_reference_accepts_asset_uri(self):
        payload = video_api.build_image_reference_payload("asset://asset-20260624155748-cb5d4")
        self.assertEqual(payload["image_url"]["url"], "asset://asset-20260624155748-cb5d4")

    def test_asset_reference_rejects_non_asset_uri(self):
        with self.assertRaisesRegex(ValueError, "model_asset_uri must use asset://asset-... format."):
            video_api.build_asset_image_reference_payload("asset-20260624155748-cb5d4")

    def test_file_to_data_url_encodes_local_file(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(b"fake-png")

        try:
            data_url = upload_module.file_to_data_url(temp_path, default_mime_type="image/png")
        finally:
            temp_path.unlink(missing_ok=True)

        self.assertEqual(data_url, "data:image/png;base64,ZmFrZS1wbmc=")

    def test_video_reference_rejects_invalid_url(self):
        with self.assertRaisesRegex(ValueError, "video_url must be a valid http or https URL."):
            video_api.build_video_reference_payload("not-a-url")

    def test_audio_reference_rejects_invalid_url(self):
        with self.assertRaisesRegex(ValueError, "audio_url must be a valid http or https URL."):
            video_api.build_audio_reference_payload("file:///tmp/test.mp3")

    def test_wait_for_video_completion_polls_until_completed(self):
        client = FakeVideoClient(
            [
                {"id": "video-123", "status": "queued"},
                {"id": "video-123", "status": "running"},
                {"id": "video-123", "status": "succeeded", "content": {"video_url": "https://example.com/result.mp4"}},
            ]
        )
        result = video_api.wait_for_video_completion(client, "video-123")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(client.calls[0][0:2], ("GET", "/contents/generations/tasks/video-123"))

    def test_text_node_returns_remote_preview_url(self):
        fake_client = FakeVideoClient(
            [
                {"id": "video-123"},
                {"id": "video-123", "status": "succeeded", "content": {"video_url": "https://example.com/result.mp4"}},
            ]
        )

        @contextmanager
        def fake_runtime_client():
            yield fake_client

        with mock.patch.object(seedance_nodes, "_runtime_client", fake_runtime_client):
            result = seedance_nodes.SeedanceTextNode().generate(
                "doubao-seedance-2-0-fast-260128",
                "A calm coastal scene.",
                "720p",
                "5",
                "adaptive",
                True,
                False,
            )

        self.assertNotIn("ui", result)
        self.assertEqual(fake_client.calls[0][0:2], ("POST", "/contents/generations/tasks"))
        self.assertEqual(
            result["result"],
            ("https://example.com/result.mp4", "video-123", ""),
        )

    def test_first_frame_node_builds_first_frame_content(self):
        fake_client = FakeVideoClient(
            [
                {"id": "video-123"},
                {"id": "video-123", "status": "succeeded", "content": {"video_url": "https://example.com/result.mp4"}},
            ]
        )

        @contextmanager
        def fake_runtime_client():
            yield fake_client

        with mock.patch.object(seedance_nodes, "_runtime_client", fake_runtime_client):
            with mock.patch.object(seedance_nodes, "_upload_image_reference", return_value="https://example.com/first.png"):
                result = seedance_nodes.SeedanceFirstFrameNode().generate(
                    "doubao-seedance-2-0-fast-260128",
                    "",
                    "720p",
                    "5",
                    "adaptive",
                    True,
                    False,
                    image=object(),
                )

        request_payload = fake_client.calls[0][2]["json"]
        self.assertNotIn("prompt", request_payload)
        self.assertNotIn("extra_body", request_payload)
        self.assertEqual(request_payload["content"][0]["role"], "first_frame")
        self.assertEqual(result["result"][1], "video-123")

    def test_first_last_frame_node_builds_expected_roles(self):
        fake_client = FakeVideoClient(
            [
                {"id": "video-123"},
                {"id": "video-123", "status": "succeeded", "content": {"video_url": "https://example.com/result.mp4"}},
            ]
        )

        @contextmanager
        def fake_runtime_client():
            yield fake_client

        with mock.patch.object(seedance_nodes, "_runtime_client", fake_runtime_client):
            with mock.patch.object(
                seedance_nodes,
                "_upload_image_reference",
                side_effect=["https://example.com/first.png", "https://example.com/last.png"],
            ):
                result = seedance_nodes.SeedanceFirstLastFrameNode().generate(
                    "doubao-seedance-2-0-fast-260128",
                    "Keep the character consistent.",
                    "720p",
                    "5",
                    "adaptive",
                    True,
                    False,
                    first_image=object(),
                    last_image=object(),
                )

        request_payload = fake_client.calls[0][2]["json"]
        self.assertEqual(request_payload["content"][0], {"type": "text", "text": "Keep the character consistent."})
        self.assertEqual(
            [item["role"] for item in request_payload["content"][1:]],
            ["first_frame", "last_frame"],
        )
        self.assertEqual(result["result"][1], "video-123")

    def test_asset_model_node_builds_asset_and_outfit_references_in_order(self):
        fake_client = FakeVideoClient(
            [
                {"id": "video-123"},
                {"id": "video-123", "status": "succeeded", "content": {"video_url": "https://example.com/result.mp4"}},
            ]
        )

        @contextmanager
        def fake_runtime_client():
            yield fake_client

        with mock.patch.object(seedance_nodes, "_runtime_client", fake_runtime_client):
            with mock.patch.object(
                seedance_nodes,
                "_upload_image_reference",
                side_effect=["data:image/png;base64,b3V0Zml0", "data:image/png;base64,ZXh0cmE="],
            ):
                result = seedance_nodes.SeedanceAssetModelNode().generate(
                    "doubao-seedance-2-0-fast-260128",
                    "asset://asset-20260624155748-cb5d4",
                    "Use image 1 as the model, image 2 as the outfit, and image 3 as the background.",
                    outfit_image=object(),
                    resolution="720p",
                    duration="5",
                    ratio="adaptive",
                    generate_audio=True,
                    watermark=False,
                    extra_reference_asset_uri="asset://asset-20260625120000-bg001",
                    extra_reference_image=object(),
                )

        request_payload = fake_client.calls[0][2]["json"]
        self.assertEqual(
            request_payload["content"][0],
            {"type": "text", "text": "Use image 1 as the model, image 2 as the outfit, and image 3 as the background."},
        )
        self.assertEqual(
            [item["image_url"]["url"] for item in request_payload["content"][1:]],
            [
                "asset://asset-20260624155748-cb5d4",
                "data:image/png;base64,b3V0Zml0",
                "asset://asset-20260625120000-bg001",
                "data:image/png;base64,ZXh0cmE=",
            ],
        )
        self.assertEqual(
            [item["role"] for item in request_payload["content"][1:]],
            ["reference_image", "reference_image", "reference_image", "reference_image"],
        )
        self.assertEqual(result["result"][1], "video-123")

    def test_asset_model_default_prompt_uses_image_numbers_not_asset_id(self):
        input_types = seedance_nodes.SeedanceAssetModelNode.INPUT_TYPES()
        default_prompt = input_types["required"]["prompt"][1]["default"]
        self.assertIn("图片1", default_prompt)
        self.assertIn("图片2", default_prompt)
        self.assertNotIn("asset://", default_prompt)

    def test_upload_image_asset_node_uses_source_url_and_waits_for_active_asset(self):
        fake_client = FakeAssetClient("ak", "sk")

        @contextmanager
        def fake_asset_client():
            yield fake_client

        with mock.patch.object(seedance_nodes, "_asset_client", fake_asset_client):
            result = seedance_nodes.SeedanceUploadImageAssetNode().upload(
                group_id="group-202606250001-test",
                source_url="https://example.com/source.png",
                project_name="default",
                name="background",
                wait_for_active=True,
            )

        self.assertEqual(
            fake_client.created_assets[0],
            {
                "group_id": "group-202606250001-test",
                "source_url": "https://example.com/source.png",
                "asset_type": "Image",
                "project_name": "default",
                "name": "background",
            },
        )
        self.assertEqual(
            result["result"],
            (
                "asset://asset-202606250001-test",
                "asset-202606250001-test",
                "Active",
                "https://example.com/asset.png",
            ),
        )

    def test_upload_image_asset_node_uploads_local_image_when_source_url_missing(self):
        fake_client = FakeAssetClient("ak", "sk")

        @contextmanager
        def fake_asset_client():
            yield fake_client

        with mock.patch.object(seedance_nodes, "_asset_client", fake_asset_client):
            with mock.patch.object(seedance_nodes, "_upload_image_for_asset", return_value="https://tmpfiles.org/dl/1/source.png"):
                result = seedance_nodes.SeedanceUploadImageAssetNode().upload(
                    group_id="group-202606250001-test",
                    source_url="",
                    project_name="default",
                    name="",
                    wait_for_active=False,
                    image=object(),
                )

        self.assertEqual(fake_client.created_assets[0]["source_url"], "https://tmpfiles.org/dl/1/source.png")
        self.assertEqual(result["result"][0], "asset://asset-202606250001-test")
        self.assertEqual(result["result"][2], "Processing")

    def test_upload_image_asset_node_requires_source_url_or_image(self):
        with self.assertRaisesRegex(ValueError, "Either source_url or image is required"):
            seedance_nodes.SeedanceUploadImageAssetNode().upload(
                group_id="group-202606250001-test",
                source_url="",
                project_name="default",
                name="",
                wait_for_active=False,
            )

    def test_multimodal_node_builds_mixed_references(self):
        fake_client = FakeVideoClient(
            [
                {"id": "video-123"},
                {"id": "video-123", "status": "succeeded", "content": {"video_url": "https://example.com/result.mp4"}},
            ]
        )

        @contextmanager
        def fake_runtime_client():
            yield fake_client

        fake_video = FakeVideoReference()
        fake_audio = {"waveform": "fake-waveform", "sample_rate": 44100}

        with mock.patch.object(seedance_nodes, "_runtime_client", fake_runtime_client):
            with mock.patch.object(seedance_nodes, "_upload_image_reference", return_value="https://example.com/ref.jpg"):
                with mock.patch.object(seedance_nodes, "_upload_video_reference", return_value="https://example.com/ref.mp4"):
                    with mock.patch.object(seedance_nodes, "_upload_audio_reference", return_value="https://example.com/ref.mp3"):
                        result = seedance_nodes.SeedanceMultimodalNode().generate(
                            "doubao-seedance-2-0-fast-260128",
                            "",
                            "720p",
                            "5",
                            "adaptive",
                            True,
                            False,
                            image_1=object(),
                            video_1=fake_video,
                            audio_1=fake_audio,
                        )

        request_payload = fake_client.calls[0][2]["json"]
        content = request_payload["content"]
        self.assertNotIn("prompt", request_payload)
        self.assertNotIn("extra_body", request_payload)
        self.assertEqual(
            [item["role"] for item in content],
            ["reference_image", "reference_video", "reference_audio"],
        )
        self.assertEqual(result["result"][1], "video-123")

    def test_multimodal_node_requires_at_least_one_reference(self):
        with self.assertRaisesRegex(ValueError, "At least one image, video, or audio reference is required."):
            seedance_nodes.SeedanceMultimodalNode().generate(
                "doubao-seedance-2-0-fast-260128",
                "",
                "720p",
                "5",
                "adaptive",
                True,
                False,
            )

    def test_multimodal_node_rejects_audio_only(self):
        with self.assertRaisesRegex(ValueError, "At least one image or video reference is required when audio references are provided."):
            seedance_nodes.SeedanceMultimodalNode().generate(
                "doubao-seedance-2-0-fast-260128",
                "",
                "720p",
                "5",
                "adaptive",
                True,
                False,
                audio_1={"waveform": "fake-waveform", "sample_rate": 44100},
            )

    def test_multimodal_node_surfaces_upload_failures(self):
        with mock.patch.object(seedance_nodes, "_upload_image_reference", side_effect=ValueError("upload failed")):
            with self.assertRaisesRegex(ValueError, "upload failed"):
                seedance_nodes.SeedanceMultimodalNode().generate(
                    "doubao-seedance-2-0-fast-260128",
                    "",
                    "720p",
                    "5",
                    "adaptive",
                    True,
                    False,
                    image_1=object(),
                )

    def test_preview_video_returns_remote_url_when_save_disabled(self):
        result = seedance_nodes.PreviewVideoNode().run(
            "https://example.com/video.mp4",
            "ComfyUI-Seedance",
            False,
        )
        self.assertEqual(result["ui"]["video_url"], ["https://example.com/video.mp4"])
        self.assertEqual(result["result"], ("",))

    def test_preview_video_saves_local_video_when_requested(self):
        fake_client = FakeVideoClient([], base_url="https://ark.cn-beijing.volces.com/api/v3")

        @contextmanager
        def fake_runtime_client():
            yield fake_client

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            with mock.patch.object(seedance_nodes, "_runtime_client", fake_runtime_client):
                with mock.patch.object(seedance_nodes.folder_paths, "get_output_directory", return_value=str(tmpdir_path)):
                    with mock.patch.object(
                        seedance_nodes.folder_paths,
                        "get_save_image_path",
                        return_value=(str(tmpdir_path), "ComfyUI-Seedance", 1, "", None),
                    ):
                        result = seedance_nodes.PreviewVideoNode().run(
                            "https://example.com/video.mp4",
                            "ComfyUI-Seedance",
                            True,
                        )

        self.assertEqual(
            result["ui"]["video_url"],
            ["/api/view?type=output&filename=ComfyUI-Seedance_00001_.mp4"],
        )
        self.assertTrue(result["result"][0].endswith("ComfyUI-Seedance_00001_.mp4"))

    def test_examples_are_valid_json(self):
        examples_dir = REPO_ROOT / "examples"
        example_files = sorted(examples_dir.glob("*.json"))
        self.assertGreaterEqual(len(example_files), 4)

        for example_path in example_files:
            data = json.loads(example_path.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)


if __name__ == "__main__":
    unittest.main()
