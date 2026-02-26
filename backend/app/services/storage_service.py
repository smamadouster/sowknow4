"""
File storage service for managing document buckets with at-rest encryption for confidential documents
"""

import base64
import os
import uuid
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class EncryptionError(Exception):
    """Raised when encryption or decryption fails"""

    pass


def _base64_encode(data: bytes) -> bytes:
    """Base64 encode data to be compatible with Fernet key format"""
    return base64.urlsafe_b64encode(data.ljust(32, b"\0")[:32])


def get_encryption_key() -> Optional[bytes]:
    """
    Get encryption key from environment variable or derive from password.

    STORAGE_ENCRYPTION_KEY can be:
    - A valid Fernet key (base64 encoded 32 bytes)
    - A password string that will be derived into a key using PBKDF2
    - Empty or not set (encryption disabled for development)

    Returns:
        Fernet key bytes or None if not configured
    """
    key = os.getenv("STORAGE_ENCRYPTION_KEY")
    if not key:
        logger.warning(
            "STORAGE_ENCRYPTION_KEY not set - confidential encryption disabled"
        )
        return None

    try:
        # Validate it's a proper Fernet key
        Fernet(key)
        return key
    except Exception:
        # Try to treat as password and derive key
        try:
            salt = os.getenv("STORAGE_ENCRYPTION_SALT", "sowknow_default_salt")
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt.encode(),
                iterations=100000,
            )
            derived_key = _base64_encode(kdf.derive(key.encode()))
            return derived_key
        except Exception as e:
            logger.error(f"Failed to derive encryption key: {e}")
            return None


