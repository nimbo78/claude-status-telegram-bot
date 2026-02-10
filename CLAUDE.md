# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python 3.12 async Telegram bot that monitors status.claude.com and sends notifications for incidents, status changes, and component updates. Polls the Statuspage API every 5 minutes (configurable) and edits existing messages when incidents receive updates to keep chat clean.

## Development Commands

### Docker (Primary Method)

```bash
# Start the bot
docker compose up -d

# View logs in real-time
docker compose logs -f

# Restart after config changes
docker compose restart

# Stop the bot
docker compose down

# Update to latest pre-built image (production)
docker compose pull && docker compose up -d

# Rebuild from source (development)
docker compose up -d --build
```

### GitHub Actions CI/CD

The repository uses GitHub Actions to automatically build and publish Docker images to GitHub Container Registry (ghcr.io) when:
- Code is pushed to the `main` branch
- A new version tag is created

**Workflow file**: `.github/workflows/docker-build.yml`

This enables quick deployment on remote servers without needing to build locally - just `docker compose pull` to get the latest image.

### Local Python Development

```bash
# Setup virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

# Run bot
STATE_FILE=./state.json python bot.py
```

### Configuration

Required environment variables in `.env`:
- `TELEGRAM_BOT_TOKEN` - Get from @BotFather
- `TELEGRAM_CHAT_ID` - Get from @userinfobot (comma-separated for multiple destinations)

Optional:
- `POLL_INTERVAL` - Seconds between checks (default: 300)
- `STATE_FILE` - Path to state persistence file (default: /data/state.json)
- `LOG_LEVEL` - DEBUG/INFO/WARNING/ERROR (default: INFO)

## Architecture

### Core Components

- **bot.py** - Main polling loop, change detection logic, and `/status` command handler
- **statuspage.py** - Statuspage API client with typed data models (StatusSummary, Incident, Component, IncidentUpdate)
- **notifier.py** - Telegram message formatting and sending/editing, handles MarkdownV2 escaping
- **storage.py** - JSON state persistence to track changes and message IDs
- **config.py** - Environment variable loading via python-dotenv

### State Management

The bot maintains state in a JSON file to detect changes and avoid duplicate notifications:

```python
{
  "indicator": str,              # Overall status: none/minor/major/critical
  "components": {},              # {component_id: status}
  "incident_ids": [],            # Known incident IDs
  "incident_updates": {},        # {incident_id: [update_ids]}
  "incident_statuses": {},       # {incident_id: status}
  "message_ids": {}              # {incident_id: {chat_id: message_id}}
}
```

**Critical**: `message_ids` stores Telegram message IDs keyed by incident ID and chat ID, enabling the bot to edit messages when incidents receive updates. When editing fails (message deleted, too old), the bot falls back to sending a new message.

### Change Detection Flow

1. **First Run** (`state["indicator"] is None`):
   - Sends startup notification with current status
   - Initializes state without triggering change notifications

2. **Subsequent Runs**:
   - Compares fetched summary with saved state
   - Triggers notifications for: overall status changes, component status changes, new incidents, incident updates
   - **Incident updates**: Edits the original message rather than sending new ones (keeps chat clean)
   - Updates state after processing all changes

### Async Architecture

- Uses `asyncio` for concurrent operations
- `aiohttp` for non-blocking API requests
- `python-telegram-bot` v21+ (async version)
- Polling loop runs as background task via `asyncio.create_task()`
- `/status` command handled by telegram.ext handlers

### Telegram Message Editing

When an incident receives updates, the bot edits the original message with the full timeline. This requires:
- Storing `message_ids` per incident per chat in state
- Comparing incident update IDs to detect new updates
- Comparing incident status to detect status changes
- Building full message content on each edit (includes all updates in reverse chronological order)

### API Integration

Uses Statuspage API v2 endpoint: `https://status.claude.com/api/v2/summary.json`
- Unauthenticated, no rate limit
- Returns: overall status, components, incidents with updates, scheduled maintenances
- Filters out component groups and the "Visit status.claude.com" placeholder component

### Error Handling

- Continues polling on API failures (logs warning, retries next cycle)
- Catches exceptions in poll loop to prevent crashes
- Gracefully handles Telegram API errors (bad requests, network issues)
- Falls back to sending new message if editing fails

## Key Implementation Details

- **MarkdownV2 Escaping**: All user-facing text must be escaped via `_esc()` in notifier.py
- **Multiple Destinations**: Bot sends to all configured chat IDs (user chats, groups, channels)
- **Docker Volume**: State file persists in `/data` volume to survive container restarts
- **Logging**: Structured logging with configurable level, outputs to stdout for Docker logs
