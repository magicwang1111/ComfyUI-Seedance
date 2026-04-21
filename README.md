# ComfyUI-Seedance

`ComfyUI-Seedance` is a small ComfyUI custom node pack for generating Seedance videos through AIHubMix relay mode.

It exposes five nodes under the `ComfyUI-Seedance` category:

- `ComfyUI-Seedance Text-to-Video`
- `ComfyUI-Seedance First-Frame-to-Video`
- `ComfyUI-Seedance First-Last-Frame-to-Video`
- `ComfyUI-Seedance Multimodal-to-Video`
- `ComfyUI-Seedance Preview Video`

## What It Supports

- Model switching inside every generation node:
  - `doubao-seedance-2-0-260128`
  - `doubao-seedance-2-0-fast-260128`
- AIHubMix relay mode through `https://aihubmix.com`
- Seedance-native parameter names:
  - `resolution`
  - `duration`
  - `ratio`
  - `generate_audio`
  - `watermark`
- Automatic upload of local image, video, and audio references to `tmpfiles.org`
- A standalone `Preview Video` node for explicit playback and saving

## Mode Split

The generation nodes now mirror the three official Seedance image/video input modes instead of guessing from image count:

- `Text-to-Video`
  Pure text generation. `prompt` is required.
- `First-Frame-to-Video`
  Uses one local `IMAGE` and sends it as `first_frame`.
- `First-Last-Frame-to-Video`
  Uses two local `IMAGE` inputs and sends them as `first_frame` and `last_frame`.
- `Multimodal-to-Video`
  Uses reference inputs only:
  - `image_1` through `image_9` become `reference_image`
  - `video_1` through `video_3` become `reference_video`
  - `audio_1` through `audio_3` become `reference_audio`

`Multimodal-to-Video` keeps its original node name for workflow compatibility, but it is now explicitly the reference-mode node.

## Current API Notes

- This package only supports AIHubMix relay mode.
- `resolution` is limited to `480p` and `720p`.
- The node UI exposes `duration` as integers `4` through `15` for strict control.
- The backend payload builder still understands `-1` as model-auto duration for direct API use.
- `ratio` is limited to `adaptive`, `16:9`, `9:16`, `1:1`, `4:3`, `3:4`, and `21:9`.
- `Text-to-Video` requires a non-empty `prompt`.
- The non-text generation nodes allow an empty `prompt` and omit it from the API request.
- `Multimodal-to-Video` requires at least one reference input and rejects audio-only requests.
- `tmpfiles.org` files expire after 60 minutes and the upload limit is 100 MB per file.
- The temporary URLs are not exposed in the node UI.
- Seedance control fields are sent inside `extra_body` to match the public AIHubMix relay example structure.

## Human Face Limitation

The official Volcengine Seedance 2.0 / 2.0 fast documentation states that multimodal reference mode does not directly support ordinary human-face reference images or videos.

Practical guidance:

- If your goal is "make this portrait photo come alive", prefer `First-Frame-to-Video`.
- Use `Multimodal-to-Video` for reference-style composition, pacing, scene, or mixed media guidance.
- This plugin does not try to detect faces or block requests automatically; it only exposes the modes explicitly.

## Configuration

Create [config.local.json](./config.local.json) in the repository root. Use [config.example.json](./config.example.json) as the template.

```json
{
  "api_key": "",
  "base_url": "https://aihubmix.com",
  "poll_interval": 15.0,
  "request_timeout": 60,
  "upload_timeout": 120
}
```

Supported environment variables:

- `SEEDANCE_API_KEY`
- `SEEDANCE_BASE_URL`
- `SEEDANCE_POLL_INTERVAL`
- `SEEDANCE_REQUEST_TIMEOUT`
- `SEEDANCE_UPLOAD_TIMEOUT`
- `AIHUBMIX_API_KEY`
- `AIHUBMIX_BASE_URL`
- `AIHUBMIX_POLL_INTERVAL`
- `AIHUBMIX_REQUEST_TIMEOUT`
- `AIHUBMIX_UPLOAD_TIMEOUT`

Priority:

1. `config.local.json`
2. Environment variables

## Installation

1. Place this folder under `ComfyUI/custom_nodes`.
2. Install Python dependencies:

   ```bash
   pip install -r ComfyUI/custom_nodes/ComfyUI-Seedance/requirements.txt
   ```

3. Add `config.local.json`.
4. Restart ComfyUI.

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

See [examples/README.md](./examples/README.md) for a quick description of each one.

## References

- [AIHubMix Video Gen documentation (CN)](https://docs.aihubmix.com/cn/api/Video-Gen)
- [Volcengine Create Video Generation Task documentation (CN)](https://www.volcengine.com/docs/82379/1520757?lang=zh)
- [AIHubMix model list](https://aihubmix.com/models)
- [tmpfiles API](https://tmpfiles.org/api)
