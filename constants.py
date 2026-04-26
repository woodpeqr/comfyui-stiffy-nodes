import os
from pathlib import Path

ENCODED_PROMPT_TYPE = "ENCODED_PROMPT"
NEGATIVE_CATEGORY = "negative"
NEW_PRESET_SENTINEL = "-- new --"

ROOT_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
USER_PRESETS_PATH = ROOT_DIR.joinpath("styles").joinpath("user-presets.yaml")
