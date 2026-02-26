from pydantic import BaseModel
from typing import Optional


class GenerateReportRequest(BaseModel):
    """Request body for POST /reports/generate."""

    report_type: str = "system_summary"
    format: str = "pdf"
    filters: dict = {}
    output_filename: Optional[str] = None


class GenerateReportResponse(BaseModel):
    """Response returned by POST /reports/generate."""

    task_id: str
    status: str = "processing"
    status_url: str
    message: str = "Report generation queued"
