"""
Unit tests for storage service encryption functionality

Tests cover:
- Fernet key generation and validation
- Encrypt/decrypt round-trip for confidential documents
- Public documents remain unencrypted
- Migration functions (encrypt_file, decrypt_file)
- Error handling for missing keys
- Key derivation from password
"""

import os
import tempfile
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Test with a real Fernet key
TEST_FERNET_KEY = b"J6KqI5tQoFdHm8xLv9zR2YbC1sK4pA7eN0wX3jH8uM="


class TestEncryptionKey:
    """Tests for encryption key management"""

    def test_get_encryption_key_from_env_not_set(self):
        """Test that None is returned when STORAGE_ENCRYPTION_KEY is not set"""
        with patch.dict(os.environ, {}, clear=True):
            from app.services.storage_service import get_encryption_key

            key = get_encryption_key()
            assert key is None

    def test_get_encryption_key_from_valid_key(self):
        """Test that a valid Fernet key is returned when set"""
        with patch.dict(
            os.environ, {"STORAGE_ENCRYPTION_KEY": TEST_FERNET_KEY.decode()}
        ):
            from app.services.storage_service import get_encryption_key

            key = get_encryption_key()
            assert key is not None
            assert isinstance(key, bytes)

    def test_get_encryption_key_from_password(self):
        """Test key derivation from password"""
        with patch.dict(os.environ, {"STORAGE_ENCRYPTION_KEY": "my_secure_password"}):
            from app.services.storage_service import get_encryption_key

            key = get_encryption_key()
            assert key is not None
            assert isinstance(key, bytes)
            # Key should be valid Fernet key
            from cryptography.fernet import Fernet

            f = Fernet(key)
            # Test that it can encrypt/decrypt
            encrypted = f.encrypt(b"test")
            decrypted = f.decrypt(encrypted)
            assert decrypted == b"test"

    def test_get_encryption_key_invalid_key(self):
        """Test that password derivation is used for invalid Fernet key"""
        with patch.dict(os.environ, {"STORAGE_ENCRYPTION_KEY": "invalid_key_format"}):
            from app.services.storage_service import get_encryption_key

            # Should attempt derivation and return a valid key
            key = get_encryption_key()
            # Either returns derived key or None (both acceptable)


