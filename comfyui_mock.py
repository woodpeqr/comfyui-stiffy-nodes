#!/usr/bin/env python3
"""
Mock ComfyUI environment for testing node logic.
Run from the repo root:  python comfyui_mock.py
"""
import importlib.util
import shutil
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

# ─── Mock ComfyUI dependencies ────────────────────────────────────────────────

for _mod in ["nodes", "server", "folder_paths", "comfy", "comfy.utils", "comfy.sd",
             "utils", "threadpoolctl"]:
    sys.modules[_mod] = MagicMock()

_nodes_mock = sys.modules["nodes"]
_nodes_mock.NODE_CLASS_MAPPINGS = {}
_nodes_mock.NODE_DISPLAY_NAME_MAPPINGS = {}

# ─── Bootstrap the package ───────────────────────────────────────────────────
# The directory name has hyphens so we register it as a Python package manually.

REPO = Path(__file__).parent
PKG = "stiffy_nodes"

_pkg = types.ModuleType(PKG)
_pkg.__path__ = [str(REPO)]
_pkg.__package__ = PKG
sys.modules[PKG] = _pkg


def _load(name: str):
    full_name = f"{PKG}.{name}"
    spec = importlib.util.spec_from_file_location(full_name, REPO / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = PKG
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("utils")
constants = _load("constants")
_load("models")
node_logic = _load("node_logic")
node_defs = _load("node_definitions")

Prompt = sys.modules[f"{PKG}.models"].Prompt
StiffySimplePresetNode = node_defs.StiffySimplePresetNode
StiffyComplexPresetNode = node_defs.StiffyComplexPresetNode
StiffyComboNode = node_defs.StiffyComboNode
StiffyDecoderNode = node_defs.StiffyDecoderNode

# ─── Test helpers ─────────────────────────────────────────────────────────────

_pass = 0
_fail = 0


def test(label: str, fn):
    global _pass, _fail
    try:
        fn()
        print(f"  \033[32m✓\033[0m {label}")
        _pass += 1
    except Exception as exc:
        print(f"  \033[31m✗\033[0m {label}: {exc}")
        _fail += 1


# ─── Tests ────────────────────────────────────────────────────────────────────

def run_all(tmp_dir: Path):
    # Redirect preset storage to temp dir
    constants.USER_PRESETS_PATH = tmp_dir / "user-presets.yaml"
    node_logic.USER_PRESETS_PATH = tmp_dir / "user-presets.yaml"

    # ── Encode / decode ──────────────────────────────────────────────────────
    print("\n── encode / decode ──")

    def t_roundtrip():
        prompts = [Prompt(category="body", prompt="slim body"), Prompt(category="negative", prompt="bad quality")]
        encoded = node_logic.encode_prompts(prompts)
        decoded = node_logic.decode_prompts(encoded)
        assert len(decoded) == 2
        assert decoded[0].category == "body" and decoded[0].prompt == "slim body"
        assert decoded[1].category == "negative"
    test("encode/decode round-trip", t_roundtrip)

    def t_decode_to_strings():
        enc = node_logic.encode_prompts([
            Prompt(category="body", prompt="slim body"),
            Prompt(category="action", prompt="jumping"),
            Prompt(category="negative", prompt="bad quality"),
        ])
        pos, neg = node_logic.decode_to_strings(enc)
        assert "slim body" in pos and "jumping" in pos
        assert "bad quality" in neg
    test("decode_to_strings", t_decode_to_strings)

    def t_dedup():
        enc = node_logic.encode_prompts([Prompt(category="body", prompt="slim body, slim body, petite")])
        pos, _ = node_logic.decode_to_strings(enc, deduplicate=True)
        assert pos == "slim body, petite", f"got: {pos!r}"
    test("deduplication", t_dedup)

    def t_empty_encode():
        assert node_logic.encode_prompts([]) == ""
    test("empty encode returns empty string", t_empty_encode)

    def t_empty_decode():
        assert node_logic.decode_prompts("") == []
    test("empty decode returns empty list", t_empty_decode)

    # ── Preset CRUD ──────────────────────────────────────────────────────────
    print("\n── preset CRUD ──")

    def t_save_load():
        prompts = [Prompt(category="body", prompt="slim body"), Prompt(category="negative", prompt="bad")]
        node_logic.save_preset("test-body", prompts)
        loaded = node_logic.load_preset("test-body")
        assert loaded is not None and loaded[0].prompt == "slim body"
    test("save and load", t_save_load)

    def t_list_all():
        names = node_logic.list_preset_names()
        assert "test-body" in names
    test("list all presets", t_list_all)

    def t_list_by_category():
        assert "test-body" in node_logic.list_preset_names("body")
        assert "test-body" not in node_logic.list_preset_names("action")
    test("list by category", t_list_by_category)

    def t_missing_preset():
        assert node_logic.load_preset("does-not-exist") is None
    test("load missing preset returns None", t_missing_preset)

    # ── Simple preset node ───────────────────────────────────────────────────
    print("\n── StiffySimplePresetNode ──")

    def t_simple_output():
        node = StiffySimplePresetNode()
        (enc,) = node.get_stiffy(category="body", prompt="slim body, skinny", negative_prompt="bad quality", save=False)
        decoded = node_logic.decode_prompts(enc)
        cats = {p.category for p in decoded}
        assert "body" in cats and "negative" in cats
    test("outputs encoded prompt with body + negative", t_simple_output)

    def t_simple_save():
        node = StiffySimplePresetNode()
        node.get_stiffy(category="action", preset_name="my-jump", prompt="jumping", save=True)
        stored = node_logic.load_preset("my-jump")
        assert stored is not None and any(p.prompt == "jumping" for p in stored)
    test("saves preset to disk when save=True", t_simple_save)

    def t_simple_conflict():
        node = StiffySimplePresetNode()
        try:
            node.get_stiffy(category="action", preset_name="my-jump", prompt="running", save=False)
            raise AssertionError("expected PresetConflictError")
        except node_logic.PresetConflictError:
            pass
    test("raises PresetConflictError on mismatch with save=False", t_simple_conflict)

    def t_simple_no_conflict_new_name():
        node = StiffySimplePresetNode()
        # Brand-new name — no stored preset, no conflict even with save=False
        (enc,) = node.get_stiffy(category="body", preset_name="brand-new", prompt="curvy", save=False)
        assert enc  # Just produces output, no error
    test("no conflict for new preset name", t_simple_no_conflict_new_name)

    def t_simple_no_negative_when_empty():
        node = StiffySimplePresetNode()
        (enc,) = node.get_stiffy(category="body", prompt="slim body", negative_prompt="", save=False)
        decoded = node_logic.decode_prompts(enc)
        assert not any(p.category == "negative" for p in decoded)
    test("no negative entry when negative_prompt is empty", t_simple_no_negative_when_empty)

    # ── Complex preset node ──────────────────────────────────────────────────
    print("\n── StiffyComplexPresetNode ──")

    def t_complex_output():
        node = StiffyComplexPresetNode()
        (enc,) = node.get_stiffy(
            preset_name="gothic",
            save=True,
            environment_prompt="dark castle",
            lighting_prompt="moonlight",
            mood_prompt="ominous",
            negative_prompt="oversaturated",
        )
        decoded = node_logic.decode_prompts(enc)
        cats = {p.category for p in decoded}
        assert {"environment", "lighting", "mood", "negative"}.issubset(cats)
        stored = node_logic.load_preset("gothic")
        assert stored is not None
    test("outputs multi-category encoded prompt and saves", t_complex_output)

    def t_complex_skips_empty():
        node = StiffyComplexPresetNode()
        (enc,) = node.get_stiffy(environment_prompt="forest", lighting_prompt="", save=False)
        decoded = node_logic.decode_prompts(enc)
        cats = {p.category for p in decoded}
        assert "environment" in cats
        assert "lighting" not in cats
    test("skips empty category fields", t_complex_skips_empty)

    # ── Combo node ───────────────────────────────────────────────────────────
    print("\n── StiffyComboNode ──")

    MERGE_ALL = node_logic.MERGE_ALL_SENTINEL

    def _pnginfo(unique_id, source_map):
        """Build minimal extra_pnginfo structure for combo node tests."""
        return {"workflow": {"nodes": [{"id": unique_id, "properties": {"_source_map": source_map}}]}}

    def t_combo_merge():
        enc1 = node_logic.encode_prompts([Prompt(category="body", prompt="slim body"), Prompt(category="negative", prompt="blurry")])
        enc2 = node_logic.encode_prompts([Prompt(category="action", prompt="jumping"), Prompt(category="negative", prompt="low quality")])
        node = StiffyComboNode()
        source_map = {"Node A": "encoded_1", "Node B": "encoded_2"}
        pnginfo = _pnginfo("1", source_map)
        (merged,) = node.get_stiffy(unique_id="1", extra_pnginfo=pnginfo, encoded_1=enc1, encoded_2=enc2)
        decoded = node_logic.decode_prompts(merged)
        cats = {p.category for p in decoded}
        assert "body" in cats and "action" in cats and "negative" in cats
    test("merges multiple inputs", t_combo_merge)

    def t_combo_selection():
        enc1 = node_logic.encode_prompts([Prompt(category="body", prompt="slim body")])
        enc2 = node_logic.encode_prompts([Prompt(category="body", prompt="curvy body")])
        node = StiffyComboNode()
        source_map = {"Node A": "encoded_1", "Node B": "encoded_2"}
        pnginfo = _pnginfo("2", source_map)
        # sel_body = "Node A" → only use encoded_1 for body category
        (merged,) = node.get_stiffy(unique_id="2", extra_pnginfo=pnginfo,
                                     encoded_1=enc1, encoded_2=enc2, sel_body="Node A")
        decoded = node_logic.decode_prompts(merged)
        body = next(p for p in decoded if p.category == "body")
        assert body.prompt == "slim body", f"got: {body.prompt!r}"
    test("category selection picks correct source", t_combo_selection)

    def t_combo_empty():
        node = StiffyComboNode()
        (merged,) = node.get_stiffy()
        assert merged == ""
    test("empty combo returns empty string", t_combo_empty)

    # ── Decoder node ─────────────────────────────────────────────────────────
    print("\n── StiffyDecoderNode ──")

    def t_decoder():
        enc = node_logic.encode_prompts([
            Prompt(category="body", prompt="slim body"),
            Prompt(category="action", prompt="jumping"),
            Prompt(category="negative", prompt="bad quality"),
        ])
        node = StiffyDecoderNode()
        pos, neg = node.get_stiffy(enc)
        assert "slim body" in pos and "jumping" in pos
        assert "bad quality" in neg
    test("decodes to positive and negative strings", t_decoder)

    def t_decoder_dedup():
        enc = node_logic.encode_prompts([
            Prompt(category="body", prompt="slim body, slim body, petite"),
            Prompt(category="negative", prompt="bad quality, bad quality"),
        ])
        node = StiffyDecoderNode()
        pos, neg = node.get_stiffy(enc, deduplicate=True)
        assert pos == "slim body, petite", f"got: {pos!r}"
        assert neg == "bad quality", f"got: {neg!r}"
    test("deduplication toggle works", t_decoder_dedup)

    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n{'─' * 40}")
    print(f"  {_pass} passed  |  {_fail} failed")
    if _fail:
        sys.exit(1)


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp())
    try:
        run_all(tmp)
    finally:
        shutil.rmtree(tmp)
