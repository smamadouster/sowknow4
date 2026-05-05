import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.models.document import Document, DocumentStatus
from app.tasks.pipeline_orchestrator import dispatch_document

session = SessionLocal()

doc_ids = [
    "f903c7f1-61d1-497b-a181-e1cae37334dd",
    "bced18b4-cf55-42c4-a9d3-4f5c5ce2c39c",
    "c26fd625-31e4-4d22-8781-256b7b54883d",
    "fd4a49de-ba66-47af-a317-8a391208b462",
]

for doc_id in doc_ids:
    doc = session.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        print(f"Doc {doc_id} not found")
        continue
    
    stage = session.query(PipelineStage).filter(
        PipelineStage.document_id == doc_id,
        PipelineStage.stage == StageEnum.EMBEDDED
    ).first()
    
    if stage:
        stage.status = StageStatus.PENDING
        stage.attempt = 0
        stage.started_at = None
        stage.completed_at = None
        stage.error_message = None
        print(f"Reset embedded stage for {doc_id}")
    else:
        print(f"No embedded stage found for {doc_id}, creating one")
        stage = PipelineStage(
            document_id=doc_id,
            stage=StageEnum.EMBEDDED,
            status=StageStatus.PENDING,
            attempt=0,
            max_attempts=3,
        )
        session.add(stage)
    
    doc.status = DocumentStatus.PROCESSING
    doc.pipeline_error = None
    doc.pipeline_retry_count = 0
    
    session.commit()
    
    result = dispatch_document(doc_id, from_stage=StageEnum.EMBEDDED)
    print(f"Dispatched {doc_id} from EMBEDDED: {result}")

session.close()
print("Done")