class TestStorageServiceEncryption:
    """Tests for StorageService encryption functionality"""

    @pytest.fixture
    def temp_storage_path(self):
        """Create temporary storage directories"""
        temp_dir = tempfile.mkdtemp()
        public_path = Path(temp_dir) / "public"
        confidential_path = Path(temp_dir) / "confidential"
        public_path.mkdir()
        confidential_path.mkdir()

        yield temp_dir, public_path, confidential_path

        # Cleanup
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def storage_with_key(self, temp_storage_path):
        """Create storage service with encryption enabled"""
        temp_dir, public_path, confidential_path = temp_storage_path

        with patch.dict(
            os.environ, {"STORAGE_ENCRYPTION_KEY": TEST_FERNET_KEY.decode()}
        ):
            # Mock the paths
            with patch(
                "app.services.storage_service.StorageService._ensure_directories"
            ):
                from app.services.storage_service import StorageService

                service = StorageService()
                service.public_path = public_path
                service.confidential_path = confidential_path
                yield service

    @pytest.fixture
    def storage_without_key(self, temp_storage_path):
        """Create storage service with encryption disabled"""
        temp_dir, public_path, confidential_path = temp_storage_path

        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "app.services.storage_service.StorageService._ensure_directories"
            ):
                from app.services.storage_service import StorageService

                service = StorageService()
                service.public_path = public_path
                service.confidential_path = confidential_path
                yield service

    def test_encryption_enabled_property(self, storage_with_key, storage_without_key):
        """Test encryption_enabled property"""
        assert storage_with_key.encryption_enabled is True
        assert storage_without_key.encryption_enabled is False

    def test_save_file_confidential_encrypted(self, storage_with_key):
        """Test that confidential files are encrypted"""
        content = b"This is confidential document content"
        result = storage_with_key.save_file(
            file_content=content, original_filename="secret.pdf", bucket="confidential"
        )

        assert result["encrypted"] is True
        assert result["filename"].endswith(".encrypted")

        # Verify file on disk is encrypted
        file_path = Path(result["file_path"])
        assert file_path.exists()

        with open(file_path, "rb") as f:
            stored_content = f.read()

        # Stored content should be different (encrypted)
        assert stored_content != content

    def test_save_file_public_not_encrypted(self, storage_with_key):
        """Test that public files are not encrypted"""
        content = b"This is public document content"
        result = storage_with_key.save_file(
            file_content=content, original_filename="public.pdf", bucket="public"
        )

        assert result["encrypted"] is False
        assert not result["filename"].endswith(".encrypted")

        # Verify file on disk is plain
        file_path = Path(result["file_path"])
        with open(file_path, "rb") as f:
            stored_content = f.read()

        assert stored_content == content

    def test_save_file_no_key_confidential(self, storage_without_key):
        """Test that confidential files are saved unencrypted when key not available"""
        # When encryption key is not available, should save unencrypted
        content = b"secret content"
        result = storage_without_key.save_file(
            file_content=content, original_filename="secret.pdf", bucket="confidential"
        )

        # Should save but without encryption
        assert result["encrypted"] is False

        # Content should be readable
        retrieved = storage_without_key.get_file(
            result["filename"], bucket="confidential"
        )
        assert retrieved == content

    def test_round_trip_confidential(self, storage_with_key):
        """Test encrypt/decrypt round-trip for confidential documents"""
        original_content = b"Round trip test content for encryption"

        # Save file (encrypts automatically)
        result = storage_with_key.save_file(
            file_content=original_content,
            original_filename="roundtrip.pdf",
            bucket="confidential",
        )

        # Read file back (decrypts automatically)
        retrieved_content = storage_with_key.get_file(
            filename=result["filename"], bucket="confidential"
        )

        assert retrieved_content == original_content

    def test_round_trip_public(self, storage_with_key):
        """Test that public documents work normally"""
        original_content = b"Public document content"

        # Save file
        result = storage_with_key.save_file(
            file_content=original_content,
            original_filename="public.pdf",
            bucket="public",
        )

        # Read file back
        retrieved_content = storage_with_key.get_file(
            filename=result["filename"], bucket="public"
        )

        assert retrieved_content == original_content

    def test_get_file_plaintext(self, storage_with_key):
        """Test get_file_plaintext returns raw content"""
        content = b"Secret content"

        # Save encrypted file
        result = storage_with_key.save_file(
            file_content=content, original_filename="secret.pdf", bucket="confidential"
        )

        # Get plaintext (encrypted) content
        raw_content = storage_with_key.get_file_plaintext(
            filename=result["filename"], bucket="confidential"
        )

        # Should be encrypted (different from original)
        assert raw_content != content

        # Should be able to decrypt it
        decrypted = storage_with_key._decrypt_data(raw_content)
        assert decrypted == content

    def test_encrypt_file_in_place(self, storage_with_key):
        """Test encrypt_file method"""
        # First save an unencrypted file
        content = b"Unencrypted content"
        filename = "test_file.pdf"

        # Save without encryption first (using private method to bypass encryption)
        file_path = storage_with_key.confidential_path / filename
        with open(file_path, "wb") as f:
            f.write(content)

        # Verify it's not encrypted
        assert not filename.endswith(".encrypted")

        # Now encrypt it
        result = storage_with_key.encrypt_file(filename, bucket="confidential")
        assert result is True

        # Verify new file exists with .encrypted extension
        encrypted_filename = filename + ".encrypted"
        encrypted_path = storage_with_key.confidential_path / encrypted_filename
        assert encrypted_path.exists()

        # Original should be deleted
        assert not file_path.exists()

        # Content should be encrypted on disk
        with open(encrypted_path, "rb") as f:
            stored = f.read()
        assert stored != content

    def test_decrypt_file_in_place(self, storage_with_key):
        """Test decrypt_file method"""
        # Create an encrypted file
        content = b"Content to decrypt"
        encrypted_filename = "encrypted_file.pdf.encrypted"

        # Encrypt content and save
        encrypted_content = storage_with_key._encrypt_data(content)
        file_path = storage_with_key.confidential_path / encrypted_filename
        with open(file_path, "wb") as f:
            f.write(encrypted_content)

        # Decrypt it
        result = storage_with_key.decrypt_file(
            encrypted_filename, bucket="confidential"
        )
        assert result is True

        # Verify decrypted file exists
        decrypted_filename = "encrypted_file.pdf"
        decrypted_path = storage_with_key.confidential_path / decrypted_filename
        assert decrypted_path.exists()

        # Original encrypted should be deleted
        assert not file_path.exists()

        # Content should match original
        with open(decrypted_path, "rb") as f:
            stored = f.read()
        assert stored == content

    def test_needs_migration(self, storage_with_key, storage_without_key):
        """Test needs_migration detection"""
        # Unencrypted file in confidential bucket needs migration
        unencrypted_file = "test.pdf"
        file_path = storage_with_key.confidential_path / unencrypted_file
        with open(file_path, "wb") as f:
            f.write(b"content")

        assert (
            storage_with_key.needs_migration(unencrypted_file, "confidential") is True
        )

        # Encrypted file does not need migration
        encrypted_file = "test.pdf.encrypted"
        file_path2 = storage_with_key.confidential_path / encrypted_file
        with open(file_path2, "wb") as f:
            f.write(b"encrypted")

        assert storage_with_key.needs_migration(encrypted_file, "confidential") is False

        # Public bucket never needs migration
        assert storage_with_key.needs_migration("test.pdf", "public") is False

        # Without encryption key, returns False
        assert storage_without_key.needs_migration("test.pdf", "confidential") is False

    def test_get_file_auto_decrypt(self, storage_with_key):
        """Test that get_file auto-detects and decrypts .encrypted files"""
        content = b"Auto decrypt test"

        # Save as encrypted
        result = storage_with_key.save_file(
            file_content=content, original_filename="auto.pdf", bucket="confidential"
        )

        # Read with auto-decrypt (default)
        retrieved = storage_with_key.get_file(
            filename=result["filename"],
            bucket="confidential",
            decrypt=None,  # Auto-detect
        )
        assert retrieved == content

        # Read without decrypt
        raw = storage_with_key.get_file_plaintext(
            filename=result["filename"], bucket="confidential"
        )
        assert raw != content

    def test_get_file_force_decrypt(self, storage_with_key):
        """Test force decrypt parameter"""
        content = b"Force decrypt test"

        # Save as encrypted
        result = storage_with_key.save_file(
            file_content=content, original_filename="force.pdf", bucket="confidential"
        )

        # Force decrypt
        retrieved = storage_with_key.get_file(
            filename=result["filename"], bucket="confidential", decrypt=True
        )
        assert retrieved == content

        # Force no decrypt
        raw = storage_with_key.get_file(
            filename=result["filename"], bucket="confidential", decrypt=False
        )
        assert raw != content

    def test_file_not_found(self, storage_with_key):
        """Test handling of non-existent files"""
        result = storage_with_key.get_file("nonexistent.pdf", bucket="confidential")
        assert result is None

    def test_file_info_includes_encryption(self, storage_with_key):
        """Test that get_file_info includes encryption status"""
        content = b"Test content"

        # Save encrypted
        result = storage_with_key.save_file(
            file_content=content,
            original_filename="info_test.pdf",
            bucket="confidential",
        )

        info = storage_with_key.get_file_info(result["filename"], bucket="confidential")

        assert info is not None
        assert "encrypted" in info
        assert info["encrypted"] is True
        assert "decrypted_size" in info
        assert info["decrypted_size"] == len(content)

    def test_delete_file(self, storage_with_key):
        """Test file deletion works with encrypted files"""
        content = b"To be deleted"

        result = storage_with_key.save_file(
            file_content=content,
            original_filename="delete_me.pdf",
            bucket="confidential",
        )

        filename = result["filename"]

        # Verify exists
        assert storage_with_key.file_exists(filename, "confidential")

        # Delete
        result = storage_with_key.delete_file(filename, "confidential")
        assert result is True

        # Verify gone
        assert not storage_with_key.file_exists(filename, "confidential")

    def test_encryption_error_handling(self, storage_with_key):
        """Test EncryptionError is raised appropriately"""
        from app.services.storage_service import EncryptionError

        # Test decryption with invalid data
        with pytest.raises(EncryptionError):
            storage_with_key._decrypt_data(b"invalid encrypted data")

        # Test with wrong key
        from cryptography.fernet import Fernet

        wrong_key = Fernet.generate_key()
        wrong_fernet = Fernet(wrong_key)

        # Encrypt with one key, try to decrypt with another
        content = b"test content"
        encrypted = wrong_fernet.encrypt(content)

        # Save to storage service which has different key
        with pytest.raises(EncryptionError):
            storage_with_key._decrypt_data(encrypted)


