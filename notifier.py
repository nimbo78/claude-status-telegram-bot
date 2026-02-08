"""Telegram notification sender with message editing for incident updates."""

import logging
from typing import Optional

import telegram

import config

logger = logging.getLogger(__name__)

INDICATOR_EMOJI = {
    "none": "🟢",
    "minor": "🟡",
    "major": "🟠",
    "critical": "🔴",
}

COMPONENT_STATUS_EMOJI = {
    "operational": "🟢",
    "degraded_performance": "🟡",
    "partial_outage": "🟠",
    "major_outage": "🔴",
    "under_maintenance": "🔧",
}

INCIDENT_STATUS_EMOJI = {
    "investigating": "🔍",
    "identified": "🎯",
    "monitoring": "👀",
    "resolved": "✅",
    "postmortem": "📋",
    "scheduled": "📅",
    "in_progress": "🔧",
    "verifying": "🔎",
    "completed": "✅",
}


def _esc(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    result = ""
    for ch in text:
        if ch in r"_*[]()~`>#+-=|{}.!\\":
            result += f"\\{ch}"
        else:
            result += ch
    return result


def _format_status(name: str) -> str:
    return name.replace("_", " ").title()


def _get_bot() -> telegram.Bot:
    return telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)


async def _send(text: str) -> Optional[int]:
    """Send message, return message_id."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured, skipping")
        return None
    try:
        bot = _get_bot()
        msg = await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        logger.info("Sent message %d", msg.message_id)
        return msg.message_id
    except Exception:
        logger.exception("Failed to send Telegram message")
        return None


async def _edit(message_id: int, text: str) -> bool:
    """Edit existing message. Returns True on success."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    try:
        bot = _get_bot()
        await bot.edit_message_text(
            chat_id=config.TELEGRAM_CHAT_ID,
            message_id=message_id,
            text=text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        logger.info("Edited message %d", message_id)
        return True
    except telegram.error.BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.debug("Message %d unchanged, skip", message_id)
            return True
        logger.exception("Failed to edit message %d", message_id)
        return False
    except Exception:
        logger.exception("Failed to edit message %d", message_id)
        return False


def build_incident_message(
    name: str, status: str, impact: str, shortlink: str,
    updates: list[tuple[str, str, str]],  # [(status, body, created_at), ...]
) -> str:
    """Build a full incident message with all updates (for sending or editing)."""
    resolved = status in ("resolved", "completed", "postmortem")
    header_emoji = "✅" if resolved else "🚨"
    header_label = "Resolved" if resolved else "Incident"

    s_emoji = INCIDENT_STATUS_EMOJI.get(status, "⚠️")
    i_emoji = INDICATOR_EMOJI.get(impact, "⚪")

    parts = [
        f"{header_emoji} *{_esc(header_label)}: {_esc(name)}*\n",
        f"\n{s_emoji} Status: {_esc(_format_status(status))}",
        f"\n{i_emoji} Impact: {_esc(_format_status(impact))}\n",
    ]

    if updates:
        parts.append(f"\n{'─' * 20}\n")
        # Updates come newest-first from API; show chronologically (oldest first)
        for u_status, u_body, u_time in reversed(updates):
            u_emoji = INCIDENT_STATUS_EMOJI.get(u_status, "ℹ️")
            # Show just time portion: "2025-02-08T14:30:00Z" -> "14:30"
            time_short = u_time[11:16] if len(u_time) > 16 else u_time
            parts.append(f"\n{u_emoji} *{_esc(time_short)}* — {_esc(_format_status(u_status))}")
            if u_body:
                parts.append(f"\n{_esc(u_body)}")
            parts.append("")

    if shortlink:
        parts.append(f"\n[View on status page]({_esc(shortlink)})")

    return "\n".join(parts)


async def send_incident(
    name: str, status: str, impact: str, shortlink: str,
    updates: list[tuple[str, str, str]],
) -> Optional[int]:
    """Send new incident message, return message_id."""
    text = build_incident_message(name, status, impact, shortlink, updates)
    return await _send(text)


async def edit_incident(
    message_id: int,
    name: str, status: str, impact: str, shortlink: str,
    updates: list[tuple[str, str, str]],
) -> bool:
    """Edit existing incident message with updated info."""
    text = build_incident_message(name, status, impact, shortlink, updates)
    return await _edit(message_id, text)


async def notify_status_change(old_indicator: str, new_indicator: str, description: str):
    emoji_old = INDICATOR_EMOJI.get(old_indicator, "⚪")
    emoji_new = INDICATOR_EMOJI.get(new_indicator, "⚪")
    text = (
        f"⚡ *Overall Status Changed*\n\n"
        f"{emoji_old} {_esc(_format_status(old_indicator or 'unknown'))} "
        f"→ {emoji_new} {_esc(_format_status(new_indicator))}\n\n"
        f"_{_esc(description)}_"
    )
    await _send(text)


async def notify_component_change(name: str, old_status: str, new_status: str):
    emoji_old = COMPONENT_STATUS_EMOJI.get(old_status, "⚪")
    emoji_new = COMPONENT_STATUS_EMOJI.get(new_status, "⚪")
    text = (
        f"🔄 *Component: {_esc(name)}*\n\n"
        f"{emoji_old} {_esc(_format_status(old_status))} "
        f"→ {emoji_new} {_esc(_format_status(new_status))}"
    )
    await _send(text)


async def notify_startup(indicator: str, components: list[tuple[str, str]]):
    emoji = INDICATOR_EMOJI.get(indicator, "⚪")
    lines = [
        f"🤖 *Claude Status Bot Started*\n",
        f"\n{emoji} Overall: {_esc(_format_status(indicator))}\n",
    ]
    if components:
        lines.append("\n*Components:*")
        for name, status in components:
            c_emoji = COMPONENT_STATUS_EMOJI.get(status, "⚪")
            lines.append(f"\n{c_emoji} {_esc(name)}")
    await _send("\n".join(lines))
