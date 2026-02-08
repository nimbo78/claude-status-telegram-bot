"""JSON-file state persistence for tracking status changes and Telegram message IDs."""

import json
import logging
import os
from typing import Any

import config

logger = logging.getLogger(__name__)

_DEFAULT_STATE: dict[str, Any] = {
    "indicator": None,
    "components": {},           # component_id -> status
    "incident_ids": [],         # list of known incident IDs
    "incident_updates": {},     # incident_id -> list of update IDs
    "incident_statuses": {},    # incident_id -> last known status
    "message_ids": {},          # incident_id -> telegram message_id (for editing)
}


def _ensure_dir():
    directory = os.path.dirname(config.STATE_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)


def load_state() -> dict[str, Any]:
    if not os.path.exists(config.STATE_FILE):
        logger.info("No state file found, starting fresh")
        return json.loads(json.dumps(_DEFAULT_STATE))
    try:
        with open(config.STATE_FILE, "r") as f:
            state = json.load(f)
            for key, default in _DEFAULT_STATE.items():
                if key not in state:
                    state[key] = type(default)() if isinstance(default, (dict, list)) else default
            return state
    except Exception:
        logger.exception("Failed to read state file, starting fresh")
        return json.loads(json.dumps(_DEFAULT_STATE))


def save_state(state: dict[str, Any]):
    _ensure_dir()
    try:
        with open(config.STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        logger.exception("Failed to save state file")
