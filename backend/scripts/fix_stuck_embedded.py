import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.models.document import Document, DocumentStatus
from app.tasks.pipeline_orchestrator import dispatch_document

session = SessionLocal()

doc_ids = [
    "6a77da8a-ae61-4635-9a59-bc5a79741584",
    "8d3b50ca-ead2-4152-8ecf-207f1112232f",
    "c4ad6fa5-a5da-46c4-9e14-d7069e438f9f",
]

for doc_id in doc_ids:
    doc = session.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        print(f"Doc {doc_id} not found")
        continue
    
    # Reset embedded stage
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
    
    # Reset document status and error
    doc.status = DocumentStatus.PROCESSING
    doc.pipeline_error = None
    doc.pipeline_retry_count = 0
    
    session.commit()
    
    # Dispatch from embedded stage
    result = dispatch_document(doc_id, from_stage=StageEnum.EMBEDDED)
    print(f"Dispatched {doc_id} from EMBEDDED: {result}")

session.close()
print("Done")
