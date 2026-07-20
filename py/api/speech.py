import base64
import codecs
import json
import time
import uuid

import httpx


DEFAULT_SPEECH_BASE_URL = "https://openspeech.bytedance.com/api/v3/tts"
DEFAULT_SPEECH_REQUEST_TIMEOUT = 60
DEFAULT_SPEECH_POLL_INTERVAL = 5.0
DEFAULT_SPEECH_WAIT_TIMEOUT = 900
SPEECH_RESOURCE_ID = "seed-icl-2.0"
MAX_VOICE_SAMPLE_BYTES = 10 * 1024 * 1024

VOICE_STATUS_NAMES = {
    0: "NotFound",
    1: "Training",
    2: "Success",
    3: "Failed",
    4: "Active",
}


class SpeechAPIError(Exception):
    def __init__(self, status_code, code=None, message=None, logid="", payload=None):
        self.status_code = status_code
        self.code = code
        self.message = message or "Unknown speech API error."
        self.logid = str(logid or "")
        self.payload = payload
        super().__init__(self.__str__())

    def __str__(self):
        details = [f"Speech API request failed with HTTP {self.status_code}"]
        if self.code is not None:
            details.append(f"code={self.code}")
        details.append(self.message)
        if self.logid:
            details.append(f"logid={self.logid}")
        return ": ".join(details)

    @classmethod
    def from_response(cls, response):
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            payload = None

        if isinstance(payload, dict):
            code = payload.get("code")
            message = payload.get("message") or payload.get("detail")
        else:
            code = None
            message = response.text.strip()

        return cls(
            response.status_code,
            code=code,
            message=message,
            logid=response.headers.get("X-Tt-Logid", ""),
            payload=payload,
        )


class IncrementalJSONObjects:
    def __init__(self):
        self._utf8_decoder = codecs.getincrementaldecoder("utf-8")()
        self._json_decoder = json.JSONDecoder()
        self._buffer = ""

    def feed(self, chunk):
        self._buffer += self._utf8_decoder.decode(chunk, final=False)
        return self._drain()

    def finish(self):
        self._buffer += self._utf8_decoder.decode(b"", final=True)
        objects = self._drain()
        if self._buffer.strip():
            raise ValueError("Speech API returned an incomplete JSON object.")
        return objects

    def _drain(self):
        objects = []
        while True:
            self._buffer = self._buffer.lstrip()
            if not self._buffer:
                break
            try:
                value, end = self._json_decoder.raw_decode(self._buffer)
            except json.JSONDecodeError:
                break
            objects.append(value)
            self._buffer = self._buffer[end:]
        return objects


def voice_status_name(status):
    try:
        normalized = int(status)
    except (TypeError, ValueError):
        return str(status or "Unknown")
    return VOICE_STATUS_NAMES.get(normalized, f"Unknown({normalized})")


def validate_voice_sample(audio_bytes):
    if not audio_bytes:
        raise ValueError("audio sample is empty.")
    if len(audio_bytes) > MAX_VOICE_SAMPLE_BYTES:
        raise ValueError("audio sample must not exceed 10 MB.")


def build_voice_clone_payload(
    custom_speaker_id,
    audio_bytes,
    language,
    demo_text,
    reference_text="",
    enable_audio_denoise=False,
    disable_volume_normalization=False,
):
    validate_voice_sample(audio_bytes)
    payload = {
        "speaker_id": "custom_speaker_id",
        "custom_speaker_id": custom_speaker_id,
        "audio": {
            "data": base64.b64encode(audio_bytes).decode("ascii"),
            "format": "wav",
        },
        "language": int(language),
        "extra_params": {
            "demo_text": demo_text,
            "enable_audio_denoise": bool(enable_audio_denoise),
            "disable_volume_normalization": bool(disable_volume_normalization),
        },
    }
    if reference_text:
        payload["text"] = reference_text
    return payload


def build_voice_query_payload(custom_speaker_id):
    return {
        "speaker_id": "custom_speaker_id",
        "custom_speaker_id": custom_speaker_id,
    }


def build_tts_payload(
    text,
    custom_speaker_id,
    speech_rate=0,
    loudness_rate=0,
    pitch=0,
    explicit_language="",
    tone_fidelity=False,
    context_texts=None,
):
    additions = {
        "tone_fidelity": bool(tone_fidelity),
        "post_process": {"pitch": int(pitch)},
    }
    if explicit_language:
        additions["explicit_language"] = explicit_language
    normalized_contexts = [str(value).strip() for value in (context_texts or []) if str(value).strip()]
    if normalized_contexts:
        additions["context_texts"] = normalized_contexts

    return {
        "req_params": {
            "text": text,
            "speaker": custom_speaker_id,
            "audio_params": {
                "format": "pcm",
                "sample_rate": 24000,
                "speech_rate": int(speech_rate),
                "loudness_rate": int(loudness_rate),
            },
            "additions": json.dumps(additions, ensure_ascii=False),
        }
    }