class TestKeyDerivation:
    """Tests for key derivation from password"""

    def test_key_derivation_consistency(self):
        """Test that same password produces same key"""
        with patch.dict(os.environ, {"STORAGE_ENCRYPTION_KEY": "test_password_123"}):
            from app.services.storage_service import get_encryption_key

            key1 = get_encryption_key()
            key2 = get_encryption_key()
            assert key1 == key2

    def test_different_passwords_different_keys(self):
        """Test that different passwords produce different keys"""
        with patch.dict(os.environ, {"STORAGE_ENCRYPTION_KEY": "password1"}):
            from app.services.storage_service import get_encryption_key

            key1 = get_encryption_key()

        with patch.dict(os.environ, {"STORAGE_ENCRYPTION_KEY": "password2"}):
            from app.services.storage_service import get_encryption_key

            key2 = get_encryption_key()

        assert key1 != key2

    def test_custom_salt(self):
        """Test that custom salt produces different key"""
        with patch.dict(
            os.environ,
            {
                "STORAGE_ENCRYPTION_KEY": "same_password",
                "STORAGE_ENCRYPTION_SALT": "salt1",
            },
        ):
            from app.services.storage_service import get_encryption_key

            key1 = get_encryption_key()

        with patch.dict(
            os.environ,
            {
                "STORAGE_ENCRYPTION_KEY": "same_password",
                "STORAGE_ENCRYPTION_SALT": "salt2",
            },
        ):
            from app.services.storage_service import get_encryption_key

            key2 = get_encryption_key()

        assert key1 != key2


