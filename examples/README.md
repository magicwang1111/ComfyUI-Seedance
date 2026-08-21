# Examples

This folder contains ten starter workflows for Seedance generation, assets, preview, and V3 postpaid custom voices:

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

- `06_comfyui_seedance_asset_group_and_upload_workflow.json`
  Uses `ComfyUI-Seedance Create Asset Group` and `ComfyUI-Seedance Upload Asset` to create an Ark asset group and upload a virtual avatar asset through the new generic asset node.

- `07_comfyui_seedance_asset_uri_multimodal_workflow.json`
  Shows how to pass existing `asset://...` image, video, and audio references directly into `ComfyUI-Seedance Multimodal-to-Video` without local media loader nodes.

- `08_comfyui_seedance_voice_clone_train_query_workflow.json`
  Loads a sample, trains a V3 postpaid custom voice, and previews the audition. The disabled query branch can be enabled after entering an existing `custom_speaker_id`.

- `09_comfyui_seedance_voice_clone_tts_workflow.json`
  Shows formal `seed-icl-2.0` synthesis, including optional voice-instruction and previous-context inputs. The branch is disabled and `confirm_activation_fee` is false by default because the first request activates the 138 CNY voice slot.

- `10_comfyui_seedance_25_omni_workflow.json`
  Connects one image, video, and audio to the dynamic Seedance 2.5 Omni inputs. Connecting a trailing media socket automatically adds the next socket, up to 30 images, 10 videos, and 10 audios.

Prepare `config.local.json` first, then import the workflow you want to start from.
