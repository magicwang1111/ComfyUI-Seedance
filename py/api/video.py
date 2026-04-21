import json
import time
import urllib.parse
from urllib.parse import urlparse


MODEL_OPTIONS = [
    "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-fast-260128",
]
RESOLUTION_OPTIONS = ["480p", "720p"]
DURATION_OPTIONS = ["-1"] + [str(value) for value in range(4, 16)]
NODE_DURATION_OPTIONS = [str(value) for value in range(4, 16)]
RATIO_OPTIONS = ["adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]

ACTIVE_VIDEO_STATUSES = {"queued", "pending", "running", "in_progress"}
FAILURE_VIDEO_STATUSES = {"failed", "error", "cancelled"}
COMPLETED_VIDEO_STATUS = "completed"


def _clean_prompt(prompt):
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string.")
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("prompt is required.")
    return prompt


def _validate_model_name(model_name):
    normalized = str(model_name).strip()
    if normalized not in MODEL_OPTIONS:
        raise ValueError(f"model must be one of: {', '.join(MODEL_OPTIONS)}.")
    return normalized


def _validate_resolution(resolution):
    normalized = str(resolution).strip()
    if normalized not in RESOLUTION_OPTIONS:
        raise ValueError(f"resolution must be one of: {', '.join(RESOLUTION_OPTIONS)}.")
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


def _validate_image_url(value):
    return _validate_remote_url(value, "image_url")


def _build_reference_payload(reference_type, role, url, field_name):
    if reference_type == "image_url":
        validated_url = _validate_image_url(url)
    else:
        validated_url = _validate_remote_url(url, field_name)
    return {
        "type": reference_type,
        "role": role,
        reference_type: {"url": validated_url},
    }


def build_image_reference_payload(image_url):
    return _build_reference_payload("image_url", "reference_image", image_url, "image_url")


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
):
    extra_body = {
        "duration": _validate_duration(duration),
        "ratio": _validate_ratio(ratio),
        "watermark": bool(watermark),
    }

    if content is not None:
        if not isinstance(content, list) or not content:
            raise ValueError("content must be a non-empty list when provided.")
        extra_body["content"] = content

    payload = {
        "model": _validate_model_name(model_name),
        "prompt": _clean_prompt(prompt),
        "resolution": _validate_resolution(resolution),
        "generate_audio": bool(generate_audio),
        "extra_body": extra_body,
    }

    return payload


def submit_video_generation(client, model_name, payload):
    _validate_model_name(model_name)
    return client.request("POST", "/v1/videos", json=payload)


def fetch_video_status(client, task_id):
    safe_video_id = urllib.parse.quote(str(task_id).strip(), safe="")
    return client.request("GET", f"/v1/videos/{safe_video_id}")


def video_content_path(video_id):
    safe_video_id = urllib.parse.quote(str(video_id).strip(), safe="")
    return f"/v1/videos/{safe_video_id}/content"


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


def extract_task_id(client, submission):
    del client
    task_id = str(submission.get("id") or "").strip()
    if not task_id:
        raise ValueError("Video API did not return a task identifier in `id`.")
    return task_id


def extract_result_video_url(client, task_id, task_info):
    del task_info
    return client.absolute_url(video_content_path(task_id))
