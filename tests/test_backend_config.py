import importlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


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


ENV_KEYS = {
    "SEEDANCE_API_KEY": "",
    "SEEDANCE_BASE_URL": "",
    "SEEDANCE_POLL_INTERVAL": "",
    "SEEDANCE_REQUEST_TIMEOUT": "",
    "SEEDANCE_UPLOAD_TIMEOUT": "",
    "AIHUBMIX_API_KEY": "",
    "AIHUBMIX_BASE_URL": "",
    "AIHUBMIX_POLL_INTERVAL": "",
    "AIHUBMIX_REQUEST_TIMEOUT": "",
    "AIHUBMIX_UPLOAD_TIMEOUT": "",
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
    def __init__(self, responses, base_url="https://aihubmix.com"):
        super().__init__("fake-key", timeout=60, base_url=base_url, poll_interval=0.0)
        self._responses = list(responses)
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._responses.pop(0)


class FakeVideoReference:
    def __init__(self):
        self.saved_paths = []

    def save_to(self, path):
        self.saved_paths.append(path)
        Path(path).write_bytes(b"video-bytes")


class BackendConfigTests(unittest.TestCase):
    def test_node_mapping_contains_text_multimodal_and_preview_nodes(self):
        self.assertEqual(len(seedance_package.NODE_CLASS_MAPPINGS), 3)
        self.assertIn("ComfyUI-Seedance Text-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Multimodal-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Preview Video", seedance_package.NODE_CLASS_MAPPINGS)

    def test_model_options_include_seedance_models(self):
        self.assertEqual(
            video_api.MODEL_OPTIONS,
            [
                "doubao-seedance-2-0-260128",
                "doubao-seedance-2-0-fast-260128",
            ],
        )

    def test_resolution_ratio_and_duration_options_match_plan(self):
        self.assertEqual(video_api.RESOLUTION_OPTIONS, ["480p", "720p"])
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
                        "base_url": "https://json.example.com/v1/",
                        "poll_interval": 12.5,
                        "request_timeout": 90,
                        "upload_timeout": 140,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {**ENV_KEYS, "AIHUBMIX_API_KEY": "env-key", "AIHUBMIX_BASE_URL": "https://env.example.com"},
                clear=False,
            ):
                with mock.patch.object(seedance_nodes, "CONFIG_JSON_PATH", json_path):
                    with mock.patch.object(seedance_nodes, "Client", FakeResolvedClient):
                        client = seedance_nodes._create_runtime_client()
                        upload_timeout = seedance_nodes._create_upload_timeout()

            self.assertEqual(client.api_key, "json-key")
            self.assertEqual(client.timeout, 90)
            self.assertEqual(client.base_url, "https://json.example.com")
            self.assertEqual(client.poll_interval, 12.5)
            self.assertEqual(upload_timeout, 140)

    def test_runtime_client_uses_env_when_json_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "config.local.json"

            with mock.patch.dict(
                os.environ,
                {
                    **ENV_KEYS,
                    "SEEDANCE_API_KEY": "env-key",
                    "SEEDANCE_BASE_URL": "https://env.example.com/v1/",
                    "SEEDANCE_POLL_INTERVAL": "20",
                    "SEEDANCE_REQUEST_TIMEOUT": "75",
                    "SEEDANCE_UPLOAD_TIMEOUT": "150",
                },
                clear=False,
            ):
                with mock.patch.object(seedance_nodes, "CONFIG_JSON_PATH", json_path):
                    with mock.patch.object(seedance_nodes, "Client", FakeResolvedClient):
                        client = seedance_nodes._create_runtime_client()
                        upload_timeout = seedance_nodes._create_upload_timeout()

            self.assertEqual(client.api_key, "env-key")
            self.assertEqual(client.timeout, 75)
            self.assertEqual(client.base_url, "https://env.example.com")
            self.assertEqual(client.poll_interval, 20.0)
            self.assertEqual(upload_timeout, 150)

    def test_tmpfiles_url_is_converted_to_direct_download(self):
        self.assertEqual(
            upload_module._normalize_tmpfiles_download_url("http://tmpfiles.org/123/example.jpg"),
            "https://tmpfiles.org/dl/123/example.jpg",
        )

    def test_client_normalizes_base_url(self):
        client = client_module.Client("test-key", base_url="https://aihubmix.com/v1/")
        try:
            self.assertEqual(client.base_url, "https://aihubmix.com")
        finally:
            client.close()

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
        self.assertEqual(payload["prompt"], "A calm coastal scene.")
        self.assertEqual(payload["resolution"], "720p")
        self.assertEqual(payload["generate_audio"], True)
        self.assertEqual(payload["extra_body"]["duration"], 5)
        self.assertEqual(payload["extra_body"]["ratio"], "adaptive")
        self.assertEqual(payload["extra_body"]["watermark"], False)
        self.assertNotIn("content", payload["extra_body"])

    def test_image_payload_contains_reference_content(self):
        payload = video_api.build_generation_payload(
            "doubao-seedance-2-0-fast-260128",
            "Animate the image.",
            "480p",
            "-1",
            "16:9",
            False,
            True,
            content=[video_api.build_image_reference_payload("https://example.com/ref.jpg")],
        )
        part = payload["extra_body"]["content"][0]
        self.assertEqual(part["type"], "image_url")
        self.assertEqual(part["role"], "reference_image")
        self.assertEqual(part["image_url"]["url"], "https://example.com/ref.jpg")
        self.assertEqual(payload["extra_body"]["duration"], -1)

    def test_video_payload_contains_reference_content(self):
        payload = video_api.build_generation_payload(
            "doubao-seedance-2-0-fast-260128",
            "Restyle the video.",
            "720p",
            "5",
            "9:16",
            True,
            False,
            content=[video_api.build_video_reference_payload("https://example.com/ref.mp4")],
        )
        part = payload["extra_body"]["content"][0]
        self.assertEqual(part["type"], "video_url")
        self.assertEqual(part["role"], "reference_video")
        self.assertEqual(part["video_url"]["url"], "https://example.com/ref.mp4")

    def test_audio_payload_contains_reference_content(self):
        payload = video_api.build_generation_payload(
            "doubao-seedance-2-0-fast-260128",
            "Visualize the music.",
            "720p",
            "5",
            "1:1",
            True,
            False,
            content=[video_api.build_audio_reference_payload("https://example.com/ref.mp3")],
        )
        part = payload["extra_body"]["content"][0]
        self.assertEqual(part["type"], "audio_url")
        self.assertEqual(part["role"], "reference_audio")
        self.assertEqual(part["audio_url"]["url"], "https://example.com/ref.mp3")

    def test_image_reference_rejects_non_url_non_data_input(self):
        with self.assertRaisesRegex(ValueError, "image_url must be a valid http or https URL."):
            video_api.build_image_reference_payload("ZmFrZQ==")

    def test_image_reference_rejects_data_url(self):
        with self.assertRaisesRegex(ValueError, "image_url must be a valid http or https URL."):
            video_api.build_image_reference_payload("data:image/jpeg;base64,ZmFrZQ==")

    def test_multimodal_payload_preserves_reference_order(self):
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
        self.assertEqual(
            [item["type"] for item in payload["extra_body"]["content"]],
            ["image_url", "video_url", "audio_url"],
        )

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
                {"id": "video-123", "status": "completed"},
            ]
        )
        result = video_api.wait_for_video_completion(client, "video-123")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(client.calls), 3)

    def test_text_node_returns_remote_preview_url(self):
        fake_client = FakeVideoClient(
            [
                {"id": "video-123", "status": "in_progress"},
                {"id": "video-123", "status": "completed"},
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
        self.assertEqual(
            result["result"],
            ("https://aihubmix.com/v1/videos/video-123/content", "video-123", ""),
        )

    def test_multimodal_node_builds_mixed_references(self):
        fake_client = FakeVideoClient(
            [
                {"id": "video-123", "status": "in_progress"},
                {"id": "video-123", "status": "completed"},
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
                            "Blend the supplied references.",
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
        content = request_payload["extra_body"]["content"]
        image_url = content[0]["image_url"]["url"]
        self.assertEqual(image_url, "https://example.com/ref.jpg")
        self.assertEqual([item["type"] for item in content], ["image_url", "video_url", "audio_url"])
        self.assertEqual(result["result"][1], "video-123")

    def test_multimodal_node_requires_at_least_one_reference(self):
        with self.assertRaisesRegex(ValueError, "At least one image, video, or audio reference is required."):
            seedance_nodes.SeedanceMultimodalNode().generate(
                "doubao-seedance-2-0-fast-260128",
                "Animate the references.",
                "720p",
                "5",
                "adaptive",
                True,
                False,
            )

    def test_multimodal_node_surfaces_upload_failures(self):
        with mock.patch.object(seedance_nodes, "_upload_image_reference", side_effect=ValueError("upload failed")):
            with self.assertRaisesRegex(ValueError, "upload failed"):
                seedance_nodes.SeedanceMultimodalNode().generate(
                    "doubao-seedance-2-0-fast-260128",
                    "Animate the references.",
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
        self.assertEqual(
            result["ui"]["video_url"],
            ["https://example.com/video.mp4"],
        )
        self.assertEqual(result["result"], ("",))

    def test_preview_video_saves_local_video_when_requested(self):
        fake_client = FakeVideoClient([], base_url="https://aihubmix.com")

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
