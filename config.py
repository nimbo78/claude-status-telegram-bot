import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Multiple chat IDs supported: comma-separated
_raw_chat_ids = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = []
for cid in _raw_chat_ids.split(","):
    cid = cid.strip()
    if cid:
        if cid.startswith("@"):
            # Channel username - keep as string
            TELEGRAM_CHAT_IDS.append(cid)
        else:
            # Numeric ID - convert to integer
            try:
                TELEGRAM_CHAT_IDS.append(int(cid))
            except ValueError:
                # Fallback: keep as string if conversion fails
                TELEGRAM_CHAT_IDS.append(cid)

# Statuspage
STATUSPAGE_BASE_URL = os.getenv(
    "STATUSPAGE_BASE_URL", "https://status.claude.com"
)

# Polling interval in seconds (default: 5 minutes)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))

# State file path (inside container: /data/state.json)
STATE_FILE = os.getenv("STATE_FILE", "/data/state.json")

# Log level
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
