"""Agent Memory models (draft v0.1 — see docs/agent_memory/SPEC.md).

Persistent, layered memory distilled from chat conversations:

- L0 Conversation : raw `chat_messages` (already exists)
- L1 Atom         : `memory_atoms` — facts / preferences / constraints / decisions
- L2 Scenario     : `memory_scenarios` — knowledge blocks around a project/scenario
- L3 Profile      : `memory_profiles` — long-term persona / stable patterns

All tables are additive, own-schema, and carry their own `visibility`
(default `private`) so nothing leaks by default. No FK to any hot-path table.
`search_vector` is accent-folded with the SAME `sowknow.unaccent()` expression
as migration 036 so existing search patterns (multi-config @@, pgvector) work
unchanged.
"""

import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import relationship

from app.models.base import Base, GUIDType, TimestampMixin


class MemoryVisibility(enum.StrEnum):
    """Ownership model for memory assets — private by default."""

    PRIVATE = "private"  # owner only (default)
    TEAM = "team"  # all team members can read
    AGENT = "agent"  # bound to a specific agent scope


class MemoryStatus(enum.StrEnum):
    """Lifecycle status — nothing enters search/context before `reviewed`."""

    PENDING = "pending"  # freshly distilled, not yet reviewed
    REVIEWED = "reviewed"  # accepted; eligible for retrieval/injection
    REJECTED = "rejected"  # human/agent rejected; excluded


class MemoryAtomKind(enum.StrEnum):
    """L1 atom kinds."""

    FACT = "fact"
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    DECISION = "decision"


class MemoryAtom(Base, TimestampMixin):
    """L1 — one distilled, traceable fact/preference/constraint/decision."""

    __tablename__ = "memory_atoms"
    __table_args__ = (
        Index("ix_memory_atoms_user_status", "owner_id", "status"),
        Index("ix_memory_atoms_owner_kind", "owner_id", "kind"),
        {"schema": "sowknow"},
    )

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    owner_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(
        Enum(MemoryAtomKind, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    statement = Column(Text, nullable=False)
    confidence = Column(Integer, default=50)  # 0-100

    # Traceability (grounding): every atom must link back to its source.
    source_message_ids = Column(JSONB, default=list)
    source_session_ids = Column(JSONB, default=list)
    entity_ids = Column(JSONB, default=list)  # optional links to `entities`

    search_vector = Column(TSVECTOR, nullable=True)
    visibility = Column(
        Enum(MemoryVisibility, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=MemoryVisibility.PRIVATE,
        server_default="private",
    )
    status = Column(
        Enum(MemoryStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=MemoryStatus.PENDING,
        server_default="pending",
    )

    first_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner = relationship("User", back_populates="memory_atoms")

    def __repr__(self) -> str:
        return f"<MemoryAtom {self.kind}: {self.statement[:50]}...>"


class MemoryScenario(Base, TimestampMixin):
    """L2 — a knowledge block clustering related atoms around a scenario."""

    __tablename__ = "memory_scenarios"
    __table_args__ = (
        Index("ix_memory_scenarios_user_status", "owner_id", "status"),
        {"schema": "sowknow"},
    )

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    owner_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(512), nullable=False)
    summary = Column(Text, nullable=False)
    scope = Column(String(255), nullable=True)  # project/scenario label

    atom_ids = Column(JSONB, default=list)  # L1 atoms folded into this block
    source_session_ids = Column(JSONB, default=list)

    search_vector = Column(TSVECTOR, nullable=True)
    visibility = Column(
        Enum(MemoryVisibility, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=MemoryVisibility.PRIVATE,
        server_default="private",
    )
    status = Column(
        Enum(MemoryStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=MemoryStatus.PENDING,
        server_default="pending",
    )
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", back_populates="memory_scenarios")

    def __repr__(self) -> str:
        return f"<MemoryScenario {self.title[:50]}...>"


class MemoryProfile(Base, TimestampMixin):
    """L3 — long-term persona / stable patterns (one row per owner, upsert)."""

    __tablename__ = "memory_profiles"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    owner_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    persona = Column(JSONB, default=dict)  # {communication_pref, priorities, decision_style, ...}
    stable_patterns = Column(JSONB, default=list)  # recurring behaviours
    version = Column(Integer, default=1)

    owner = relationship("User", back_populates="memory_profile")

    def __repr__(self) -> str:
        return f"<MemoryProfile owner={self.owner_id} v{self.version}>"


class MemoryAssetBinding(Base, TimestampMixin):
    """Bind a memory asset to an agent scope with priority + opt-in."""

    __tablename__ = "memory_asset_bindings"
    __table_args__ = (
        Index("ix_memory_bindings_scope", "agent_scope", "asset_type", "asset_id"),
        {"schema": "sowknow"},
    )

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    owner_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_scope = Column(String(100), nullable=False)  # e.g. "chat:default", "collection:legal"
    asset_type = Column(String(20), nullable=False)  # "atom" | "scenario" | "profile"
    asset_id = Column(GUIDType(as_uuid=True), nullable=False)  # FK resolved by asset_type
    priority = Column(Integer, default=0)  # injection order
    enabled = Column(Boolean, nullable=False, default=True)
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<MemoryAssetBinding {self.agent_scope} → {self.asset_type}:{self.asset_id}>"
