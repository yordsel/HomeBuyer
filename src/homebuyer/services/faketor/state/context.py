"""ResearchContext, TurnState, and ResearchContextStore.

ResearchContext is the persistent state — one per authenticated user or
one per anonymous session. TurnState is ephemeral per-turn state that
accumulates facts and promotes them to ResearchContext at end of turn.
ResearchContextStore manages the lifecycle.

Phase G (#65-69) adds DB persistence for authenticated users:
- persist() writes serialized state to research_contexts table
- load_or_create() loads from DB on cache miss, applies confidence decay
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from homebuyer.services.faketor.accumulator import AnalysisAccumulator
from homebuyer.services.faketor.state.buyer import BuyerState, Signal
from homebuyer.services.faketor.state.market import MarketDelta, MarketSnapshot
from homebuyer.services.faketor.state.property import PropertyState

if TYPE_CHECKING:
    from homebuyer.storage.database import Database

logger = logging.getLogger(__name__)

# Staleness threshold — same as MarketSnapshot._STALE_SECONDS
_STALE_SECONDS = 4 * 3600


# ---------------------------------------------------------------------------
# ResearchContext — persistent state
# ---------------------------------------------------------------------------


@dataclass
class ResearchContext:
    """The persistent research state — one per authenticated user.

    This is the single object that flows through the entire pipeline.
    Every component reads from or writes to the ResearchContext.
    For anonymous users, a transient ResearchContext is created in
    memory (keyed by session_id) with the same structure.
    """

    user_id: str | None = None
    session_id: str | None = None
    created_at: float = 0.0
    last_active: float = 0.0

    buyer: BuyerState = field(default_factory=BuyerState)
    market: MarketSnapshot = field(default_factory=MarketSnapshot)
    property: PropertyState = field(default_factory=PropertyState)

    # Computed on load for returning users, None otherwise
    market_delta: MarketDelta | None = None

    def touch(self) -> None:
        """Update last_active timestamp."""
        self.last_active = time.time()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "buyer": self.buyer.to_dict(),
            "market": self.market.to_dict(),
            "property": self.property.to_dict(),
            "market_delta": self.market_delta.to_dict() if self.market_delta else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchContext:
        ctx = cls(
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            created_at=data.get("created_at", 0.0),
            last_active=data.get("last_active", 0.0),
            buyer=BuyerState.from_dict(data.get("buyer", {})),
            market=MarketSnapshot.from_dict(data.get("market", {})),
            property=PropertyState.from_dict(data.get("property", {})),
        )
        if data.get("market_delta"):
            ctx.market_delta = MarketDelta.from_dict(data["market_delta"])
        return ctx


# ---------------------------------------------------------------------------
# TurnState — ephemeral per-turn state
# ---------------------------------------------------------------------------


@dataclass
class TurnState:
    """Ephemeral per-turn state. Not persisted. Not an entity.

    Created fresh for each turn, accumulates facts and job history
    during the turn, then promotes relevant state to ResearchContext
    before the context is persisted.
    """

    turn_count: int = 0
    job_history: list[dict[str, Any]] = field(default_factory=list)
    fact_accumulator: AnalysisAccumulator = field(default_factory=AnalysisAccumulator)

    # Collected during the turn for promotion
    buyer_extractions: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    # (segment_id, confidence, optional trigger signal)
    # Code review fix for #29: carry trigger so segment_history records evidence.
    segment_update: tuple[str, float, Signal | None] | None = None
    analysis_records: list[dict[str, Any]] = field(default_factory=list)
    filter_update: dict[str, Any] | None = None
    focus_update: dict[str, Any] | None = None

    def promote(self, context: ResearchContext) -> list[str]:
        """Promote accumulated state to the persistent ResearchContext.

        Called at end of each turn. Returns descriptions of what was promoted.
        """
        promoted: list[str] = []

        # 1. Buyer factors → BuyerState.profile
        if self.buyer_extractions:
            updated = context.buyer.profile.apply_extraction(self.buyer_extractions)
            if updated:
                promoted.append(f"Updated buyer profile: {', '.join(updated)}")

        # 2. Segment changes → BuyerState
        # Code review fix for #29: unpack trigger, suppress self-transitions.
        if self.segment_update:
            seg_id, confidence, trigger = self.segment_update
            old_seg = context.buyer.segment_id
            # Only record a transition if the segment actually changed.
            # Same-segment confidence upgrades update in-place without a
            # history entry (they aren't real transitions).
            if seg_id != old_seg:
                context.buyer.record_transition(
                    from_segment=old_seg,
                    to_segment=seg_id,
                    confidence=confidence,
                    trigger=trigger,
                )
                promoted.append(f"Segment: {old_seg} → {seg_id} ({confidence:.0%})")
            elif confidence > context.buyer.segment_confidence:
                # Same segment, higher confidence — update in-place, no history entry
                context.buyer.segment_confidence = confidence

        # 3. Property analyses → PropertyState.analyses
        for rec in self.analysis_records:
            context.property.record_analysis(
                property_id=rec["property_id"],
                address=rec["address"],
                tool_name=rec["tool_name"],
                result_summary=rec["result_summary"],
                conclusion=rec.get("conclusion"),
                market_snapshot_at=context.market.snapshot_at,
            )
        if self.analysis_records:
            promoted.append(f"Recorded {len(self.analysis_records)} analyses")

        # 4. Filter operations → PropertyState.filter_intent
        if self.filter_update:
            from homebuyer.services.faketor.state.property import FilterIntent

            context.property.filter_intent = FilterIntent(
                criteria=self.filter_update.get("criteria", {}),
                description=self.filter_update.get("description", ""),
                created_at=time.time(),
            )
            promoted.append(f"Updated filter: {self.filter_update.get('description', '')}")

        # 5. Focus property
        if self.focus_update:
            from homebuyer.services.faketor.state.property import FocusProperty

            context.property.focus_property = FocusProperty(
                property_id=self.focus_update["property_id"],
                address=self.focus_update.get("address", ""),
                property_context=self.focus_update.get("property_context", {}),
                status_checked_at=time.time(),
            )
            promoted.append(f"Focus property: {self.focus_update.get('address', '')}")

        # Update activity timestamp
        context.touch()

        return promoted


# ---------------------------------------------------------------------------
# ResearchContextStore — lifecycle management
# ---------------------------------------------------------------------------


class ResearchContextStore:
    """Manages research context lifecycle.

    For authenticated users: persists to DB (research_contexts table) with
    in-memory cache for fast access. For anonymous users: in-memory cache
    keyed by session_id with TTL-based eviction.

    Phase G (#65-69): DB persistence for authenticated users.
    """

    def __init__(
        self,
        ttl_seconds: int = 1800,
        db: Database | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._db = db
        # In-memory stores — cache for authenticated users, primary for anonymous
        self._by_user: dict[str, ResearchContext] = {}
        self._by_session: dict[str, ResearchContext] = {}
        # Code review fix for #30: guard shared dicts in async context.
        # FastAPI runs on an async event loop; concurrent requests for the
        # same user_id can interleave between await points, causing duplicate
        # context creation or lost state during promotion.
        self._lock = asyncio.Lock()

    async def load_or_create(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> ResearchContext:
        """Load an existing research context or create a new one.

        For authenticated users:
        1. Check in-memory cache
        2. If miss, check DB (Phase G)
        3. If found, apply confidence decay if stale (>4 hours)
        4. If not found, create new empty context

        For anonymous users:
        - Look up by session_id in in-memory cache
        - Create empty context if not found
        - Evict expired sessions
        """
        async with self._lock:
            self._evict_expired()

            now = time.time()

            # Authenticated user path
            if user_id:
                ctx = self._by_user.get(user_id)
                if not ctx:
                    # Cache miss — try loading from DB
                    ctx = self._load_from_db(user_id)
                    if ctx:
                        self._by_user[user_id] = ctx

                if ctx:
                    # Check if the buyer profile needs confidence decay
                    if ctx.last_active and (now - ctx.last_active) > _STALE_SECONDS:
                        ctx.buyer.profile.apply_confidence_decay()
                        logger.info(
                            "Applied confidence decay for user %s (%.1fh stale)",
                            user_id,
                            (now - ctx.last_active) / 3600,
                        )
                    ctx.touch()
                    return ctx

                # Create new context for authenticated user
                ctx = ResearchContext(
                    user_id=user_id,
                    session_id=session_id,
                    created_at=now,
                    last_active=now,
                )
                self._by_user[user_id] = ctx
                return ctx

            # Anonymous user path
            if session_id:
                ctx = self._by_session.get(session_id)
                if ctx:
                    ctx.touch()
                    return ctx

                ctx = ResearchContext(
                    session_id=session_id,
                    created_at=now,
                    last_active=now,
                )
                self._by_session[session_id] = ctx
                return ctx

            # No user_id or session_id — create ephemeral context
            return ResearchContext(created_at=now, last_active=now)

    async def persist(self, context: ResearchContext) -> None:
        """Persist research context.

        For authenticated users: writes to both in-memory cache and DB.
        For anonymous users: in-memory cache only.
        """
        async with self._lock:
            if context.user_id:
                self._by_user[context.user_id] = context
                self._persist_to_db(context)
            elif context.session_id:
                self._by_session[context.session_id] = context

    # ------------------------------------------------------------------
    # DB persistence helpers (Phase G)
    # ------------------------------------------------------------------

    def _persist_to_db(self, context: ResearchContext) -> None:
        """Write context to the research_contexts table.

        Uses INSERT OR REPLACE (upsert) since user_id is the PK.
        Only called for authenticated users. Anonymous users are
        never persisted to DB.
        """
        if not self._db or not context.user_id:
            return

        try:
            user_id_int = int(context.user_id)
        except (ValueError, TypeError):
            logger.warning("Cannot persist: user_id %r is not a valid int", context.user_id)
            return

        now = time.time()
        last_active_ts = _epoch_to_iso(context.last_active) if context.last_active else _epoch_to_iso(now)
        created_ts = _epoch_to_iso(context.created_at) if context.created_at else last_active_ts

        buyer_json = json.dumps(context.buyer.to_dict())
        market_json = json.dumps(context.market.to_dict())
        property_json = json.dumps(context.property.to_dict())

        try:
            self._db.execute(
                "INSERT OR REPLACE INTO research_contexts "
                "(user_id, session_id, created_at, last_active, "
                "buyer_state, market_snapshot, property_state) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id_int,
                    context.session_id,
                    created_ts,
                    last_active_ts,
                    buyer_json,
                    market_json,
                    property_json,
                ),
            )
            self._db.commit()
            logger.debug("Persisted research context for user %s", context.user_id)
        except Exception:
            logger.exception("Failed to persist research context for user %s", context.user_id)

    def _load_from_db(self, user_id: str) -> ResearchContext | None:
        """Load research context from the DB for a returning user.

        Returns None if no saved context exists or if DB is unavailable.
        """
        if not self._db:
            return None

        try:
            user_id_int = int(user_id)
        except (ValueError, TypeError):
            return None

        try:
            row = self._db.fetchone(
                "SELECT * FROM research_contexts WHERE user_id = ?",
                (user_id_int,),
            )
        except Exception:
            logger.exception("Failed to load research context for user %s", user_id)
            return None

        if not row:
            return None

        try:
            buyer_data = json.loads(row["buyer_state"]) if row["buyer_state"] else {}
            market_data = json.loads(row["market_snapshot"]) if row["market_snapshot"] else {}
            property_data = json.loads(row["property_state"]) if row["property_state"] else {}

            ctx = ResearchContext(
                user_id=user_id,
                session_id=row.get("session_id"),
                created_at=_iso_to_epoch(row["created_at"]) if row["created_at"] else 0.0,
                last_active=_iso_to_epoch(row["last_active"]) if row["last_active"] else 0.0,
                buyer=BuyerState.from_dict(buyer_data),
                market=MarketSnapshot.from_dict(market_data),
                property=PropertyState.from_dict(property_data),
            )
            logger.info("Loaded research context from DB for user %s", user_id)
            return ctx
        except Exception:
            logger.exception("Failed to deserialize research context for user %s", user_id)
            return None

    def _evict_expired(self) -> None:
        """Remove anonymous sessions that have exceeded TTL."""
        now = time.time()
        expired = [
            sid
            for sid, ctx in self._by_session.items()
            if (now - ctx.last_active) > self._ttl_seconds
        ]
        for sid in expired:
            del self._by_session[sid]
        if expired:
            logger.debug("Evicted %d expired anonymous sessions", len(expired))


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _epoch_to_iso(epoch: float) -> str:
    """Convert epoch seconds to ISO 8601 string (UTC, no timezone suffix)."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _iso_to_epoch(iso_str: str) -> float:
    """Convert ISO 8601 string to epoch seconds."""
    try:
        dt = datetime.strptime(iso_str, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0
