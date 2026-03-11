"""Session-scoped property cache for Faketor chat conversations.

Provides a server-side working set of properties that evolves as the
conversation progresses.  Enables conversational follow-ups like
"which of those are in North Berkeley?" by maintaining a filter stack
that can be pushed (narrow) and popped (undo).

Designed for later persistence: all data structures are serializable
to JSON for storage in a sessions DB table.
"""

import logging
import time
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Optional

logger = logging.getLogger(__name__)

# Key fields stored per property in the working set
WORKING_SET_FIELDS = (
    "id",
    "address",
    "neighborhood",
    "beds",
    "baths",
    "sqft",
    "building_sqft",
    "lot_size_sqft",
    "zoning_class",
    "property_type",
    "last_sale_price",
    "year_built",
    "latitude",
    "longitude",
    "property_category",
    "record_type",
    "lot_group_key",
    "situs_unit",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FilterLayer:
    """A single filter operation that narrowed the working set."""

    description: str  # Human-readable, e.g. "SFH with lots > 7000 sqft"
    source_tool: str  # "search_properties", "query_database"
    property_ids_before: int
    property_ids_after: int
    applied_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PropertyRecord:
    """Lightweight property snapshot stored in the working set."""

    id: int
    address: str = ""
    neighborhood: Optional[str] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    building_sqft: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    zoning_class: Optional[str] = None
    property_type: Optional[str] = None
    last_sale_price: Optional[int] = None
    year_built: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    property_category: Optional[str] = None
    record_type: Optional[str] = None
    lot_group_key: Optional[str] = None
    situs_unit: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Session working set
# ---------------------------------------------------------------------------


class SessionWorkingSet:
    """Per-session property working set with stack-based filtering.

    The working set is a dict of property_id → PropertyRecord.
    The filter stack records each narrowing operation along with a
    snapshot of the previous state so it can be restored on pop.
    """

    _MAX_DISCUSSED = 10
    _MAX_SAMPLE = 25

    def __init__(self) -> None:
        self.properties: dict[int, PropertyRecord] = {}
        # Stack of (FilterLayer, snapshot_of_previous_properties)
        self._filter_stack: list[tuple[FilterLayer, dict[int, PropertyRecord]]] = []
        # Properties the user has drilled into (LIFO, capped at _MAX_DISCUSSED)
        self._discussed: list[PropertyRecord] = []

    @property
    def count(self) -> int:
        return len(self.properties)

    @property
    def filter_stack(self) -> list[FilterLayer]:
        return [layer for layer, _ in self._filter_stack]

    # -- Mutation methods ----------------------------------------------------

    def set_properties(
        self,
        rows: list[dict],
        description: str,
        source_tool: str,
    ) -> None:
        """Replace the entire working set (initial population or reset)."""
        self.properties = {}
        self._filter_stack.clear()
        for row in rows:
            pid = row.get("id")
            if pid is None:
                continue
            self.properties[pid] = PropertyRecord(
                **{k: row.get(k) for k in WORKING_SET_FIELDS}
            )
        logger.info(
            "Working set initialized: %d properties (%s)",
            len(self.properties),
            description,
        )

    def augment_properties(self, rows: list[dict]) -> int:
        """Add new properties to the working set without clearing existing ones.

        Returns the number of newly added properties.
        """
        added = 0
        for row in rows:
            pid = row.get("id")
            if pid is None or pid in self.properties:
                continue
            self.properties[pid] = PropertyRecord(
                **{k: row.get(k) for k in WORKING_SET_FIELDS}
            )
            added += 1
        if added:
            logger.info("Working set augmented: +%d properties (total %d)", added, len(self.properties))
        return added

    def push_filter(
        self,
        new_ids: set[int],
        description: str,
        source_tool: str,
    ) -> None:
        """Narrow the working set to the intersection with *new_ids*."""
        snapshot = dict(self.properties)  # shallow copy for restore
        count_before = len(self.properties)

        self.properties = {
            pid: prop
            for pid, prop in self.properties.items()
            if pid in new_ids
        }

        layer = FilterLayer(
            description=description,
            source_tool=source_tool,
            property_ids_before=count_before,
            property_ids_after=len(self.properties),
        )
        self._filter_stack.append((layer, snapshot))
        logger.info(
            "Filter pushed: '%s' (%d → %d)",
            description,
            count_before,
            len(self.properties),
        )

    def pop_filter(self) -> Optional[FilterLayer]:
        """Undo the most recent filter, restoring the previous working set."""
        if not self._filter_stack:
            return None
        layer, snapshot = self._filter_stack.pop()
        self.properties = snapshot
        logger.info(
            "Filter popped: '%s' (restored to %d properties)",
            layer.description,
            len(self.properties),
        )
        return layer

    def expand_properties(
        self,
        rows: list[dict],
        description: str,
        source_tool: str,
    ) -> int:
        """Add new properties to the working set (expand operation).

        Unlike ``augment_properties``, this pushes a filter layer so
        ``pop_filter()`` can undo the expansion.

        Returns the number of newly added properties.
        """
        snapshot = dict(self.properties)  # snapshot for undo
        count_before = len(self.properties)

        added = 0
        for row in rows:
            pid = row.get("id")
            if pid is None or pid in self.properties:
                continue
            self.properties[pid] = PropertyRecord(
                **{k: row.get(k) for k in WORKING_SET_FIELDS}
            )
            added += 1

        if added:
            layer = FilterLayer(
                description=f"expand: {description}",
                source_tool=source_tool,
                property_ids_before=count_before,
                property_ids_after=len(self.properties),
            )
            self._filter_stack.append((layer, snapshot))
            logger.info(
                "Working set expanded: +%d properties (%d → %d) '%s'",
                added, count_before, len(self.properties), description,
            )
        return added

    # -- Discussed properties ------------------------------------------------

    @property
    def discussed(self) -> list[PropertyRecord]:
        """Properties the user has drilled into, LIFO order, capped."""
        return list(self._discussed)

    def add_discussed(self, property_id: int) -> None:
        """Mark a property as discussed (called when per-property tools run).

        If the property is already discussed, move it to the front.
        The property must be in the current working set.
        """
        record = self.properties.get(property_id)
        if record is None:
            return  # Not in working set — caller should use add_discussed_record

        # Remove if already present (will re-add at front)
        self._discussed = [p for p in self._discussed if p.id != property_id]
        self._discussed.insert(0, record)
        if len(self._discussed) > self._MAX_DISCUSSED:
            self._discussed = self._discussed[: self._MAX_DISCUSSED]

    def add_discussed_record(self, record: PropertyRecord) -> None:
        """Add a PropertyRecord directly to the discussed list.

        Use this when the property is not in the current working set
        (e.g. looked up by address independently).
        """
        self._discussed = [p for p in self._discussed if p.id != record.id]
        self._discussed.insert(0, record)
        if len(self._discussed) > self._MAX_DISCUSSED:
            self._discussed = self._discussed[: self._MAX_DISCUSSED]

    # -- Query methods -------------------------------------------------------

    def get_sample(self, limit: int | None = None) -> list[dict]:
        """Return a sample of properties as dicts for the frontend sidebar.

        Sorted by address for deterministic ordering, capped at *limit*
        (defaults to ``_MAX_SAMPLE``).
        """
        cap = limit if limit is not None else self._MAX_SAMPLE
        props = sorted(self.properties.values(), key=lambda p: p.address or "")
        return [p.to_dict() for p in props[:cap]]

    def get_property_ids(self) -> list[int]:
        """Sorted list of property IDs in the working set."""
        return sorted(self.properties.keys())

    def get_descriptor(self) -> str:
        """Concise working set summary for injection into Claude's system prompt."""
        if not self.properties:
            return ""

        n = len(self.properties)
        props = list(self.properties.values())

        lines = [f"PROPERTY WORKING SET: {n} properties"]

        # Filter history
        if self._filter_stack:
            filters = [layer.description for layer, _ in self._filter_stack]
            lines.append(f"  Filters applied: {' → '.join(filters)}")
            lines.append(f"  Filter depth: {len(self._filter_stack)} (can undo)")

        # Neighborhood distribution (top 5)
        neighborhoods: dict[str, int] = {}
        for p in props:
            if p.neighborhood:
                neighborhoods[p.neighborhood] = neighborhoods.get(p.neighborhood, 0) + 1
        if neighborhoods:
            top = sorted(neighborhoods.items(), key=lambda x: -x[1])[:5]
            dist = ", ".join(f"{name} ({ct})" for name, ct in top)
            if len(neighborhoods) > 5:
                dist += f", +{len(neighborhoods) - 5} more"
            lines.append(f"  Neighborhoods: {dist}")

        # Property type distribution (top 3)
        types: dict[str, int] = {}
        for p in props:
            if p.property_type:
                types[p.property_type] = types.get(p.property_type, 0) + 1
        if types:
            top = sorted(types.items(), key=lambda x: -x[1])[:3]
            dist = ", ".join(f"{name} ({ct})" for name, ct in top)
            lines.append(f"  Types: {dist}")

        # Property category distribution (top 5)
        categories: dict[str, int] = {}
        for p in props:
            if p.property_category:
                categories[p.property_category] = categories.get(p.property_category, 0) + 1
        if categories:
            top = sorted(categories.items(), key=lambda x: -x[1])[:5]
            dist = ", ".join(f"{name} ({ct})" for name, ct in top)
            lines.append(f"  Categories: {dist}")

        # Record type distribution
        rec_types: dict[str, int] = {}
        for p in props:
            if p.record_type:
                rec_types[p.record_type] = rec_types.get(p.record_type, 0) + 1
        if rec_types:
            dist = ", ".join(f"{name} ({ct})" for name, ct in rec_types.items())
            lines.append(f"  Record types: {dist}")

        # Lot size range
        lot_sizes = [p.lot_size_sqft for p in props if p.lot_size_sqft]
        if lot_sizes:
            lines.append(
                f"  Lot size: {min(lot_sizes):,} - {max(lot_sizes):,} sqft "
                f"(median {int(median(lot_sizes)):,})"
            )

        # Price range
        prices = [p.last_sale_price for p in props if p.last_sale_price]
        if prices:
            lines.append(
                f"  Last sale: ${min(prices):,} - ${max(prices):,} "
                f"(median ${int(median(prices)):,})"
            )

        # Zoning distribution (top 5)
        zones: dict[str, int] = {}
        for p in props:
            if p.zoning_class:
                zones[p.zoning_class] = zones.get(p.zoning_class, 0) + 1
        if zones:
            top = sorted(zones.items(), key=lambda x: -x[1])[:5]
            dist = ", ".join(f"{z} ({ct})" for z, ct in top)
            lines.append(f"  Zoning: {dist}")

        return "\n".join(lines)

    # -- Serialization -------------------------------------------------------

    def to_serializable(self) -> dict:
        """Serialize for future DB persistence."""
        return {
            "properties": {
                str(pid): prop.to_dict()
                for pid, prop in self.properties.items()
            },
            "filter_stack": [
                {
                    "layer": layer.to_dict(),
                    "snapshot_ids": list(snapshot.keys()),
                }
                for layer, snapshot in self._filter_stack
            ],
            "discussed": [p.to_dict() for p in self._discussed],
        }


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

_DEFAULT_SESSION_TTL = 1800  # 30 minutes


class SessionManager:
    """Manages per-conversation session caches in memory.

    Sessions expire after a configurable TTL of inactivity.
    Designed so the underlying data can later be serialized to a
    sessions table (session_id, user_id, working_set_json, ...).
    """

    def __init__(self, ttl_seconds: int = _DEFAULT_SESSION_TTL) -> None:
        self._sessions: dict[str, dict] = {}
        self._ttl = ttl_seconds

    def get_or_create(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> SessionWorkingSet:
        """Get existing session or create a new one.  Updates last_accessed."""
        self._evict_expired()

        if session_id in self._sessions:
            session = self._sessions[session_id]
            session["last_accessed"] = time.time()
            return session["working_set"]

        working_set = SessionWorkingSet()
        self._sessions[session_id] = {
            "working_set": working_set,
            "created_at": time.time(),
            "last_accessed": time.time(),
            "user_id": user_id,
        }
        logger.info("Created session %s", session_id[:8])
        return working_set

    def get(self, session_id: str) -> Optional[SessionWorkingSet]:
        """Get session if it exists and is not expired."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if time.time() - session["last_accessed"] > self._ttl:
            del self._sessions[session_id]
            return None
        session["last_accessed"] = time.time()
        return session["working_set"]

    def delete(self, session_id: str) -> None:
        """Explicitly remove a session."""
        self._sessions.pop(session_id, None)

    def active_count(self) -> int:
        """Number of active (non-expired) sessions."""
        self._evict_expired()
        return len(self._sessions)

    def _evict_expired(self) -> None:
        """Remove expired sessions."""
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s["last_accessed"] > self._ttl
        ]
        for sid in expired:
            del self._sessions[sid]
            logger.info("Evicted expired session %s", sid[:8])
