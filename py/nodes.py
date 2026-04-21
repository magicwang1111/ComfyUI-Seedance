import json
import os
import urllib.parse
from contextlib import contextmanager
from pathlib import Path

import folder_paths

from .api import (
    Client,
    MODEL_OPTIONS,
    NODE_DURATION_OPTIONS,
    RATIO_OPTIONS,
    RESOLUTION_OPTIONS,
    VideoAPIError,
    build_audio_reference_payload,
    build_generation_payload,
    build_image_reference_payload,
    build_video_reference_payload,
    extract_result_video_url,
    extract_task_id,
    submit_video_generation,
    wait_for_video_completion,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_JSON_PATH = ROOT_DIR / "config.local.json"

NODE_PREFIX = "ComfyUI-Seedance"
NODE_CATEGORY = NODE_PREFIX
DEFAULT_FILENAME_PREFIX = NODE_PREFIX
DEFAULT_BASE_URL = "https://aihubmix.com"
DEFAULT_POLL_INTERVAL = 15.0
DEFAULT_REQUEST_TIMEOUT = 60


def _load_json_config():
    if not CONFIG_JSON_PATH.exists():
        return {}

    try:
        with CONFIG_JSON_PATH.open("r", encoding="utf-8") as handle:
            config_data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{CONFIG_JSON_PATH.name} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Failed to read {CONFIG_JSON_PATH.name}: {exc}") from exc

    if not isinstance(config_data, dict):
        raise ValueError(f"{CONFIG_JSON_PATH.name} must contain a top-level JSON object.")

    return config_data


def _json_value_present(config_data, key):
    if key not in config_data:
        return False

    value = config_data[key]
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _load_env_value(*keys):
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _parse_request_timeout(value):
    if isinstance(value, bool):
        raise ValueError("request_timeout must be an integer.")

    if isinstance(value, int):
        timeout = value
    else:
        try:
            timeout = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("request_timeout must be an integer.") from exc

    if timeout < 5:
        raise ValueError("request_timeout must be greater than or equal to 5.")

    return timeout


def _parse_poll_interval(value):
    if isinstance(value, bool):
        raise ValueError("poll_interval must be a number.")

    if isinstance(value, (int, float)):
        interval = float(value)
    else:
        try:
            interval = float(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("poll_interval must be a number.") from exc

    if interval <= 0:
        raise ValueError("poll_interval must be greater than 0.")

    return interval


def _normalize_base_url(value):
    normalized = str(value or "").strip().rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3].rstrip("/")
    return normalized or DEFAULT_BASE_URL


def _resolve_api_key(config_data):
    if _json_value_present(config_data, "api_key"):
        return str(config_data["api_key"]).strip()

    env_value = _load_env_value("SEEDANCE_API_KEY", "AIHUBMIX_API_KEY")
    if env_value:
        return env_value

    raise ValueError(
        "An api_key is required. Add api_key to config.local.json or set SEEDANCE_API_KEY or AIHUBMIX_API_KEY."
    )


def _resolve_base_url(config_data):
    if _json_value_present(config_data, "base_url"):
        return _normalize_base_url(config_data["base_url"])

    env_value = _load_env_value("SEEDANCE_BASE_URL", "AIHUBMIX_BASE_URL")
    if env_value:
        return _normalize_base_url(env_value)

    return DEFAULT_BASE_URL


def _resolve_poll_interval(config_data):
    if _json_value_present(config_data, "poll_interval"):
        return _parse_poll_interval(config_data["poll_interval"])

    env_value = _load_env_value("SEEDANCE_POLL_INTERVAL", "AIHUBMIX_POLL_INTERVAL")
    if env_value:
        return _parse_poll_interval(env_value)

    return DEFAULT_POLL_INTERVAL


def _resolve_request_timeout(config_data):
    if _json_value_present(config_data, "request_timeout"):
        return _parse_request_timeout(config_data["request_timeout"])

    env_value = _load_env_value("SEEDANCE_REQUEST_TIMEOUT", "AIHUBMIX_REQUEST_TIMEOUT")
    if env_value:
        return _parse_request_timeout(env_value)

    return DEFAULT_REQUEST_TIMEOUT


def _create_runtime_client():
    config_data = _load_json_config()
    return Client(
        _resolve_api_key(config_data),
        timeout=_resolve_request_timeout(config_data),
        base_url=_resolve_base_url(config_data),
        poll_interval=_resolve_poll_interval(config_data),
    )


@contextmanager
def _runtime_client():
    client = _create_runtime_client()
    try:
        yield client
    finally:
        client.close()


def _raise_with_api_guidance(exc):
    if exc.status_code in {401, 403}:
        raise ValueError(
            f"The video API rejected the request with {exc.status_code}. "
            "Check api_key, base_url, billing, and model availability."
        ) from exc

    if exc.status_code == 429:
        raise ValueError("AIHubMix rate limit exceeded (429). Wait and retry.") from exc

    raise ValueError(str(exc)) from exc


def _saved_result(filename, subfolder, folder_type):
    return {
        "filename": filename,
        "subfolder": subfolder,
        "type": folder_type,
    }


def _build_local_media_view_url(filename, subfolder, folder_type):
    query = [
        f"type={urllib.parse.quote(str(folder_type), safe='')}",
        f"filename={urllib.parse.quote(str(filename), safe='')}",
    ]
    if subfolder:
        query.append(f"subfolder={urllib.parse.quote(str(subfolder), safe='')}")
    return "/api/view?" + "&".join(query)


def _submit_and_wait(client, model_name, payload):
    try:
        submission = submit_video_generation(client, model_name, payload)
    except VideoAPIError as exc:
        _raise_with_api_guidance(exc)

    task_id = extract_task_id(client, submission)

    try:
        task_info = wait_for_video_completion(client, task_id)
    except VideoAPIError as exc:
        _raise_with_api_guidance(exc)

    return task_id, task_info


def _build_video_result(client, task_id, task_info):
    remote_video_url = extract_result_video_url(client, task_id, task_info)
    return {"result": (remote_video_url, task_id, "")}


def _build_preview_result(video_url, filename_prefix, save_output):
    if isinstance(video_url, list):
        video_url = video_url[0] if video_url else ""

    video_url = str(video_url or "").strip()
    if not video_url:
        raise ValueError("video_url is required.")

    if not save_output:
        return {
            "ui": {"video_url": [video_url]},
            "result": ("",),
        }

    output_dir = folder_paths.get_output_directory()
    full_output_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(filename_prefix, output_dir)
    saved_name = f"{filename}_{counter:05}_.mp4"
    file_path = os.path.join(full_output_folder, saved_name)
    local_preview_url = _build_local_media_view_url(saved_name, subfolder, "output")

    with _runtime_client() as client:
        client.download_to_file(video_url, file_path)

    return {
        "ui": {
            "images": [_saved_result(saved_name, subfolder, "output")],
            "video_url": [local_preview_url],
            "animated": (True,),
        },
        "result": (file_path,),
    }


def _build_generation_result(model, prompt, resolution, duration, ratio, generate_audio, watermark, content=None):
    with _runtime_client() as client:
        payload = build_generation_payload(
            model,
            prompt,
            resolution,
            duration,
            ratio,
            generate_audio=generate_audio,
            watermark=watermark,
            content=content,
        )
        task_id, task_info = _submit_and_wait(client, model, payload)
        print(f"[{NODE_PREFIX}] completed {model} task_id={task_id}")
        return _build_video_result(client, task_id, task_info)


def _common_generation_inputs():
    return {
        "model": (MODEL_OPTIONS, {"default": "doubao-seedance-2-0-fast-260128"}),
        "prompt": ("STRING", {"multiline": True, "default": ""}),
        "resolution": (RESOLUTION_OPTIONS, {"default": "720p"}),
        "duration": (NODE_DURATION_OPTIONS, {"default": "5"}),
        "ratio": (RATIO_OPTIONS, {"default": "adaptive"}),
        "generate_audio": ("BOOLEAN", {"default": True}),
        "watermark": ("BOOLEAN", {"default": False}),
    }


def _multimodal_optional_inputs():
    inputs = {}

    for index in range(1, 10):
        inputs[f"image_url_{index}"] = ("STRING", {"default": ""})

    for index in range(1, 4):
        inputs[f"video_url_{index}"] = ("STRING", {"default": ""})
        inputs[f"audio_url_{index}"] = ("STRING", {"default": ""})

    return inputs


def _collect_reference_content(image_urls, video_urls, audio_urls):
    content = []

    for image_url in image_urls:
        if str(image_url or "").strip():
            content.append(build_image_reference_payload(image_url))

    for video_url in video_urls:
        if str(video_url or "").strip():
            content.append(build_video_reference_payload(video_url))

    for audio_url in audio_urls:
        if str(audio_url or "").strip():
            content.append(build_audio_reference_payload(audio_url))

    if not content:
        raise ValueError("At least one image URL, video URL, or audio URL reference is required.")

    return content


class SeedanceTextNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("url", "video_id", "file_path")
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": _common_generation_inputs()}

    def generate(self, model, prompt, resolution, duration, ratio, generate_audio, watermark):
        return _build_generation_result(
            model,
            prompt,
            resolution,
            duration,
            ratio,
            generate_audio,
            watermark,
        )


class SeedanceMultimodalNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("url", "video_id", "file_path")
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": _common_generation_inputs(),
            "optional": _multimodal_optional_inputs(),
        }

    def generate(
        self,
        model,
        prompt,
        resolution,
        duration,
        ratio,
        generate_audio,
        watermark,
        image_url_1="",
        image_url_2="",
        image_url_3="",
        image_url_4="",
        image_url_5="",
        image_url_6="",
        image_url_7="",
        image_url_8="",
        image_url_9="",
        video_url_1="",
        video_url_2="",
        video_url_3="",
        audio_url_1="",
        audio_url_2="",
        audio_url_3="",
    ):
        content = _collect_reference_content(
            [
                image_url_1,
                image_url_2,
                image_url_3,
                image_url_4,
                image_url_5,
                image_url_6,
                image_url_7,
                image_url_8,
                image_url_9,
            ],
            [video_url_1, video_url_2, video_url_3],
            [audio_url_1, audio_url_2, audio_url_3],
        )
        return _build_generation_result(
            model,
            prompt,
            resolution,
            duration,
            ratio,
            generate_audio,
            watermark,
            content=content,
        )


class PreviewVideoNode:
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("file_path",)
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_url": ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": DEFAULT_FILENAME_PREFIX}),
                "save_output": ("BOOLEAN", {"default": True}),
            }
        }

    def run(self, video_url, filename_prefix=DEFAULT_FILENAME_PREFIX, save_output=True):
        return _build_preview_result(video_url, filename_prefix, save_output)