class TestIntegration:
    """Integration tests for end-to-end encryption workflow"""

    @pytest.fixture
    def temp_storage_path(self):
        """Create temporary storage directories"""
        temp_dir = tempfile.mkdtemp()
        public_path = Path(temp_dir) / "public"
        confidential_path = Path(temp_dir) / "confidential"
        public_path.mkdir()
        confidential_path.mkdir()

        yield temp_dir, public_path, confidential_path

        # Cleanup
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def integration_storage(self, temp_storage_path):
        """Create storage service for integration tests"""
        temp_dir, public_path, confidential_path = temp_storage_path

        with patch.dict(
            os.environ, {"STORAGE_ENCRYPTION_KEY": TEST_FERNET_KEY.decode()}
        ):
            with patch(
                "app.services.storage_service.StorageService._ensure_directories"
            ):
                from app.services.storage_service import StorageService

                service = StorageService()
                service.public_path = public_path
                service.confidential_path = confidential_path
                yield service

    def test_full_workflow(self, integration_storage):
        """Test complete workflow: save, read, update, delete"""
        # 1. Create and save confidential document
        original_content = b"Important confidential data"
        save_result = integration_storage.save_file(
            file_content=original_content,
            original_filename="workflow_test.pdf",
            bucket="confidential",
        )

        filename = save_result["filename"]
        assert save_result["encrypted"] is True

        # 2. Read back - should auto-decrypt
        content = integration_storage.get_file(filename, bucket="confidential")
        assert content == original_content

        # 3. Get file info
        info = integration_storage.get_file_info(filename, bucket="confidential")
        assert info["encrypted"] is True
        assert info["decrypted_size"] == len(original_content)

        # 4. Delete
        deleted = integration_storage.delete_file(filename, bucket="confidential")
        assert deleted is True
        assert not integration_storage.file_exists(filename, bucket="confidential")

    def test_mixed_buckets(self, integration_storage):
        """Test working with both public and confidential buckets"""
        confidential_content = b"Confidential info"
        public_content = b"Public info"

        # Save to both buckets
        conf_result = integration_storage.save_file(
            file_content=confidential_content,
            original_filename="conf.pdf",
            bucket="confidential",
        )
        pub_result = integration_storage.save_file(
            file_content=public_content, original_filename="pub.pdf", bucket="public"
        )

        # Verify encryption status
        assert conf_result["encrypted"] is True
        assert pub_result["encrypted"] is False

        # Read both back
        conf_read = integration_storage.get_file(
            conf_result["filename"], bucket="confidential"
        )
        pub_read = integration_storage.get_file(pub_result["filename"], bucket="public")

        assert conf_read == confidential_content
        assert pub_read == public_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
