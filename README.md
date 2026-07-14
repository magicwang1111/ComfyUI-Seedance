# ComfyUI-Seedance

`ComfyUI-Seedance` is a small ComfyUI custom node pack for generating Seedance videos through Volcengine Ark or LAS.

It exposes eleven nodes under the `ComfyUI-Seedance` category:

- `ComfyUI-Seedance Text-to-Video`
- `ComfyUI-Seedance First-Frame-to-Video`
- `ComfyUI-Seedance First-Last-Frame-to-Video`
- `ComfyUI-Seedance Asset Model-to-Video`
- `ComfyUI-Seedance Create Asset Group`
- `ComfyUI-Seedance Upload Asset`
- `ComfyUI-Seedance Get Asset`
- `ComfyUI-Seedance Trusted Person Asset`
- `ComfyUI-Seedance Upload Image Asset`
- `ComfyUI-Seedance Multimodal-to-Video`
- `ComfyUI-Seedance Preview Video`

## What It Supports

- Model switching inside every generation node:
  - `doubao-seedance-2-0-260128`
  - `doubao-seedance-2-0-fast-260128`
  - `doubao-seedance-2-0-mini-260615`
- `api_provider: "ark"` through `https://ark.cn-beijing.volces.com/api/v3`
- `api_provider: "las"` through `https://operator.las.cn-shanghai.volces.com/api/v1`
- Seedance-native parameter names:
  - `resolution`
  - `duration`
  - `ratio`
  - `generate_audio`
  - `watermark`
- Local image references are sent as `data:image/...;base64,...` values.
- Local video and audio references are uploaded to a public URL bridge.
- Public upload bridge priority:
  - configured Aliyun OSS signed URL
  - fallback `tmpfiles.org`
- Ark or LAS asset group creation through `CreateAssetGroup`
- Ark or LAS asset upload and status lookup through `CreateAsset` / `GetAsset`
- Direct `asset://asset-...` references for image / video / audio slots in generation nodes
- Real-person validation from the `Trusted Person Asset` node UI is Ark-only
- A standalone `Preview Video` node for explicit playback and saving

## Mode Split

The generation nodes mirror the official Seedance image/video input modes instead of guessing from image count:

- `Text-to-Video`
  Pure text generation. `prompt` is required.
- `First-Frame-to-Video`
  Accepts either a local `IMAGE` or an `image_asset_uri` as `first_frame`, plus optional local or asset-backed video/audio references.
- `First-Last-Frame-to-Video`
  Accepts local or asset-backed `first_frame` and `last_frame` references.
- `Asset Model-to-Video`
  Uses an `asset://asset-...` human or virtual model asset as `图片1`, an outfit/product image or asset as `图片2`, and generates a model video from the prompt. It also accepts optional image, video, and audio references.
- `Create Asset Group`
  Creates a new Ark private asset group inside the selected project.
- `Upload Asset`
  Uploads a local or remote image/video/audio file into an existing Ark asset group and returns `asset://asset-...`.
- `Get Asset`
  Retrieves current Ark asset metadata so you can poll asynchronous asset processing explicitly.
- `Upload Image Asset`
  Keeps the old image-only upload workflow for compatibility.
- `Trusted Person Asset`
  Creates the H5 real-person validation session, writes the resulting `GroupId` into the node, then uploads an image into that verified Asset Group.
- `Multimodal-to-Video`
  Uses reference inputs only, and each slot can now be filled by either local media or a direct asset URI.

## Current API Notes

- Ark supports the standard, Fast, and Mini models. LAS supports only the standard and Fast models; LAS rejects Mini even if an old workflow supplies it.
- `resolution` supports `480p`, `720p`, `1080p`, and `4k`.
- `doubao-seedance-2-0-fast-260128` and `doubao-seedance-2-0-mini-260615` only support `480p` and `720p`.
- `doubao-seedance-2-0-260128` supports `480p`, `720p`, `1080p`, and `4k`.
- The node UI exposes `duration` as integers `4` through `15` for strict control.
- The backend payload builder still understands `-1` as model-auto duration for direct API use.
- `ratio` is limited to `adaptive`, `16:9`, `9:16`, `1:1`, `4:3`, `3:4`, and `21:9`.
- `Text-to-Video` requires a non-empty `prompt`.
- The non-text generation nodes allow an empty `prompt` and omit the text item from `content`.
- `Multimodal-to-Video` requires at least one reference input and rejects audio-only requests.
- `Asset Model-to-Video` requires `model_asset_uri` in `asset://asset-...` format and also requires either `outfit_image` or `outfit_asset_uri`.
- `CreateAsset` is asynchronous. When `wait_for_active=true`, upload nodes poll `GetAsset` until the asset reaches `Active`.
- The `Upload Asset` node supports `Image`, `Video`, and `Audio`.
- When a local slot and its corresponding asset URI slot are both filled, the node raises an explicit conflict error instead of guessing.
- Seedance control fields are sent as top-level task API fields, and text prompts are sent as `{"type": "text"}` items in `content`.

