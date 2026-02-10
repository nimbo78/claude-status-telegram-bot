# Deployment Guide

## Quick Deploy from GitHub Container Registry

This method uses pre-built Docker images from GitHub, so you don't need to build anything locally.

### First Time Setup

1. **On your remote server**, create a directory and download the configuration files:

```bash
mkdir -p ~/claude-status-bot
cd ~/claude-status-bot

# Download docker-compose.yml
curl -O https://raw.githubusercontent.com/nimbo78/claude-status-telegram-bot/main/docker-compose.yml

# Download .env.example
curl -O https://raw.githubusercontent.com/nimbo78/claude-status-telegram-bot/main/.env.example

# Create your .env file
cp .env.example .env
```

2. **Edit `.env`** with your credentials:

```bash
nano .env
```

Add your:
- `TELEGRAM_BOT_TOKEN` (from @BotFather)
- `TELEGRAM_CHAT_ID` (from @userinfobot)

3. **Start the bot**:

```bash
docker compose pull
docker compose up -d
```

4. **Check logs**:

```bash
docker compose logs -f
```

### Updating to Latest Version

When new changes are pushed to the main branch, GitHub automatically builds a new image.

To update your bot:

```bash
cd ~/claude-status-bot
docker compose pull
docker compose up -d
```

That's it! Docker will pull the latest image and restart the container.

### Useful Commands

```bash
# View logs
docker compose logs -f

# Stop the bot
docker compose down

# Restart the bot
docker compose restart

# Check status
docker compose ps

# Update and restart
docker compose pull && docker compose up -d
```

## Alternative: Build Locally

If you prefer to build the image yourself instead of using the pre-built one:

1. **Edit `docker-compose.yml`**:

```yaml
services:
  claude-status-bot:
    # Comment out the image line:
    # image: ghcr.io/nimbo78/claude-status-telegram-bot:main

    # Uncomment the build line:
    build: .
```

2. **Clone the repository**:

```bash
git clone https://github.com/nimbo78/claude-status-telegram-bot.git
cd claude-status-telegram-bot
```

3. **Configure and run**:

```bash
cp .env.example .env
nano .env  # Add your credentials
docker compose up -d --build
```

## GitHub Container Registry Access

The images are public, so no authentication is required to pull them. The images are automatically built when:

- Code is pushed to the `main` branch
- A new tag is created (e.g., `v1.0.0`)

## Image Tags

- `main` - Latest version from the main branch (recommended for most users)
- `sha-XXXXXXX` - Specific commit hash
- `vX.Y.Z` - Specific version tag (when available)

Example using a specific version:

```yaml
image: ghcr.io/nimbo78/claude-status-telegram-bot:v1.0.0
```

## Troubleshooting

### "permission denied" when pulling image

Make sure Docker is installed and running:

```bash
sudo systemctl start docker
sudo systemctl enable docker
```

### Bot not sending messages

1. Check logs: `docker compose logs -f`
2. Verify your `.env` file has correct `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
3. Make sure the bot is added to the chat/channel if sending to groups/channels

### Image not updating

Force pull the latest image:

```bash
docker compose pull --ignore-buildable
docker compose up -d --force-recreate
```
