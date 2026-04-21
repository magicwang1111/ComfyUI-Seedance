# Examples

This folder contains four small starter workflows for the Seedance generation nodes plus the standalone preview node:

- `01_comfyui_seedance_text_workflow.json`
  Uses `ComfyUI-Seedance Text-to-Video` and pipes the returned `url` into `ComfyUI-Seedance Preview Video`.

- `02_comfyui_seedance_multimodal_image_workflow.json`
  Uses `ComfyUI-Seedance Multimodal-to-Video` with a public `image_url`, then previews the generated result.

- `03_comfyui_seedance_multimodal_video_audio_workflow.json`
  Uses `ComfyUI-Seedance Multimodal-to-Video` with a public `video_url` and `audio_url`, then previews the generated result.

- `04_comfyui_seedance_multimodal_mixed_workflow.json`
  Uses `ComfyUI-Seedance Multimodal-to-Video` with public `image_url`, `video_url`, and `audio_url` references.

Prepare `config.local.json` first, then import the workflow you want to start from.
