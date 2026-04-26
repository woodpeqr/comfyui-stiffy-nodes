from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Self, Tuple

import yaml

from .constants import NEGATIVE_CATEGORY, ROOT_DIR, USER_PRESETS_PATH
from .models import CategoryList, Prompt


# ─── File cache ───────────────────────────────────────────────────────────────

@dataclass
class CachedFile:
    time_modified: float
    contents: str


class FileCache:
    _items: Dict[Path, CachedFile] = {}

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> str:
        m_time = self.path.stat().st_mtime
        cached = self._items.get(self.path)
        if cached and cached.time_modified == m_time:
            return cached.contents
        print(f"{self.path} cache miss")
        with open(self.path) as f:
            cf = CachedFile(contents=f.read(), time_modified=m_time)
        self._items[self.path] = cf
        return cf.contents

    def write(self, contents: str) -> None:
        with open(self.path, "w") as f:
            f.write(contents)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @classmethod
    def open(cls, path: Path, create_if_does_not_exist: bool = False) -> Self:
        if not path.exists():
            if create_if_does_not_exist:
                path.touch()
            else:
                raise FileNotFoundError(f"{path} does not exist!")
        if not path.is_file():
            raise ValueError(f"{path} is not a file!")
        return cls(path)

    @classmethod
    def clear(cls) -> None:
        cls._items.clear()


# ─── Category loading ─────────────────────────────────────────────────────────

_leaf_categories_cache: Optional[List[str]] = None


def get_leaf_categories() -> List[str]:
    global _leaf_categories_cache
    if _leaf_categories_cache is not None:
        return _leaf_categories_cache
    path = ROOT_DIR / "categories.yaml"
    with open(path) as f:
        raw = yaml.safe_load(f)
    _leaf_categories_cache = CategoryList.from_yaml(raw).categories
    return _leaf_categories_cache


# ─── Preset storage ───────────────────────────────────────────────────────────

class PresetConflictError(Exception):
    pass


def _load_preset_storage() -> Dict[str, List[Prompt]]:
    if not USER_PRESETS_PATH.exists():
        return {}
    fc = FileCache.open(USER_PRESETS_PATH)
    raw = yaml.safe_load(fc.read())
    if not raw:
        return {}
    return {
        name: [Prompt(**entry) for entry in entries]
        for name, entries in raw.items()
        if entries
    }


def _save_preset_storage(storage: Dict[str, List[Prompt]]) -> None:
    USER_PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fc = FileCache.open(USER_PRESETS_PATH, create_if_does_not_exist=True)
    fc.write(yaml.dump(
        {name: [p.model_dump() for p in prompts] for name, prompts in storage.items()},
        default_flow_style=False,
        allow_unicode=True,
    ))


def load_preset(name: str) -> Optional[List[Prompt]]:
    return _load_preset_storage().get(name)


def save_preset(name: str, prompts: List[Prompt]) -> None:
    storage = _load_preset_storage()
    storage[name] = prompts
    _save_preset_storage(storage)


def list_preset_names(category: Optional[str] = None) -> List[str]:
    storage = _load_preset_storage()
    if category is None:
        return list(storage.keys())
    return [
        name for name, prompts in storage.items()
        if any(p.category == category for p in prompts)
    ]


def check_and_maybe_save_preset(
    name: str,
    prompts: List[Prompt],
    do_save: bool,
) -> None:
    """Raise PresetConflictError if stored preset differs and do_save is False. Save if do_save is True."""
    from .constants import NEW_PRESET_SENTINEL
    if not name or name == NEW_PRESET_SENTINEL:
        return
    stored = load_preset(name)
    if stored is not None:
        stored_map = {p.category: p.prompt for p in stored}
        new_map = {p.category: p.prompt for p in prompts}
        if stored_map != new_map and not do_save:
            raise PresetConflictError(
                f"Preset '{name}' is stored with different content. "
                "Enable 'save' to overwrite, or clear the preset name to use in-graph only."
            )
    if do_save:
        save_preset(name, prompts)


# ─── Prompt encoding ─────────────────────────────────────────────────────────

def encode_prompts(prompts: List[Prompt]) -> str:
    if not prompts:
        return ""
    return yaml.dump(
        [p.model_dump() for p in prompts],
        default_flow_style=False,
        allow_unicode=True,
    )


def decode_prompts(encoded: str) -> List[Prompt]:
    if not encoded:
        return []
    raw = yaml.safe_load(encoded)
    if not raw:
        return []
    return [Prompt(**entry) for entry in raw]


def join_prompt_strings(*parts: str) -> str:
    return ", ".join(p.strip(" ,") for p in parts if p and p.strip(" ,"))


def dedup_prompt_string(s: str) -> str:
    seen: Dict[str, bool] = {}
    result: List[str] = []
    for token in (t.strip() for t in s.split(",")):
        if token and token not in seen:
            seen[token] = True
            result.append(token)
    return ", ".join(result)


def decode_to_strings(encoded: str, deduplicate: bool = False) -> Tuple[str, str]:
    prompts = decode_prompts(encoded)
    positives = [p.prompt for p in prompts if p.category != NEGATIVE_CATEGORY and p.prompt]
    negatives = [p.prompt for p in prompts if p.category == NEGATIVE_CATEGORY and p.prompt]
    pos = join_prompt_strings(*positives)
    neg = join_prompt_strings(*negatives)
    if deduplicate:
        pos = dedup_prompt_string(pos)
        neg = dedup_prompt_string(neg)
    return pos, neg


def merge_encoded_with_selections(
    encoded_inputs: List[Optional[str]],
    category_selections: Dict[str, int],
) -> str:
    """
    Merge multiple encoded prompts into one, respecting per-category source selections.

    encoded_inputs: list of encoded strings, index 0 = input slot 1 (1-based externally)
    category_selections: {category: 1-based input index}, 0 or absent = merge all sources
    """
    decoded: Dict[int, List[Prompt]] = {}
    for i, enc in enumerate(encoded_inputs):
        if enc:
            decoded[i + 1] = decode_prompts(enc)

    if not decoded:
        return ""

    category_parts: Dict[str, List[str]] = {}
    for idx, prompts in decoded.items():
        for prompt in prompts:
            sel = category_selections.get(prompt.category, 0)
            if sel != 0 and sel != idx:
                continue
            if prompt.prompt:
                category_parts.setdefault(prompt.category, []).append(prompt.prompt)

    result = [
        Prompt(category=cat, prompt=join_prompt_strings(*parts))
        for cat, parts in category_parts.items()
    ]
    return encode_prompts(result)