## OSS Public Upload Bridge

Ark `CreateAsset` needs a public URL. This plugin now supports an OSS-first bridge for local files.

### Upload priority

1. If OSS is fully configured, local files are uploaded to OSS and returned as signed GET URLs.
2. If OSS is not configured, the plugin falls back to `tmpfiles.org`.

### OSS config fields

- `oss_endpoint`
- `oss_access_key_id`
- `oss_access_key_secret`
- `oss_bucket`
- `oss_prefix`
- `oss_signed_url_expires`

### Notes

- The generated OSS object key uses `oss_prefix/YYYY/MM/DD/<timestamp>-<random>.<ext>`.
- `oss_signed_url_expires` is in seconds.
- The fallback bridge still uses `tmpfiles.org`, with its existing public temporary-file behavior.
- Local image references used directly in generation requests still stay as `data:image/...` when supported by Ark; the public upload bridge is used for local asset upload and local video/audio references.

## Human Face Limitation

The official Volcengine Seedance 2.0 / 2.0 fast documentation states that multimodal reference mode does not directly support ordinary human-face reference images or videos.

Practical guidance:

- If your goal is “make this portrait photo come alive”, prefer `First-Frame-to-Video`.
- If your goal uses a real-person or virtual model asset from Ark, use `Asset Model-to-Video` and pass the asset URI, for example `asset://asset-20260624155748-cb5d4`.
- Use `Multimodal-to-Video` for reference-style composition, pacing, scene, or mixed media guidance.
- This plugin does not try to detect faces or block requests automatically; it only exposes the modes explicitly.

## Asset Library Workflow

### 1. Create an asset group

Use `ComfyUI-Seedance Create Asset Group`.

Inputs:

- `name`
- `description`
- `project_name`
- `group_type` (default `AIGC`)

Outputs:

- `group_id`
- `project_name`
- `group_type`
- `name`

### 2. Upload an asset

Use `ComfyUI-Seedance Upload Asset`.

Inputs:

- `group_id`
- `asset_type` = `Image` / `Video` / `Audio`
- `source_url`
- `project_name`
- `name`
- `wait_for_active`
- Optional `image`
- Optional `video`
- Optional `audio`

Rules:

- If `source_url` is provided, the node uploads directly from that URL.
- If `source_url` is blank, you must provide the local input matching `asset_type`.
- Mismatched local input types are rejected explicitly.

Outputs:

- `asset_uri`
- `group_id`
- `asset_id`
- `asset_type`
- `status`
- `asset_url`

### 3. Query an asset

Use `ComfyUI-Seedance Get Asset`.

Inputs:

- `asset_id`
- `project_name`

Outputs:

- `asset_uri`
- `group_id`
- `asset_type`
- `status`
- `asset_url`
- `name`

This is useful when `CreateAsset` is still processing or when you deliberately set `wait_for_active=false`.

## Asset Model Workflow

Use `ComfyUI-Seedance Asset Model-to-Video` when Ark rejects an ordinary image with `input image may contain real person`.

Inputs:

- `model_asset_uri`: a trusted Ark private or virtual model asset URI, such as `asset://asset-20260624155748-cb5d4`
- Either `outfit_image` or `outfit_asset_uri`: clothing, product, or main visual reference. The prompt should call this `图片2`.
- `extra_reference_asset_uri`: optional trusted background, scene, or style asset. The prompt should call this `图片3`.
- `extra_reference_image`: optional local scene, composition, or style reference. If `extra_reference_asset_uri` is also present, this becomes `图片4`.
- Optional `reference_video` or `reference_video_asset_uri`
- Optional `reference_audio` or `reference_audio_asset_uri`

Recommended prompt:

```text
图片1中的模特穿上图片2中的服装，保持图片1的人脸身份、发型和身材特征一致，服装款式、颜色、材质严格参考图片2。生成电商模特展示视频，人物自然站立/转身展示服装，背景简洁，画面干净。
```

Do not write the asset ID directly in the prompt. Use `图片1`, `图片2`, `图片3`, and so on to refer to references by their order in the request.

## Trusted Person Asset Workflow

Use `ComfyUI-Seedance Trusted Person Asset` when the real-person Asset Group has not been created yet.

This node is only available with `api_provider: "ark"`. LAS real-person assets must be authorized and added manually in the LAS console; running this node in LAS mode returns an explicit error.

1. Keep `project_name` aligned with the project used by the Seedance inference endpoint.
2. Click `创建真人认证`. The node creates a 30-minute validation session and opens the Ark H5 page.
3. Complete the validation and return to ComfyUI. The node writes the resulting `group_id` automatically.
4. Connect an `IMAGE`, or provide `source_url`, and queue the node.
5. Connect the returned `asset_uri` to `Asset Model-to-Video`.

