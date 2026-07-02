# ComfyUI-Seedance

`ComfyUI-Seedance` is a small ComfyUI custom node pack for generating Seedance videos through the Volcengine Ark native Video Generation Task API.

It exposes eight nodes under the `ComfyUI-Seedance` category:

- `ComfyUI-Seedance Text-to-Video`
- `ComfyUI-Seedance First-Frame-to-Video`
- `ComfyUI-Seedance First-Last-Frame-to-Video`
- `ComfyUI-Seedance Asset Model-to-Video`
- `ComfyUI-Seedance Trusted Person Asset`
- `ComfyUI-Seedance Upload Image Asset`
- `ComfyUI-Seedance Multimodal-to-Video`
- `ComfyUI-Seedance Preview Video`

## What It Supports

- Model switching inside every generation node:
  - `doubao-seedance-2-0-260128`
  - `doubao-seedance-2-0-fast-260128`
  - `doubao-seedance-2-0-mini-260615`
- Volcengine Ark native API through `https://ark.cn-beijing.volces.com/api/v3`
- Seedance-native parameter names:
  - `resolution`
  - `duration`
  - `ratio`
  - `generate_audio`
  - `watermark`
- Local image references are sent as `data:image/...;base64,...` values.
- Local video and audio references are uploaded to `tmpfiles.org` public URLs.
- Image assets can be uploaded to the Ark private trusted asset library through `CreateAsset` / `GetAsset`.
- Real-person validation can be created and completed from the `Trusted Person Asset` node UI.
- A standalone `Preview Video` node for explicit playback and saving

## Mode Split

The generation nodes now mirror the three official Seedance image/video input modes instead of guessing from image count:

- `Text-to-Video`
  Pure text generation. `prompt` is required.
- `First-Frame-to-Video`
  Uses one local `IMAGE` as `first_frame` and accepts optional video/audio references.
- `First-Last-Frame-to-Video`
  Uses two local `IMAGE` inputs and sends them as `first_frame` and `last_frame`.
- `Asset Model-to-Video`
  Uses an `asset://asset-...` human or virtual model asset as `图片1`, an outfit/product image as `图片2`, and generates a model video from the prompt. It also accepts optional image, video, and audio references.
- `Upload Image Asset`
  Uploads a local ComfyUI `IMAGE`, or a provided public `source_url`, into Ark's private trusted asset library and returns `asset://asset-...`.
- `Trusted Person Asset`
  Creates the H5 real-person validation session, writes the resulting `GroupId` into the node, then uploads an image into that verified Asset Group.
- `Multimodal-to-Video`
  Uses reference inputs only:
  - `image_1` through `image_9` become `reference_image`
  - `video_1` through `video_3` become `reference_video`
  - `audio_1` through `audio_3` become `reference_audio`

`Multimodal-to-Video` keeps its original node name for workflow compatibility, but it is now explicitly the reference-mode node.

## Current API Notes

- This package only supports the Volcengine Ark native task API.
- `resolution` supports `480p`, `720p`, `1080p`, and `4k`.
- `doubao-seedance-2-0-fast-260128` and `doubao-seedance-2-0-mini-260615` only support `480p` and `720p`.
- `doubao-seedance-2-0-260128` supports `480p`, `720p`, `1080p`, and `4k`.
- The node UI exposes `duration` as integers `4` through `15` for strict control.
- The backend payload builder still understands `-1` as model-auto duration for direct API use.
- `ratio` is limited to `adaptive`, `16:9`, `9:16`, `1:1`, `4:3`, `3:4`, and `21:9`.
- `Text-to-Video` requires a non-empty `prompt`.
- The non-text generation nodes allow an empty `prompt` and omit the text item from `content`.
- `Multimodal-to-Video` requires at least one reference input and rejects audio-only requests.
- `Asset Model-to-Video` requires an asset URI in `asset://asset-...` format and an outfit/product image.
- `Asset Model-to-Video` also accepts optional image, video, and audio references. Local video/audio files are uploaded to `tmpfiles.org`.
- `Upload Image Asset` requires Ark Access Key credentials and an existing `GroupId`; it does not create asset groups or run real-person validation.
- `Trusted Person Asset` requires the Seedance advanced creation entitlement and an AK/SK identity with `ArkFullAccess`.
- Local image inputs do not use `tmpfiles.org`; they are encoded into the Ark request body.
- `tmpfiles.org` is still used for local video/audio inputs and for local image asset upload. Files expire after 60 minutes and the upload limit is 100 MB per file.
- The temporary URLs are not exposed in the node UI.
- Seedance control fields are sent as top-level task API fields, and text prompts are sent as `{"type": "text"}` items in `content`.

