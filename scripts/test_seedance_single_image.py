import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
API_DIR = ROOT_DIR / "py"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from api import (  # noqa: E402
    Client,
    VideoAPIError,
    build_first_frame_payload,
    build_generation_payload,
    extract_result_video_url,
    extract_task_id,
    submit_video_generation,
    upload_file_to_tmpfiles,
    wait_for_video_completion,
)


CONFIG_JSON_PATH = ROOT_DIR / "config.local.json"
DEFAULT_BASE_URL = "https://aihubmix.com"
DEFAULT_POLL_INTERVAL = 15.0
DEFAULT_REQUEST_TIMEOUT = 60
DEFAULT_UPLOAD_TIMEOUT = 120
DEFAULT_IMAGE_PATH = r"E:\ai-toolkit\datasets\0417xiaohan\2026-04-17 124555.jpg"
DEFAULT_PROMPT = """Use Image 1 as the only visual reference and keep the same subject, outfit, pose style, and background from Image 1.
Keep the camera framing close to the original portrait and do not replace the character, outfit, or location.
Only create subtle natural motion: slight body movement, gentle breathing, a small smile, soft hair movement, and a light sway of the dress, as if the original photo is coming to life."""


def _load_json_config():
    if not CONFIG_JSON_PATH.exists():
        return {}

    with CONFIG_JSON_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError(f"{CONFIG_JSON_PATH.name} must contain a JSON object.")

    return payload


def _load_env_value(*keys):
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _json_value_present(config_data, key):
    if key not in config_data:
        return False

    value = config_data[key]
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _parse_timeout(value, field_name):
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")

    try:
        timeout = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc

    if timeout < 5:
        raise ValueError(f"{field_name} must be greater than or equal to 5.")

    return timeout


def _parse_poll_interval(value):
    if isinstance(value, bool):
        raise ValueError("poll_interval must be a number.")

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
        return _parse_timeout(config_data["request_timeout"], "request_timeout")

    env_value = _load_env_value("SEEDANCE_REQUEST_TIMEOUT", "AIHUBMIX_REQUEST_TIMEOUT")
    if env_value:
        return _parse_timeout(env_value, "request_timeout")

    return DEFAULT_REQUEST_TIMEOUT


def _resolve_upload_timeout(config_data):
    if _json_value_present(config_data, "upload_timeout"):
        return _parse_timeout(config_data["upload_timeout"], "upload_timeout")

    env_value = _load_env_value("SEEDANCE_UPLOAD_TIMEOUT", "AIHUBMIX_UPLOAD_TIMEOUT")
    if env_value:
        return _parse_timeout(env_value, "upload_timeout")

    return DEFAULT_UPLOAD_TIMEOUT


def _build_run_dir(output_dir):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / f"seedance_single_image_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_json(file_path, payload):
    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Upload a local image to a temporary public URL and test a Seedance first-frame image-to-video request."
    )
    parser.add_argument("--image", default=DEFAULT_IMAGE_PATH, help="Local image path.")
    parser.add_argument("--model", default="doubao-seedance-2-0-260128", help="Seedance model name.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt sent to Seedance.")
    parser.add_argument("--resolution", default="720p", choices=["480p", "720p"], help="Output resolution.")
    parser.add_argument("--duration", type=int, default=4, help="Clip duration in seconds.")
    parser.add_argument(
        "--ratio",
        default="3:4",
        choices=["adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
        help="Output ratio.",
    )
    parser.add_argument("--generate-audio", action="store_true", help="Enable audio generation.")
    parser.add_argument("--watermark", action="store_true", help="Enable watermark.")
    parser.add_argument("--submit-only", action="store_true", help="Submit the task but do not wait for completion.")
    parser.add_argument("--no-download", action="store_true", help="Do not download the completed video.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "debug_outputs"),
        help="Directory used to save debug JSON files and downloaded video.",
    )
    return parser


def main():
    args = _build_parser().parse_args()
    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"Image file does not exist: {image_path}")

    config_data = _load_json_config()
    api_key = _resolve_api_key(config_data)
    base_url = _resolve_base_url(config_data)
    poll_interval = _resolve_poll_interval(config_data)
    request_timeout = _resolve_request_timeout(config_data)
    upload_timeout = _resolve_upload_timeout(config_data)

    output_dir = Path(args.output_dir).expanduser().resolve()
    run_dir = _build_run_dir(output_dir)

    print(f"[Seedance Test] Local image: {image_path}")
    print("[Seedance Test] Uploading local image to a temporary public URL...")
    reference_image_url = upload_file_to_tmpfiles(image_path, timeout=upload_timeout)
    print(f"[Seedance Test] Uploaded image URL: {reference_image_url}")

    payload = build_generation_payload(
        model_name=args.model,
        prompt=args.prompt,
        resolution=args.resolution,
        duration=args.duration,
        ratio=args.ratio,
        generate_audio=args.generate_audio,
        watermark=args.watermark,
        content=[build_first_frame_payload(reference_image_url)],
        prompt_required=False,
    )
    _write_json(run_dir / "request_payload.json", payload)

    client = Client(
        api_key=api_key,
        timeout=request_timeout,
        base_url=base_url,
        poll_interval=poll_interval,
    )
    try:
        submission = submit_video_generation(client, args.model, payload)
        _write_json(run_dir / "submission.json", submission)
        task_id = extract_task_id(client, submission)
        print(f"[Seedance Test] Task submitted: {task_id}")

        if args.submit_only:
            print(f"[Seedance Test] Request payload saved to: {run_dir / 'request_payload.json'}")
            return 0

        print("[Seedance Test] Waiting for task completion...")
        task_info = wait_for_video_completion(client, task_id)
        _write_json(run_dir / "task_result.json", task_info)
        result_url = extract_result_video_url(client, task_id, task_info)
        print(f"[Seedance Test] Result URL: {result_url}")

        if not args.no_download:
            output_video_path = run_dir / f"{task_id}.mp4"
            client.download_to_file(result_url, output_video_path)
            print(f"[Seedance Test] Downloaded video: {output_video_path}")

        print(f"[Seedance Test] Debug files saved under: {run_dir}")
        return 0
    except VideoAPIError as exc:
        print(f"[Seedance Test] API error: {exc}", file=sys.stderr)
        print(f"[Seedance Test] Debug files saved under: {run_dir}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
