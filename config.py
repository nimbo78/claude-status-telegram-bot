import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

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
