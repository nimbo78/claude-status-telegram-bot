"""Main polling loop + /status command handler."""

import asyncio
import logging
import sys

from telegram import Update, BotDescription
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import config
import notifier
import statuspage
import storage

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("bot")


# ── /status command ──────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command — reply with current Claude status."""
    summary = await statuspage.fetch_summary()
    if not summary:
        await update.message.reply_text("⚠️ Failed to fetch status from API")
        return

    emoji = notifier.INDICATOR_EMOJI.get(summary.indicator, "⚪")
    lines = [f"{emoji} *Overall: {notifier._esc(notifier._format_status(summary.indicator))}*\n"]

    lines.append("\n*Components:*")
    for c in summary.components:
        c_emoji = notifier.COMPONENT_STATUS_EMOJI.get(c.status, "⚪")
        lines.append(f"\n{c_emoji} {notifier._esc(c.name)}")

    if summary.incidents:
        lines.append(f"\n\n🚨 *Active incidents: {len(summary.incidents)}*")
        for inc in summary.incidents:
            i_emoji = notifier.INCIDENT_STATUS_EMOJI.get(inc.status, "⚠️")
            lines.append(f"\n{i_emoji} {notifier._esc(inc.name)}")
            if inc.incident_updates:
                latest = inc.incident_updates[0]
                if latest.body:
                    lines.append(f"\n_{notifier._esc(latest.body)}_")
    else:
        lines.append("\n\n✅ No active incidents")

    lines.append(f"\n\n[status\\.claude\\.com](https://status.claude.com)")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


# ── Polling loop ─────────────────────────────────────────────────

def _incident_updates_tuples(inc: statuspage.Incident) -> list[tuple[str, str, str]]:
    return [(u.status, u.body, u.created_at) for u in inc.incident_updates]


async def process_summary(summary: statuspage.StatusSummary, state: dict) -> dict:
    is_first_run = state["indicator"] is None

    if is_first_run:
        component_list = [(c.name, c.status) for c in summary.components]
        await notifier.notify_startup(summary.indicator, component_list)
        state["indicator"] = summary.indicator
        state["components"] = {c.id: c.status for c in summary.components}
        state["incident_ids"] = [i.id for i in summary.incidents]
        state["incident_updates"] = {
            i.id: [u.id for u in i.incident_updates] for i in summary.incidents
        }
        state["incident_statuses"] = {i.id: i.status for i in summary.incidents}
        return state

    # Overall status change
    if summary.indicator != state["indicator"]:
        await notifier.notify_status_change(
            state["indicator"], summary.indicator, summary.description
        )
        state["indicator"] = summary.indicator

    # Component status changes
    for comp in summary.components:
        old_status = state["components"].get(comp.id)
        if old_status and old_status != comp.status:
            await notifier.notify_component_change(comp.name, old_status, comp.status)
        state["components"][comp.id] = comp.status

    # Incidents
    known_ids = set(state["incident_ids"])
    for inc in summary.incidents:
        updates_tuples = _incident_updates_tuples(inc)
        known_update_ids = set(state["incident_updates"].get(inc.id, []))
        current_update_ids = [u.id for u in inc.incident_updates]
        has_new_updates = any(uid not in known_update_ids for uid in current_update_ids)
        status_changed = state.get("incident_statuses", {}).get(inc.id) != inc.status

        if inc.id not in known_ids:
            msg_ids = await notifier.send_incident(
                inc.name, inc.status, inc.impact, inc.shortlink, updates_tuples
            )
            state["incident_ids"].append(inc.id)
            if msg_ids:
                state["message_ids"][inc.id] = msg_ids
            logger.info("New incident: %s (sent to %d chats)", inc.name, len(msg_ids))

        elif has_new_updates or status_changed:
            msg_ids = state.get("message_ids", {}).get(inc.id, {})
            if msg_ids:
                success = await notifier.edit_incident(
                    msg_ids, inc.name, inc.status, inc.impact,
                    inc.shortlink, updates_tuples
                )
                if not success:
                    new_msg_ids = await notifier.send_incident(
                        inc.name, inc.status, inc.impact,
                        inc.shortlink, updates_tuples
                    )
                    if new_msg_ids:
                        state["message_ids"][inc.id] = new_msg_ids
                logger.info("Updated incident: %s", inc.name)
            else:
                new_msg_ids = await notifier.send_incident(
                    inc.name, inc.status, inc.impact, inc.shortlink, updates_tuples
                )
                if new_msg_ids:
                    state["message_ids"][inc.id] = new_msg_ids

        state["incident_updates"][inc.id] = current_update_ids
        state["incident_statuses"][inc.id] = inc.status

    return state


async def poll_task():
    """Background polling task."""
    state = storage.load_state()
    while True:
        try:
            summary = await statuspage.fetch_summary()
            if summary:
                state = await process_summary(summary, state)
                storage.save_state(state)
            else:
                logger.warning("Failed to fetch summary, will retry")
        except Exception:
            logger.exception("Error in poll loop")
        await asyncio.sleep(config.POLL_INTERVAL)


async def post_init(application):
    """Start polling loop after bot initializes."""
    asyncio.create_task(poll_task())


def main():
    logger.info(
        "Starting Claude Status Bot (polling every %ds, sending to %d chat(s))",
        config.POLL_INTERVAL, len(config.TELEGRAM_CHAT_IDS),
    )
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set!")
        sys.exit(1)
    if not config.TELEGRAM_CHAT_IDS:
        logger.error("TELEGRAM_CHAT_ID is not set!")
        sys.exit(1)

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("status", cmd_status))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
