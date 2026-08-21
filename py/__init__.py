from .nodes import (
    NODE_PREFIX,
    PreviewVideoNode,
    Seedance25OmniNode,
    SeedanceAssetModelNode,
    SeedanceCreateAssetGroupNode,
    SeedanceFirstFrameNode,
    SeedanceFirstLastFrameNode,
    SeedanceGetAssetNode,
    SeedanceMultimodalNode,
    SeedanceTextNode,
    SeedanceTrustedPersonAssetNode,
    SeedanceUploadAssetNode,
    SeedanceUploadImageAssetNode,
    VoiceCloneV3QueryNode,
    VoiceCloneV3TTSNode,
    VoiceCloneV3TrainNode,
)


def _node_name(label):
    return f"{NODE_PREFIX} {label}"


NODE_CLASS_MAPPINGS = {
    _node_name("Text-to-Video"): SeedanceTextNode,
    _node_name("First-Frame-to-Video"): SeedanceFirstFrameNode,
    _node_name("First-Last-Frame-to-Video"): SeedanceFirstLastFrameNode,
    _node_name("Asset Model-to-Video"): SeedanceAssetModelNode,
    _node_name("Create Asset Group"): SeedanceCreateAssetGroupNode,
    _node_name("Upload Asset"): SeedanceUploadAssetNode,
    _node_name("Get Asset"): SeedanceGetAssetNode,
    _node_name("Trusted Person Asset"): SeedanceTrustedPersonAssetNode,
    _node_name("Upload Image Asset"): SeedanceUploadImageAssetNode,
    _node_name("Multimodal-to-Video"): SeedanceMultimodalNode,
    _node_name("2.5 Omni-to-Video"): Seedance25OmniNode,
    _node_name("Preview Video"): PreviewVideoNode,
    _node_name("Voice Clone V3 Train"): VoiceCloneV3TrainNode,
    _node_name("Voice Clone V3 Query"): VoiceCloneV3QueryNode,
    _node_name("Voice Clone V3 TTS"): VoiceCloneV3TTSNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {key: key for key in NODE_CLASS_MAPPINGS}