The default callback targets the current ComfyUI server. Set `callback_url` only when ComfyUI is behind a proxy or must use a different browser-reachable address. The workflow never stores the H5 link or `BytedToken`.

## Configuration

Create [config.local.json](./config.local.json) in the repository root. Use [config.example.json](./config.example.json) as the template.

```json
{
  "api_provider": "ark",
  "api_key": "",
  "base_url": "https://ark.cn-beijing.volces.com/api/v3",
  "poll_interval": 15.0,
  "request_timeout": 60,
  "upload_timeout": 120,
  "oss_endpoint": "oss-cn-hangzhou.aliyuncs.com",
  "oss_access_key_id": "",
  "oss_access_key_secret": "",
  "oss_bucket": "",
  "oss_prefix": "ComfyUI-Seedance-tmp",
  "oss_signed_url_expires": 86400,
  "access_key_id": "",
  "secret_access_key": "",
  "asset_base_url": "https://ark.cn-beijing.volcengineapi.com",
  "asset_project_name": "default",
  "asset_poll_interval": 5.0,
  "asset_timeout": 60,
  "asset_wait_timeout": 900,
  "las_api_key": "",
  "las_region": "cn-shanghai",
  "las_base_url": "https://operator.las.cn-shanghai.volces.com/api/v1"
}
```

- `api_provider` defaults to `ark`; set it to `las` to use LAS Shanghai.
- `api_key` and `access_key_id` / `secret_access_key` are used only by Ark.
- `las_api_key` is used by LAS generation and normal asset APIs. `LAS_DEFAULT_API_KEY` remains a compatible legacy config key.
- `oss_*` fields configure the public upload bridge for local files.

Supported environment variables:

- `ARK_API_KEY`
- `LAS_API_KEY`
- `SEEDANCE_API_KEY`
- `SEEDANCE_BASE_URL`
- `SEEDANCE_POLL_INTERVAL`
- `SEEDANCE_REQUEST_TIMEOUT`
- `SEEDANCE_UPLOAD_TIMEOUT`
- `OSS_ENDPOINT`
- `OSS_ACCESS_KEY_ID`
- `OSS_ACCESS_KEY_SECRET`
- `OSS_BUCKET`
- `OSS_PREFIX`
- `OSS_SIGNED_URL_EXPIRES`
- `ARK_ACCESS_KEY_ID`
- `ARK_SECRET_ACCESS_KEY`
- `VOLCENGINE_ACCESS_KEY_ID`
- `VOLCENGINE_SECRET_ACCESS_KEY`
- `SEEDANCE_ASSET_BASE_URL`
- `SEEDANCE_ASSET_PROJECT_NAME`
- `SEEDANCE_ASSET_POLL_INTERVAL`
- `SEEDANCE_ASSET_TIMEOUT`
- `SEEDANCE_ASSET_WAIT_TIMEOUT`

Priority:

1. `config.local.json`
2. Environment variables

## Installation

1. Place this folder under `ComfyUI/custom_nodes`.
2. Install Python dependencies:

   ```bash
   pip install -r ComfyUI/custom_nodes/ComfyUI-Seedance/requirements.txt
   ```

3. Add `config.local.json` with `api_provider: "ark"` and an Ark API key, or with `api_provider: "las"` and `las_api_key`.
4. Ark asset upload additionally needs `access_key_id` and `secret_access_key`; LAS asset upload needs only `las_api_key`.
5. To use OSS relay for local media, also fill the `oss_*` fields or set the corresponding `OSS_*` environment variables.
6. Restart ComfyUI.

## Node Interfaces

### Text-to-Video

Inputs:

- `model`
- `prompt`
- `resolution`
- `duration`
- `ratio`
- `generate_audio`
- `watermark`

### First-Frame-to-Video

Inputs:

- `model`
- `prompt`
- `resolution`
- `duration`
- `ratio`
- `generate_audio`
- `watermark`
- Optional `image`
- Optional `image_asset_uri`
- Optional `reference_video` as ComfyUI `VIDEO`
- Optional `reference_video_asset_uri`
- Optional `reference_audio` as ComfyUI `AUDIO`
- Optional `reference_audio_asset_uri`

### First-Last-Frame-to-Video

Inputs:

- `model`
- `prompt`
- `resolution`
- `duration`
- `ratio`
- `generate_audio`
- `watermark`
- Optional `first_image`
- Optional `first_image_asset_uri`
- Optional `last_image`
- Optional `last_image_asset_uri`

### Asset Model-to-Video

Inputs:

