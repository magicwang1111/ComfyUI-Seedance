import json
import os
import tempfile
import urllib.parse
import wave
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

import folder_paths
import numpy
import PIL.Image

from .api import (
    AssetAPIError,
    AssetClient,
    LASAssetClient,
    Client,
    DEFAULT_ASSET_BASE_URL,
    DEFAULT_ASSET_GROUP_TYPE,
    DEFAULT_ASSET_POLL_INTERVAL,
    DEFAULT_ASSET_TIMEOUT,
    DEFAULT_ASSET_WAIT_TIMEOUT,
    DEFAULT_OSS_SIGNED_URL_EXPIRES,
    DEFAULT_UPLOAD_TIMEOUT,
    IMAGE_DATA_URL_MAX_SIZE_BYTES,
    MODEL_OPTIONS,
    LAS_MODEL_OPTIONS,
    NODE_DURATION_OPTIONS,
    RATIO_OPTIONS,
    RESOLUTION_OPTIONS,
    VideoAPIError,
    build_audio_reference_payload,
    build_asset_image_reference_payload,
    build_first_frame_payload,
    build_generation_payload,
    build_image_reference_payload,
    build_last_frame_payload,
    build_video_reference_payload,
    asset_uri_from_id,
    extract_result_video_url,
    extract_task_id,
    file_to_data_url,
    submit_video_generation,
    upload_file_to_public_url,
    wait_for_video_completion,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_JSON_PATH = ROOT_DIR / "config.local.json"

NODE_PREFIX = "ComfyUI-Seedance"
NODE_CATEGORY = NODE_PREFIX
DEFAULT_FILENAME_PREFIX = "Seedance_%year%%month%%day%_%hour%%minute%%second%"
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_LAS_BASE_URL = "https://operator.las.cn-shanghai.volces.com/api/v1"
DEFAULT_POLL_INTERVAL = 15.0
DEFAULT_REQUEST_TIMEOUT = 60
DEFAULT_UPLOAD_TIMEOUT_SECONDS = DEFAULT_UPLOAD_TIMEOUT
DEFAULT_ASSET_PROJECT_NAME = "default"
ASSET_TYPE_OPTIONS = ["Image", "Video", "Audio"]
DEFAULT_ASSET_MODEL_PROMPT = (
    "图片1中的模特穿上图片2中的服装，保持图片1的人脸身份、发型和身材特征一致，"
    "服装款式、颜色、材质严格参考图片2。生成电商模特展示视频，人物自然站立/转身展示服装，"
    "背景简洁，画面干净。"
)


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
    return normalized or DEFAULT_BASE_URL


def _resolve_api_provider(config_data):
    provider = str(config_data.get("api_provider") or "ark").strip().lower()
    if provider not in {"ark", "las"}:
        raise ValueError("api_provider must be either 'ark' or 'las'.")
    return provider


def _resolve_las_api_key(config_data):
    for key in ("las_api_key", "LAS_DEFAULT_API_KEY"):
        if _json_value_present(config_data, key):
            return str(config_data[key]).strip()
    env_value = _load_env_value("LAS_API_KEY")
    if env_value:
        return env_value
    raise ValueError("A las_api_key is required when api_provider is 'las'.")


def _resolve_api_key(config_data):
    if _json_value_present(config_data, "api_key"):
        return str(config_data["api_key"]).strip()

    env_value = _load_env_value("ARK_API_KEY", "SEEDANCE_API_KEY")
    if env_value:
        return env_value

    raise ValueError("An api_key is required. Add api_key to config.local.json or set ARK_API_KEY or SEEDANCE_API_KEY.")


def _resolve_base_url(config_data):
    if _resolve_api_provider(config_data) == "las":
        region = str(config_data.get("las_region") or "cn-shanghai").strip().lower()
        if region != "cn-shanghai":
            raise ValueError("las_region must be 'cn-shanghai'.")
        if _json_value_present(config_data, "las_base_url"):
            return str(config_data["las_base_url"]).strip().rstrip("/")
        return DEFAULT_LAS_BASE_URL
    if _json_value_present(config_data, "base_url"):
        return _normalize_base_url(config_data["base_url"])

    env_value = _load_env_value("SEEDANCE_BASE_URL")
    if env_value:
        return _normalize_base_url(env_value)

    return DEFAULT_BASE_URL


def _resolve_poll_interval(config_data):
    if _json_value_present(config_data, "poll_interval"):
        return _parse_poll_interval(config_data["poll_interval"])

    env_value = _load_env_value("SEEDANCE_POLL_INTERVAL")
    if env_value:
        return _parse_poll_interval(env_value)

    return DEFAULT_POLL_INTERVAL


def _resolve_request_timeout(config_data):
    if _json_value_present(config_data, "request_timeout"):
        return _parse_request_timeout(config_data["request_timeout"])

    env_value = _load_env_value("SEEDANCE_REQUEST_TIMEOUT")
    if env_value:
        return _parse_request_timeout(env_value)

    return DEFAULT_REQUEST_TIMEOUT


def _resolve_upload_timeout(config_data):
    if _json_value_present(config_data, "upload_timeout"):
        return _parse_request_timeout(config_data["upload_timeout"])

    env_value = _load_env_value("SEEDANCE_UPLOAD_TIMEOUT")
    if env_value:
        return _parse_request_timeout(env_value)

    return DEFAULT_UPLOAD_TIMEOUT_SECONDS


def _resolve_access_key_id(config_data):
    if _json_value_present(config_data, "access_key_id"):
        return str(config_data["access_key_id"]).strip()

    env_value = _load_env_value("ARK_ACCESS_KEY_ID", "VOLCENGINE_ACCESS_KEY_ID", "VOLC_ACCESS_KEY_ID")
    if env_value:
        return env_value

    raise ValueError(
        "An access_key_id is required for asset upload. "
        "Add access_key_id to config.local.json or set ARK_ACCESS_KEY_ID."
    )


def _resolve_secret_access_key(config_data):
    if _json_value_present(config_data, "secret_access_key"):
        return str(config_data["secret_access_key"]).strip()

    env_value = _load_env_value("ARK_SECRET_ACCESS_KEY", "VOLCENGINE_SECRET_ACCESS_KEY", "VOLC_SECRET_ACCESS_KEY")
    if env_value:
        return env_value

    raise ValueError(
        "A secret_access_key is required for asset upload. "
        "Add secret_access_key to config.local.json or set ARK_SECRET_ACCESS_KEY."
    )


def _resolve_asset_base_url(config_data):
    if _json_value_present(config_data, "asset_base_url"):
        return str(config_data["asset_base_url"]).strip().rstrip("/")

    env_value = _load_env_value("SEEDANCE_ASSET_BASE_URL", "ARK_ASSET_BASE_URL")
    if env_value:
        return env_value.rstrip("/")

    return DEFAULT_ASSET_BASE_URL


def _resolve_asset_poll_interval(config_data):
    if _json_value_present(config_data, "asset_poll_interval"):
        return _parse_poll_interval(config_data["asset_poll_interval"])

    env_value = _load_env_value("SEEDANCE_ASSET_POLL_INTERVAL", "ARK_ASSET_POLL_INTERVAL")
    if env_value:
        return _parse_poll_interval(env_value)

    return DEFAULT_ASSET_POLL_INTERVAL


def _resolve_asset_timeout(config_data):
    if _json_value_present(config_data, "asset_timeout"):
        return _parse_request_timeout(config_data["asset_timeout"])

    env_value = _load_env_value("SEEDANCE_ASSET_TIMEOUT", "ARK_ASSET_TIMEOUT")
    if env_value:
        return _parse_request_timeout(env_value)

    return DEFAULT_ASSET_TIMEOUT


def _resolve_asset_wait_timeout(config_data):
    if _json_value_present(config_data, "asset_wait_timeout"):
        return _parse_request_timeout(config_data["asset_wait_timeout"])

    env_value = _load_env_value("SEEDANCE_ASSET_WAIT_TIMEOUT", "ARK_ASSET_WAIT_TIMEOUT")
    if env_value:
        return _parse_request_timeout(env_value)

    return DEFAULT_ASSET_WAIT_TIMEOUT


def _resolve_asset_project_name(config_data):
    if _json_value_present(config_data, "asset_project_name"):
        return str(config_data["asset_project_name"]).strip()

    env_value = _load_env_value("SEEDANCE_ASSET_PROJECT_NAME", "ARK_PROJECT_NAME")
    if env_value:
        return env_value

    return DEFAULT_ASSET_PROJECT_NAME


def _create_runtime_client():
    config_data = _load_json_config()
    provider = _resolve_api_provider(config_data)
    return Client(
        _resolve_las_api_key(config_data) if provider == "las" else _resolve_api_key(config_data),
        timeout=_resolve_request_timeout(config_data),
        base_url=_resolve_base_url(config_data),
        poll_interval=_resolve_poll_interval(config_data),
    )


def _create_upload_timeout():
    config_data = _load_json_config()
    return _resolve_upload_timeout(config_data)


def _resolve_oss_endpoint(config_data):
    if _json_value_present(config_data, "oss_endpoint"):
        return str(config_data["oss_endpoint"]).strip()

    return _load_env_value("OSS_ENDPOINT")


def _resolve_oss_access_key_id(config_data):
    if _json_value_present(config_data, "oss_access_key_id"):
        return str(config_data["oss_access_key_id"]).strip()

    return _load_env_value("OSS_ACCESS_KEY_ID")


def _resolve_oss_access_key_secret(config_data):
    if _json_value_present(config_data, "oss_access_key_secret"):
        return str(config_data["oss_access_key_secret"]).strip()

    return _load_env_value("OSS_ACCESS_KEY_SECRET")


def _resolve_oss_bucket(config_data):
    if _json_value_present(config_data, "oss_bucket"):
        return str(config_data["oss_bucket"]).strip()

    return _load_env_value("OSS_BUCKET")


def _resolve_oss_prefix(config_data):
    if _json_value_present(config_data, "oss_prefix"):
        return str(config_data["oss_prefix"]).strip()

    return _load_env_value("OSS_PREFIX")


def _resolve_oss_signed_url_expires(config_data):
    if _json_value_present(config_data, "oss_signed_url_expires"):
        return _parse_request_timeout(config_data["oss_signed_url_expires"])

    env_value = _load_env_value("OSS_SIGNED_URL_EXPIRES")
    if env_value:
        return _parse_request_timeout(env_value)

    return DEFAULT_OSS_SIGNED_URL_EXPIRES


def _create_public_upload_config():
    config_data = _load_json_config()
    return {
        "oss_endpoint": _resolve_oss_endpoint(config_data),
        "oss_access_key_id": _resolve_oss_access_key_id(config_data),
        "oss_access_key_secret": _resolve_oss_access_key_secret(config_data),
        "oss_bucket": _resolve_oss_bucket(config_data),
        "oss_prefix": _resolve_oss_prefix(config_data),
        "oss_signed_url_expires": _resolve_oss_signed_url_expires(config_data),
    }


def _create_asset_client():
    config_data = _load_json_config()
    if _resolve_api_provider(config_data) == "las":
        return LASAssetClient(
            _resolve_las_api_key(config_data),
            base_url=_resolve_base_url(config_data),
            timeout=_resolve_asset_timeout(config_data),
            poll_interval=_resolve_asset_poll_interval(config_data),
            wait_timeout=_resolve_asset_wait_timeout(config_data),
        )
    return AssetClient(
        _resolve_access_key_id(config_data),
        _resolve_secret_access_key(config_data),
        base_url=_resolve_asset_base_url(config_data),
        timeout=_resolve_asset_timeout(config_data),
        poll_interval=_resolve_asset_poll_interval(config_data),
        wait_timeout=_resolve_asset_wait_timeout(config_data),
    )


def _create_asset_project_name():
    config_data = _load_json_config()
    return _resolve_asset_project_name(config_data)


@contextmanager
def _runtime_client():
    client = _create_runtime_client()
    try:
        yield client
    finally:
        client.close()


@contextmanager
def _asset_client():
    client = _create_asset_client()
    try:
        yield client
    finally:
        client.close()


def _raise_with_api_guidance(exc):
    provider = _resolve_api_provider(_load_json_config())
    if exc.status_code in {401, 403}:
        credential_name = "las_api_key" if provider == "las" else "api_key"
        raise ValueError(
            f"The video API rejected the request with {exc.status_code}. "
            f"Check {credential_name}, base_url, billing, and model availability."
        ) from exc

    if exc.status_code == 429:
        raise ValueError("Volcengine Ark rate limit exceeded (429). Wait and retry.") from exc

    raise ValueError(str(exc)) from exc


def _raise_with_asset_api_guidance(exc):
    provider = _resolve_api_provider(_load_json_config())
    if exc.status_code in {401, 403}:
        if provider == "las":
            raise ValueError(
                f"The LAS asset API rejected the request with {exc.status_code}. "
                "Check las_api_key, LAS asset permissions, and project_name."
            ) from exc
        raise ValueError(
            f"The asset API rejected the request with {exc.status_code}. "
            "Check access_key_id, secret_access_key, ArkFullAccess permission, and project_name."
        ) from exc

    if exc.status_code == 429:
        raise ValueError("Volcengine Ark asset API rate limit exceeded (429). Wait and retry.") from exc

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


def _submit_and_wait(client, model_name, payload, provider):
    try:
        submission = submit_video_generation(client, model_name, payload, provider=provider)
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

    filename_prefix = str(filename_prefix or "").strip() or DEFAULT_FILENAME_PREFIX
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


def _build_generation_result(
    model,
    prompt,
    resolution,
    duration,
    ratio,
    generate_audio,
    watermark,
    content=None,
    prompt_required=True,
):
    config_data = _load_json_config()
    provider = _resolve_api_provider(config_data)
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
            prompt_required=prompt_required,
            provider=provider,
        )
        task_id, task_info = _submit_and_wait(client, model, payload, provider)
        print(f"[{NODE_PREFIX}] succeeded {model} task_id={task_id}")
        return _build_video_result(client, task_id, task_info)


