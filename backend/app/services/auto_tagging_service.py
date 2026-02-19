"""
Auto-Tagging Service for Document Ingestion

Uses Gemini Flash to automatically extract topics, entities, importance,
and language from documents during the ingestion pipeline.
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.models.document import Document, DocumentTag, DocumentLanguage, DocumentBucket
from app.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)


class AutoTaggingService:
    """Service for automatic document tagging on ingestion"""

    def __init__(self):
        self.gemini_service = gemini_service
        self._ollama_service = None
        self._openrouter_service = None
    
    def _get_ollama_service(self):
        if self._ollama_service is None:
            from app.services.ollama_service import ollama_service
            self._ollama_service = ollama_service
        return self._ollama_service
    
    def _get_openrouter_service(self):
        if self._openrouter_service is None:
            from app.services.openrouter_service import openrouter_service
            self._openrouter_service = openrouter_service
        return self._openrouter_service

    async def tag_document(
        self,
        document: Document,
        extracted_text: str,
        db_session=None
    ) -> List[DocumentTag]:
        """
        Auto-tag a document with topics, entities, importance, and language

        Args:
            document: Document model instance
            extracted_text: Extracted text content from document
            db_session: Database session for creating tags

        Returns:
            List of created DocumentTag objects
        """
        try:
            # Determine LLM routing based on document bucket
            use_ollama = document.bucket == DocumentBucket.CONFIDENTIAL
            
            # Prepare the text for analysis (truncate if too long)
            analysis_text = self._prepare_text_for_analysis(extracted_text, document.filename)

            # Call appropriate LLM to extract tags
            if use_ollama:
                tags_data = await self._extract_tags_with_ollama(analysis_text, document)
            else:
                tags_data = await self._extract_tags_with_gemini(analysis_text, document)

            if not tags_data:
                logger.warning(f"No tags extracted for document {document.id}")
                return []

            # Create DocumentTag objects
            tags = []
            current_time = datetime.utcnow()

            # Topic tags
            for topic in tags_data.get("topics", [])[:5]:
                tags.append(DocumentTag(
                    document_id=document.id,
                    tag_name=topic,
                    tag_type="topic",
                    auto_generated=True,
                    confidence_score=85,
                    created_at=current_time
                ))

            # Entity tags
            for entity in tags_data.get("entities", [])[:10]:
                tags.append(DocumentTag(
                    document_id=document.id,
                    tag_name=entity["name"],
                    tag_type=entity.get("type", "entity"),
                    auto_generated=True,
                    confidence_score=entity.get("confidence", 75),
                    created_at=current_time
                ))

            # Importance tag
            importance = tags_data.get("importance")
            if importance:
                tags.append(DocumentTag(
                    document_id=document.id,
                    tag_name=importance,
                    tag_type="importance",
                    auto_generated=True,
                    confidence_score=80,
                    created_at=current_time
                ))

            # Language detection (update document field too)
            language = tags_data.get("language", "unknown")
            if language and language != "unknown":
                try:
                    document.language = DocumentLanguage(language)
                except ValueError:
                    pass  # Keep existing language

            # Save tags if db_session provided
            if db_session:
                for tag in tags:
                    db_session.add(tag)
                db_session.flush()

            logger.info(f"Auto-tagged document {document.id} with {len(tags)} tags")
            return tags

        except Exception as e:
            logger.error(f"Error auto-tagging document {document.id}: {e}")
            return []

    def _prepare_text_for_analysis(self, text: str, filename: str) -> str:
        """Prepare text for Gemini analysis"""
        # Get first 3000 characters for analysis
        text_preview = text[:3000] if text else ""

        # Add filename context
        return f"Filename: {filename}\n\nContent:\n{text_preview}"

    async def _extract_tags_with_gemini(
        self,
        text: str,
        document: Document
    ) -> Optional[Dict[str, Any]]:
        """Extract tags using OpenRouter (MiniMax) for public documents"""

        system_prompt = """You are an intelligent document tagger for SOWKNOW. Analyze the document and extract:

1. **topics**: 3-5 main topics/themes (single words or short phrases)
2. **entities**: Named entities (people, organizations, locations) with their types
3. **importance**: Overall importance level (critical, high, medium, low)
4. **language**: Document language (en, fr, multi, unknown)

Respond ONLY with valid JSON in this exact format:
```json
{
  "topics": ["topic1", "topic2", "topic3"],
  "entities": [
    {"name": "Entity Name", "type": "person|organization|location|other", "confidence": 85}
  ],
  "importance": "high",
  "language": "en"
}
```"""

        user_prompt = f"""Analyze this document and extract tags:

Filename: {document.filename}
File Type: {document.mime_type}

{text}

