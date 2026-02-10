"""
File storage service for managing document buckets
"""
import os
import uuid
from pathlib import Path
from typing import Optional
import shutil
from datetime import datetime


class StorageService:
    """Service for managing file storage in public and confidential buckets"""

    def __init__(self):
        # Base storage paths
        self.base_path = Path("/data")
        self.public_path = self.base_path / "public"
        self.confidential_path = self.base_path / "confidential"

        # Create directories if they don't exist
        self._ensure_directories()

    def _ensure_directories(self):
        """Ensure storage directories exist"""
        self.public_path.mkdir(parents=True, exist_ok=True)
        self.confidential_path.mkdir(parents=True, exist_ok=True)

    def get_bucket_path(self, bucket: str) -> Path:
        """Get the path for a specific bucket"""
        if bucket == "confidential":
            return self.confidential_path
        return self.public_path

    def generate_filename(self, original_filename: str) -> str:
        """Generate a unique filename while preserving extension"""
        # Get file extension
        extension = Path(original_filename).suffix
        # Generate unique identifier
        unique_id = str(uuid.uuid4())
        # Add timestamp for better organization
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        # Combine: timestamp_uuid + extension
        return f"{timestamp}_{unique_id}{extension}"

    def save_file(
        self,
        file_content: bytes,
        original_filename: str,
        bucket: str = "public"
    ) -> dict:
        """
        Save a file to the specified bucket

        Args:
            file_content: File content as bytes
            original_filename: Original filename
            bucket: Either "public" or "confidential"

        Returns:
            dict with filename, file_path, and size
        """
        # Generate unique filename
        filename = self.generate_filename(original_filename)

        # Get bucket path
        bucket_path = self.get_bucket_path(bucket)
        file_path = bucket_path / filename

        # Write file
        with open(file_path, "wb") as f:
            f.write(file_content)

        # Get file size
        size = len(file_content)

        return {
            "filename": filename,
            "file_path": str(file_path),
            "size": size
        }

    def delete_file(self, filename: str, bucket: str = "public") -> bool:
        """
        Delete a file from the specified bucket

        Args:
            filename: Filename to delete
            bucket: Either "public" or "confidential"

        Returns:
            True if deleted, False otherwise
        """
        try:
            bucket_path = self.get_bucket_path(bucket)
            file_path = bucket_path / filename

            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error deleting file {filename}: {str(e)}")
            return False

    def get_file(self, filename: str, bucket: str = "public") -> Optional[bytes]:
        """
        Get file content from the specified bucket

        Args:
            filename: Filename to retrieve
            bucket: Either "public" or "confidential"

        Returns:
            File content as bytes or None if not found
        """
        try:
            bucket_path = self.get_bucket_path(bucket)
            file_path = bucket_path / filename

            if file_path.exists():
                with open(file_path, "rb") as f:
                    return f.read()
            return None
        except Exception as e:
            print(f"Error reading file {filename}: {str(e)}")
            return None

    def file_exists(self, filename: str, bucket: str = "public") -> bool:
        """Check if a file exists in the specified bucket"""
        bucket_path = self.get_bucket_path(bucket)
        file_path = bucket_path / filename
        return file_path.exists()

    def get_file_info(self, filename: str, bucket: str = "public") -> Optional[dict]:
        """Get file information"""
        try:
            bucket_path = self.get_bucket_path(bucket)
            file_path = bucket_path / filename

            if file_path.exists():
                stat = file_path.stat()
                return {
                    "filename": filename,
                    "file_path": str(file_path),
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime)
                }
            return None
        except Exception as e:
            print(f"Error getting file info {filename}: {str(e)}")
            return None


# Global storage service instance
storage_service = StorageService()
