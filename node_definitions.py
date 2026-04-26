from typing import List, Optional, Tuple

from .constants import ENCODED_PROMPT_TYPE, NEGATIVE_CATEGORY, NEW_PRESET_SENTINEL
from .models import Prompt
from .node_logic import (
    check_and_maybe_save_preset,
    decode_to_strings,
    encode_prompts,
    get_leaf_categories,
    list_preset_names,
    merge_encoded_with_selections,
)


class StiffySimplePresetNode:
    @classmethod
    def INPUT_TYPES(cls):
        cats = get_leaf_categories()
        presets = [NEW_PRESET_SENTINEL] + list_preset_names()
        return {
            "required": {
                "category": (cats, {"default": cats[0] if cats else ""}),
            },
            "optional": {
                "load_preset": (presets, {"default": NEW_PRESET_SENTINEL}),
                "preset_name": ("STRING", {"multiline": False, "default": ""}),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                "save": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = (ENCODED_PROMPT_TYPE,)
    RETURN_NAMES = ("encoded_prompt",)
    CATEGORY = "stiffy"
    FUNCTION = "get_stiffy"

    def get_stiffy(
        self,
        category: str,
        load_preset: str = NEW_PRESET_SENTINEL,
        preset_name: str = "",
        prompt: str = "",
        negative_prompt: str = "",
        save: bool = False,
    ) -> Tuple[str]:
        prompts: List[Prompt] = [Prompt(category=category, prompt=prompt)]
        if negative_prompt.strip(" ,"):
            prompts.append(Prompt(category=NEGATIVE_CATEGORY, prompt=negative_prompt))

        check_and_maybe_save_preset(preset_name, prompts, save)

        return (encode_prompts(prompts),)


class StiffyComplexPresetNode:
    @classmethod
    def INPUT_TYPES(cls):
        cats = get_leaf_categories()
        presets = [NEW_PRESET_SENTINEL] + list_preset_names()
        category_widgets = {
            f"{cat}_prompt": ("STRING", {"multiline": False, "default": ""})
            for cat in cats
        }
        return {
            "optional": {
                "load_preset": (presets, {"default": NEW_PRESET_SENTINEL}),
                "preset_name": ("STRING", {"multiline": False, "default": ""}),
                "save": ("BOOLEAN", {"default": False}),
                **category_widgets,
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    RETURN_TYPES = (ENCODED_PROMPT_TYPE,)
    RETURN_NAMES = ("encoded_prompt",)
    CATEGORY = "stiffy"
    FUNCTION = "get_stiffy"

    def get_stiffy(
        self,
        load_preset: str = NEW_PRESET_SENTINEL,
        preset_name: str = "",
        save: bool = False,
        negative_prompt: str = "",
        **kwargs,
    ) -> Tuple[str]:
        cats = get_leaf_categories()
        prompts: List[Prompt] = []

        for cat in cats:
            p = kwargs.get(f"{cat}_prompt", "").strip(" ,")
            if p:
                prompts.append(Prompt(category=cat, prompt=p))

        if negative_prompt.strip(" ,"):
            prompts.append(Prompt(category=NEGATIVE_CATEGORY, prompt=negative_prompt))

        check_and_maybe_save_preset(preset_name, prompts, save)

        return (encode_prompts(prompts),)


class StiffyComboNode:
    @classmethod
    def INPUT_TYPES(cls):
        cats = get_leaf_categories()
        encoded_inputs = {
            f"encoded_{i}": (ENCODED_PROMPT_TYPE, {"forceInput": True})
            for i in range(1, 17)
        }
        sel_widgets = {
            f"sel_{cat}": ("INT", {"default": 0, "min": 0, "max": 16, "step": 1})
            for cat in [*cats, NEGATIVE_CATEGORY]
        }
        return {"optional": {**encoded_inputs, **sel_widgets}}

    RETURN_TYPES = (ENCODED_PROMPT_TYPE,)
    RETURN_NAMES = ("encoded_prompt",)
    CATEGORY = "stiffy"
    FUNCTION = "get_stiffy"

    def get_stiffy(self, **kwargs) -> Tuple[str]:
        cats = get_leaf_categories()
        encoded_inputs = [kwargs.get(f"encoded_{i}") for i in range(1, 17)]
        category_selections = {
            cat: kwargs.get(f"sel_{cat}", 0)
            for cat in [*cats, NEGATIVE_CATEGORY]
        }
        return (merge_encoded_with_selections(encoded_inputs, category_selections),)


class StiffyDecoderNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "encoded_prompt": (ENCODED_PROMPT_TYPE, {"forceInput": True}),
            },
            "optional": {
                "deduplicate": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt")
    CATEGORY = "stiffy"
    FUNCTION = "get_stiffy"

    def get_stiffy(self, encoded_prompt: str, deduplicate: bool = False) -> Tuple[str, str]:
        return decode_to_strings(encoded_prompt, deduplicate)
