"""Memory review API (draft v0.1 — docs/agent_memory/SPEC.md).

Owner-scoped endpoints to list distilled atoms/scenarios and review them
(pending → reviewed / rejected). Reviewed atoms are the only ones eligible
for chat context injection (memory_search_service filters status=reviewed).

Access: any authenticated user sees ONLY their own memory assets.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.memory import (
    MemoryAtom,
    MemoryProfile,
    MemoryScenario,
    MemoryStatus,
)
from app.models.learned_skill import LearnedSkill
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory"])


class AtomResponse(BaseModel):
    id: UUID
    kind: str
    statement: str
    confidence: int
    status: str
    visibility: str
    source_session_ids: list
    created_at: object

    class Config:
        from_attributes = True


class ScenarioResponse(BaseModel):
    id: UUID
    title: str
    summary: str
    scope: str | None
    status: str
    visibility: str
    created_at: object

    class Config:
        from_attributes = True


class MemoryListResponse(BaseModel):
    atoms: list[AtomResponse]
    scenarios: list[ScenarioResponse]
    total_atoms: int
    total_scenarios: int


class ProfileResponse(BaseModel):
    persona: dict
    stable_patterns: list
    version: int


class AtomReviewRequest(BaseModel):
    status: str = Field(..., pattern="^(pending|reviewed|rejected)$")


@router.get("/atoms", response_model=MemoryListResponse)
async def list_memory(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryListResponse:
    """List the current user's memory atoms + scenarios (pending first)."""
    atoms = (
        (
            await db.execute(
                select(MemoryAtom)
                .where(MemoryAtom.owner_id == current_user.id)
                .order_by(MemoryAtom.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    scenarios = (
        (
            await db.execute(
                select(MemoryScenario)
                .where(MemoryScenario.owner_id == current_user.id)
                .order_by(MemoryScenario.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return MemoryListResponse(
        atoms=[AtomResponse.model_validate(a) for a in atoms],
        scenarios=[ScenarioResponse.model_validate(s) for s in scenarios],
        total_atoms=len(atoms),
        total_scenarios=len(scenarios),
    )


@router.get("/profile", response_model=ProfileResponse)
async def get_memory_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    """Return the owner's L3 profile (persona + stable patterns), if built."""
    profile = (
        (await db.execute(select(MemoryProfile).where(MemoryProfile.owner_id == current_user.id))).scalars().first()
    )
    if profile is None:
        return ProfileResponse(persona={}, stable_patterns=[], version=0)
    return ProfileResponse(
        persona=profile.persona or {},
        stable_patterns=profile.stable_patterns or [],
        version=profile.version or 0,
    )


@router.post("/profile/build", response_model=ProfileResponse)
async def build_memory_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    """Build/refresh the owner's L3 profile now (instead of waiting for the
    monthly beat). Uses only reviewed atoms/scenarios."""
    from app.services.memory_service import memory_service

    ok = await memory_service.build_profile(db, current_user.id)
    if not ok:
        return ProfileResponse(persona={}, stable_patterns=[], version=0)
    profile = (
        (await db.execute(select(MemoryProfile).where(MemoryProfile.owner_id == current_user.id))).scalars().first()
    )
    return ProfileResponse(
        persona=profile.persona or {},
        stable_patterns=profile.stable_patterns or [],
        version=profile.version or 0,
    )


@router.patch("/atoms/{atom_id}", response_model=AtomResponse)
async def review_atom(
    atom_id: UUID,
    body: AtomReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AtomResponse:
    """Review one atom: pending → reviewed (eligible for injection) or rejected."""
    atom = (
        (
            await db.execute(
                select(MemoryAtom).where(
                    MemoryAtom.id == atom_id,
                    MemoryAtom.owner_id == current_user.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if atom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Atom not found")
    atom.status = body.status
    await db.commit()
    await db.refresh(atom)
    logger.info(
        "memory.review user=%s atom=%s → %s",
        current_user.id,
        atom_id,
        body.status,
    )
    return AtomResponse.model_validate(atom)


class SkillResponse(BaseModel):
    id: UUID
    title: str
    trigger: str
    steps: list
    validation: list
    source_type: str
    source_ref: str | None
    status: str
    version: int

    class Config:
        from_attributes = True


class SkillListResponse(BaseModel):
    skills: list[SkillResponse]
    total: int


class SkillReviewRequest(BaseModel):
    status: str = Field(..., pattern="^(draft|active|archived)$")


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillListResponse:
    """List the owner's learned skills (draft first)."""
    skills = (
        (
            await db.execute(
                select(LearnedSkill)
                .where(LearnedSkill.owner_id == current_user.id)
                .order_by(LearnedSkill.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return SkillListResponse(
        skills=[SkillResponse.model_validate(s) for s in skills],
        total=len(skills),
    )


@router.patch("/skills/{skill_id}", response_model=SkillResponse)
async def review_skill(
    skill_id: UUID,
    body: SkillReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """Review one skill: draft → active (eligible) or archived."""
    skill = (
        (
            await db.execute(
                select(LearnedSkill).where(
                    LearnedSkill.id == skill_id,
                    LearnedSkill.owner_id == current_user.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    skill.status = body.status
    await db.commit()
    await db.refresh(skill)
    return SkillResponse.model_validate(skill)


@router.post("/atoms/{atom_id}/reject", response_model=AtomResponse)
async def reject_atom(
    atom_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AtomResponse:
    """Reject one atom (shorthand for PATCH status=rejected)."""
    return await review_atom(
        atom_id,
        AtomReviewRequest(status=MemoryStatus.REJECTED.value),
        current_user=current_user,
        db=db,
    )