Extract the tags now:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            response_parts = []
            # Use OpenRouter (MiniMax) for public documents instead of direct Gemini
            llm_service = self._get_openrouter_service()
            async for chunk in llm_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.3,
                max_tokens=1000
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response_parts.append(chunk)

            response_text = "".join(response_parts).strip()

            # Extract JSON
            import json
            json_text = self._extract_json(response_text)

            if json_text:
                return json.loads(json_text)

        except Exception as e:
            logger.error(f"OpenRouter tagging error: {e}")

        return None

    async def _extract_tags_with_ollama(
        self,
        text: str,
        document: Document
    ) -> Optional[Dict[str, Any]]:
        """Extract tags using Ollama"""

        system_prompt = """You are an intelligent document tagger for SOWKNOW. Analyze the document and extract:

1. **topics**: 3-5 main topics/themes (single words or short phrases)
2. **entities**: Named entities (people, organizations, locations) with their types
3. **importance**: Overall importance level (critical, high, medium, low)
4. **language**: Document language (en, fr, multi, unknown)

Respond ONLY with valid JSON in this exact format:
```json
{
  "topics": ["topic1", "topic2", "topic3"],
  "entities": [
    {"name": "Entity Name", "type": "person|organization|location|other", "confidence": 85}
  ],
  "importance": "high",
  "language": "en"
}
```"""

        user_prompt = f"""Analyze this document and extract tags:

Filename: {document.filename}
File Type: {document.mime_type}

{text}

Extract the tags now:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            llm_service = self._get_ollama_service()
            response_parts = []
            async for chunk in llm_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.3,
                max_tokens=1000
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response_parts.append(chunk)

            response_text = "".join(response_parts).strip()

            import json
            json_text = self._extract_json(response_text)

            if json_text:
                return json.loads(json_text)

        except Exception as e:
            logger.error(f"Ollama tagging error: {e}")

        return None

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON from response text"""
        text = text.strip()

        # Remove markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()

        # Find JSON object
        if text.startswith("{"):
            brace_count = 0
            end_pos = 0
            for i, char in enumerate(text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i + 1
                        break
            if end_pos > 0:
                return text[:end_pos]

        return None

    async def detect_language(self, text: str) -> str:
        """
        Detect document language from text content

        Returns: 'en', 'fr', 'multi', or 'unknown'
        """
        if not text or len(text) < 50:
            return "unknown"

        # Simple heuristic detection
        text_lower = text.lower()[:1000]

        # French indicators
        fr_indicators = [' le ', ' la ', ' les ', ' un ', ' une ', ' des ', ' et ',
                        ' est ', ' sont ', ' pour ', ' avec ', ' sans ', ' pas ',
                        'plus', 'être', 'avoir', 'faire', 'aller', 'voir']

        # English indicators
        en_indicators = [' the ', ' a ', ' an ', ' and ', ' or ', ' but ', ' with ',
                        ' without ', ' not ', ' is ', ' are ', ' was ', ' were ',
                        'have', 'has', 'had', 'will', 'would', 'could', 'should']

        fr_count = sum(1 for indicator in fr_indicators if indicator in text_lower)
        en_count = sum(1 for indicator in en_indicators if indicator in text_lower)

        if fr_count > en_count * 1.5:
            return "fr"
        elif en_count > fr_count * 1.5:
            return "en"
        elif fr_count > 2 and en_count > 2:
            return "multi"
        else:
            return "unknown"

    async def suggest_similar_documents(
        self,
        document_id: str,
        db_session,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Suggest similar documents based on tag overlap

        Args:
            document_id: ID of the reference document
            db_session: Database session
            limit: Maximum number of suggestions

        Returns:
            List of similar documents with similarity scores
        """
        from sqlalchemy import func, and_

        # Get tags for the reference document
        ref_tags = db_session.query(DocumentTag.tag_name).filter(
            DocumentTag.document_id == document_id
        ).all()

        if not ref_tags:
            return []

        ref_tag_names = [tag[0] for tag in ref_tags]

        # Find documents with shared tags
        similar = db_session.query(
            DocumentTag.document_id,
            func.count(DocumentTag.tag_name).label('shared_count')
        ).filter(
            and_(
                DocumentTag.tag_name.in_(ref_tag_names),
                DocumentTag.document_id != document_id
            )
        ).group_by(
            DocumentTag.document_id
        ).order_by(
            func.count(DocumentTag.tag_name).desc()
        ).limit(limit).all()

        results = []
        for doc_id, shared_count in similar:
            # Get document info
            doc = db_session.query(Document).filter(Document.id == doc_id).first()
            if doc:
                results.append({
                    "id": str(doc.id),
                    "filename": doc.filename,
                    "shared_tags": shared_count,
                    "similarity_score": round(shared_count / len(ref_tag_names), 2)
                })

        return results


# Global auto-tagging service instance
auto_tagging_service = AutoTaggingService()
