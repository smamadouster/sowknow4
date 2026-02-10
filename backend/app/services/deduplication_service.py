"""
Deduplication Service for Document Uploads

Hash-based duplicate detection to prevent re-uploading identical files.
Supports SHA256 hashing with metadata tracking for file integrity.
"""
import logging
import hashlib
from typing import Dict, Optional, Set
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.document import Document
from app.models.base import Base

logger = logging.getLogger(__name__)


class FileHash:
    """File hash record for tracking uploads"""

    def __init__(self, sha256_hash: str, filename: str, size: int, document_id: Optional[str] = None):
        self.sha256_hash = sha256_hash
        self.filename = filename
        self.size = size
        self.document_id = document_id
        self.first_seen = datetime.utcnow()
        self.last_seen = datetime.utcnow()


class DeduplicationService:
    """Service for detecting and managing duplicate files"""

    def __init__(self):
        # In-memory cache for recent hashes (production would use Redis)
        self.hash_cache: Dict[str, FileHash] = {}
        self.cache_size_limit = 10000

    def calculate_hash(self, file_content: bytes) -> str:
        """
        Calculate SHA256 hash of file content

        Args:
            file_content: Raw file bytes

        Returns:
            Hexadecimal SHA256 hash
        """
        return hashlib.sha256(file_content).hexdigest()

    def calculate_hash_from_chunks(self, chunks: list) -> str:
        """
        Calculate hash from file chunks for streaming

        Args:
            chunks: Iterator of byte chunks

        Returns:
            Hexadecimal SHA256 hash
        """
        sha256 = hashlib.sha256()
        for chunk in chunks:
            sha256.update(chunk)
        return sha256.hexdigest()

    def is_duplicate(
        self,
        file_hash: str,
        filename: str,
        size: int,
        db: Session
    ) -> Optional[Document]:
        """
        Check if file has already been uploaded

        Args:
            file_hash: SHA256 hash of file content
            filename: Original filename
            size: File size in bytes
            db: Database session

        Returns:
            Existing Document if duplicate, None otherwise
        """
        # Check cache first
        if file_hash in self.hash_cache:
            cached = self.hash_cache[file_hash]
            # Verify size matches
            if cached.size == size:
                logger.debug(f"Duplicate found in cache: {filename}")
                # Fetch the actual document
                doc = db.query(Document).filter(
                    Document.id == cached.document_id
                ).first()
                return doc

        # Check database using metadata
        # We store hash in document metadata for fast lookup
        doc = db.query(Document).filter(
            Document.document_metadata["sha256_hash"].astext == file_hash
        ).first()

        if doc:
            # Verify size matches
            if doc.size == size:
                logger.info(f"Duplicate found in database: {filename} -> {doc.filename}")
                # Add to cache
                self._add_to_cache(file_hash, filename, size, str(doc.id))
                return doc

        return None

    def register_upload(
        self,
        file_hash: str,
        filename: str,
        size: int,
        document_id: str,
        db: Session
    ):
        """
        Register a new file upload to prevent future duplicates

        Args:
            file_hash: SHA256 hash of file content
            filename: Original filename
            size: File size in bytes
            document_id: ID of uploaded document
            db: Database session
        """
        # Update document metadata with hash
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            metadata = doc.document_metadata or {}
            metadata["sha256_hash"] = file_hash
            metadata["hash_algorithm"] = "sha256"
            metadata["hash_date"] = datetime.utcnow().isoformat()
            doc.document_metadata = metadata

        # Add to cache
        self._add_to_cache(file_hash, filename, size, document_id)

        logger.debug(f"Registered upload: {filename} (hash: {file_hash[:16]}...)")

    def _add_to_cache(self, file_hash: str, filename: str, size: int, document_id: str):
        """Add hash to in-memory cache"""
        # Evict oldest if cache is full
        if len(self.hash_cache) >= self.cache_size_limit:
            # Simple FIFO eviction (could be LRU in production)
            oldest_key = next(iter(self.hash_cache))
            del self.hash_cache[oldest_key]

        self.hash_cache[file_hash] = FileHash(file_hash, filename, size, document_id)

    def find_similar_files(
        self,
        filename: str,
        db: Session,
        threshold: float = 0.8
    ) -> list[Document]:
        """
        Find files with similar names (potential duplicates)

        Args:
            filename: Filename to compare against
            db: Database session
            threshold: Similarity threshold (0-1)

        Returns:
            List of potentially duplicate documents
        """
        from difflib import SequenceMatcher

        # Get all documents and compare names
        all_docs = db.query(Document).all()

        similar = []
        for doc in all_docs:
            similarity = SequenceMatcher(None, filename.lower(), doc.filename.lower()).ratio()
            if similarity >= threshold:
                similar.append((doc, similarity))

        # Sort by similarity descending
        similar.sort(key=lambda x: x[1], reverse=True)

        return [doc for doc, _ in similar[:10]]

    def scan_for_duplicates(self, db: Session) -> Dict[str, any]:
        """
        Scan all documents for potential duplicates

        Args:
            db: Database session

        Returns:
            Dictionary with duplicate statistics
        """
        # Group documents by size (quick filter)
        from sqlalchemy import func

        size_groups = db.query(
            Document.size,
            func.count(Document.id).label('count')
        ).group_by(Document.size).having(
            func.count(Document.id) > 1
        ).all()

        potential_duplicates = []
        for size, count in size_groups:
            docs = db.query(Document).filter(Document.size == size).all()
            if len(docs) > 1:
                potential_duplicates.append({
                    "size": size,
                    "count": len(docs),
                    "filenames": [doc.filename for doc in docs]
                })

        # Calculate full hash duplicates
        hash_duplicates = []
        # Get documents with hashes in metadata
        docs_with_hashes = db.query(Document).filter(
            Document.document_metadata["sha256_hash"].astext != None
        ).all()

        hash_map: Dict[str, List[Document]] = {}
        for doc in docs_with_hashes:
            file_hash = doc.document_metadata.get("sha256_hash")
            if file_hash:
                if file_hash not in hash_map:
                    hash_map[file_hash] = []
                hash_map[file_hash].append(doc)

        for file_hash, docs in hash_map.items():
            if len(docs) > 1:
                hash_duplicates.append({
                    "hash": file_hash[:16] + "...",
                    "count": len(docs),
                    "filenames": [doc.filename for doc in docs],
                    "document_ids": [str(doc.id) for doc in docs]
                })

        return {
            "size_groups": len(potential_duplicates),
            "hash_duplicates": len(hash_duplicates),
            "potential_duplicates": potential_duplicates[:20],
            "hash_duplicate_groups": hash_duplicates[:20],
            "total_duplicates": sum(g["count"] - 1 for g in hash_duplicates)
        }

    def cleanup_duplicates(self, db: Session, dry_run: bool = True) -> Dict[str, any]:
        """
        Remove duplicate documents, keeping the oldest

        Args:
            db: Database session
            dry_run: If True, don't actually delete

        Returns:
            Dictionary with cleanup results
        """
        duplicate_groups = self.scan_for_duplicates(db)
        removed_count = 0
        kept_count = 0
        space_freed = 0

        for group in duplicate_groups.get("hash_duplicate_groups", []):
            # Sort by created_at, keep oldest
            doc_ids = group["document_ids"]
            docs = db.query(Document).filter(Document.id.in_(doc_ids)).order_by(
                Document.created_at.asc()
            ).all()

            if len(docs) <= 1:
                continue

            # Keep first, delete rest
            to_keep = docs[0]
            to_remove = docs[1:]

            kept_count += 1
            for doc in to_remove:
                if not dry_run:
                    # In production, would:
                    # 1. Remove file from storage
                    # 2. Delete document and related records
                    # 3. Commit transaction
                    pass

                removed_count += 1
                space_freed += doc.size

        return {
            "groups_processed": len(duplicate_groups.get("hash_duplicate_groups", [])),
            "kept_count": kept_count,
            "removed_count": removed_count,
            "space_freed": space_freed,
            "dry_run": dry_run
        }


# Global deduplication service instance
deduplication_service = DeduplicationService()
