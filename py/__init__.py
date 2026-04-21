from .nodes import (
    NODE_PREFIX,
    PreviewVideoNode,
    SeedanceMultimodalNode,
    SeedanceTextNode,
)


def _node_name(label):
    return f"{NODE_PREFIX} {label}"


NODE_CLASS_MAPPINGS = {
    _node_name("Text-to-Video"): SeedanceTextNode,
    _node_name("Multimodal-to-Video"): SeedanceMultimodalNode,
    _node_name("Preview Video"): PreviewVideoNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {key: key for key in NODE_CLASS_MAPPINGS}
