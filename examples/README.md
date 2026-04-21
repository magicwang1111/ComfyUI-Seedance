# Examples

This folder contains four small starter workflows for the Seedance generation nodes plus the standalone preview node:

- `01_comfyui_seedance_text_workflow.json`
  Uses `ComfyUI-Seedance Text-to-Video` and pipes the returned `url` into `ComfyUI-Seedance Preview Video`.

- `02_comfyui_seedance_multimodal_image_workflow.json`
  Uses `LoadImage`, `ComfyUI-Seedance Multimodal-to-Video`, and `ComfyUI-Seedance Preview Video`.

- `03_comfyui_seedance_multimodal_video_audio_workflow.json`
  Uses `LoadVideo`, `LoadAudio`, `ComfyUI-Seedance Multimodal-to-Video`, and `ComfyUI-Seedance Preview Video`.

- `04_comfyui_seedance_multimodal_mixed_workflow.json`
  Uses `LoadImage`, `LoadVideo`, `LoadAudio`, `ComfyUI-Seedance Multimodal-to-Video`, and `ComfyUI-Seedance Preview Video`.

Prepare `config.local.json` first, then import the workflow you want to start from.
