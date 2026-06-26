import json
import os
import tempfile
import urllib.parse
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

import folder_paths
import numpy
import PIL.Image

from .api import (
    AssetAPIError,
    AssetClient,
    Client,
    DEFAULT_ASSET_BASE_URL,
    DEFAULT_ASSET_POLL_INTERVAL,
    DEFAULT_ASSET_TIMEOUT,
    DEFAULT_UPLOAD_TIMEOUT,
    IMAGE_DATA_URL_MAX_SIZE_BYTES,
    MODEL_OPTIONS,
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
    upload_file_to_tmpfiles,
    wait_for_video_completion,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_JSON_PATH = ROOT_DIR / "config.local.json"

NODE_PREFIX = "ComfyUI-Seedance"
NODE_CATEGORY = NODE_PREFIX
DEFAULT_FILENAME_PREFIX = NODE_PREFIX
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_POLL_INTERVAL = 15.0
DEFAULT_REQUEST_TIMEOUT = 60
DEFAULT_UPLOAD_TIMEOUT_SECONDS = DEFAULT_UPLOAD_TIMEOUT
DEFAULT_ASSET_PROJECT_NAME = "default"
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


def _resolve_api_key(config_data):
    if _json_value_present(config_data, "api_key"):
        return str(config_data["api_key"]).strip()

    env_value = _load_env_value("ARK_API_KEY", "SEEDANCE_API_KEY")
    if env_value:
        return env_value

    raise ValueError("An api_key is required. Add api_key to config.local.json or set ARK_API_KEY or SEEDANCE_API_KEY.")


def _resolve_base_url(config_data):
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


def _resolve_asset_project_name(config_data):
    if _json_value_present(config_data, "asset_project_name"):
        return str(config_data["asset_project_name"]).strip()

    env_value = _load_env_value("SEEDANCE_ASSET_PROJECT_NAME", "ARK_PROJECT_NAME")
    if env_value:
        return env_value

    return DEFAULT_ASSET_PROJECT_NAME


def _create_runtime_client():
    config_data = _load_json_config()
    return Client(
        _resolve_api_key(config_data),
        timeout=_resolve_request_timeout(config_data),
        base_url=_resolve_base_url(config_data),
        poll_interval=_resolve_poll_interval(config_data),
    )


def _create_upload_timeout():
    config_data = _load_json_config()
    return _resolve_upload_timeout(config_data)


def _create_asset_client():
    config_data = _load_json_config()
    return AssetClient(
        _resolve_access_key_id(config_data),
        _resolve_secret_access_key(config_data),
        base_url=_resolve_asset_base_url(config_data),
        timeout=_resolve_asset_timeout(config_data),
        poll_interval=_resolve_asset_poll_interval(config_data),
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
    if exc.status_code in {401, 403}:
        raise ValueError(
            f"The video API rejected the request with {exc.status_code}. "
            "Check api_key, base_url, billing, and model availability."
        ) from exc

    if exc.status_code == 429:
        raise ValueError("Volcengine Ark rate limit exceeded (429). Wait and retry.") from exc

    raise ValueError(str(exc)) from exc


def _raise_with_asset_api_guidance(exc):
    if exc.status_code in {401, 403}:
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
        )
        task_id, task_info = _submit_and_wait(client, model, payload)
        print(f"[{NODE_PREFIX}] succeeded {model} task_id={task_id}")
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
        inputs[f"image_{index}"] = ("IMAGE",)

    for index in range(1, 4):
        inputs[f"video_{index}"] = ("VIDEO",)
        inputs[f"audio_{index}"] = ("AUDIO",)

    return inputs


def _first_frame_inputs():
    return {
        "required": {
            **_common_generation_inputs(),
            "image": ("IMAGE",),
        }
    }


def _first_last_frame_inputs():
    return {
        "required": {
            **_common_generation_inputs(),
            "first_image": ("IMAGE",),
            "last_image": ("IMAGE",),
        }
    }


def _asset_model_inputs():
    common_inputs = _common_generation_inputs()
    return {
        "required": {
            "model": common_inputs["model"],
            "model_asset_uri": ("STRING", {"default": "asset://asset-"}),
            "prompt": ("STRING", {"multiline": True, "default": DEFAULT_ASSET_MODEL_PROMPT}),
            "outfit_image": ("IMAGE",),
            "resolution": common_inputs["resolution"],
            "duration": common_inputs["duration"],
            "ratio": common_inputs["ratio"],
            "generate_audio": common_inputs["generate_audio"],
            "watermark": common_inputs["watermark"],
        },
        "optional": {
            "extra_reference_asset_uri": ("STRING", {"default": ""}),
            "extra_reference_image": ("IMAGE",),
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
        return upload_file_to_tmpfiles(temp_path, timeout=_create_upload_timeout())
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _upload_video_reference(video):
    if video is None:
        raise ValueError("video is required.")

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
        temp_path = handle.name

    try:
        video.save_to(temp_path)
        return upload_file_to_tmpfiles(temp_path, timeout=_create_upload_timeout())
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _upload_audio_reference(audio):
    if audio is None:
        raise ValueError("audio is required.")

    import torchaudio

    waveform = audio["waveform"].cpu()[0]
    if waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        temp_path = handle.name

    try:
        torchaudio.save(temp_path, waveform, audio["sample_rate"])
        return upload_file_to_tmpfiles(temp_path, timeout=_create_upload_timeout())
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _build_first_frame_content(image):
    return [build_first_frame_payload(_upload_image_reference(image))]


def _build_first_last_frame_content(first_image, last_image):
    return [
        build_first_frame_payload(_upload_image_reference(first_image)),
        build_last_frame_payload(_upload_image_reference(last_image)),
    ]


def _build_asset_model_content(model_asset_uri, outfit_image, extra_reference_image=None, extra_reference_asset_uri=""):
    content = [
        build_asset_image_reference_payload(model_asset_uri),
        build_image_reference_payload(_upload_image_reference(outfit_image)),
    ]

    extra_reference_asset_uri = str(extra_reference_asset_uri or "").strip()
    if extra_reference_asset_uri:
        content.append(build_image_reference_payload(extra_reference_asset_uri))

    if extra_reference_image is not None:
        content.append(build_image_reference_payload(_upload_image_reference(extra_reference_image)))

    return content


def _resolve_asset_source_url(image, source_url):
    source_url = str(source_url or "").strip()
    if source_url:
        return source_url
    if image is None:
        raise ValueError("Either source_url or image is required for asset upload.")
    return _upload_image_for_asset(image)


def _build_asset_upload_result(group_id, source_url, project_name, name, wait_for_active, image=None):
    project_name = str(project_name or "").strip() or _create_asset_project_name()
    source_url = _resolve_asset_source_url(image, source_url)

    with _asset_client() as client:
        try:
            created_asset = client.create_asset(
                group_id=group_id,
                source_url=source_url,
                asset_type="Image",
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

    return {"result": (asset_uri_from_id(asset_id), asset_id, status, asset_url)}


def _collect_reference_content(images, videos, audios):
    image_inputs = [image for image in images if image is not None]
    video_inputs = [video for video in videos if video is not None]
    audio_inputs = [audio for audio in audios if audio is not None]

    if audio_inputs and not image_inputs and not video_inputs:
        raise ValueError("At least one image or video reference is required when audio references are provided.")

    content = []

    for image in image_inputs:
        content.append(build_image_reference_payload(_upload_image_reference(image)))

    for video in video_inputs:
        content.append(build_video_reference_payload(_upload_video_reference(video)))

    for audio in audio_inputs:
        content.append(build_audio_reference_payload(_upload_audio_reference(audio)))

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


class SeedanceUploadImageAssetNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("asset_uri", "asset_id", "status", "asset_url")
    FUNCTION = "upload"
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return _upload_image_asset_inputs()

    def upload(self, group_id, source_url="", project_name=DEFAULT_ASSET_PROJECT_NAME, name="", wait_for_active=True, image=None):
        return _build_asset_upload_result(
            group_id=group_id,
            source_url=source_url,
            project_name=project_name,
            name=name,
            wait_for_active=wait_for_active,
            image=image,
        )


class SeedanceFirstFrameNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("url", "video_id", "file_path")
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = NODE_CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return _first_frame_inputs()

    def generate(self, model, prompt, resolution, duration, ratio, generate_audio, watermark, image):
        return _build_generation_result(
            model,
            prompt,
            resolution,
            duration,
            ratio,
            generate_audio,
            watermark,
            content=_build_first_frame_content(image),
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

    def generate(self, model, prompt, resolution, duration, ratio, generate_audio, watermark, first_image, last_image):
        return _build_generation_result(
            model,
            prompt,
            resolution,
            duration,
            ratio,
            generate_audio,
            watermark,
            content=_build_first_last_frame_content(first_image, last_image),
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
        outfit_image,
        resolution,
        duration,
        ratio,
        generate_audio,
        watermark,
        extra_reference_asset_uri="",
        extra_reference_image=None,
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
                outfit_image,
                extra_reference_image=extra_reference_image,
                extra_reference_asset_uri=extra_reference_asset_uri,
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
        image_2=None,
        image_3=None,
        image_4=None,
        image_5=None,
        image_6=None,
        image_7=None,
        image_8=None,
        image_9=None,
        video_1=None,
        video_2=None,
        video_3=None,
        audio_1=None,
        audio_2=None,
        audio_3=None,
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
            [video_1, video_2, video_3],
            [audio_1, audio_2, audio_3],
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
