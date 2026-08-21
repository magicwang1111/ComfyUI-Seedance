import json
import time
import urllib.parse
from urllib.parse import urlparse


MODEL_OPTIONS = [
    "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-fast-260128",
    "doubao-seedance-2-0-mini-260615",
]
SEEDANCE_25_MODEL = "doubao-seedance-2-5-260628"
ARK_MODEL_OPTIONS = [*MODEL_OPTIONS, SEEDANCE_25_MODEL]
LAS_MODEL_OPTIONS = [
    "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-fast-260128",
]
RESOLUTION_OPTIONS = ["480p", "720p", "1080p", "4k"]
SEEDANCE_25_RESOLUTION_OPTIONS = ["480p", "720p", "1080p"]
DURATION_OPTIONS = ["-1"] + [str(value) for value in range(4, 16)]
NODE_DURATION_OPTIONS = [str(value) for value in range(4, 16)]
RATIO_OPTIONS = ["adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]
SEEDANCE_25_DURATION_OPTIONS = ["-1"] + [str(value) for value in range(4, 31)]
SEEDANCE_25_TASK_TYPE_OPTIONS = ["auto", "reference", "edit", "extend"]

STANDARD_MODEL = "doubao-seedance-2-0-260128"
FAST_MODEL = "doubao-seedance-2-0-fast-260128"
MINI_MODEL = "doubao-seedance-2-0-mini-260615"
ARK_VIDEO_TOKEN_RATES_CNY_PER_MILLION = {
    STANDARD_MODEL: {"with_video_input": 28.0, "without_video_input": 46.0},
    FAST_MODEL: {"with_video_input": 22.0, "without_video_input": 37.0},
    MINI_MODEL: {"with_video_input": 14.0, "without_video_input": 23.0},
    SEEDANCE_25_MODEL: {
        "with_video_input": {"480p": 42.0, "720p": 42.0, "1080p": 46.0},
        "without_video_input": {"480p": 70.0, "720p": 70.0, "1080p": 77.0},
    },
}
ACTIVE_VIDEO_STATUSES = {"queued", "pending", "running", "in_progress"}
FAILURE_VIDEO_STATUSES = {"failed", "error", "cancelled", "canceled", "expired"}
COMPLETED_VIDEO_STATUS = "succeeded"


def _clean_prompt(prompt, required=True):
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string.")
    prompt = prompt.strip()
    if not prompt and required:
        raise ValueError("prompt is required.")
    return prompt


def _validate_model_name(model_name, provider="ark"):
    normalized = str(model_name).strip()
    allowed_models = LAS_MODEL_OPTIONS if provider == "las" else ARK_MODEL_OPTIONS
    if normalized not in allowed_models:
        raise ValueError(f"{provider} model must be one of: {', '.join(allowed_models)}.")
    return normalized


def _validate_resolution(model_name, resolution):
    normalized = str(resolution).strip()
    if normalized not in RESOLUTION_OPTIONS:
        raise ValueError(f"resolution must be one of: {', '.join(RESOLUTION_OPTIONS)}.")
    if model_name in {FAST_MODEL, MINI_MODEL} and normalized in {"1080p", "4k"}:
        raise ValueError(f"{model_name} does not support resolution {normalized}; use 480p or 720p.")
    return normalized


def _validate_duration(duration):
    if isinstance(duration, bool):
        raise ValueError("duration must be an integer.")

    try:
        normalized = int(str(duration).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("duration must be an integer.") from exc

    if normalized == -1 or 4 <= normalized <= 15:
        return normalized

    raise ValueError("duration must be -1 or an integer from 4 to 15.")


def _validate_ratio(ratio):
    normalized = str(ratio).strip()
    if normalized not in RATIO_OPTIONS:
        raise ValueError(f"ratio must be one of: {', '.join(RATIO_OPTIONS)}.")
    return normalized


def _validate_remote_url(value, field_name):
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required.")

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be a valid http or https URL.")

    return normalized


def _validate_remote_or_asset_url(value, field_name):
    normalized = str(value or "").strip()
    if normalized.startswith("asset://"):
        return _validate_asset_uri(normalized, field_name)
    return _validate_remote_url(value, field_name)


def _validate_asset_uri(value, field_name="asset_uri"):
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    if not normalized.lower().startswith("asset://asset-"):
        raise ValueError(f"{field_name} must use asset://asset-... format.")
    return normalized


def _validate_image_url(value):
    normalized = str(value or "").strip()
    if normalized.startswith("asset://"):
        return _validate_asset_uri(normalized, "image_url")
    if normalized.startswith("data:image/") and ";base64," in normalized:
        return normalized
    return _validate_remote_url(value, "image_url")


def _build_reference_payload(reference_type, role, url, field_name):
    if reference_type == "image_url":
        validated_url = _validate_image_url(url)
    else:
        validated_url = _validate_remote_or_asset_url(url, field_name)
    return {
        "type": reference_type,
        "role": role,
        reference_type: {"url": validated_url},
    }


def build_first_frame_payload(image_url):
    return _build_reference_payload("image_url", "first_frame", image_url, "image_url")


def build_last_frame_payload(image_url):
    return _build_reference_payload("image_url", "last_frame", image_url, "image_url")


def build_image_reference_payload(image_url):
    return _build_reference_payload("image_url", "reference_image", image_url, "image_url")


def build_asset_image_reference_payload(asset_uri):
    return _build_reference_payload("image_url", "reference_image", _validate_asset_uri(asset_uri, "model_asset_uri"), "image_url")


def build_video_reference_payload(video_url):
    return _build_reference_payload("video_url", "reference_video", video_url, "video_url")


def build_audio_reference_payload(audio_url):
    return _build_reference_payload("audio_url", "reference_audio", audio_url, "audio_url")


def build_generation_payload(
    model_name,
    prompt,
    resolution,
    duration,
    ratio,
    generate_audio=True,
    watermark=False,
    content=None,
    prompt_required=True,
    provider="ark",
):
    validated_model = _validate_model_name(model_name, provider=provider)
    cleaned_prompt = _clean_prompt(prompt, required=prompt_required)
    request_content = []

    if cleaned_prompt:
        request_content.append({"type": "text", "text": cleaned_prompt})
    if content is not None:
        if not isinstance(content, list) or not content:
            raise ValueError("content must be a non-empty list when provided.")
        request_content.extend(content)
    if not request_content:
        raise ValueError("content must contain a prompt or at least one reference.")

    return {
        "model": validated_model,
        "content": request_content,
        "resolution": _validate_resolution(validated_model, resolution),
        "duration": _validate_duration(duration),
        "ratio": _validate_ratio(ratio),
        "generate_audio": bool(generate_audio),
        "watermark": bool(watermark),
    }


def build_seedance_25_omni_payload(
    model_name,
    prompt,
    task_type,
    resolution,
    duration,
    ratio,
    generate_audio,
    watermark,
    content,
):
    validated_model = _validate_model_name(model_name)
    if validated_model != SEEDANCE_25_MODEL:
        raise ValueError(f"Seedance 2.5 Omni model must be {SEEDANCE_25_MODEL}.")

    normalized_task_type = str(task_type).strip().lower()
    if normalized_task_type not in SEEDANCE_25_TASK_TYPE_OPTIONS:
        raise ValueError(
            "omni_reference_task_type must be one of: "
            + ", ".join(SEEDANCE_25_TASK_TYPE_OPTIONS)
            + "."
        )

    normalized_resolution = str(resolution).strip().lower()
    if normalized_resolution not in SEEDANCE_25_RESOLUTION_OPTIONS:
        raise ValueError(
            "Seedance 2.5 resolution must be one of: "
            + ", ".join(SEEDANCE_25_RESOLUTION_OPTIONS)
            + "."
        )

    normalized_duration = _validate_seedance_25_duration(duration)
    normalized_ratio = _validate_ratio(ratio)

    if not isinstance(content, list) or not content:
        raise ValueError("Seedance 2.5 Omni requires at least one image, video, or audio reference.")

    allowed_roles = {
        "image_url": "reference_image",
        "video_url": "reference_video",
        "audio_url": "reference_audio",
    }
    counts = {content_type: 0 for content_type in allowed_roles}
    for item in content:
        if not isinstance(item, dict) or item.get("type") not in allowed_roles:
            raise ValueError("Seedance 2.5 Omni content must contain only reference image, video, or audio items.")
        content_type = item["type"]
        if item.get("role") != allowed_roles[content_type]:
            raise ValueError(f"{content_type} role must be {allowed_roles[content_type]}.")
        counts[content_type] += 1

    limits = {"image_url": 30, "video_url": 10, "audio_url": 10}
    for content_type, limit in limits.items():
        if counts[content_type] > limit:
            raise ValueError(f"Seedance 2.5 Omni supports at most {limit} {content_type} references.")

    if normalized_task_type in {"edit", "extend"} and not counts["video_url"]:
        raise ValueError(f"Seedance 2.5 Omni {normalized_task_type} requires at least one video reference.")
    if normalized_task_type in {"edit", "extend"} and normalized_ratio != "adaptive":
        raise ValueError(f"Seedance 2.5 Omni {normalized_task_type} requires ratio=adaptive.")
    if normalized_task_type == "edit" and normalized_duration != -1:
        raise ValueError("Seedance 2.5 Omni edit requires duration=-1.")

    request_content = []
    cleaned_prompt = _clean_prompt(prompt, required=False)
    if cleaned_prompt:
        request_content.append({"type": "text", "text": cleaned_prompt})
    request_content.extend(content)

    return {
        "model": validated_model,
        "content": request_content,
        "omni_reference_task_type": normalized_task_type,
        "resolution": normalized_resolution,
        "duration": normalized_duration,
        "ratio": normalized_ratio,
        "generate_audio": bool(generate_audio),
        "watermark": bool(watermark),
        "output_format": "mp4",
    }


def _validate_seedance_25_duration(duration):
    if isinstance(duration, bool):
        raise ValueError("duration must be an integer.")
    try:
        normalized = int(str(duration).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("duration must be an integer.") from exc
    if normalized == -1 or 4 <= normalized <= 30:
        return normalized
    raise ValueError("Seedance 2.5 duration must be -1 or an integer from 4 to 30.")


def submit_video_generation(client, model_name, payload, provider="ark"):
    _validate_model_name(model_name, provider=provider)
    return client.request("POST", "/contents/generations/tasks", json=payload)


def fetch_video_status(client, task_id):
    safe_video_id = urllib.parse.quote(str(task_id).strip(), safe="")
    return client.request("GET", f"/contents/generations/tasks/{safe_video_id}")


def video_content_path(video_id):
    safe_video_id = urllib.parse.quote(str(video_id).strip(), safe="")
    return f"/contents/generations/tasks/{safe_video_id}"


def describe_task_error(task_info):
    if not isinstance(task_info, dict):
        return "Unknown video task error."

    error_payload = task_info.get("error")
    if isinstance(error_payload, dict):
        return error_payload.get("message") or json.dumps(error_payload, ensure_ascii=False)
    if error_payload:
        return str(error_payload)

    message = task_info.get("message")
    if message:
        return str(message)

    status = task_info.get("status") or "unknown"
    return f"Video generation ended with status={status}."


def wait_for_video_completion(client, task_id):
    while True:
        task_info = fetch_video_status(client, task_id)
        status = str(task_info.get("status", "")).strip().lower()

        if status == COMPLETED_VIDEO_STATUS:
            return task_info

        if status in FAILURE_VIDEO_STATUSES:
            raise RuntimeError(describe_task_error(task_info))

        if status not in ACTIVE_VIDEO_STATUSES:
            raise RuntimeError(f"Unexpected video task status: {status or 'unknown'}.")

        time.sleep(client.poll_interval)


def extract_video_usage_tokens(task_info):
    if not isinstance(task_info, dict):
        return None

    usage = task_info.get("usage")
    if not isinstance(usage, dict):
        return None

    raw_tokens = usage.get("total_tokens")
    if raw_tokens is None:
        raw_tokens = usage.get("completion_tokens")
    if isinstance(raw_tokens, bool):
        return None

    try:
        tokens = int(raw_tokens)
    except (TypeError, ValueError):
        return None

    return tokens if tokens >= 0 else None


def estimate_ark_video_cost(model_name, task_info, has_video_input, resolution=None):
    total_tokens = extract_video_usage_tokens(task_info)
    rates = ARK_VIDEO_TOKEN_RATES_CNY_PER_MILLION.get(str(model_name).strip())
    if total_tokens is None or rates is None:
        return None

    rate_key = "with_video_input" if has_video_input else "without_video_input"
    unit_rate = rates[rate_key]
    if isinstance(unit_rate, dict):
        normalized_resolution = str(resolution or task_info.get("resolution") or "").strip().lower()
        unit_rate = unit_rate.get(normalized_resolution)
        if unit_rate is None:
            return None
    return {
        "total_tokens": total_tokens,
        "unit_rate_cny_per_million": unit_rate,
        "estimated_cost_cny": total_tokens * unit_rate / 1_000_000,
        "has_video_input": bool(has_video_input),
    }


def extract_task_id(client, submission):
    del client
    task_id = str(submission.get("id") or "").strip()
    if not task_id:
        raise ValueError("Video API did not return a task identifier in `id`.")
    return task_id


def extract_result_video_url(client, task_id, task_info):
    del client, task_id
    if not isinstance(task_info, dict):
        raise ValueError("Video task result did not include a response object.")

    content = task_info.get("content")
    if isinstance(content, dict):
        video_url = str(content.get("video_url") or "").strip()
        if video_url:
            return video_url

    video_url = str(task_info.get("video_url") or "").strip()
    if video_url:
        return video_url

    raise ValueError("Video task succeeded but did not include content.video_url.")