class SpeechClient:
    def __init__(
        self,
        api_key,
        timeout=DEFAULT_SPEECH_REQUEST_TIMEOUT,
        base_url=DEFAULT_SPEECH_BASE_URL,
        poll_interval=DEFAULT_SPEECH_POLL_INTERVAL,
        wait_timeout=DEFAULT_SPEECH_WAIT_TIMEOUT,
        transport=None,
    ):
        api_key = str(api_key or "").strip()
        if not api_key:
            raise ValueError("speech_api_key is required.")

        self.api_key = api_key
        self.timeout = int(timeout)
        self.base_url = str(base_url or DEFAULT_SPEECH_BASE_URL).strip().rstrip("/")
        self.poll_interval = float(poll_interval)
        self.wait_timeout = int(wait_timeout)
        timeout_config = httpx.Timeout(connect=10.0, read=self.timeout, write=self.timeout, pool=self.timeout)
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_config,
            transport=transport,
            headers={"Content-Type": "application/json", "X-Api-Key": self.api_key},
        )

    @staticmethod
    def request_headers(resource_id=""):
        headers = {"X-Api-Request-Id": str(uuid.uuid4())}
        if resource_id:
            headers["X-Api-Resource-Id"] = resource_id
            headers["X-Control-Require-Usage-Tokens-Return"] = "*"
        return headers

    def _post_json(self, path, payload):
        try:
            response = self._client.post(path, json=payload, headers=self.request_headers())
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Speech API request timed out after {self.timeout}s for POST {path}.") from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Speech API request failed for POST {path}: {exc}") from exc

        if response.status_code != 200:
            raise SpeechAPIError.from_response(response)

        result = response.json()
        code = result.get("code") if isinstance(result, dict) else None
        if code not in {None, 0, 20000000}:
            raise SpeechAPIError(
                response.status_code,
                code=code,
                message=result.get("message"),
                logid=response.headers.get("X-Tt-Logid", ""),
                payload=result,
            )
        if isinstance(result, dict):
            result.setdefault("logid", response.headers.get("X-Tt-Logid", ""))
        return result

    def train_voice(self, payload):
        return self._post_json("/voice_clone", payload)

    def get_voice(self, custom_speaker_id):
        return self._post_json("/get_voice", build_voice_query_payload(custom_speaker_id))

    def wait_for_voice(self, custom_speaker_id):
        deadline = time.monotonic() + self.wait_timeout
        last_result = None
        while True:
            try:
                last_result = self.get_voice(custom_speaker_id)
            except SpeechAPIError as exc:
                message = str(exc.message or "").lower()
                resource_binding_pending = int(exc.code or 0) == 55000000 and (
                    "resource id is mismatched with speaker related resource" in message
                )
                if not resource_binding_pending or time.monotonic() >= deadline:
                    raise
                time.sleep(self.poll_interval)
                continue
            status = int(last_result.get("status", 0))
            if status in {2, 4}:
                return last_result
            if status == 3:
                raise SpeechAPIError(
                    200,
                    code=last_result.get("code"),
                    message=last_result.get("message") or "Voice training failed.",
                    logid=last_result.get("logid", ""),
                    payload=last_result,
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Voice training did not finish within {self.wait_timeout}s; "
                    f"last_status={voice_status_name(status)} custom_speaker_id={custom_speaker_id}."
                )
            time.sleep(self.poll_interval)

    def download_audio(self, url):
        try:
            response = self._client.get(url)
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Demo audio download timed out after {self.timeout}s.") from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Demo audio download failed: {exc}") from exc
        if response.status_code != 200:
            raise SpeechAPIError.from_response(response)
        return response.content

    def synthesize(self, payload):
        parser = IncrementalJSONObjects()
        audio_parts = []
        frames = []
        usage_text_words = 0
        logid = ""
        try:
            with self._client.stream(
                "POST",
                "/unidirectional",
                json=payload,
                headers=self.request_headers(SPEECH_RESOURCE_ID),
            ) as response:
                logid = response.headers.get("X-Tt-Logid", "")
                if response.status_code != 200:
                    response.read()
                    raise SpeechAPIError.from_response(response)
                for chunk in response.iter_bytes():
                    for frame in parser.feed(chunk):
                        audio_part, frame_usage = self._parse_tts_frame(frame, logid)
                        frames.append(self._summarize_tts_frame(frame))
                        if audio_part:
                            audio_parts.append(audio_part)
                        usage_text_words = max(usage_text_words, frame_usage)
                for frame in parser.finish():
                    audio_part, frame_usage = self._parse_tts_frame(frame, logid)
                    frames.append(self._summarize_tts_frame(frame))
                    if audio_part:
                        audio_parts.append(audio_part)
                    usage_text_words = max(usage_text_words, frame_usage)
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Speech synthesis timed out after {self.timeout}s.") from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Speech synthesis request failed: {exc}") from exc

        if not audio_parts:
            raise SpeechAPIError(200, message="Speech synthesis returned no audio data.", logid=logid, payload=frames)
        return b"".join(audio_parts), usage_text_words, {"logid": logid, "frames": frames}

    @staticmethod
    def _parse_tts_frame(frame, logid):
        if not isinstance(frame, dict):
            raise SpeechAPIError(200, message="Speech synthesis returned a non-object frame.", logid=logid, payload=frame)
        code = frame.get("code")
        if code not in {None, 0, 20000000}:
            raise SpeechAPIError(
                200,
                code=code,
                message=frame.get("message"),
                logid=logid,
                payload=frame,
            )
        data = frame.get("data")
        try:
            audio_part = base64.b64decode(data, validate=True) if data else b""
        except (ValueError, base64.binascii.Error) as exc:
            raise SpeechAPIError(200, code=code, message="Speech synthesis returned invalid base64 audio.", logid=logid) from exc
        usage = frame.get("usage") or {}
        return audio_part, int(usage.get("text_words") or 0)

    @staticmethod
    def _summarize_tts_frame(frame):
        summarized = dict(frame)
        data = summarized.pop("data", None)
        if isinstance(data, str):
            summarized["audio_base64_characters"] = len(data)
        return summarized

    def close(self):
        self._client.close()
