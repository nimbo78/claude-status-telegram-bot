"""Main polling loop: detects changes, sends/edits Telegram notifications."""

import asyncio
import logging
import sys

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


def _incident_updates_tuples(inc: statuspage.Incident) -> list[tuple[str, str, str]]:
    """Extract (status, body, created_at) from incident updates."""
    return [(u.status, u.body, u.created_at) for u in inc.incident_updates]


async def process_summary(summary: statuspage.StatusSummary, state: dict) -> dict:
    """Compare summary against saved state, send/edit notifications, return new state."""
    is_first_run = state["indicator"] is None

    # --- First run: send startup, seed state ---
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

    # --- Overall status change ---
    if summary.indicator != state["indicator"]:
        await notifier.notify_status_change(
            state["indicator"], summary.indicator, summary.description
        )
        state["indicator"] = summary.indicator

    # --- Component status changes ---
    for comp in summary.components:
        old_status = state["components"].get(comp.id)
        if old_status and old_status != comp.status:
            await notifier.notify_component_change(comp.name, old_status, comp.status)
        state["components"][comp.id] = comp.status

    # --- Incidents ---
    known_ids = set(state["incident_ids"])

    for inc in summary.incidents:
        updates_tuples = _incident_updates_tuples(inc)
        known_update_ids = set(state["incident_updates"].get(inc.id, []))
        current_update_ids = [u.id for u in inc.incident_updates]
        has_new_updates = any(uid not in known_update_ids for uid in current_update_ids)
        status_changed = state.get("incident_statuses", {}).get(inc.id) != inc.status

        if inc.id not in known_ids:
            # --- New incident: send message, store message_id ---
            msg_id = await notifier.send_incident(
                inc.name, inc.status, inc.impact, inc.shortlink, updates_tuples
            )
            state["incident_ids"].append(inc.id)
            if msg_id:
                state["message_ids"][inc.id] = msg_id
            logger.info("New incident: %s (msg=%s)", inc.name, msg_id)

        elif has_new_updates or status_changed:
            # --- Updated incident: edit existing message ---
            msg_id = state.get("message_ids", {}).get(inc.id)
            if msg_id:
                success = await notifier.edit_incident(
                    msg_id, inc.name, inc.status, inc.impact,
                    inc.shortlink, updates_tuples
                )
                if not success:
                    # Edit failed (message too old, deleted, etc.) — send new
                    new_msg_id = await notifier.send_incident(
                        inc.name, inc.status, inc.impact,
                        inc.shortlink, updates_tuples
                    )
                    if new_msg_id:
                        state["message_ids"][inc.id] = new_msg_id
                logger.info("Updated incident: %s (edited msg=%s)", inc.name, msg_id)
            else:
                # No stored message_id — send new
                new_msg_id = await notifier.send_incident(
                    inc.name, inc.status, inc.impact, inc.shortlink, updates_tuples
                )
                if new_msg_id:
                    state["message_ids"][inc.id] = new_msg_id

        # Update tracking state
        state["incident_updates"][inc.id] = current_update_ids
        state["incident_statuses"][inc.id] = inc.status

    return state


async def poll_loop():
    logger.info("Starting Claude Status Bot (polling every %ds)", config.POLL_INTERVAL)

    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set!")
        sys.exit(1)
    if not config.TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_CHAT_ID is not set!")
        sys.exit(1)

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


def main():
    asyncio.run(poll_loop())


if __name__ == "__main__":
    main()
