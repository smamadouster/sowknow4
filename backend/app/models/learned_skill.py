"""Learned Skill (draft — docs/agent_memory/SPEC.md extension).

A reusable runbook distilled from real work: completed collection runs and
resolved guardian incidents become skills (trigger → steps → validation),
stored as drafts (`status=pending`) that only enter the active skill set after
review — mirroring the atom review doctrine.
"""

import enum
import uuid

from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base, GUIDType, TimestampMixin


class SkillStatus(enum.StrEnum):
    DRAFT = "draft"  # distilled, not yet reviewed
    ACTIVE = "active"  # reviewed/approved — eligible for use
    ARCHIVED = "archived"  # superseded or rejected


class LearnedSkill(Base, TimestampMixin):
    """One distilled runbook skill."""

    __tablename__ = "memory_skills"
    __table_args__ = (
        Index("ix_memory_skills_status", "status"),
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
    trigger = Column(Text, nullable=False)  # when to use this skill
    steps = Column(JSONB, default=list)  # ordered execution steps
    validation = Column(JSONB, default=list)  # how to verify success
    source_type = Column(String(30), nullable=False)  # "collection" | "incident"
    source_ref = Column(String(255), nullable=True)
    status = Column(
        String(20),
        nullable=False,
        default=SkillStatus.DRAFT.value,
        server_default=SkillStatus.DRAFT.value,
    )
    version = Column(Integer, default=1)

    def __repr__(self) -> str:
        return f"<LearnedSkill {self.title[:50]} ({self.status})>"