- `model`
- `model_asset_uri`
- `prompt`
- `resolution`
- `duration`
- `ratio`
- `generate_audio`
- `watermark`
- Optional `outfit_image`
- Optional `outfit_asset_uri`
- Optional `extra_reference_asset_uri`
- Optional `extra_reference_image`
- Optional `reference_video` as ComfyUI `VIDEO`
- Optional `reference_video_asset_uri`
- Optional `reference_audio` as ComfyUI `AUDIO`
- Optional `reference_audio_asset_uri`

### Create Asset Group

Inputs:

- `name`
- `description`
- `project_name`
- `group_type`

Outputs:

- `group_id`
- `project_name`
- `group_type`
- `name`

### Upload Asset

Inputs:

- `group_id`
- `asset_type`
- `source_url`
- `project_name`
- `name`
- `wait_for_active`
- Optional `image`
- Optional `video`
- Optional `audio`

Outputs:

- `asset_uri`
- `group_id`
- `asset_id`
- `asset_type`
- `status`
- `asset_url`

### Get Asset

Inputs:

- `asset_id`
- `project_name`

Outputs:

- `asset_uri`
- `group_id`
- `asset_type`
- `status`
- `asset_url`
- `name`

### Upload Image Asset

Inputs:

- `group_id`
- `source_url`
- `project_name`
- `name`
- `wait_for_active`
- Optional `image`

Outputs:

- `asset_uri`
- `asset_id`
- `status`
- `asset_url`

### Trusted Person Asset

Inputs:

- `group_id` (filled by the validation controls or provided manually)
- `callback_url` (optional; blank uses the current ComfyUI server)
- `source_url`
- `project_name`
- `name`
- `wait_for_active`
- Optional `image`

Outputs:

- `asset_uri`
- `group_id`
- `asset_id`
- `status`
- `asset_url`

### Multimodal-to-Video

Inputs:

- `model`
- `prompt`
- `resolution`
- `duration`
- `ratio`
- `generate_audio`
- `watermark`
- Optional `image_1` through `image_9` as ComfyUI `IMAGE`
- Optional `image_asset_uri_1` through `image_asset_uri_9`
- Optional `video_1` through `video_3` as ComfyUI `VIDEO`
- Optional `video_asset_uri_1` through `video_asset_uri_3`
- Optional `audio_1` through `audio_3` as ComfyUI `AUDIO`
- Optional `audio_asset_uri_1` through `audio_asset_uri_3`

### Shared Outputs

All generation nodes output:

- `url`
- `video_id`
- `file_path`

`Preview Video` inputs:

- `video_url`
- `filename_prefix`
- `save_output`

Notes:

- Generation nodes return the remote result URL and leave `file_path` empty.
- To preview the generated video inside ComfyUI, connect `url` to `ComfyUI-Seedance Preview Video`.
- With `save_output=false`, the preview node plays the remote URL directly.
- With `save_output=true`, it downloads the MP4 to ComfyUI output first, then previews the local file.
- Saving is enabled by default. Files are stored as `Seedance_YYYYMMDD_HHMMSS_00001_.mp4`, so they sort in timeline order.

## Examples

Starter workflow JSON files live in [examples/](./examples):

- [01_comfyui_seedance_text_workflow.json](./examples/01_comfyui_seedance_text_workflow.json)
- [02_comfyui_seedance_first_frame_workflow.json](./examples/02_comfyui_seedance_first_frame_workflow.json)
- [03_comfyui_seedance_first_last_frame_workflow.json](./examples/03_comfyui_seedance_first_last_frame_workflow.json)
- [04_comfyui_seedance_multimodal_mixed_workflow.json](./examples/04_comfyui_seedance_multimodal_mixed_workflow.json)
- [05_comfyui_seedance_trusted_person_asset_workflow.json](./examples/05_comfyui_seedance_trusted_person_asset_workflow.json)
- [06_comfyui_seedance_asset_group_and_upload_workflow.json](./examples/06_comfyui_seedance_asset_group_and_upload_workflow.json)
- [07_comfyui_seedance_asset_uri_multimodal_workflow.json](./examples/07_comfyui_seedance_asset_uri_multimodal_workflow.json)

See [examples/README.md](./examples/README.md) for a quick description of each one.

## References

- [Volcengine Create Video Generation Task documentation (CN)](https://www.volcengine.com/docs/82379/1520757?lang=zh)
- [Volcengine Seedance 2.0 SDK examples (CN)](https://www.volcengine.com/docs/82379/2291680?lang=zh)
- [Volcengine private trusted asset library guide (CN)](https://www.volcengine.com/docs/82379/2333589?lang=zh)
- [Volcengine CreateAsset documentation (CN)](https://www.volcengine.com/docs/82379/2318271?lang=zh)
- [Volcengine CreateAssetGroup documentation (CN)](https://www.volcengine.com/docs/82379/2318270)
- [tmpfiles API](https://tmpfiles.org/api)
