import importlib
import io
import json
import os
import sys
import tempfile
import unittest
import wave
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import httpx
import numpy


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
    "SEEDANCE_SPEECH_API_KEY": "",
    "OSS_ENDPOINT": "",
    "OSS_ACCESS_KEY_ID": "",
    "OSS_ACCESS_KEY_SECRET": "",
    "OSS_BUCKET": "",
    "OSS_PREFIX": "",
    "OSS_SIGNED_URL_EXPIRES": "",
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
    "SEEDANCE_ASSET_WAIT_TIMEOUT": "",
    "ARK_ASSET_WAIT_TIMEOUT": "",
    "SEEDANCE_ASSET_PROJECT_NAME": "",
    "ARK_PROJECT_NAME": "",
    "LAS_API_KEY": "",
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
    def __init__(
        self,
        access_key_id,
        secret_access_key,
        base_url=None,
        timeout=60,
        poll_interval=5.0,
        wait_timeout=900,
    ):
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.base_url = base_url
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.wait_timeout = wait_timeout
        self.created_assets = []
        self.created_groups = []
        self.closed = False

    def create_asset_group(self, name, description="", group_type="AIGC", project_name="default"):
        self.created_groups.append(
            {
                "name": name,
                "description": description,
                "group_type": group_type,
                "project_name": project_name,
            }
        )
        return {"Id": "group-202606250001-test"}

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

    def get_asset(self, asset_id, project_name="default"):
        return {
            "Id": asset_id,
            "GroupId": "group-202606250001-test",
            "AssetType": "Image",
            "Status": "Active",
            "URL": "https://example.com/asset.png",
            "Name": "asset-name",
            "ProjectName": project_name,
        }

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
    def test_download_to_file_does_not_forward_ark_authorization(self):
        captured = {}

        @contextmanager
        def fake_stream(method, path, **kwargs):
            captured.update({"method": method, "path": path, **kwargs})
            yield httpx.Response(200, content=b"video-bytes", request=httpx.Request(method, path))

        client = client_module.Client("ark-secret")
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "video.mp4"
                with mock.patch.object(client_module.httpx, "stream", fake_stream):
                    client.download_to_file("https://storage.example.com/signed.mp4", output_path)
                self.assertEqual(output_path.read_bytes(), b"video-bytes")
        finally:
            client.close()

        self.assertNotIn("headers", captured)
        self.assertTrue(captured["follow_redirects"])

    def test_download_error_reads_stream_before_building_api_error(self):
        @contextmanager
        def fake_stream(method, path, **kwargs):
            yield httpx.Response(
                403,
                stream=httpx.ByteStream(b"SignatureDoesNotMatch"),
                request=httpx.Request(method, path),
            )

        client = client_module.Client("ark-secret")
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "video.mp4"
                with mock.patch.object(client_module.httpx, "stream", fake_stream):
                    with self.assertRaisesRegex(client_module.VideoAPIError, "SignatureDoesNotMatch"):
                        client.download_to_file("https://storage.example.com/signed.mp4", output_path)
        finally:
            client.close()

    def test_node_mapping_contains_all_generation_and_preview_nodes(self):
        self.assertEqual(len(seedance_package.NODE_CLASS_MAPPINGS), 14)
        self.assertIn("ComfyUI-Seedance Text-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance First-Frame-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance First-Last-Frame-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Asset Model-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Create Asset Group", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Upload Asset", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Get Asset", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Trusted Person Asset", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Upload Image Asset", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Multimodal-to-Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Preview Video", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Voice Clone V3 Train", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Voice Clone V3 Query", seedance_package.NODE_CLASS_MAPPINGS)
        self.assertIn("ComfyUI-Seedance Voice Clone V3 TTS", seedance_package.NODE_CLASS_MAPPINGS)

    def test_voice_clone_nodes_expose_expected_inputs_and_fee_guard(self):
        train_inputs = seedance_nodes.VoiceCloneV3TrainNode.INPUT_TYPES()
        self.assertEqual(train_inputs["required"]["audio"], ("AUDIO",))
        self.assertIn("custom_speaker_id", train_inputs["required"])
        self.assertIn("demo_text", train_inputs["required"])

        query_inputs = seedance_nodes.VoiceCloneV3QueryNode.INPUT_TYPES()
        self.assertEqual(list(query_inputs["required"]), ["custom_speaker_id"])

        tts_node = seedance_nodes.VoiceCloneV3TTSNode()
        tts_inputs = tts_node.INPUT_TYPES()
        self.assertIn("voice_instruction", tts_inputs["optional"])
        self.assertIn("previous_context", tts_inputs["optional"])
        with self.assertRaisesRegex(ValueError, "138 CNY"):
            tts_node.synthesize("测试", "custom_cn_20260720_a1b2c3d4", confirm_activation_fee=False)

    def test_custom_speaker_id_and_demo_text_validation(self):
        valid = "custom_cn_20260720_a1b2c3d4"
        self.assertEqual(seedance_nodes._validate_custom_speaker_id(valid), valid)
        with self.assertRaisesRegex(ValueError, "8-256"):
            seedance_nodes._validate_custom_speaker_id("bad")
        with self.assertRaisesRegex(ValueError, "reserved"):
            seedance_nodes._validate_custom_speaker_id("S_reserved_voice")
        with self.assertRaisesRegex(ValueError, "4-300"):
            seedance_nodes._validate_demo_text("短")

    def test_voice_training_wav_is_mono(self):
        waveform = numpy.stack(
            [numpy.full(800, 0.25, dtype=numpy.float32), numpy.full(800, -0.25, dtype=numpy.float32)]
        )[numpy.newaxis, :, :]
        wav_bytes = seedance_nodes._audio_to_wav_bytes({"waveform": waveform, "sample_rate": 16000})
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getframerate(), 16000)

    def test_voice_demo_download_prefers_seed_icl_2_model(self):
        client = mock.Mock()
        client.download_audio.return_value = b"demo-bytes"
        result = {
            "demo_audio": "https://example.com/v1-top.wav",
            "speaker_status": [
                {"model_type": 1, "demo_audio": "https://example.com/v1.wav"},
                {"model_type": 5, "demo_audio": "https://example.com/v2.wav"},
            ],
        }
        with mock.patch.object(seedance_nodes, "_decode_audio_bytes", return_value={"sample_rate": 24000}):
            audio = seedance_nodes._download_demo_audio(client, result, required=True)
        client.download_audio.assert_called_once_with("https://example.com/v2.wav")
        self.assertEqual(audio["sample_rate"], 24000)

    def test_speech_permission_error_explains_required_services(self):
        error = seedance_nodes.SpeechAPIError(
            403,
            code=45000030,
            message="requested resource not granted",
            logid="log-voice-permission",
        )
        message = seedance_nodes._speech_api_error_message(error)
        self.assertIn("Voice Clone 2.0", message)
        self.assertIn("postpaid voice service", message)
        self.assertIn("log-voice-permission", message)

    def test_speech_api_key_is_resolved_independently(self):
        with mock.patch.dict(os.environ, {"SEEDANCE_SPEECH_API_KEY": "speech-env-key"}, clear=False):
            self.assertEqual(seedance_nodes._resolve_speech_api_key({}), "speech-env-key")
            self.assertEqual(
                seedance_nodes._resolve_speech_api_key({"speech_api_key": "speech-json-key", "api_key": "ark-key"}),
                "speech-json-key",
            )

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
                        "oss_endpoint": "oss-cn-hangzhou.aliyuncs.com",
                        "oss_access_key_id": "oss-ak",
                        "oss_access_key_secret": "oss-sk",
                        "oss_bucket": "bucket-a",
                        "oss_prefix": "seedance/tmp",
                        "oss_signed_url_expires": 1800,
                        "access_key_id": "json-ak",
                        "secret_access_key": "json-sk",
                        "asset_base_url": "https://json.example.com",
                        "asset_project_name": "json-project",
                        "asset_poll_interval": 6.5,
                        "asset_timeout": 95,
                        "asset_wait_timeout": 700,
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
                            public_upload_config = seedance_nodes._create_public_upload_config()
                            asset_client = seedance_nodes._create_asset_client()
                            asset_project_name = seedance_nodes._create_asset_project_name()

            self.assertEqual(client.api_key, "json-key")
            self.assertEqual(client.timeout, 90)
            self.assertEqual(client.base_url, "https://json.example.com/api/v3")
            self.assertEqual(client.poll_interval, 12.5)
            self.assertEqual(upload_timeout, 140)
            self.assertEqual(
                public_upload_config,
                {
                    "oss_endpoint": "oss-cn-hangzhou.aliyuncs.com",
                    "oss_access_key_id": "oss-ak",
                    "oss_access_key_secret": "oss-sk",
                    "oss_bucket": "bucket-a",
                    "oss_prefix": "seedance/tmp",
                    "oss_signed_url_expires": 1800,
                },
            )
            self.assertEqual(asset_client.access_key_id, "json-ak")
            self.assertEqual(asset_client.secret_access_key, "json-sk")
            self.assertEqual(asset_client.base_url, "https://json.example.com")
            self.assertEqual(asset_client.timeout, 95)
            self.assertEqual(asset_client.poll_interval, 6.5)
            self.assertEqual(asset_client.wait_timeout, 700)
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
                    "OSS_ENDPOINT": "oss-cn-beijing.aliyuncs.com",
                    "OSS_ACCESS_KEY_ID": "env-oss-ak",
                    "OSS_ACCESS_KEY_SECRET": "env-oss-sk",
                    "OSS_BUCKET": "env-bucket",
                    "OSS_PREFIX": "env-prefix",
                    "OSS_SIGNED_URL_EXPIRES": "2400",
                    "ARK_ACCESS_KEY_ID": "env-ak",
                    "ARK_SECRET_ACCESS_KEY": "env-sk",
                    "SEEDANCE_ASSET_BASE_URL": "https://asset-env.example.com/",
                    "SEEDANCE_ASSET_POLL_INTERVAL": "7",
                    "SEEDANCE_ASSET_TIMEOUT": "80",
                    "SEEDANCE_ASSET_WAIT_TIMEOUT": "800",
                    "SEEDANCE_ASSET_PROJECT_NAME": "env-project",
                },
                clear=False,
            ):
                with mock.patch.object(seedance_nodes, "CONFIG_JSON_PATH", json_path):
                    with mock.patch.object(seedance_nodes, "Client", FakeResolvedClient):
                        with mock.patch.object(seedance_nodes, "AssetClient", FakeAssetClient):
                            client = seedance_nodes._create_runtime_client()
                            upload_timeout = seedance_nodes._create_upload_timeout()
                            public_upload_config = seedance_nodes._create_public_upload_config()
                            asset_client = seedance_nodes._create_asset_client()
                            asset_project_name = seedance_nodes._create_asset_project_name()

            self.assertEqual(client.api_key, "env-key")
            self.assertEqual(client.timeout, 75)
            self.assertEqual(client.base_url, "https://env.example.com/api/v3")
            self.assertEqual(client.poll_interval, 20.0)
            self.assertEqual(upload_timeout, 150)
            self.assertEqual(
                public_upload_config,
                {
                    "oss_endpoint": "oss-cn-beijing.aliyuncs.com",
                    "oss_access_key_id": "env-oss-ak",
                    "oss_access_key_secret": "env-oss-sk",
                    "oss_bucket": "env-bucket",
                    "oss_prefix": "env-prefix",
                    "oss_signed_url_expires": 2400,
                },
            )
            self.assertEqual(asset_client.access_key_id, "env-ak")
            self.assertEqual(asset_client.secret_access_key, "env-sk")
            self.assertEqual(asset_client.base_url, "https://asset-env.example.com")
            self.assertEqual(asset_client.timeout, 80)
            self.assertEqual(asset_client.poll_interval, 7.0)
            self.assertEqual(asset_client.wait_timeout, 800)
            self.assertEqual(asset_project_name, "env-project")

    def test_las_runtime_uses_only_las_configuration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "config.local.json"
            json_path.write_text(
                json.dumps(
                    {
                        "api_provider": "las",
                        "las_api_key": "las-json-key",
                        "las_region": "cn-shanghai",
                        "api_key": "ark-key-that-must-not-be-used",
                        "access_key_id": "ark-ak-that-must-not-be-used",
                        "secret_access_key": "ark-sk-that-must-not-be-used",
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {**ENV_KEYS, "LAS_API_KEY": "las-env-key"}, clear=False):
                with mock.patch.object(seedance_nodes, "CONFIG_JSON_PATH", json_path):
                    with mock.patch.object(seedance_nodes, "Client", FakeResolvedClient):
                        client = seedance_nodes._create_runtime_client()

            self.assertEqual(client.api_key, "las-json-key")
            self.assertEqual(client.base_url, "https://operator.las.cn-shanghai.volces.com/api/v1")

    def test_las_asset_factory_uses_api_key_not_ark_aksk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "config.local.json"
            json_path.write_text(
                json.dumps(
                    {
                        "api_provider": "las",
                        "LAS_DEFAULT_API_KEY": "legacy-las-key",
                        "access_key_id": "ark-ak-that-must-not-be-used",
                        "secret_access_key": "ark-sk-that-must-not-be-used",
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(seedance_nodes, "CONFIG_JSON_PATH", json_path):
                client = seedance_nodes._create_asset_client()
        try:
            self.assertIsInstance(client, asset_api.LASAssetClient)
            self.assertEqual(client.api_key, "legacy-las-key")
        finally:
            client.close()

    def test_las_node_model_options_hide_mini(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "config.local.json"
            json_path.write_text(json.dumps({"api_provider": "las", "las_api_key": "test-key"}), encoding="utf-8")
            with mock.patch.object(seedance_nodes, "CONFIG_JSON_PATH", json_path):
                options = seedance_nodes.SeedanceTextNode.INPUT_TYPES()["required"]["model"][0]

        self.assertEqual(options, video_api.LAS_MODEL_OPTIONS)

    def test_invalid_api_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "api_provider must be either"):
            seedance_nodes._resolve_api_provider({"api_provider": "other"})

    def test_tmpfiles_url_is_converted_to_direct_download(self):
        self.assertEqual(
            upload_module._normalize_tmpfiles_download_url("http://tmpfiles.org/123/example.jpg"),
            "https://tmpfiles.org/dl/123/example.jpg",
        )

    def test_oss_object_key_uses_prefix_and_extension(self):
        object_key = upload_module._build_oss_object_key(
            "seedance/tmp",
            "clip.mp4",
            now=1700000000,
            token="abc12345",
        )
        self.assertEqual(object_key, "seedance/tmp/2023/11/14/1700000000-abc12345.mp4")

    def test_upload_file_to_public_url_prefers_oss_when_configured(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(b"video-bytes")

        try:
            config = {
                "oss_endpoint": "oss-cn-hangzhou.aliyuncs.com",
                "oss_access_key_id": "oss-ak",
                "oss_access_key_secret": "oss-sk",
                "oss_bucket": "bucket-a",
                "oss_prefix": "seedance/tmp",
                "oss_signed_url_expires": 1800,
            }
            with mock.patch.object(upload_module, "upload_file_to_oss", return_value="https://oss.example.com/file") as upload_oss:
                with mock.patch.object(upload_module, "upload_file_to_tmpfiles") as upload_tmpfiles:
                    result = upload_module.upload_file_to_public_url(temp_path, public_upload_config=config)
        finally:
            temp_path.unlink(missing_ok=True)

        self.assertEqual(result, "https://oss.example.com/file")
        upload_oss.assert_called_once()
        upload_tmpfiles.assert_not_called()

    def test_upload_file_to_public_url_falls_back_to_tmpfiles(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(b"image-bytes")

        try:
            with mock.patch.object(upload_module, "upload_file_to_tmpfiles", return_value="https://tmpfiles.org/dl/1/file.png") as upload_tmpfiles:
                result = upload_module.upload_file_to_public_url(temp_path, public_upload_config={})
        finally:
            temp_path.unlink(missing_ok=True)

        self.assertEqual(result, "https://tmpfiles.org/dl/1/file.png")
        upload_tmpfiles.assert_called_once()

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

    def test_asset_client_posts_create_asset_group_request(self):
        seen_requests = []

        def handler(request):
            seen_requests.append(request)
            return httpx.Response(200, json={"Result": {"Id": "group-123"}})

        client = asset_api.AssetClient(
            "ak-test",
            "sk-test",
            base_url="https://ark.cn-beijing.volcengineapi.com/",
            transport=httpx.MockTransport(handler),
        )
        try:
            result = client.create_asset_group(
                "group-name",
                description="group description",
                group_type="AIGC",
                project_name="project-a",
            )
        finally:
            client.close()

        self.assertEqual(result["Id"], "group-123")
        self.assertEqual(str(seen_requests[0].url), "https://ark.cn-beijing.volcengineapi.com/?Action=CreateAssetGroup&Version=2024-01-01")
        self.assertEqual(
            json.loads(seen_requests[0].content.decode("utf-8")),
            {
                "Name": "group-name",
                "Description": "group description",
                "GroupType": "AIGC",
                "ProjectName": "project-a",
            },
        )

    def test_las_asset_client_uses_bearer_open_endpoint(self):
        seen_requests = []

        def handler(request):
            seen_requests.append(request)
            return httpx.Response(200, json={"Result": {"Id": "Asset-123"}})

        client = asset_api.LASAssetClient(
            "las-test",
            transport=httpx.MockTransport(handler),
        )
        try:
            result = client.create_asset("group-123", "https://example.com/source.png", project_name="project-a")
        finally:
            client.close()

        self.assertEqual(result["Id"], "Asset-123")
        self.assertEqual(
            str(seen_requests[0].url),
            "https://operator.las.cn-shanghai.volces.com/api/v1/open/CreateAsset",
        )
        self.assertEqual(seen_requests[0].headers["Authorization"], "Bearer las-test")
        self.assertNotIn("X-Date", seen_requests[0].headers)

    def test_asset_client_posts_validation_session_actions(self):
        seen_requests = []

        def handler(request):
            seen_requests.append(request)
            if request.url.params["Action"] == "CreateVisualValidateSession":
                return httpx.Response(200, json={"Result": {"BytedToken": "token-123", "H5Link": "https://h5.example.com"}})
            return httpx.Response(200, json={"Result": {"GroupId": "group-123"}})

        client = asset_api.AssetClient(
            "ak-test",
            "sk-test",
            base_url="https://ark.cn-beijing.volcengineapi.com/",
            transport=httpx.MockTransport(handler),
        )
        try:
            session = client.create_visual_validate_session(
                "https://comfy.example.com/seedance/assets/validation/callback",
                project_name="project-a",
            )
            result = client.get_visual_validate_result("token-123", project_name="project-a")
        finally:
            client.close()

        self.assertEqual(session["BytedToken"], "token-123")
        self.assertEqual(result["GroupId"], "group-123")
        self.assertEqual(
            [request.url.params["Action"] for request in seen_requests],
            ["CreateVisualValidateSession", "GetVisualValidateResult"],
        )
        self.assertEqual(
            json.loads(seen_requests[0].content.decode("utf-8")),
            {
                "CallbackURL": "https://comfy.example.com/seedance/assets/validation/callback",
                "ProjectName": "project-a",
            },
        )
        self.assertEqual(
            json.loads(seen_requests[1].content.decode("utf-8")),
            {"BytedToken": "token-123", "ProjectName": "project-a"},
        )

    def test_asset_wait_has_total_timeout(self):
        client = asset_api.AssetClient(
            "ak-test",
            "sk-test",
            poll_interval=0,
            wait_timeout=1,
        )
        try:
            with mock.patch.object(client, "get_asset", return_value={"Status": "Processing"}):
                with mock.patch.object(asset_api.time, "monotonic", side_effect=[10.0, 11.1]):
                    with self.assertRaisesRegex(TimeoutError, "Timed out after 1 seconds"):
                        client.wait_for_asset_active("asset-123")
        finally:
            client.close()

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

    def test_las_rejects_mini_model(self):
        with self.assertRaisesRegex(ValueError, "las model must be one of"):
            video_api.build_generation_payload(
                "doubao-seedance-2-0-mini-260615",
                "A prompt.",
                "720p",
                "5",
                "adaptive",
                provider="las",
            )

    def test_asset_uri_accepts_las_uppercase_asset_id(self):
        payload = video_api.build_asset_image_reference_payload("asset://Asset-2026-test")
        self.assertEqual(payload["image_url"]["url"], "asset://Asset-2026-test")

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

    def test_video_reference_accepts_asset_uri(self):
        payload = video_api.build_video_reference_payload("asset://asset-20260624155748-cb5d4")
        self.assertEqual(payload["video_url"]["url"], "asset://asset-20260624155748-cb5d4")

    def test_audio_reference_rejects_invalid_url(self):
        with self.assertRaisesRegex(ValueError, "audio_url must be a valid http or https URL."):
            video_api.build_audio_reference_payload("file:///tmp/test.mp3")

    def test_audio_reference_accepts_asset_uri(self):
        payload = video_api.build_audio_reference_payload("asset://asset-20260624155748-cb5d4")
        self.assertEqual(payload["audio_url"]["url"], "asset://asset-20260624155748-cb5d4")

    def test_audio_waveform_is_written_as_pcm_wav_without_torchcodec(self):
        waveform = numpy.array(
            [
                [-1.0, 0.0, 1.0],
                [0.5, -0.5, 0.25],
            ],
            dtype=numpy.float32,
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            temp_path = Path(handle.name)

        try:
            seedance_nodes._write_audio_waveform_wav(temp_path, waveform, 44100)
            with wave.open(str(temp_path), "rb") as wav_file:
                self.assertEqual(wav_file.getnchannels(), 2)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.getframerate(), 44100)
                self.assertEqual(wav_file.getnframes(), 3)
        finally:
            temp_path.unlink(missing_ok=True)

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
                with mock.patch.object(
                    seedance_nodes,
                    "_upload_video_reference",
                    return_value="https://example.com/reference.mp4",
                ):
                    with mock.patch.object(
                        seedance_nodes,
                        "_upload_audio_reference",
                        return_value="https://example.com/reference.wav",
                    ):
                        result = seedance_nodes.SeedanceFirstFrameNode().generate(
                            "doubao-seedance-2-0-fast-260128",
                            "",
                            "720p",
                            "5",
                            "adaptive",
                            True,
                            False,
                            image=object(),
                            reference_video=FakeVideoReference(),
                            reference_audio={"waveform": "fake-waveform", "sample_rate": 44100},
                        )

        request_payload = fake_client.calls[0][2]["json"]
        self.assertNotIn("prompt", request_payload)
        self.assertNotIn("extra_body", request_payload)
        self.assertEqual(
            [item["role"] for item in request_payload["content"]],
            ["first_frame", "reference_video", "reference_audio"],
        )
        input_types = seedance_nodes.SeedanceFirstFrameNode.INPUT_TYPES()
        self.assertEqual(input_types["optional"]["reference_video"], ("VIDEO",))
        self.assertEqual(input_types["optional"]["reference_audio"], ("AUDIO",))
        self.assertEqual(input_types["optional"]["image_asset_uri"][0], "STRING")
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
        input_types = seedance_nodes.SeedanceFirstLastFrameNode.INPUT_TYPES()
        self.assertEqual(input_types["optional"]["first_image_asset_uri"][0], "STRING")
        self.assertEqual(result["result"][1], "video-123")

    def test_first_frame_node_accepts_asset_uri_inputs(self):
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
            result = seedance_nodes.SeedanceFirstFrameNode().generate(
                "doubao-seedance-2-0-fast-260128",
                "",
                "720p",
                "5",
                "adaptive",
                True,
                False,
                image_asset_uri="asset://asset-image-1",
                reference_video_asset_uri="asset://asset-video-1",
                reference_audio_asset_uri="asset://asset-audio-1",
            )

        request_payload = fake_client.calls[0][2]["json"]
        self.assertEqual(
            [item[item["type"]]["url"] for item in request_payload["content"]],
            ["asset://asset-image-1", "asset://asset-video-1", "asset://asset-audio-1"],
        )
        self.assertEqual(result["result"][1], "video-123")

    def test_first_frame_node_rejects_conflicting_image_inputs(self):
        with self.assertRaisesRegex(ValueError, "image and image_asset_uri cannot both be provided"):
            seedance_nodes.SeedanceFirstFrameNode().generate(
                "doubao-seedance-2-0-fast-260128",
                "",
                "720p",
                "5",
                "adaptive",
                True,
                False,
                image=object(),
                image_asset_uri="asset://asset-image-1",
            )

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
                with mock.patch.object(
                    seedance_nodes,
                    "_upload_video_reference",
                    return_value="https://example.com/reference.mp4",
                ):
                    with mock.patch.object(
                        seedance_nodes,
                        "_upload_audio_reference",
                        return_value="https://example.com/reference.wav",
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
                            reference_video=FakeVideoReference(),
                            reference_audio={"waveform": "fake-waveform", "sample_rate": 44100},
                        )

        request_payload = fake_client.calls[0][2]["json"]
        self.assertEqual(
            request_payload["content"][0],
            {"type": "text", "text": "Use image 1 as the model, image 2 as the outfit, and image 3 as the background."},
        )
        self.assertEqual(
            [item["image_url"]["url"] for item in request_payload["content"][1:5]],
            [
                "asset://asset-20260624155748-cb5d4",
                "data:image/png;base64,b3V0Zml0",
                "asset://asset-20260625120000-bg001",
                "data:image/png;base64,ZXh0cmE=",
            ],
        )
        self.assertEqual(
            [item["role"] for item in request_payload["content"][1:]],
            [
                "reference_image",
                "reference_image",
                "reference_image",
                "reference_image",
                "reference_video",
                "reference_audio",
            ],
        )
        self.assertEqual(
            request_payload["content"][-2]["video_url"]["url"],
            "https://example.com/reference.mp4",
        )
        self.assertEqual(
            request_payload["content"][-1]["audio_url"]["url"],
            "https://example.com/reference.wav",
        )
        self.assertEqual(result["result"][1], "video-123")

    def test_asset_model_node_accepts_asset_uri_outfit_and_media_references(self):
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
            result = seedance_nodes.SeedanceAssetModelNode().generate(
                "doubao-seedance-2-0-fast-260128",
                "asset://asset-model-1",
                "Use image 1 as the model and image 2 as the outfit.",
                resolution="720p",
                duration="5",
                ratio="adaptive",
                generate_audio=True,
                watermark=False,
                outfit_asset_uri="asset://asset-outfit-1",
                reference_video_asset_uri="asset://asset-video-1",
                reference_audio_asset_uri="asset://asset-audio-1",
            )

        request_payload = fake_client.calls[0][2]["json"]
        self.assertEqual(
            [item[item["type"]]["url"] for item in request_payload["content"][1:]],
            ["asset://asset-model-1", "asset://asset-outfit-1", "asset://asset-video-1", "asset://asset-audio-1"],
        )
        self.assertEqual(result["result"][1], "video-123")

    def test_asset_model_default_prompt_uses_image_numbers_not_asset_id(self):
        input_types = seedance_nodes.SeedanceAssetModelNode.INPUT_TYPES()
        default_prompt = input_types["required"]["prompt"][1]["default"]
        self.assertIn("图片1", default_prompt)
        self.assertIn("图片2", default_prompt)
        self.assertNotIn("asset://", default_prompt)
        self.assertEqual(input_types["optional"]["reference_video"], ("VIDEO",))
        self.assertEqual(input_types["optional"]["reference_audio"], ("AUDIO",))
        self.assertEqual(input_types["optional"]["outfit_asset_uri"][0], "STRING")

    def test_create_asset_group_node_returns_group_metadata(self):
        fake_client = FakeAssetClient("ak", "sk")

        @contextmanager
        def fake_asset_client():
            yield fake_client

        with mock.patch.object(seedance_nodes, "_asset_client", fake_asset_client):
            result = seedance_nodes.SeedanceCreateAssetGroupNode().create(
                name="virtual-person-a",
                description="test group",
                project_name="default",
                group_type="AIGC",
            )

        self.assertEqual(fake_client.created_groups[0]["name"], "virtual-person-a")
        self.assertEqual(
            result["result"],
            ("group-202606250001-test", "default", "AIGC", "virtual-person-a"),
        )

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

    def test_upload_asset_node_supports_video_asset_type(self):
        fake_client = FakeAssetClient("ak", "sk")

        @contextmanager
        def fake_asset_client():
            yield fake_client

        with mock.patch.object(seedance_nodes, "_asset_client", fake_asset_client):
            with mock.patch.object(seedance_nodes, "_upload_video_file", return_value="https://oss.example.com/video.mp4"):
                result = seedance_nodes.SeedanceUploadAssetNode().upload(
                    group_id="group-202606250001-test",
                    asset_type="Video",
                    source_url="",
                    project_name="default",
                    name="demo-video",
                    wait_for_active=False,
                    video=FakeVideoReference(),
                )

        self.assertEqual(fake_client.created_assets[0]["asset_type"], "Video")
        self.assertEqual(result["result"][1], "group-202606250001-test")
        self.assertEqual(result["result"][3], "Video")

    def test_upload_asset_node_rejects_mismatched_local_input(self):
        with self.assertRaisesRegex(ValueError, "asset_type=Audio only accepts the audio input"):
            seedance_nodes.SeedanceUploadAssetNode().upload(
                group_id="group-202606250001-test",
                asset_type="Audio",
                source_url="",
                project_name="default",
                name="demo-audio",
                wait_for_active=False,
                image=object(),
            )

    def test_get_asset_node_returns_asset_metadata(self):
        fake_client = FakeAssetClient("ak", "sk")

        @contextmanager
        def fake_asset_client():
            yield fake_client

        with mock.patch.object(seedance_nodes, "_asset_client", fake_asset_client):
            result = seedance_nodes.SeedanceGetAssetNode().get(
                asset_id="asset-202606250001-test",
                project_name="default",
            )

        self.assertEqual(
            result["result"],
            (
                "asset://asset-202606250001-test",
                "group-202606250001-test",
                "Image",
                "Active",
                "https://example.com/asset.png",
                "asset-name",
            ),
        )

    def test_trusted_person_asset_node_returns_group_id_with_asset(self):
        fake_client = FakeAssetClient("ak", "sk")

        @contextmanager
        def fake_asset_client():
            yield fake_client

        with mock.patch.object(seedance_nodes, "_asset_client", fake_asset_client):
            result = seedance_nodes.SeedanceTrustedPersonAssetNode().upload(
                group_id="group-202607020001-test",
                source_url="https://example.com/person.png",
                project_name="default",
                wait_for_active=True,
            )

        self.assertEqual(
            result["result"],
            (
                "asset://asset-202606250001-test",
                "group-202607020001-test",
                "asset-202606250001-test",
                "Active",
                "https://example.com/asset.png",
            ),
        )

    def test_trusted_person_asset_node_requires_completed_validation(self):
        with self.assertRaisesRegex(ValueError, "Complete real-person validation"):
            seedance_nodes.SeedanceTrustedPersonAssetNode().upload(
                group_id="group-",
                source_url="https://example.com/person.png",
            )

    def test_trusted_person_asset_node_rejects_las_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "config.local.json"
            json_path.write_text(json.dumps({"api_provider": "las", "las_api_key": "test-key"}), encoding="utf-8")
            with mock.patch.object(seedance_nodes, "CONFIG_JSON_PATH", json_path):
                with self.assertRaisesRegex(ValueError, "not supported with api_provider='las'"):
                    seedance_nodes.SeedanceTrustedPersonAssetNode().upload("group-123", source_url="https://example.com/person.png")

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

    def test_multimodal_node_accepts_asset_uri_references(self):
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
            result = seedance_nodes.SeedanceMultimodalNode().generate(
                "doubao-seedance-2-0-fast-260128",
                "",
                "720p",
                "5",
                "adaptive",
                True,
                False,
                image_asset_uri_1="asset://asset-image-1",
                video_asset_uri_1="asset://asset-video-1",
                audio_asset_uri_1="asset://asset-audio-1",
            )

        request_payload = fake_client.calls[0][2]["json"]
        self.assertEqual(
            [item[item["type"]]["url"] for item in request_payload["content"]],
            ["asset://asset-image-1", "asset://asset-video-1", "asset://asset-audio-1"],
        )
        self.assertEqual(result["result"][1], "video-123")

    def test_multimodal_node_rejects_conflicting_local_and_asset_inputs(self):
        with self.assertRaisesRegex(ValueError, "image_1 and image_asset_uri_1 cannot both be provided"):
            seedance_nodes.SeedanceMultimodalNode().generate(
                "doubao-seedance-2-0-fast-260128",
                "",
                "720p",
                "5",
                "adaptive",
                True,
                False,
                image_1=object(),
                image_asset_uri_1="asset://asset-image-1",
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

    def test_preview_video_hides_save_controls(self):
        required = seedance_nodes.PreviewVideoNode.INPUT_TYPES()["required"]
        self.assertNotIn("filename_prefix", required)
        self.assertNotIn("save_output", required)
        self.assertEqual(
            seedance_nodes.DEFAULT_FILENAME_PREFIX,
            "Seedance_%year%%month%%day%_%hour%%minute%%second%",
        )

    def test_examples_are_valid_json(self):
        examples_dir = REPO_ROOT / "examples"
        example_files = sorted(examples_dir.glob("*.json"))
        self.assertGreaterEqual(len(example_files), 4)

        for example_path in example_files:
            data = json.loads(example_path.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)


if __name__ == "__main__":
    unittest.main()