class StorageService:
    """Service for managing file storage in public and confidential buckets

    Confidential documents are encrypted at rest using Fernet symmetric encryption.
    The encryption key is configured via STORAGE_ENCRYPTION_KEY environment variable.
    """

    def __init__(self):
        # Base storage paths
        self.base_path = Path("/data")
        self.public_path = self.base_path / "public"
        self.confidential_path = self.base_path / "confidential"

        # Initialize encryption
        self._fernet: Optional[Fernet] = None
        self._init_encryption()

        # Create directories if they don't exist
        self._ensure_directories()

    def _init_encryption(self):
        """Initialize Fernet encryption from environment variable"""
        key = get_encryption_key()
        if key:
            try:
                self._fernet = Fernet(key)
                logger.info("Fernet encryption initialized for confidential documents")
            except Exception as e:
                logger.error(f"Failed to initialize Fernet: {e}")
                self._fernet = None
        else:
            logger.warning(
                "Encryption disabled - STORAGE_ENCRYPTION_KEY not configured"
            )
            self._fernet = None

    @property
    def encryption_enabled(self) -> bool:
        """Check if encryption is enabled"""
        return self._fernet is not None

    def _ensure_directories(self):
        """Ensure storage directories exist"""
        self.public_path.mkdir(parents=True, exist_ok=True)
        self.confidential_path.mkdir(parents=True, exist_ok=True)

    def _encrypt_data(self, data: bytes) -> bytes:
        """Encrypt data using Fernet

        Args:
            data: Plaintext bytes to encrypt

        Returns:
            Encrypted bytes (Fernet token)

        Raises:
            EncryptionError: If encryption fails
        """
        if not self._fernet:
            raise EncryptionError("Encryption not initialized")

        try:
            return self._fernet.encrypt(data)
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise EncryptionError(f"Failed to encrypt data: {e}")

    def _decrypt_data(self, data: bytes) -> bytes:
        """Decrypt data using Fernet

        Args:
            data: Encrypted bytes (Fernet token) to decrypt

        Returns:
            Decrypted plaintext bytes

        Raises:
            EncryptionError: If decryption fails
        """
        if not self._fernet:
            raise EncryptionError("Encryption not initialized")

        try:
            return self._fernet.decrypt(data)
        except InvalidToken as e:
            logger.error(f"Decryption failed - invalid token: {e}")
            raise EncryptionError("Failed to decrypt data - invalid token or key")
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise EncryptionError(f"Failed to decrypt data: {e}")

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

    def _is_encrypted_file(self, filename: str) -> bool:
        """Check if a file should be encrypted based on filename pattern

        Encrypted files are identified by the .encrypted extension added
        during the encryption migration process.
        """
        return filename.endswith(".encrypted")

    def save_file(
        self,
        file_content: bytes,
        original_filename: str,
        bucket: str = "public",
        force_encrypt: bool = False,
    ) -> dict:
        """
        Save a file to the specified bucket

        Args:
            file_content: File content as bytes
            original_filename: Original filename
            bucket: Either "public" or "confidential"
            force_encrypt: Force encryption even for public bucket (for migration)

        Returns:
            dict with filename, file_path, size, and encryption status
        """
        # Generate unique filename
        filename = self.generate_filename(original_filename)

        # Get bucket path
        bucket_path = self.get_bucket_path(bucket)

        # Determine if we should encrypt
        encrypt = (
            bucket == "confidential" and self._fernet is not None
        ) or force_encrypt

        if encrypt:
            if not self._fernet:
                raise EncryptionError("Cannot encrypt - encryption key not available")

            try:
                file_content = self._encrypt_data(file_content)
                # Add .encrypted extension to indicate encrypted content
                filename = filename + ".encrypted"
            except EncryptionError:
                raise

        file_path = bucket_path / filename

        # Write file
        with open(file_path, "wb") as f:
            f.write(file_content)

        # Get file size
        size = len(file_content)

        return {
            "filename": filename,
            "file_path": str(file_path),
            "size": size,
            "encrypted": encrypt,
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
            logger.error(f"Error deleting file {filename}: {str(e)}")
            return False

    def get_file(
        self, filename: str, bucket: str = "public", decrypt: bool = None
    ) -> Optional[bytes]:
        """
        Get file content from the specified bucket

        Args:
            filename: Filename to retrieve
            bucket: Either "public" or "confidential"
            decrypt: If True, force decryption; if False, skip decryption;
                    if None, auto-detect based on bucket and .encrypted extension

        Returns:
            File content as bytes or None if not found
        """
        try:
            bucket_path = self.get_bucket_path(bucket)
            file_path = bucket_path / filename

            if file_path.exists():
                with open(file_path, "rb") as f:
                    content = f.read()

                # Determine if decryption is needed
                should_decrypt = decrypt
                if should_decrypt is None:
                    # Auto-detect: decrypt confidential files and any .encrypted file
                    should_decrypt = (
                        bucket == "confidential" or filename.endswith(".encrypted")
                    ) and self._fernet is not None

                if should_decrypt and content:
                    try:
                        content = self._decrypt_data(content)
                    except EncryptionError as e:
                        logger.error(f"Failed to decrypt {filename}: {e}")
                        # Return original content if decryption fails
                        # This handles migration edge cases
                        pass

                return content
            return None
        except Exception as e:
            logger.error(f"Error reading file {filename}: {str(e)}")
            return None

    def get_file_plaintext(
        self, filename: str, bucket: str = "public"
    ) -> Optional[bytes]:
        """Get file content without decryption (for migration/testing)

        Args:
            filename: Filename to retrieve
            bucket: Either "public" or "confidential"

        Returns:
            Raw file content as bytes (possibly encrypted)
        """
        try:
            bucket_path = self.get_bucket_path(bucket)
            file_path = bucket_path / filename

            if file_path.exists():
                with open(file_path, "rb") as f:
                    return f.read()
            return None
        except Exception as e:
            logger.error(f"Error reading file {filename}: {str(e)}")
            return None

    def encrypt_file(self, filename: str, bucket: str = "confidential") -> bool:
        """
        Encrypt an existing file in place (for migration)

        Args:
            filename: Filename to encrypt
            bucket: Bucket containing the file

        Returns:
            True if successful, False otherwise
        """
        if bucket != "confidential":
            logger.warning(f"encrypt_file called for non-confidential bucket: {bucket}")
            return False

        if not self._fernet:
            logger.error("Cannot encrypt - encryption not initialized")
            return False

        try:
            # Read plain file
            content = self.get_file_plaintext(filename, bucket)
            if content is None:
                logger.error(f"File not found: {filename}")
                return False

            # Check if already encrypted
            if filename.endswith(".encrypted"):
                logger.info(f"File already encrypted: {filename}")
                return True

            # Encrypt and save with .encrypted extension
            encrypted_filename = filename + ".encrypted"
            encrypted_content = self._encrypt_data(content)

            bucket_path = self.get_bucket_path(bucket)
            new_path = bucket_path / encrypted_filename

            with open(new_path, "wb") as f:
                f.write(encrypted_content)

            # Delete original unencrypted file
            old_path = bucket_path / filename
            old_path.unlink()

            logger.info(f"Encrypted file: {filename} -> {encrypted_filename}")
            return True

        except Exception as e:
            logger.error(f"Failed to encrypt file {filename}: {e}")
            return False

    def decrypt_file(self, filename: str, bucket: str = "confidential") -> bool:
        """
        Decrypt an existing file in place (for migration rollback)

        Args:
            filename: Filename to decrypt
            bucket: Bucket containing the file

        Returns:
            True if successful, False otherwise
        """
        if not self._fernet:
            logger.error("Cannot decrypt - encryption not initialized")
            return False

        try:
            # Read encrypted file
            content = self.get_file_plaintext(filename, bucket)
            if content is None:
                logger.error(f"File not found: {filename}")
                return False

            # Check if file is encrypted
            if not filename.endswith(".encrypted"):
                logger.info(f"File not encrypted: {filename}")
                return True

            # Decrypt and save without .encrypted extension
            decrypted_filename = filename.replace(".encrypted", "")
            decrypted_content = self._decrypt_data(content)

            bucket_path = self.get_bucket_path(bucket)
            new_path = bucket_path / decrypted_filename

            with open(new_path, "wb") as f:
                f.write(decrypted_content)

            # Delete original encrypted file
            old_path = bucket_path / filename
            old_path.unlink()

            logger.info(f"Decrypted file: {filename} -> {decrypted_filename}")
            return True

        except Exception as e:
            logger.error(f"Failed to decrypt file {filename}: {e}")
            return False

    def needs_migration(self, filename: str, bucket: str = "confidential") -> bool:
        """Check if a file needs encryption migration

        Args:
            filename: Filename to check
            bucket: Bucket containing the file

        Returns:
            True if file needs encryption migration
        """
        if bucket != "confidential":
            return False

        # Needs migration if not encrypted and encryption is enabled
        if not self._fernet:
            return False

        return not filename.endswith(".encrypted")

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
                is_encrypted = filename.endswith(".encrypted")

                info = {
                    "filename": filename,
                    "file_path": str(file_path),
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime),
                    "encrypted": is_encrypted,
                }

                # Only include decrypted size if encrypted and we can decrypt
                if is_encrypted and self._fernet:
                    content = self.get_file_plaintext(filename, bucket)
                    if content:
                        try:
                            decrypted = self._decrypt_data(content)
                            info["decrypted_size"] = len(decrypted)
                        except EncryptionError:
                            pass

                return info
            return None
        except Exception as e:
            logger.error(f"Error getting file info {filename}: {str(e)}")
            return None


# Global storage service instance
storage_service = StorageService()