## Human Face Limitation

The official Volcengine Seedance 2.0 / 2.0 fast documentation states that multimodal reference mode does not directly support ordinary human-face reference images or videos.

Practical guidance:

- If your goal is "make this portrait photo come alive", prefer `First-Frame-to-Video`.
- If your goal uses a real-person or virtual model asset from Ark, use `Asset Model-to-Video` and pass the asset URI, for example `asset://asset-20260624155748-cb5d4`.
- Use `Multimodal-to-Video` for reference-style composition, pacing, scene, or mixed media guidance.
- This plugin does not try to detect faces or block requests automatically; it only exposes the modes explicitly.

## Asset Model Workflow

Use `ComfyUI-Seedance Asset Model-to-Video` when Ark rejects an ordinary image with `input image may contain real person`.

Inputs:

- `model_asset_uri`: a trusted Ark private or virtual model asset URI, such as `asset://asset-20260624155748-cb5d4`.
- `outfit_image`: local clothing, product, or main visual reference. The prompt should call this `图片2`.
- `extra_reference_asset_uri`: optional trusted background, scene, or style asset. The prompt should call this `图片3`.
- `extra_reference_image`: optional local scene, composition, or style reference. If `extra_reference_asset_uri` is also present, this becomes `图片4`.

Recommended prompt:

```text
图片1中的模特穿上图片2中的服装，保持图片1的人脸身份、发型和身材特征一致，服装款式、颜色、材质严格参考图片2。生成电商模特展示视频，人物自然站立/转身展示服装，背景简洁，画面干净。
```

Do not write the asset ID directly in the prompt. Use `图片1`, `图片2`, `图片3`, and so on to refer to references by their order in the request.

## Asset Upload Workflow

Use `ComfyUI-Seedance Upload Image Asset` when you need a real-person or model image to become an Ark trusted asset first.

For ordinary backgrounds, scenes, products, or clothing images, use the normal image inputs instead. A real-person Asset Group checks face consistency against the verified person in that group, so uploading a background or unrelated face to that group will fail with `FaceMismatch`.

Inputs:

- `group_id`: existing Ark Asset Group ID, such as `group-...`.
- `source_url`: optional public image URL. If set, the node uses it directly.
- `image`: optional local ComfyUI image. Used only when `source_url` is empty.
- `project_name`: Ark project name. Keep it aligned with the project used by your Seedance endpoint.
- `name`: optional asset display name.
- `wait_for_active`: when enabled, the node polls `GetAsset` until the asset is `Active`.

Outputs:

- `asset_uri`: connect this to `model_asset_uri` or `extra_reference_asset_uri`.
- `asset_id`
- `status`
- `asset_url`

Local image asset upload first publishes the image to `tmpfiles.org`, because Ark `CreateAsset` requires a public URL. If tmpfiles is unstable on your network, provide a stable `source_url` instead.

## Trusted Person Asset Workflow

Use `ComfyUI-Seedance Trusted Person Asset` when the real-person Asset Group has not been created yet.

1. Keep `project_name` aligned with the project used by the Seedance inference endpoint.
2. Click `创建真人认证`. The node creates a 30-minute validation session and opens the Ark H5 page.
3. Complete the validation and return to ComfyUI. The node writes the resulting `group_id` automatically.
4. Connect an `IMAGE`, or provide `source_url`, and queue the node.
5. Connect the returned `asset_uri` to `Asset Model-to-Video`.