def _common_generation_inputs():
    config_data = _load_json_config()
    provider = _resolve_api_provider(config_data)
    return {
        "model": (LAS_MODEL_OPTIONS if provider == "las" else MODEL_OPTIONS, {"default": "doubao-seedance-2-0-fast-260128"}),
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
        inputs[f"image_{index}"] = ("IMAGE",)
        inputs[f"image_asset_uri_{index}"] = ("STRING", {"default": ""})

    for index in range(1, 4):
        inputs[f"video_{index}"] = ("VIDEO",)
        inputs[f"video_asset_uri_{index}"] = ("STRING", {"default": ""})
        inputs[f"audio_{index}"] = ("AUDIO",)
        inputs[f"audio_asset_uri_{index}"] = ("STRING", {"default": ""})

    return inputs


def _first_frame_inputs():
    return {
        "required": {
            **_common_generation_inputs(),
        },
        "optional": {
            "image": ("IMAGE",),
            "image_asset_uri": ("STRING", {"default": ""}),
            "reference_video": ("VIDEO",),
            "reference_video_asset_uri": ("STRING", {"default": ""}),
            "reference_audio": ("AUDIO",),
            "reference_audio_asset_uri": ("STRING", {"default": ""}),
        },
    }


def _first_last_frame_inputs():
    return {
        "required": {
            **_common_generation_inputs(),
        },
        "optional": {
            "first_image": ("IMAGE",),
            "first_image_asset_uri": ("STRING", {"default": ""}),
            "last_image": ("IMAGE",),
            "last_image_asset_uri": ("STRING", {"default": ""}),
        },
    }


def _asset_model_inputs():
    common_inputs = _common_generation_inputs()
    return {
        "required": {
            "model": common_inputs["model"],
            "model_asset_uri": ("STRING", {"default": "asset://asset-"}),
            "prompt": ("STRING", {"multiline": True, "default": DEFAULT_ASSET_MODEL_PROMPT}),
            "resolution": common_inputs["resolution"],
            "duration": common_inputs["duration"],
            "ratio": common_inputs["ratio"],
            "generate_audio": common_inputs["generate_audio"],
            "watermark": common_inputs["watermark"],
        },
        "optional": {
            "outfit_image": ("IMAGE",),
            "outfit_asset_uri": ("STRING", {"default": ""}),
            "extra_reference_asset_uri": ("STRING", {"default": ""}),
            "extra_reference_image": ("IMAGE",),
            "reference_video": ("VIDEO",),
            "reference_video_asset_uri": ("STRING", {"default": ""}),
            "reference_audio": ("AUDIO",),
            "reference_audio_asset_uri": ("STRING", {"default": ""}),
        },
    }


def _create_asset_group_inputs():
    return {
        "required": {
            "name": ("STRING", {"default": "seedance_asset_group"}),
            "description": ("STRING", {"default": "", "multiline": True}),
            "project_name": ("STRING", {"default": DEFAULT_ASSET_PROJECT_NAME}),
            "group_type": ("STRING", {"default": DEFAULT_ASSET_GROUP_TYPE}),
        }
    }


def _upload_asset_inputs():
    return {
        "required": {
            "group_id": ("STRING", {"default": "group-"}),
            "asset_type": (ASSET_TYPE_OPTIONS, {"default": "Image"}),
            "source_url": ("STRING", {"default": ""}),
            "project_name": ("STRING", {"default": DEFAULT_ASSET_PROJECT_NAME}),
            "name": ("STRING", {"default": ""}),
            "wait_for_active": ("BOOLEAN", {"default": True}),
        },
        "optional": {
            "image": ("IMAGE",),
            "video": ("VIDEO",),
            "audio": ("AUDIO",),
        },
    }


def _upload_image_asset_inputs():
    return {
        "required": {
            "group_id": ("STRING", {"default": "group-"}),
            "source_url": ("STRING", {"default": ""}),
            "project_name": ("STRING", {"default": DEFAULT_ASSET_PROJECT_NAME}),
            "name": ("STRING", {"default": ""}),
            "wait_for_active": ("BOOLEAN", {"default": True}),
        },
        "optional": {
            "image": ("IMAGE",),
        },
    }


def _get_asset_inputs():
    return {
        "required": {
            "asset_id": ("STRING", {"default": "asset-"}),
            "project_name": ("STRING", {"default": DEFAULT_ASSET_PROJECT_NAME}),
        }
    }


def _trusted_person_asset_inputs():
    return {
        "required": {
            "group_id": ("STRING", {"default": "group-"}),
            "callback_url": ("STRING", {"default": ""}),
            "source_url": ("STRING", {"default": ""}),
            "project_name": ("STRING", {"default": DEFAULT_ASSET_PROJECT_NAME}),
            "name": ("STRING", {"default": ""}),
            "wait_for_active": ("BOOLEAN", {"default": True}),
        },
        "optional": {
            "image": ("IMAGE",),
        },
    }


def _tensor_to_pil_image(image):
    if image is None:
        raise ValueError("image is required.")

    if isinstance(image, Iterable) and not hasattr(image, "ndim"):
        image = next(iter(image), None)

    if image is None:
        raise ValueError("image is required.")

    if getattr(image, "ndim", None) == 3:
        image = image.unsqueeze(0)

    np_imgs = numpy.clip(image.cpu().numpy() * 255.0, 0.0, 255.0).astype(numpy.uint8)
    return PIL.Image.fromarray(np_imgs[0])


def _upload_image_reference(image):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        temp_path = handle.name

    try:
        pil_image = _tensor_to_pil_image(image)
        pil_image.save(temp_path, format="PNG")
        return file_to_data_url(temp_path, "image/png", max_size_bytes=IMAGE_DATA_URL_MAX_SIZE_BYTES)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _upload_image_for_asset(image):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        temp_path = handle.name

    try:
        pil_image = _tensor_to_pil_image(image)
        pil_image.save(temp_path, format="PNG")
        return upload_file_to_public_url(
            temp_path,
            timeout=_create_upload_timeout(),
            public_upload_config=_create_public_upload_config(),
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _upload_video_file(video):
    if video is None:
        raise ValueError("video is required.")

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
        temp_path = handle.name

    try:
        video.save_to(temp_path)
        return upload_file_to_public_url(
            temp_path,
            timeout=_create_upload_timeout(),
            public_upload_config=_create_public_upload_config(),
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _upload_video_reference(video):
    return _upload_video_file(video)


def _write_audio_waveform_wav(file_path, waveform, sample_rate):
    if hasattr(waveform, "detach"):
        waveform = waveform.detach()
    if hasattr(waveform, "cpu"):
        waveform = waveform.cpu()
    if hasattr(waveform, "numpy"):
        waveform = waveform.numpy()

    samples = numpy.asarray(waveform, dtype=numpy.float32)
    if samples.ndim == 3:
        if samples.shape[0] == 0:
            raise ValueError("audio waveform batch is empty.")
        samples = samples[0]
    if samples.ndim == 1:
        samples = samples[numpy.newaxis, :]
    if samples.ndim != 2 or samples.shape[0] == 0 or samples.shape[1] == 0:
        raise ValueError("audio waveform must contain channels and samples.")

    try:
        normalized_sample_rate = int(sample_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError("audio sample_rate must be a positive integer.") from exc
    if normalized_sample_rate <= 0:
        raise ValueError("audio sample_rate must be a positive integer.")

    pcm_samples = numpy.rint(numpy.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(file_path), "wb") as wav_file:
        wav_file.setnchannels(pcm_samples.shape[0])
        wav_file.setsampwidth(2)
        wav_file.setframerate(normalized_sample_rate)
        wav_file.writeframes(pcm_samples.T.tobytes())


def _upload_audio_file(audio):
    if audio is None:
        raise ValueError("audio is required.")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        temp_path = handle.name

    try:
        _write_audio_waveform_wav(temp_path, audio["waveform"], audio["sample_rate"])
        return upload_file_to_public_url(
            temp_path,
            timeout=_create_upload_timeout(),
            public_upload_config=_create_public_upload_config(),
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _upload_audio_reference(audio):
    return _upload_audio_file(audio)


def _normalize_optional_string(value):
    return str(value or "").strip()


def _resolve_media_reference_url(local_value, asset_uri, local_input_name, asset_uri_name, upload_local, required=False):
    normalized_asset_uri = _normalize_optional_string(asset_uri)
    if local_value is not None and normalized_asset_uri:
        raise ValueError(f"{local_input_name} and {asset_uri_name} cannot both be provided.")

    if normalized_asset_uri:
        return normalized_asset_uri

    if local_value is not None:
        return upload_local(local_value)

    if required:
        raise ValueError(f"Either {local_input_name} or {asset_uri_name} is required.")

    return ""


def _build_first_frame_content(
    image=None,
    image_asset_uri="",
    reference_video=None,
    reference_video_asset_uri="",
    reference_audio=None,
    reference_audio_asset_uri="",
):
    first_frame_url = _resolve_media_reference_url(
        image,
        image_asset_uri,
        "image",
        "image_asset_uri",
        _upload_image_reference,
        required=True,
    )
    content = [build_first_frame_payload(first_frame_url)]

    reference_video_url = _resolve_media_reference_url(
        reference_video,
        reference_video_asset_uri,
        "reference_video",
        "reference_video_asset_uri",
        _upload_video_reference,
    )
    if reference_video_url:
        content.append(build_video_reference_payload(reference_video_url))

    reference_audio_url = _resolve_media_reference_url(
        reference_audio,
        reference_audio_asset_uri,
        "reference_audio",
        "reference_audio_asset_uri",
        _upload_audio_reference,
    )
    if reference_audio_url:
        content.append(build_audio_reference_payload(reference_audio_url))

    return content


def _build_first_last_frame_content(first_image=None, last_image=None, first_image_asset_uri="", last_image_asset_uri=""):
    first_frame_url = _resolve_media_reference_url(
        first_image,
        first_image_asset_uri,
        "first_image",
        "first_image_asset_uri",
        _upload_image_reference,
        required=True,
    )
    last_frame_url = _resolve_media_reference_url(
        last_image,
        last_image_asset_uri,
        "last_image",
        "last_image_asset_uri",
        _upload_image_reference,
        required=True,
    )
    return [
        build_first_frame_payload(first_frame_url),
        build_last_frame_payload(last_frame_url),
    ]


def _build_asset_model_content(
    model_asset_uri,
    outfit_image=None,
    outfit_asset_uri="",
    extra_reference_image=None,
    extra_reference_asset_uri="",
    reference_video=None,
    reference_video_asset_uri="",
    reference_audio=None,
    reference_audio_asset_uri="",
):
    outfit_url = _resolve_media_reference_url(
        outfit_image,
        outfit_asset_uri,
        "outfit_image",
        "outfit_asset_uri",
        _upload_image_reference,
        required=True,
    )
    content = [
        build_asset_image_reference_payload(model_asset_uri),
        build_image_reference_payload(outfit_url),
    ]

    extra_reference_asset_uri = _normalize_optional_string(extra_reference_asset_uri)
    if extra_reference_asset_uri:
        content.append(build_image_reference_payload(extra_reference_asset_uri))

    if extra_reference_image is not None:
        content.append(build_image_reference_payload(_upload_image_reference(extra_reference_image)))

    reference_video_url = _resolve_media_reference_url(
        reference_video,
        reference_video_asset_uri,
        "reference_video",
        "reference_video_asset_uri",
        _upload_video_reference,
    )
    if reference_video_url:
        content.append(build_video_reference_payload(reference_video_url))

    reference_audio_url = _resolve_media_reference_url(
        reference_audio,
        reference_audio_asset_uri,
        "reference_audio",
        "reference_audio_asset_uri",
        _upload_audio_reference,
    )
    if reference_audio_url:
        content.append(build_audio_reference_payload(reference_audio_url))

    return content


def _resolve_asset_source_url(asset_type, source_url, image=None, video=None, audio=None):
    source_url = str(source_url or "").strip()
    if source_url:
        return source_url

    normalized_type = str(asset_type or "Image").strip()
    provided_inputs = [
        ("image", image is not None),
        ("video", video is not None),
        ("audio", audio is not None),
    ]
    present_inputs = [name for name, is_present in provided_inputs if is_present]

    if normalized_type == "Image":
        if video is not None or audio is not None:
            raise ValueError("asset_type=Image only accepts the image input.")
        if image is None:
            raise ValueError("Either source_url or image is required for Image asset upload.")
        return _upload_image_for_asset(image)

    if normalized_type == "Video":
        if image is not None or audio is not None:
            raise ValueError("asset_type=Video only accepts the video input.")
        if video is None:
            raise ValueError("Either source_url or video is required for Video asset upload.")
        return _upload_video_file(video)

    if normalized_type == "Audio":
        if image is not None or video is not None:
            raise ValueError("asset_type=Audio only accepts the audio input.")
        if audio is None:
            raise ValueError("Either source_url or audio is required for Audio asset upload.")
        return _upload_audio_file(audio)

    if not present_inputs:
        raise ValueError("Either source_url or a matching local media input is required for asset upload.")
    raise ValueError(f"Unsupported asset_type: {normalized_type}")


def _build_asset_group_result(name, description, project_name, group_type):
    project_name = str(project_name or "").strip() or _create_asset_project_name()
    normalized_group_type = str(group_type or DEFAULT_ASSET_GROUP_TYPE).strip() or DEFAULT_ASSET_GROUP_TYPE

    with _asset_client() as client:
        try:
            group_info = client.create_asset_group(
                name=name,
                description=description,
                group_type=normalized_group_type,
                project_name=project_name,
            )
        except AssetAPIError as exc:
            _raise_with_asset_api_guidance(exc)

    group_id = str(group_info.get("Id") or "").strip()
    if not group_id:
        raise ValueError("CreateAssetGroup succeeded but did not return Id.")

    return {"result": (group_id, project_name, normalized_group_type, str(name or "").strip())}


def _build_asset_upload_result(group_id, asset_type, source_url, project_name, name, wait_for_active, image=None, video=None, audio=None):
    project_name = str(project_name or "").strip() or _create_asset_project_name()
    normalized_asset_type = str(asset_type or "Image").strip() or "Image"
    source_url = _resolve_asset_source_url(
        normalized_asset_type,
        source_url,
        image=image,
        video=video,
        audio=audio,
    )

    with _asset_client() as client:
        try:
            created_asset = client.create_asset(
                group_id=group_id,
                source_url=source_url,
                asset_type=normalized_asset_type,
                project_name=project_name,
                name=name,
            )
            asset_id = str(created_asset.get("Id") or "").strip()
            if not asset_id:
                raise ValueError("CreateAsset succeeded but did not return Id.")

            if wait_for_active:
                asset_info = client.wait_for_asset_active(asset_id, project_name=project_name)
                status = str(asset_info.get("Status") or "Active").strip()
                asset_url = str(asset_info.get("URL") or "").strip()
            else:
                status = str(created_asset.get("Status") or "Processing").strip()
                asset_url = str(created_asset.get("URL") or "").strip()
        except AssetAPIError as exc:
            _raise_with_asset_api_guidance(exc)

    return {"result": (asset_uri_from_id(asset_id), group_id, asset_id, normalized_asset_type, status, asset_url)}


def _build_get_asset_result(asset_id, project_name):
    project_name = str(project_name or "").strip() or _create_asset_project_name()

    with _asset_client() as client:
        try:
            asset_info = client.get_asset(asset_id, project_name=project_name)
        except AssetAPIError as exc:
            _raise_with_asset_api_guidance(exc)

    normalized_asset_id = str(asset_info.get("Id") or asset_id or "").strip()
    if not normalized_asset_id:
        raise ValueError("GetAsset did not return Id.")

    return {
        "result": (
            asset_uri_from_id(normalized_asset_id),
            str(asset_info.get("GroupId") or "").strip(),
            str(asset_info.get("AssetType") or "").strip(),
            str(asset_info.get("Status") or "").strip(),
            str(asset_info.get("URL") or "").strip(),
            str(asset_info.get("Name") or "").strip(),
        )
    }


def _collect_reference_content(images, image_asset_uris, videos, video_asset_uris, audios, audio_asset_uris):
    content = []
    image_count = 0
    video_count = 0

    for index, (image, image_asset_uri) in enumerate(zip(images, image_asset_uris, strict=False), start=1):
        reference_url = _resolve_media_reference_url(
            image,
            image_asset_uri,
            f"image_{index}",
            f"image_asset_uri_{index}",
            _upload_image_reference,
        )
        if reference_url:
            image_count += 1
            content.append(build_image_reference_payload(reference_url))

    for index, (video, video_asset_uri) in enumerate(zip(videos, video_asset_uris, strict=False), start=1):
        reference_url = _resolve_media_reference_url(
            video,
            video_asset_uri,
            f"video_{index}",
            f"video_asset_uri_{index}",
            _upload_video_reference,
        )
        if reference_url:
            video_count += 1
            content.append(build_video_reference_payload(reference_url))

    has_audio_input = any(audio is not None for audio in audios) or any(
        str(audio_asset_uri or "").strip() for audio_asset_uri in audio_asset_uris
    )
    if has_audio_input and not image_count and not video_count:
        raise ValueError("At least one image or video reference is required when audio references are provided.")

    audio_count = 0
    for index, (audio, audio_asset_uri) in enumerate(zip(audios, audio_asset_uris, strict=False), start=1):
        reference_url = _resolve_media_reference_url(
            audio,
            audio_asset_uri,
            f"audio_{index}",
            f"audio_asset_uri_{index}",
            _upload_audio_reference,
        )
        if reference_url:
            audio_count += 1
            content.append(build_audio_reference_payload(reference_url))

    if not content:
        raise ValueError("At least one image, video, or audio reference is required.")

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


class SeedanceCreateAssetGroupNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("group_id", "project_name", "group_type", "name")
    FUNCTION = "create"
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return _create_asset_group_inputs()

    def create(self, name, description="", project_name=DEFAULT_ASSET_PROJECT_NAME, group_type=DEFAULT_ASSET_GROUP_TYPE):
        return _build_asset_group_result(
            name=name,
            description=description,
            project_name=project_name,
            group_type=group_type,
        )


class SeedanceUploadAssetNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("asset_uri", "group_id", "asset_id", "asset_type", "status", "asset_url")
    FUNCTION = "upload"
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return _upload_asset_inputs()

    def upload(
        self,
        group_id,
        asset_type,
        source_url="",
        project_name=DEFAULT_ASSET_PROJECT_NAME,
        name="",
        wait_for_active=True,
        image=None,
        video=None,
        audio=None,
    ):
        return _build_asset_upload_result(
            group_id=group_id,
            asset_type=asset_type,
            source_url=source_url,
            project_name=project_name,
            name=name,
            wait_for_active=wait_for_active,
            image=image,
            video=video,
            audio=audio,
        )


class SeedanceUploadImageAssetNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("asset_uri", "asset_id", "status", "asset_url")
    FUNCTION = "upload"
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return _upload_image_asset_inputs()

    def upload(self, group_id, source_url="", project_name=DEFAULT_ASSET_PROJECT_NAME, name="", wait_for_active=True, image=None):
        result = _build_asset_upload_result(
            group_id=group_id,
            asset_type="Image",
            source_url=source_url,
            project_name=project_name,
            name=name,
            wait_for_active=wait_for_active,
            image=image,
        )
        asset_uri, _group_id, asset_id, _asset_type, status, asset_url = result["result"]
        return {"result": (asset_uri, asset_id, status, asset_url)}


class SeedanceGetAssetNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("asset_uri", "group_id", "asset_type", "status", "asset_url", "name")
    FUNCTION = "get"
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return _get_asset_inputs()

    def get(self, asset_id, project_name=DEFAULT_ASSET_PROJECT_NAME):
        return _build_get_asset_result(asset_id=asset_id, project_name=project_name)


class SeedanceFirstFrameNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("url", "video_id", "file_path")
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return _first_frame_inputs()

    def generate(
        self,
        model,
        prompt,
        resolution,
        duration,
        ratio,
        generate_audio,
        watermark,
        image=None,
        image_asset_uri="",
        reference_video=None,
        reference_video_asset_uri="",
        reference_audio=None,
        reference_audio_asset_uri="",
    ):
        return _build_generation_result(
            model,
            prompt,
            resolution,
            duration,
            ratio,
            generate_audio,
            watermark,
            content=_build_first_frame_content(
                image=image,
                image_asset_uri=image_asset_uri,
                reference_video=reference_video,
                reference_video_asset_uri=reference_video_asset_uri,
                reference_audio=reference_audio,
                reference_audio_asset_uri=reference_audio_asset_uri,
            ),
            prompt_required=False,
        )


class SeedanceFirstLastFrameNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("url", "video_id", "file_path")
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return _first_last_frame_inputs()

    def generate(
        self,
        model,
        prompt,
        resolution,
        duration,
        ratio,
        generate_audio,
        watermark,
        first_image=None,
        first_image_asset_uri="",
        last_image=None,
        last_image_asset_uri="",
    ):
        return _build_generation_result(
            model,
            prompt,
            resolution,
            duration,
            ratio,
            generate_audio,
            watermark,
            content=_build_first_last_frame_content(
                first_image=first_image,
                last_image=last_image,
                first_image_asset_uri=first_image_asset_uri,
                last_image_asset_uri=last_image_asset_uri,
            ),
            prompt_required=False,
        )


class SeedanceAssetModelNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("url", "video_id", "file_path")
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return _asset_model_inputs()

    def generate(
        self,
        model,
        model_asset_uri,
        prompt,
        resolution,
        duration,
        ratio,
        generate_audio,
        watermark,
        outfit_image=None,
        outfit_asset_uri="",
        extra_reference_asset_uri="",
        extra_reference_image=None,
        reference_video=None,
        reference_video_asset_uri="",
        reference_audio=None,
        reference_audio_asset_uri="",
    ):
        return _build_generation_result(
            model,
            prompt,
            resolution,
            duration,
            ratio,
            generate_audio,
            watermark,
            content=_build_asset_model_content(
                model_asset_uri,
                outfit_image=outfit_image,
                outfit_asset_uri=outfit_asset_uri,
                extra_reference_image=extra_reference_image,
                extra_reference_asset_uri=extra_reference_asset_uri,
                reference_video=reference_video,
                reference_video_asset_uri=reference_video_asset_uri,
                reference_audio=reference_audio,
                reference_audio_asset_uri=reference_audio_asset_uri,
            ),
            prompt_required=True,
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
        image_1=None,
        image_asset_uri_1="",
        image_2=None,
        image_asset_uri_2="",
        image_3=None,
        image_asset_uri_3="",
        image_4=None,
        image_asset_uri_4="",
        image_5=None,
        image_asset_uri_5="",
        image_6=None,
        image_asset_uri_6="",
        image_7=None,
        image_asset_uri_7="",
        image_8=None,
        image_asset_uri_8="",
        image_9=None,
        image_asset_uri_9="",
        video_1=None,
        video_asset_uri_1="",
        video_2=None,
        video_asset_uri_2="",
        video_3=None,
        video_asset_uri_3="",
        audio_1=None,
        audio_asset_uri_1="",
        audio_2=None,
        audio_asset_uri_2="",
        audio_3=None,
        audio_asset_uri_3="",
    ):
        content = _collect_reference_content(
            [
                image_1,
                image_2,
                image_3,
                image_4,
                image_5,
                image_6,
                image_7,
                image_8,
                image_9,
            ],
            [
                image_asset_uri_1,
                image_asset_uri_2,
                image_asset_uri_3,
                image_asset_uri_4,
                image_asset_uri_5,
                image_asset_uri_6,
                image_asset_uri_7,
                image_asset_uri_8,
                image_asset_uri_9,
            ],
            [video_1, video_2, video_3],
            [video_asset_uri_1, video_asset_uri_2, video_asset_uri_3],
            [audio_1, audio_2, audio_3],
            [audio_asset_uri_1, audio_asset_uri_2, audio_asset_uri_3],
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
            prompt_required=False,
        )


class SeedanceTrustedPersonAssetNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("asset_uri", "group_id", "asset_id", "status", "asset_url")
    FUNCTION = "upload"
    CATEGORY = NODE_CATEGORY
    DESCRIPTION = (
        "Create a real-person validation session from the node UI, then upload an image "
        "to the verified Ark Asset Group."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return _trusted_person_asset_inputs()

    def upload(
        self,
        group_id,
        callback_url="",
        source_url="",
        project_name=DEFAULT_ASSET_PROJECT_NAME,
        name="",
        wait_for_active=True,
        image=None,
    ):
        if _resolve_api_provider(_load_json_config()) == "las":
            raise ValueError(
                "Trusted Person Asset is not supported with api_provider='las'. "
                "Complete LAS real-person authorization in the console and use the resulting asset outside this node."
            )
        normalized_group_id = str(group_id or "").strip()
        if not normalized_group_id.startswith("group-") or normalized_group_id == "group-":
            raise ValueError("Complete real-person validation or provide a valid group_id before uploading.")

        upload_result = _build_asset_upload_result(
            group_id=normalized_group_id,
            asset_type="Image",
            source_url=source_url,
            project_name=project_name,
            name=name,
            wait_for_active=wait_for_active,
            image=image,
        )
        asset_uri, _group_id, asset_id, _asset_type, status, asset_url = upload_result["result"]
        return {"result": (asset_uri, normalized_group_id, asset_id, status, asset_url)}


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
            }
        }

    def run(self, video_url, filename_prefix=DEFAULT_FILENAME_PREFIX, save_output=True):
        return _build_preview_result(video_url, filename_prefix, save_output)
