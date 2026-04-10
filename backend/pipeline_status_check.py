"""Quick pipeline status check — run inside backend container."""
from app.database import SessionLocal
from app.models.pipeline import PipelineStage, StageEnum, StageStatus

db = SessionLocal()
for s in StageEnum:
    p = db.query(PipelineStage).filter(PipelineStage.stage == s, PipelineStage.status == StageStatus.PENDING).count()
    r = db.query(PipelineStage).filter(PipelineStage.stage == s, PipelineStage.status == StageStatus.RUNNING).count()
    c = db.query(PipelineStage).filter(PipelineStage.stage == s, PipelineStage.status == StageStatus.COMPLETED).count()
    f = db.query(PipelineStage).filter(PipelineStage.stage == s, PipelineStage.status == StageStatus.FAILED).count()
    if p or r or c or f:
        print(f"{s.value:12s}  pending={p}  running={r}  completed={c}  failed={f}")
db.close()
