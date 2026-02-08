"""Statuspage API client for status.claude.com"""

import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp

import config

logger = logging.getLogger(__name__)


@dataclass
class IncidentUpdate:
    id: str
    status: str
    body: str
    created_at: str


@dataclass
class Incident:
    id: str
    name: str
    status: str
    impact: str
    shortlink: str
    created_at: str
    updated_at: str
    incident_updates: list[IncidentUpdate] = field(default_factory=list)


@dataclass
class Component:
    id: str
    name: str
    status: str
    description: str | None = None


@dataclass
class StatusSummary:
    indicator: str  # none | minor | major | critical
    description: str
    components: list[Component]
    incidents: list[Incident]
    scheduled_maintenances: list[dict]


def _parse_incident(data: dict) -> Incident:
    updates = [
        IncidentUpdate(
            id=u["id"],
            status=u["status"],
            body=u.get("body", ""),
            created_at=u["created_at"],
        )
        for u in data.get("incident_updates", [])
    ]
    return Incident(
        id=data["id"],
        name=data["name"],
        status=data["status"],
        impact=data["impact"],
        shortlink=data.get("shortlink", ""),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        incident_updates=updates,
    )


def _parse_component(data: dict) -> Component:
    return Component(
        id=data["id"],
        name=data["name"],
        status=data["status"],
        description=data.get("description"),
    )


async def fetch_summary() -> StatusSummary | None:
    """Fetch full summary from Statuspage API."""
    url = f"{config.STATUSPAGE_BASE_URL}/api/v2/summary.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.error("Statuspage API returned %d", resp.status)
                    return None
                data = await resp.json()
    except Exception:
        logger.exception("Failed to fetch Statuspage summary")
        return None

    status_data = data.get("status", {})
    components = [_parse_component(c) for c in data.get("components", [])
                  if not c.get("group", False) and c["name"] != "Visit status.claude.com for more information"]
    incidents = [_parse_incident(i) for i in data.get("incidents", [])]
    scheduled = data.get("scheduled_maintenances", [])

    return StatusSummary(
        indicator=status_data.get("indicator", "unknown"),
        description=status_data.get("description", ""),
        components=components,
        incidents=incidents,
        scheduled_maintenances=scheduled,
    )
