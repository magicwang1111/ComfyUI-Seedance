import base64
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

import httpx


ROOT_DIR = Path(__file__).resolve().parents[1]
SPEECH_PATH = ROOT_DIR / "py" / "api" / "speech.py"
SPEC = importlib.util.spec_from_file_location("seedance_speech_api", SPEECH_PATH)
speech = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(speech)


class ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks


class SpeechAPITests(unittest.TestCase):
    def test_voice_clone_payload_uses_postpaid_v3_shape(self):
        payload = speech.build_voice_clone_payload(
            "custom_cn_20260720_a1b2c3d4",
            b"RIFFwav-bytes",
            0,
            "你好，这是一段试听文本。",
            reference_text="参考文本",
            enable_audio_denoise=True,
        )
        self.assertEqual(payload["speaker_id"], "custom_speaker_id")
        self.assertEqual(payload["custom_speaker_id"], "custom_cn_20260720_a1b2c3d4")
        self.assertEqual(base64.b64decode(payload["audio"]["data"]), b"RIFFwav-bytes")
        self.assertEqual(payload["audio"]["format"], "wav")
        self.assertEqual(payload["language"], 0)
        self.assertEqual(payload["text"], "参考文本")
        self.assertTrue(payload["extra_params"]["enable_audio_denoise"])

    def test_voice_clone_payload_rejects_sample_over_10_mb(self):
        with self.assertRaisesRegex(ValueError, "10 MB"):
            speech.build_voice_clone_payload("custom_cn_20260720_a1b2c3d4", b"x" * (10 * 1024 * 1024 + 1), 0, "测试文本")

    def test_voice_query_payload_uses_custom_speaker_marker(self):
        self.assertEqual(
            speech.build_voice_query_payload("custom_cn_20260720_a1b2c3d4"),
            {
                "speaker_id": "custom_speaker_id",
                "custom_speaker_id": "custom_cn_20260720_a1b2c3d4",
            },
        )

    def test_tts_payload_is_pcm_seed_icl_compatible(self):
        payload = speech.build_tts_payload(
            "正式合成文本",
            "custom_cn_20260720_a1b2c3d4",
            speech_rate=10,
            loudness_rate=-5,
            pitch=2,
            explicit_language="zh-cn",
            tone_fidelity=True,
            context_texts=["上一句对话", "用悲伤的语气演绎"],
        )
        params = payload["req_params"]
        self.assertEqual(params["speaker"], "custom_cn_20260720_a1b2c3d4")
        self.assertEqual(params["audio_params"]["format"], "pcm")
        self.assertEqual(params["audio_params"]["sample_rate"], 24000)
        additions = json.loads(params["additions"])
        self.assertEqual(additions["explicit_language"], "zh-cn")
        self.assertEqual(additions["post_process"]["pitch"], 2)
        self.assertTrue(additions["tone_fidelity"])
        self.assertEqual(additions["context_texts"], ["上一句对话", "用悲伤的语气演绎"])
        self.assertNotIn("context_texts", params)

    def test_incremental_json_parser_handles_arbitrary_boundaries_and_no_newlines(self):
        raw = '{"message":"你好","data":"YQ=="}{"code":20000000}' .encode("utf-8")
        parser = speech.IncrementalJSONObjects()
        values = []
        for chunk in [raw[:5], raw[5:14], raw[14:17], raw[17:31], raw[31:]]:
            values.extend(parser.feed(chunk))
        values.extend(parser.finish())
        self.assertEqual(values[0]["message"], "你好")
        self.assertEqual(values[1]["code"], 20000000)

    def test_incremental_json_parser_rejects_incomplete_final_object(self):
        parser = speech.IncrementalJSONObjects()
        parser.feed(b'{"code":')
        with self.assertRaisesRegex(ValueError, "incomplete JSON"):
            parser.finish()

    def test_synthesize_aggregates_chunked_pcm_and_usage(self):
        first = json.dumps({"code": 0, "data": base64.b64encode(b"\x01\x00").decode("ascii")})
        second = json.dumps(
            {"code": 20000000, "message": "完成", "data": base64.b64encode(b"\x02\x00").decode("ascii"), "usage": {"text_words": 6}},
            ensure_ascii=False,
        )
        raw = (first + second).encode("utf-8")

        def handler(request):
            self.assertEqual(request.headers["X-Api-Key"], "test-key")
            self.assertNotIn("Authorization", request.headers)
            self.assertEqual(request.headers["X-Api-Resource-Id"], "seed-icl-2.0")
            self.assertEqual(request.headers["X-Control-Require-Usage-Tokens-Return"], "*")
            return httpx.Response(
                200,
                headers={"X-Tt-Logid": "log-123"},
                stream=ChunkStream([raw[:7], raw[7:31], raw[31:52], raw[52:]]),
            )

        client = speech.SpeechClient("test-key", transport=httpx.MockTransport(handler))
        try:
            audio, usage, result = client.synthesize({"req_params": {}})
        finally:
            client.close()
        self.assertEqual(audio, b"\x01\x00\x02\x00")
        self.assertEqual(usage, 6)
        self.assertEqual(result["logid"], "log-123")
        self.assertNotIn("data", result["frames"][0])

    def test_voice_request_uses_speech_key_and_unique_request_id_only(self):
        seen_request_ids = []

        def handler(request):
            self.assertEqual(request.headers["X-Api-Key"], "speech-only-key")
            self.assertNotIn("Authorization", request.headers)
            self.assertNotIn("X-Api-Resource-Id", request.headers)
            seen_request_ids.append(request.headers["X-Api-Request-Id"])
            return httpx.Response(200, json={"code": 0, "status": 1})

        client = speech.SpeechClient("speech-only-key", transport=httpx.MockTransport(handler))
        try:
            client.train_voice({"speaker_id": "custom_speaker_id"})
            client.get_voice("custom_cn_20260720_a1b2c3d4")
        finally:
            client.close()
        self.assertEqual(len(seen_request_ids), 2)
        self.assertNotEqual(seen_request_ids[0], seen_request_ids[1])

    def test_wait_for_voice_retries_transient_resource_binding_mismatch(self):
        client = speech.SpeechClient("test-key", poll_interval=0, wait_timeout=5)
        client.get_voice = mock.Mock(
            side_effect=[
                speech.SpeechAPIError(
                    500,
                    code=55000000,
                    message="resource ID is mismatched with speaker related resource",
                    logid="pending-log",
                ),
                {"status": 1},
                {"status": 2, "speaker_status": []},
            ]
        )
        try:
            with mock.patch.object(speech.time, "sleep"):
                result = client.wait_for_voice("custom_cn_20260720_a1b2c3d4")
        finally:
            client.close()
        self.assertEqual(result["status"], 2)
        self.assertEqual(client.get_voice.call_count, 3)

    def test_wait_for_voice_does_not_hide_other_server_errors(self):
        client = speech.SpeechClient("test-key", poll_interval=0, wait_timeout=5)
        expected = speech.SpeechAPIError(500, code=55000000, message="database unavailable")
        client.get_voice = mock.Mock(side_effect=expected)
        try:
            with self.assertRaises(speech.SpeechAPIError) as caught:
                client.wait_for_voice("custom_cn_20260720_a1b2c3d4")
        finally:
            client.close()
        self.assertIs(caught.exception, expected)

    def test_synthesize_rejects_error_frame_with_logid(self):
        raw = json.dumps({"code": 45000000, "message": "invalid speaker"}).encode("utf-8")

        def handler(_request):
            return httpx.Response(200, headers={"X-Tt-Logid": "log-error"}, stream=ChunkStream([raw]))

        client = speech.SpeechClient("test-key", transport=httpx.MockTransport(handler))
        try:
            with self.assertRaisesRegex(speech.SpeechAPIError, "log-error"):
                client.synthesize({"req_params": {}})
        finally:
            client.close()

    def test_synthesize_rejects_success_without_audio(self):
        raw = json.dumps({"code": 20000000, "message": "ok"}).encode("utf-8")

        def handler(_request):
            return httpx.Response(200, stream=ChunkStream([raw]))

        client = speech.SpeechClient("test-key", transport=httpx.MockTransport(handler))
        try:
            with self.assertRaisesRegex(speech.SpeechAPIError, "no audio data"):
                client.synthesize({"req_params": {}})
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
