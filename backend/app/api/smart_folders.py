"""
Smart Folders and Reports API endpoints

Provides endpoints for generating AI content from documents and
creating professional PDF reports from collections.
"""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID

from app.database import get_db
from app.models.user import User
from app.models.audit import AuditLog, AuditAction
from app.schemas.collection import (
    SmartFolderGenerateRequest,
    SmartFolderResponse,
    CollectionReportRequest,
    CollectionReportResponse,
    ReportFormat,
)
from app.services.smart_folder_service import smart_folder_service
from app.services.report_service import report_service, ReportFormat as ReportFormatService
from app.api.deps import get_current_user

router = APIRouter(prefix="/smart-folders", tags=["smart-folders"])
logger = logging.getLogger(__name__)


def create_audit_log(
    db: Session,
    user_id: UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None
):
    """Helper function to create audit log entries for confidential access"""
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details) if details else None
        )
        db.add(audit_entry)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Audit logging failed: {str(e)}")


@router.post("/generate", response_model=SmartFolderResponse)
async def generate_smart_folder(
    request: SmartFolderGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate a Smart Folder with AI-created content

    Creates a new collection with AI-generated article/content based on
    the provided topic and documents gathered from the user's vault.

    - **topic**: The subject to generate content about
    - **include_confidential**: Include confidential documents (admin only)
    - **style**: Writing style (informative, creative, professional, casual)
    - **length**: Content length (short, medium, long)
    """
    # Check confidential access
    if request.include_confidential and not current_user.can_access_confidential:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access confidential documents"
        )

    try:
        result = await smart_folder_service.generate_smart_folder(
            topic=request.topic,
            style=request.style,
            length=request.length,
            include_confidential=request.include_confidential,
            user=current_user,
            db=db
        )

        # AUDIT LOG: Log confidential document access in smart folder generation
        if request.include_confidential and result.get("documents"):
            confidential_docs = [
                {"id": doc.get("id"), "filename": doc.get("filename")}
                for doc in result["documents"]
                if doc.get("bucket") == "confidential"
            ]
            if confidential_docs:
                create_audit_log(
                    db=db,
                    user_id=current_user.id,
                    action=AuditAction.CONFIDENTIAL_ACCESSED,
                    resource_type="smart_folder",
                    resource_id=str(result.get("collection_id", "unknown")),
                    details={
                        "topic": request.topic,
                        "confidential_document_count": len(confidential_docs),
                        "confidential_documents": confidential_docs,
                        "action": "generate_smart_folder"
                    }
                )
                logger.info(f"CONFIDENTIAL_ACCESSED: User {current_user.email} accessed confidential documents in smart folder generation")

        return SmartFolderResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")


@router.post("/reports/generate", response_model=CollectionReportResponse)
async def generate_collection_report(
    request: CollectionReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate a PDF report from a collection

    Creates a professional report in the specified format with analysis,
    findings, recommendations, and citations.

    - **collection_id**: The collection to generate report from
    - **format**: Report length (short, standard, comprehensive)
    - **include_citations**: Include document references
    - **language**: Report language (en, fr)
    """
    # Map format enum
    format_map = {
        "short": ReportFormatService.SHORT,
        "standard": ReportFormatService.STANDARD,
        "comprehensive": ReportFormatService.COMPREHENSIVE
    }

    report_format = format_map.get(request.format.value, ReportFormatService.STANDARD)

    try:
        result = await report_service.generate_report(
            collection_id=request.collection_id,
            format=report_format,
            include_citations=request.include_citations,
            language=request.language,
            user=current_user,
            db=db
        )

        # AUDIT LOG: Log confidential document access in report generation
        if result.get("has_confidential"):
            create_audit_log(
                db=db,
                user_id=current_user.id,
                action=AuditAction.CONFIDENTIAL_ACCESSED,
                resource_type="report",
                resource_id=str(request.collection_id),
                details={
                    "format": request.format.value,
                    "language": request.language,
                    "action": "generate_report",
                    "has_confidential": True
                }
            )
            logger.info(f"CONFIDENTIAL_ACCESSED: User {current_user.email} generated report with confidential documents")

        return CollectionReportResponse(
            report_id=UUID(result["report_id"]),
            collection_id=request.collection_id,
            format=request.format,
            content=result["content"],
            citations=result.get("citations", []),
            generated_at=datetime.fromisoformat(result["generated_at"]),
            file_url=result.get("file_url")
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation error: {str(e)}")


from datetime import datetime


@router.get("/reports/templates")
async def get_report_templates(
    current_user: User = Depends(get_current_user)
):
    """Get available report templates and formats"""
    return {
        "formats": [
            {
                "value": "short",
                "name": "Short",
                "description": "1-2 pages, executive summary style",
                "sections": ["Executive Summary", "Key Findings", "Recommendations"],
                "typical_length": "300-500 words"
            },
            {
                "value": "standard",
                "name": "Standard",
                "description": "3-5 pages, balanced overview",
                "sections": ["Executive Summary", "Introduction", "Analysis", "Key Findings", "Recommendations", "Conclusion"],
                "typical_length": "800-1500 words"
            },
            {
                "value": "comprehensive",
                "name": "Comprehensive",
                "description": "6-10 pages, in-depth analysis",
                "sections": ["Executive Summary", "Introduction", "Background", "Detailed Analysis", "Key Findings", "Supporting Evidence", "Recommendations", "Implementation Notes", "Conclusion", "Appendices"],
                "typical_length": "2000-4000 words"
            }
        ],
        "languages": [
            {"value": "en", "name": "English"},
            {"value": "fr", "name": "Français"}
        ],
        "style_options": [
            {"value": "informative", "name": "Informative", "description": "Educational, clear explanations"},
            {"value": "creative", "name": "Creative", "description": "Engaging, vivid language"},
            {"value": "professional", "name": "Professional", "description": "Formal business tone"},
            {"value": "casual", "name": "Casual", "description": "Friendly, conversational"}
        ]
    }


@router.get("/reports/{report_id}")
async def get_report(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a previously generated report"""
    # In a real implementation, this would fetch from a reports table
    # For now, return a placeholder
    raise HTTPException(status_code=501, detail="Report history not yet implemented")
