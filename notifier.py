"""Telegram notification sender with message editing for incident updates.
Supports multiple chat IDs — sends to all configured chats."""

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


async def _send(text: str) -> dict[str, int]:
    """Send message to all configured chats. Returns {chat_id: message_id}."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_IDS:
        logger.warning("Telegram not configured, skipping")
        return {}
    bot = _get_bot()
    result = {}
    for chat_id in config.TELEGRAM_CHAT_IDS:
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            result[chat_id] = msg.message_id
            logger.info("Sent message %d to %s", msg.message_id, chat_id)
        except Exception:
            logger.exception("Failed to send to %s", chat_id)
    return result


async def _edit(message_ids: dict[str, int], text: str) -> bool:
    """Edit message in all chats. Returns True if at least one succeeded."""
    if not config.TELEGRAM_BOT_TOKEN:
        return False
    bot = _get_bot()
    any_success = False
    for chat_id, msg_id in message_ids.items():
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            logger.info("Edited message %d in %s", msg_id, chat_id)
            any_success = True
        except telegram.error.BadRequest as e:
            if "message is not modified" in str(e).lower():
                any_success = True
            else:
                logger.exception("Failed to edit message %d in %s", msg_id, chat_id)
        except Exception:
            logger.exception("Failed to edit message %d in %s", msg_id, chat_id)
    return any_success


def build_incident_message(
    name: str, status: str, impact: str, shortlink: str,
    updates: list[tuple[str, str, str]],
) -> str:
    """Build a full incident message with all updates."""
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
        for u_status, u_body, u_time in reversed(updates):
            u_emoji = INCIDENT_STATUS_EMOJI.get(u_status, "ℹ️")
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
) -> dict[str, int]:
    """Send new incident message. Returns {chat_id: message_id}."""
    text = build_incident_message(name, status, impact, shortlink, updates)
    return await _send(text)


async def edit_incident(
    message_ids: dict[str, int],
    name: str, status: str, impact: str, shortlink: str,
    updates: list[tuple[str, str, str]],
) -> bool:
    """Edit existing incident message in all chats."""
    text = build_incident_message(name, status, impact, shortlink, updates)
    return await _edit(message_ids, text)


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


def build_component_status_message(components: list[tuple[str, str, str]]) -> str:
    """Build component status message showing all components.

    Args:
        components: List of (component_id, name, status) tuples

    Returns:
        Formatted message text in MarkdownV2
    """
    non_operational = [c for c in components if c[2] != "operational"]

    if not non_operational:
        header = "🟢 *All Components Operational*\n"
    else:
        header = f"⚠️ *Component Status* ({len(non_operational)} affected)\n"

    parts = [header]

    # Group by status
    status_groups = {}
    for comp_id, name, status in components:
        if status not in status_groups:
            status_groups[status] = []
        status_groups[status].append(name)

    # Show problems first, then operational
    status_order = ["major_outage", "partial_outage", "degraded_performance",
                    "under_maintenance", "operational"]

    for status in status_order:
        if status not in status_groups:
            continue
        emoji = COMPONENT_STATUS_EMOJI.get(status, "⚪")
        status_label = _format_status(status)
        parts.append(f"\n{emoji} *{_esc(status_label)}*")
        for name in sorted(status_groups[status]):
            parts.append(f"\n  • {_esc(name)}")

    return "\n".join(parts)


async def send_component_status(components: list[tuple[str, str, str]]) -> dict:
    """Send component status message to all chats.

    Returns:
        Dict mapping chat_id to message_id for each sent message
    """
    text = build_component_status_message(components)
    return await _send(text)


async def edit_component_status(message_ids: dict, components: list[tuple[str, str, str]]) -> bool:
    """Edit existing component status message in all chats.

    Returns:
        True if at least one edit succeeded
    """
    text = build_component_status_message(components)
    return await _edit(message_ids, text)


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
