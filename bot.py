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
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("bot")


# ── /status command ──────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command — reply with current Claude status."""
    summary = await statuspage.fetch_summary()
    if not summary:
        await update.message.reply_text("⚠️ Failed to fetch status from API")
        return

    emoji = notifier.INDICATOR_EMOJI.get(summary.indicator, "⚪")
    status_text = notifier._format_status(summary.indicator)

    # Compact header with status
    lines = [f"{emoji} *Claude Status: {notifier._esc(status_text)}*\n"]

    # Group components compactly
    operational = []
    non_operational = []
    for c in summary.components:
        if c.status == "operational":
            operational.append(c.name)
        else:
            c_emoji = notifier.COMPONENT_STATUS_EMOJI.get(c.status, "⚪")
            non_operational.append(f"{c_emoji} {notifier._esc(c.name)}")

    # Show non-operational first (if any)
    if non_operational:
        lines.append("*⚠️ Issues:*")
        lines.extend(non_operational)
        lines.append("")

    # Show operational services in compact list
    if operational:
        lines.append("*Services:*")
        lines.append("✓ " + notifier._esc(" • ".join(operational)))

    # Incidents section
    if summary.incidents:
        lines.append(f"\n🚨 *{len(summary.incidents)} Active Incident{'s' if len(summary.incidents) > 1 else ''}*")
        for inc in summary.incidents:
            i_emoji = notifier.INCIDENT_STATUS_EMOJI.get(inc.status, "⚠️")
            lines.append(f"{i_emoji} {notifier._esc(inc.name)}")
            if inc.incident_updates and inc.incident_updates[0].body:
                latest = inc.incident_updates[0]
                body_short = latest.body[:100] + "..." if len(latest.body) > 100 else latest.body
                lines.append(f"  _{notifier._esc(body_short)}_")
    else:
        lines.append("\n✅ No active incidents")

    lines.append(f"\n[View Details →](https://status\\.claude\\.com)")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


# ── Polling loop ─────────────────────────────────────────────────

def _incident_updates_tuples(inc: statuspage.Incident) -> list[tuple[str, str, str]]:
    return [(u.status, u.body, u.created_at) for u in inc.incident_updates]


async def _update_pinned_status(summary: statuspage.StatusSummary, state: dict) -> dict:
    """Send or edit the single pinned status message."""
    component_list = [(c.id, c.name, c.status) for c in summary.components]
    active_incidents = len(summary.incidents)
    has_msg = bool(state.get("status_message_ids"))

    if has_msg:
        success = await notifier.edit_pinned_status(
            state["status_message_ids"],
            summary.indicator, summary.description,
            component_list, active_incidents,
        )
        if not success:
            # Edit failed (message deleted, etc.) — send a new one
            msg_ids = await notifier.send_pinned_status(
                summary.indicator, summary.description,
                component_list, active_incidents,
            )
            if msg_ids:
                state["status_message_ids"] = msg_ids
                logger.info("Re-created pinned status message in %d chats", len(msg_ids))
    else:
        msg_ids = await notifier.send_pinned_status(
            summary.indicator, summary.description,
            component_list, active_incidents,
        )
        if msg_ids:
            state["status_message_ids"] = msg_ids
            logger.info("Created pinned status message in %d chats", len(msg_ids))

    return state


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

        # Send notifications for active incidents on first run
        for inc in summary.incidents:
            updates_tuples = _incident_updates_tuples(inc)
            msg_ids = await notifier.send_incident(
                inc.name, inc.status, inc.impact, inc.shortlink, updates_tuples
            )
            if msg_ids:
                state["message_ids"][inc.id] = msg_ids
            logger.info("Existing incident: %s (sent to %d chats)", inc.name, len(msg_ids))

        # Send the pinned status message
        state = await _update_pinned_status(summary, state)

        return state

    # Detect changes
    indicator_changed = summary.indicator != state["indicator"]
    component_changed = False
    for comp in summary.components:
        old_status = state["components"].get(comp.id)
        if old_status and old_status != comp.status:
            component_changed = True
            logger.info("Component %s: %s -> %s", comp.name, old_status, comp.status)
        state["components"][comp.id] = comp.status

    if indicator_changed:
        logger.info("Overall status: %s -> %s", state["indicator"], summary.indicator)
        state["indicator"] = summary.indicator

    # Edit pinned status message on any status/component change
    if indicator_changed or component_changed:
        state = await _update_pinned_status(summary, state)

    # Incidents
    known_ids = set(state["incident_ids"])
    incidents_changed = False
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
            incidents_changed = True

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
            incidents_changed = True

        state["incident_updates"][inc.id] = current_update_ids
        state["incident_statuses"][inc.id] = inc.status

    # Update pinned message if incident count changed (reflects in "X active incidents")
    prev_incident_count = state.get("active_incident_count", 0)
    curr_incident_count = len(summary.incidents)
    if (incidents_changed or curr_incident_count != prev_incident_count) \
            and not (indicator_changed or component_changed):
        state = await _update_pinned_status(summary, state)
    state["active_incident_count"] = curr_incident_count

    return state


async def poll_task():
    """Background polling task."""
    logger.info("Poll task started")
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
    application.create_task(poll_task(), name="poll_task")


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