The default callback targets the current ComfyUI server. Set `callback_url` only when ComfyUI is behind a proxy or must use a different browser-reachable address. The workflow never stores the H5 link or `BytedToken`.

Privacy warning: local asset images still use the existing `tmpfiles.org` bridge. For real-person material, prefer a controlled `source_url`; do not use the local-image path for sensitive production assets unless that public temporary upload is acceptable.

## Configuration

Create [config.local.json](./config.local.json) in the repository root. Use [config.example.json](./config.example.json) as the template.

```json
{
  "api_key": "",
  "base_url": "https://ark.cn-beijing.volces.com/api/v3",
  "poll_interval": 15.0,
  "request_timeout": 60,
  "upload_timeout": 120,
  "access_key_id": "",
  "secret_access_key": "",
  "asset_base_url": "https://ark.cn-beijing.volcengineapi.com",
  "asset_project_name": "default",
  "asset_poll_interval": 5.0,
  "asset_timeout": 60,
  "asset_wait_timeout": 900
}
```

`api_key` is the Ark Bearer API key for video generation. `access_key_id` and `secret_access_key` are the AK/SK pair for asset management APIs.

Supported environment variables:

- `ARK_API_KEY`
- `SEEDANCE_API_KEY`
- `SEEDANCE_BASE_URL`
- `SEEDANCE_POLL_INTERVAL`
- `SEEDANCE_REQUEST_TIMEOUT`
- `SEEDANCE_UPLOAD_TIMEOUT`
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

3. Add `config.local.json` with a Volcengine Ark API key, or set `ARK_API_KEY`.
4. For asset upload, also add `access_key_id` and `secret_access_key`, or set `ARK_ACCESS_KEY_ID` and `ARK_SECRET_ACCESS_KEY`.
5. Restart ComfyUI.

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
- `image`
- Optional `reference_video` as ComfyUI `VIDEO`
- Optional `reference_audio` as ComfyUI `AUDIO`

### First-Last-Frame-to-Video

Inputs:

- `model`
- `prompt`
- `resolution`
- `duration`
- `ratio`
- `generate_audio`
- `watermark`
- `first_image`
- `last_image`

### Asset Model-to-Video

Inputs:

- `model`
- `model_asset_uri`
- `prompt`
- `outfit_image`
- `resolution`
- `duration`
- `ratio`
- `generate_audio`
- `watermark`
- Optional `extra_reference_asset_uri`
- Optional `extra_reference_image`
- Optional `reference_video` as ComfyUI `VIDEO`
- Optional `reference_audio` as ComfyUI `AUDIO`

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
- Optional `video_1` through `video_3` as ComfyUI `VIDEO`
- Optional `audio_1` through `audio_3` as ComfyUI `AUDIO`

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

## Examples

Starter workflow JSON files live in [examples/](./examples):

- [01_comfyui_seedance_text_workflow.json](./examples/01_comfyui_seedance_text_workflow.json)
- [02_comfyui_seedance_first_frame_workflow.json](./examples/02_comfyui_seedance_first_frame_workflow.json)
- [03_comfyui_seedance_first_last_frame_workflow.json](./examples/03_comfyui_seedance_first_last_frame_workflow.json)
- [04_comfyui_seedance_multimodal_mixed_workflow.json](./examples/04_comfyui_seedance_multimodal_mixed_workflow.json)
- [05_comfyui_seedance_trusted_person_asset_workflow.json](./examples/05_comfyui_seedance_trusted_person_asset_workflow.json)

See [examples/README.md](./examples/README.md) for a quick description of each one.

## References

- [Volcengine Create Video Generation Task documentation (CN)](https://www.volcengine.com/docs/82379/1520757?lang=zh)
- [Volcengine Seedance 2.0 SDK examples (CN)](https://www.volcengine.com/docs/82379/2291680?lang=zh)
- [Volcengine private trusted asset library guide (CN)](https://www.volcengine.com/docs/82379/2333589?lang=zh)
- [Volcengine CreateAsset documentation (CN)](https://www.volcengine.com/docs/82379/2318271?lang=zh)
- [tmpfiles API](https://tmpfiles.org/api)
