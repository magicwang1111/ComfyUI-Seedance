# Examples

This folder contains four starter workflows for the split Seedance generation modes plus the standalone preview node:

- `01_comfyui_seedance_text_workflow.json`
  Uses `ComfyUI-Seedance Text-to-Video` and pipes the returned `url` into `ComfyUI-Seedance Preview Video`.

- `02_comfyui_seedance_first_frame_workflow.json`
  Uses `LoadImage`, `ComfyUI-Seedance First-Frame-to-Video`, and `ComfyUI-Seedance Preview Video`.

- `03_comfyui_seedance_first_last_frame_workflow.json`
  Uses two `LoadImage` nodes, `ComfyUI-Seedance First-Last-Frame-to-Video`, and `ComfyUI-Seedance Preview Video`.

- `04_comfyui_seedance_multimodal_mixed_workflow.json`
  Uses `LoadImage`, `LoadVideo`, `LoadAudio`, `ComfyUI-Seedance Multimodal-to-Video`, and `ComfyUI-Seedance Preview Video`.

Prepare `config.local.json` first, then import the workflow you want to start from.
