# Examples

This folder contains five starter workflows for the split Seedance generation modes, trusted assets, and the standalone preview node:

- `01_comfyui_seedance_text_workflow.json`
  Uses `ComfyUI-Seedance Text-to-Video` and pipes the returned `url` into `ComfyUI-Seedance Preview Video`.

- `02_comfyui_seedance_first_frame_workflow.json`
  Uses `LoadImage`, `ComfyUI-Seedance First-Frame-to-Video`, and `ComfyUI-Seedance Preview Video`.

- `03_comfyui_seedance_first_last_frame_workflow.json`
  Uses two `LoadImage` nodes, `ComfyUI-Seedance First-Last-Frame-to-Video`, and `ComfyUI-Seedance Preview Video`.

- `04_comfyui_seedance_multimodal_mixed_workflow.json`
  Uses `LoadImage`, `LoadVideo`, `LoadAudio`, `ComfyUI-Seedance Multimodal-to-Video`, and `ComfyUI-Seedance Preview Video`.

- `05_comfyui_seedance_trusted_person_asset_workflow.json`
  Uses `LoadImage` and `ComfyUI-Seedance Trusted Person Asset`. Create and complete real-person validation from the node UI before queueing the workflow.

Prepare `config.local.json` first, then import the workflow you want to start from.
