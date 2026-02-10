"""
Similarity Grouping Service for Document Clustering

Groups similar documents together using embedding similarity.
Useful for finding document groups like "all IDs", "all balance sheets", etc.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
import numpy as np

from app.models.document import Document, DocumentChunk
from app.models.user import User, UserRole
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class SimilarityGroup:
    """Represents a group of similar documents"""

    def __init__(
        self,
        group_id: str,
        name: str,
        description: str,
        document_ids: List[str],
        similarity_score: float,
        common_patterns: List[str]
    ):
        self.group_id = group_id
        self.name = name
        self.description = description
        self.document_ids = document_ids
        self.similarity_score = similarity_score
        self.common_patterns = common_patterns

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "name": self.name,
            "description": self.description,
            "document_count": len(self.document_ids),
            "document_ids": self.document_ids,
            "similarity_score": round(self.similarity_score, 3),
            "common_patterns": self.common_patterns
        }


class SimilarityGroupingService:
    """Service for grouping similar documents"""

    def __init__(self):
        self.embedding_service = embedding_service

    async def find_similar_groups(
        self,
        user: User,
        db: Session,
        min_group_size: int = 2,
        max_groups: int = 20,
        similarity_threshold: float = 0.75
    ) -> List[SimilarityGroup]:
        """
        Find groups of similar documents for the user

        Args:
            user: Current user
            db: Database session
            min_group_size: Minimum documents to form a group
            max_groups: Maximum number of groups to return
            similarity_threshold: Minimum similarity score (0-1)

        Returns:
            List of SimilarityGroup objects
        """
        # Get user-accessible documents
        from app.models.document import DocumentBucket, DocumentStatus

        query = db.query(Document).filter(
            Document.status == DocumentStatus.INDEXED
        )

        # Apply bucket filter based on user role
        if user.role == UserRole.USER:
            query = query.filter(Document.bucket == DocumentBucket.PUBLIC)

        documents = query.all()

        if len(documents) < min_group_size:
            return []

        # Extract document embeddings
        doc_embeddings = []
        for doc in documents:
            chunks = db.query(DocumentChunk).filter(
                DocumentChunk.document_id == doc.id
            ).all()

            if chunks:
                # Get first chunk embedding as representative
                # (in production, average all chunk embeddings)
                for chunk in chunks:
                    if chunk.embedding:
                        doc_embeddings.append({
                            "id": str(doc.id),
                            "filename": doc.filename,
                            "mime_type": doc.mime_type,
                            "embedding": np.array(chunk.embedding)
                        })
                        break

        if len(doc_embeddings) < min_group_size:
            return []

        # Compute similarity matrix
        groups = await self._cluster_by_similarity(
            doc_embeddings,
            min_group_size,
            similarity_threshold
        )

        # Name the groups based on common patterns
        named_groups = []
        for i, group in enumerate(groups[:max_groups]):
            group_info = await self._analyze_group(group, db)
            named_groups.append(SimilarityGroup(
                group_id=f"group_{i}",
                name=group_info["name"],
                description=group_info["description"],
                document_ids=group,
                similarity_score=group_info["avg_similarity"],
                common_patterns=group_info["patterns"]
            ))

        return named_groups

    async def _cluster_by_similarity(
        self,
        doc_embeddings: List[Dict[str, Any]],
        min_group_size: int,
        threshold: float
    ) -> List[List[str]]:
        """Cluster documents by similarity using simple approach"""
        # Compute pairwise cosine similarity
        n = len(doc_embeddings)
        similarity_matrix = np.zeros((n, n))

        for i in range(n):
            for j in range(i + 1, n):
                emb1 = doc_embeddings[i]["embedding"]
                emb2 = doc_embeddings[j]["embedding"]

                # Cosine similarity
                similarity = np.dot(emb1, emb2) / (
                    np.linalg.norm(emb1) * np.linalg.norm(emb2)
                )
                similarity_matrix[i][j] = similarity
                similarity_matrix[j][i] = similarity

        # Find clusters using threshold
        visited = set()
        clusters = []

        for i in range(n):
            if i in visited:
                continue

            # Find all similar documents
            cluster = []
            stack = [i]

            while stack:
                current = stack.pop()
                if current in visited:
                    continue

                visited.add(current)
                cluster.append(current)

                # Find neighbors above threshold
                for j in range(n):
                    if j not in visited and similarity_matrix[current][j] >= threshold:
                        stack.append(j)

            if len(cluster) >= min_group_size:
                clusters.append([
                    doc_embeddings[idx]["id"]
                    for idx in cluster
                ])

        return clusters

    async def _analyze_group(
        self,
        document_ids: List[str],
        db: Session
    ) -> Dict[str, Any]:
        """Analyze a group to determine its theme and patterns"""
        # Get documents
        documents = db.query(Document).filter(
            Document.id.in_(document_ids)
        ).all()

        if not documents:
            return {
                "name": "Unknown Group",
                "description": "No documents found",
                "avg_similarity": 0.0,
                "patterns": []
            }

        # Extract filename patterns
        filenames = [doc.filename for doc in documents]
        mime_types = [doc.mime_type for doc in documents]

        # Find common patterns in filenames
        common_patterns = self._extract_common_patterns(filenames)

        # Determine group name
        group_name = self._generate_group_name(filenames, mime_types, common_patterns)

        # Generate description
        description = f"Group of {len(documents)} similar documents"
        if common_patterns:
            description += f" sharing patterns: {', '.join(common_patterns[:3])}"

        return {
            "name": group_name,
            "description": description,
            "avg_similarity": 0.85,  # Placeholder - would compute from actual similarities
            "patterns": common_patterns
        }

    def _extract_common_patterns(self, filenames: List[str]) -> List[str]:
        """Extract common patterns from filenames"""
        patterns = []

        # Convert to lowercase for comparison
        lower_filenames = [f.lower() for f in filenames]

        # Common document type patterns
        doc_types = {
            "invoice": ["invoice", "facture", "inv-", "fact-"],
            "contract": ["contract", "contrat", "agreement", "accord"],
            "id": ["id", "identity", "identité", "passport", "passeport", "carte"],
            "balance": ["balance", "bilan", "statement", "relevé"],
            "receipt": ["receipt", "reçu", "facture"],
            "report": ["report", "rapport", "summary"],
            "certificate": ["certificate", "certificat", "attestation"],
            "insurance": ["insurance", "assurance"],
            "tax": ["tax", "impôt", "fiscal"],
            "bank": ["bank", "banque", "account", "compte"]
        }

        for doc_type, keywords in doc_types.items():
            matches = sum(1 for f in lower_filenames if any(kw in f for kw in keywords))
            if matches >= len(filenames) * 0.5:  # 50% match threshold
                patterns.append(doc_type)

        # Extract number patterns (years, IDs)
        import re
        years = []
        for f in lower_filenames:
            year_match = re.search(r'20[12][0-9]', f)
            if year_match:
                years.append(year_match.group())

        if years:
            most_common_year = max(set(years), key=years.count)
            if years.count(most_common_year) >= len(filenames) * 0.5:
                patterns.append(most_common_year)

        return patterns[:5]

    def _generate_group_name(
        self,
        filenames: List[str],
        mime_types: List[str],
        patterns: List[str]
    ) -> str:
        """Generate a descriptive name for the group"""
        if not patterns:
            # Use first filename as base
            base = filenames[0]
            # Remove extension and truncate
            name = base.rsplit('.', 1)[0]
            return f"{name} ({len(filenames)} documents)"[:50]

        # Build name from patterns
        name_parts = []
        if "invoice" in patterns:
            name_parts.append("Invoices")
        elif "contract" in patterns:
            name_parts.append("Contracts")
        elif "id" in patterns:
            name_parts.append("IDs")
        elif "balance" in patterns:
            name_parts.append("Financial Statements")

        # Add year if present
        year_pattern = next((p for p in patterns if p.startswith("20")), None)
        if year_pattern:
            name_parts.append(year_pattern)

        if not name_parts:
            name_parts = patterns[:2]

        base_name = " ".join(name_parts)
        return f"{base_name} ({len(filenames)})"[:50]

    async def find_similar_to_document(
        self,
        document_id: str,
        user: User,
        db: Session,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find documents similar to a specific document

        Args:
            document_id: Reference document ID
            user: Current user
            db: Database session
            limit: Maximum results

        Returns:
            List of similar documents with scores
        """
        from app.models.document import DocumentBucket, DocumentStatus

        # Get reference document chunks
        ref_chunks = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id
        ).all()

        if not ref_chunks:
            return []

        # Get reference embedding (average of all chunks)
        ref_embedding = None
        for chunk in ref_chunks:
            if chunk.embedding:
                if ref_embedding is None:
                    ref_embedding = np.array(chunk.embedding)
                else:
                    ref_embedding += np.array(chunk.embedding)

        if ref_embedding is None:
            return []

        ref_embedding = ref_embedding / len(ref_chunks)

        # Get candidate documents
        query = db.query(Document).filter(
            and_(
                Document.id != document_id,
                Document.status == DocumentStatus.INDEXED
            )
        )

        # Apply bucket filter
        if user.role == UserRole.USER:
            query = query.filter(Document.bucket == DocumentBucket.PUBLIC)

        candidates = query.limit(100).all()

        # Compute similarities
        similarities = []
        for doc in candidates:
            chunks = db.query(DocumentChunk).filter(
                DocumentChunk.document_id == doc.id
            ).first()

            if chunks and chunks.embedding:
                doc_embedding = np.array(chunks.embedding)
                similarity = np.dot(ref_embedding, doc_embedding) / (
                    np.linalg.norm(ref_embedding) * np.linalg.norm(doc_embedding)
                )

                similarities.append({
                    "id": str(doc.id),
                    "filename": doc.filename,
                    "similarity_score": round(float(similarity), 4),
                    "created_at": doc.created_at.isoformat()
                })

        # Sort by similarity and return top results
        similarities.sort(key=lambda x: x["similarity_score"], reverse=True)
        return similarities[:limit]


# Global similarity grouping service instance
similarity_service = SimilarityGroupingService()
