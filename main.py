from nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

from .node_definitions import (
    StiffyComboNode,
    StiffyComplexPresetNode,
    StiffyDecoderNode,
    StiffySimplePresetNode,
)

NODE_CLASS_MAPPINGS.update({
    "StiffySimplePresetNode": StiffySimplePresetNode,
    "StiffyComplexPresetNode": StiffyComplexPresetNode,
    "StiffyComboNode": StiffyComboNode,
    "StiffyDecoderNode": StiffyDecoderNode,
})

NODE_DISPLAY_NAME_MAPPINGS.update({
    "StiffySimplePresetNode": "Stiffy Simple Preset",
    "StiffyComplexPresetNode": "Stiffy Complex Preset",
    "StiffyComboNode": "Stiffy Combo",
    "StiffyDecoderNode": "Stiffy Decoder",
})
