# ComfyUI-Seedance

`ComfyUI-Seedance` is a small ComfyUI custom node pack for generating Seedance videos through AIHubMix relay mode.

It exposes three nodes under the `ComfyUI-Seedance` category:

- `ComfyUI-Seedance Text-to-Video`
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
- A standalone `Preview Video` node for explicit playback and saving
- Saving finished MP4 files into ComfyUI output through `Preview Video`
- Remote preview when `Preview Video.save_output` is disabled

## Current API Notes

- This package only supports AIHubMix relay mode.
- `resolution` is limited to `480p` and `720p`.
- The node UI exposes `duration` as integers `4` through `15` for strict control.
- The backend payload builder still understands `-1` as model-auto duration for direct API use.
- `ratio` is limited to `adaptive`, `16:9`, `9:16`, `1:1`, `4:3`, `3:4`, and `21:9`.
- `Text-to-Video` is pure text only.
- `Multimodal-to-Video` can mix up to `9` public image URLs, `3` public video URLs, and `3` public audio URLs in one request.
- `Multimodal-to-Video` requires at least one reference input.
- Image, video, and audio references all require public `http/https` URLs.
- Seedance control fields are sent inside `extra_body` to match the public AIHubMix example structure more closely.

## Configuration

Create [config.local.json](./config.local.json) in the repository root. Use [config.example.json](./config.example.json) as the template.

```json
{
  "api_key": "",
  "base_url": "https://aihubmix.com",
  "poll_interval": 15.0,
  "request_timeout": 60
}
```

Supported environment variables:

- `SEEDANCE_API_KEY`
- `SEEDANCE_BASE_URL`
- `SEEDANCE_POLL_INTERVAL`
- `SEEDANCE_REQUEST_TIMEOUT`
- `AIHUBMIX_API_KEY`
- `AIHUBMIX_BASE_URL`
- `AIHUBMIX_POLL_INTERVAL`
- `AIHUBMIX_REQUEST_TIMEOUT`

Priority:

1. `config.local.json`
2. Environment variables

`base_url` decides which relay backend the plugin uses:

- `https://aihubmix.com` or `https://aihubmix.com/v1`
  Uses AIHubMix relay mode with `Authorization: Bearer ...`

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

Outputs:

- `url`
- `video_id`
- `file_path`

### Multimodal-to-Video

Inputs:

- `model`
- `prompt`
- `resolution`
- `duration`
- `ratio`
- `generate_audio`
- `watermark`
- Optional `image_url_1` through `image_url_9`
- Optional `video_url_1` through `video_url_3`
- Optional `audio_url_1` through `audio_url_3`

Outputs:

- `url`
- `video_id`
- `file_path`

### Preview Video

Inputs:

- `video_url`
- `filename_prefix`
- `save_output`

Outputs:

- `file_path`

Notes:

- Generation nodes return the remote result URL and leave `file_path` empty.
- To preview the generated video inside ComfyUI, connect `url` to `ComfyUI-Seedance Preview Video`.
- With `save_output=false`, the preview node plays the remote URL directly.
- With `save_output=true`, it downloads the MP4 to ComfyUI output first, then previews the local file.

## Examples

Four starter workflow JSON files live in [examples/](./examples):

- [01_comfyui_seedance_text_workflow.json](./examples/01_comfyui_seedance_text_workflow.json)
- [02_comfyui_seedance_multimodal_image_workflow.json](./examples/02_comfyui_seedance_multimodal_image_workflow.json)
- [03_comfyui_seedance_multimodal_video_audio_workflow.json](./examples/03_comfyui_seedance_multimodal_video_audio_workflow.json)
- [04_comfyui_seedance_multimodal_mixed_workflow.json](./examples/04_comfyui_seedance_multimodal_mixed_workflow.json)

See [examples/README.md](./examples/README.md) for a quick description of each one.

## References

- [AIHubMix Video Gen documentation (CN)](https://docs.aihubmix.com/cn/api/Video-Gen)
- [AIHubMix model list](https://aihubmix.com/models)
