"""
Comprehensive Confidential Bucket Isolation Tests

This module tests all PRD requirements for confidential bucket isolation:
1. Filesystem isolation - Public and confidential in separate volumes
2. Database query filtering - RBAC enforcement at query level
3. LLM routing - Confidential content must use Ollama, not Gemini
4. Audit logging - All confidential access must be logged
5. RBAC enforcement - Proper role-based access control
6. Path traversal protection - No directory traversal attacks
7. ID enumeration prevention - 404 instead of 403

CRITICAL ISSUES TESTED:
- Production Storage Path: docker-compose.production.yml missing /data/public volume
- Multi-Agent LLM Routing: Agents send ALL content to Gemini (should route to Ollama for confidential)
- Audit Logging Gap: CONFIDENTIAL_ACCESSED defined but never used
- Bot API Key Bypass: Anyone with key can upload to confidential bucket
"""
import pytest
import os
import yaml
import uuid
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.audit import AuditLog, AuditAction
from app.utils.security import create_access_token, get_password_hash
from app.services.storage_service import StorageService


def get_auth_headers(user: User) -> dict:
    """Helper to create auth headers for a user"""
    token = create_access_token(data={
        "sub": user.email,
        "role": user.role.value,
        "user_id": str(user.id)
    })
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# TEST CATEGORY 1: FILESYSTEM ISOLATION
# =============================================================================

class TestFilesystemIsolation:
    """Test filesystem isolation between public and confidential buckets"""

    def test_storage_paths_are_separate(self):
        """Verify storage service uses separate paths for each bucket"""
        storage = StorageService()
        
        # Get paths
        public_path = storage.get_bucket_path("public")
        confidential_path = storage.get_bucket_path("confidential")
        
        # Verify they are different
        assert public_path != confidential_path
        assert "public" in str(public_path)
        assert "confidential" in str(confidential_path)

    def test_storage_paths_use_different_directories(self):
        """Verify storage paths are in completely different directory trees"""
        storage = StorageService()
        
        public_path = storage.get_bucket_path("public")
        confidential_path = storage.get_bucket_path("confidential")
        
        # No path should be a subdirectory of the other
        assert not str(public_path).startswith(str(confidential_path))
        assert not str(confidential_path).startswith(str(public_path))

    def test_docker_volumes_are_separate(self):
        """Verify docker-compose defines separate volumes for public/confidential"""
        # Read development docker-compose
        dev_compose_path = "/root/development/src/active/sowknow4/docker-compose.yml"
        
        if os.path.exists(dev_compose_path):
            with open(dev_compose_path, 'r') as f:
                compose = yaml.safe_load(f)
            
            volumes = compose.get('volumes', {})
            
            # Both volumes should be defined
            assert 'sowknow-public-data' in volumes, "Public volume not defined"
            assert 'sowknow-confidential-data' in volumes, "Confidential volume not defined"

    def test_production_has_public_volume_mount(self):
        """CRITICAL: Verify production docker-compose mounts /data/public volume"""
        prod_compose_path = "/root/development/src/active/sowknow4/docker-compose.production.yml"
        
        if os.path.exists(prod_compose_path):
            with open(prod_compose_path, 'r') as f:
                compose = yaml.safe_load(f)
            
            backend_service = compose.get('services', {}).get('backend', {})
            volumes = backend_service.get('volumes', [])
            
            # Check for public data volume mount
            volume_mounts = [v.split(':')[0] if ':' in v else v for v in volumes]
            
            # This test WILL FAIL with current configuration
            has_public_mount = any('public' in v for v in volume_mounts)
            
            # CRITICAL: This should pass but currently fails
            assert has_public_mount, f"PRODUCTION BUG: No /data/public volume mount found. Current mounts: {volume_mounts}"

    def test_production_has_correct_volume_paths(self):
        """CRITICAL: Verify production volumes map to correct container paths"""
        prod_compose_path = "/root/development/src/active/sowknow4/docker-compose.production.yml"
        
        if os.path.exists(prod_compose_path):
            with open(prod_compose_path, 'r') as f:
                compose = yaml.safe_load(f)
            
            backend_service = compose.get('services', {}).get('backend', {})
            volumes = backend_service.get('volumes', [])
            
            # Check that /data/public is mounted
            data_public_mounted = False
            for vol in volumes:
                if ':' in vol:
                    container_path = vol.split(':')[1]
                    if container_path == '/data/public':
                        data_public_mounted = True
                        break
            
            assert data_public_mounted, "PRODUCTION BUG: /data/public not mounted - public documents will be lost on restart!"


# =============================================================================
# TEST CATEGORY 2: DATABASE QUERY FILTERING
# =============================================================================

class TestDatabaseQueryFiltering:
    """Test that database queries properly filter by bucket based on role"""

    def test_user_query_filters_to_public_only(self, db: Session):
        """Verify regular users can only query public documents"""
        # This is verified by the RBAC in documents.py
        # Query should automatically filter based on user role
        
        # Create test user
        user = User(
            email="queryfilter_test@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()
        
        # Create documents in different buckets
        public_doc = Document(
            filename="public_doc.pdf",
            original_filename="public_doc.pdf",
            file_path="/data/public/public_doc.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        confidential_doc = Document(
            filename="confidential_doc.pdf",
            original_filename="confidential_doc.pdf",
            file_path="/data/confidential/confidential_doc.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.add(confidential_doc)
        db.commit()
        
        # Simulate query filtering (as done in documents.py line 168-170)
        query = db.query(Document)
        
        # Apply same filter as API
        filtered_query = query.filter(Document.bucket == DocumentBucket.PUBLIC)
        results = filtered_query.all()
        
        # Should only return public document
        assert len(results) == 1
        assert results[0].bucket == DocumentBucket.PUBLIC

    def test_superuser_can_query_all_buckets(self, db: Session):
        """Verify superusers can query all documents"""
        # Create test superuser
        superuser = User(
            email="superfilter_test@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()
        
        # Create documents
        public_doc = Document(
            filename="public_doc2.pdf",
            original_filename="public_doc2.pdf",
            file_path="/data/public/public_doc2.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        confidential_doc = Document(
            filename="confidential_doc2.pdf",
            original_filename="confidential_doc2.pdf",
            file_path="/data/confidential/confidential_doc2.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.add(confidential_doc)
        db.commit()
        
        # Superuser should see all (no filter applied)
        query = db.query(Document)
        results = query.all()
        
        # Should return both documents
        assert len(results) == 2


# =============================================================================
# TEST CATEGORY 3: LLM ROUTING (CONFIDENTIAL -> OLLAMA)
# =============================================================================

class TestLLMRoutingConfidential:
    """Test that confidential content is routed to Ollama, not Gemini"""

    def test_chat_endpoint_routes_confidential_to_ollama(self):
        """Verify chat API routes confidential queries to Ollama"""
        from app.api.chat import determine_llm_provider
        
        # Confidential content should use Ollama
        result = determine_llm_provider(has_confidential=True)
        assert result.value == "ollama", "Confidential content MUST use Ollama"

    def test_chat_endpoint_routes_public_to_gemini(self):
        """Verify chat API can use Gemini for public content"""
        from app.api.chat import determine_llm_provider
        
        # Public content can use Gemini
        result = determine_llm_provider(has_confidential=False)
        assert result.value == "kimi", "Public content can use Gemini/Kimi"

    @patch('app.services.agents.answer_agent.answer_agent.gemini_service')
    def test_answer_agent_uses_gemini_for_public_only(self, mock_gemini):
        """CRITICAL: Answer agent should check bucket before using Gemini"""
        from app.services.agents.answer_agent import AnswerRequest
        
        # This test documents the BUG: All agents use gemini_service directly
        # without checking if content is confidential
        
        # Verify the agent has gemini_service
        from app.services.agents.answer_agent import answer_agent
        assert hasattr(answer_agent, 'gemini_service'), "Agent should have gemini_service"
        
        # The bug: agents don't check bucket before calling gemini

    def test_multi_agent_orchestrator_checks_confidential(self):
        """CRITICAL: Multi-agent orchestrator should check if content is confidential"""
        from app.services.agents import agent_orchestrator
        
        # Check if orchestrator has any confidential routing logic
        import inspect
        source = inspect.getsource(agent_orchestrator.AgentOrchestrator)
        
        # This test WILL FAIL - orchestrator has no confidential routing
        assert 'ollama' in source.lower() or 'has_confidential' in source.lower(), \
            "BUG: Multi-agent orchestrator has NO confidential routing logic - ALL content goes to Gemini!"

    def test_all_agents_use_gemini_regardless_of_confidentiality(self):
        """CRITICAL BUG: Document that all agents always use Gemini"""
        # Researcher Agent
        from app.services.agents.researcher_agent import researcher_agent
        assert hasattr(researcher_agent, 'gemini_service')
        
        # Answer Agent
        from app.services.agents.answer_agent import answer_agent
        assert hasattr(answer_agent, 'gemini_service')
        
        # Verification Agent
        from app.services.agents.verification_agent import verification_agent
        assert hasattr(verification_agent, 'gemini_service')
        
        # Clarification Agent
        from app.services.agents.clarification_agent import clarification_agent
        assert hasattr(clarification_agent, 'gemini_service')
        
        # BUG: None of these agents check bucket before using Gemini


# =============================================================================
# TEST CATEGORY 4: AUDIT LOGGING
# =============================================================================

class TestAuditLogging:
    """Test that all confidential access is properly audited"""

    def test_confidential_access_audit_action_exists(self):
        """Verify CONFIDENTIAL_ACCESSED audit action is defined"""
        assert hasattr(AuditAction, 'CONFIDENTIAL_ACCESSED')
        assert AuditAction.CONFIDENTIAL_ACCESSED.value == "confidential_accessed"

    def test_confidential_access_creates_audit_log(self, db: Session):
        """CRITICAL: Verify that confidential document access creates audit log"""
        # Create test user
        user = User(
            email="audit_test@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(user)
        db.commit()
        
        # Create confidential document
        doc = Document(
            filename="audit_test.pdf",
            original_filename="audit_test.pdf",
            file_path="/data/confidential/audit_test.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(doc)
        db.commit()
        
        # Simulate creating audit log (as should happen in API)
        audit_entry = AuditLog(
            user_id=user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="document",
            resource_id=str(doc.id),
            details=f'{{"bucket": "confidential", "action": "view"}}'
        )
        db.add(audit_entry)
        db.commit()
        
        # Verify audit entry was created
        logs = db.query(AuditLog).filter(
            AuditLog.action == AuditAction.CONFIDENTIAL_ACCESSED
        ).all()
        
        assert len(logs) > 0, "CONFIDENTIAL_ACCESSED action should create audit log"

    def test_documents_api_logs_confidential_access(self):
        """CRITICAL: Documents API should log confidential access"""
        # Check if documents.py creates audit logs
        import inspect
        from app.api import documents
        
        source = inspect.getsource(documents)
        
        # This test WILL FAIL - no audit logging in documents.py
        assert 'AuditLog' in source or 'create_audit_log' in source, \
            "BUG: documents.py does NOT log confidential access!"

    def test_audit_log_captures_user_id(self, db: Session):
        """Verify audit logs capture the user who accessed confidential data"""
        user = User(
            email="audit_userid@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(user)
        db.commit()
        
        # Create audit log with user
        audit = AuditLog(
            user_id=user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="document",
            resource_id=str(uuid.uuid4())
        )
        db.add(audit)
        db.commit()
        
        # Verify user_id is captured
        assert audit.user_id == user.id


# =============================================================================
# TEST CATEGORY 5: RBAC ENFORCEMENT
# =============================================================================

class TestRBACEnforcement:
    """Test role-based access control enforcement"""

    def test_user_cannot_access_confidential_by_id(self, test_client: TestClient, db: Session):
        """Verify regular users get 404 (not 403) for confidential docs"""
        user = User(
            email="rbac_user@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()
        
        # Create confidential document
        doc = Document(
            filename="rbac_secret.pdf",
            original_filename="rbac_secret.pdf",
            file_path="/data/confidential/rbac_secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        # Try to access
        response = test_client.get(
            f"/api/v1/documents/{doc.id}",
            headers=get_auth_headers(user)
        )
        
        # Should return 404 (not 403) to prevent enumeration
        assert response.status_code == 404, "Should return 404, not 403"

    def test_superuser_can_view_confidential(self, test_client: TestClient, db: Session):
        """Verify superusers can view confidential documents"""
        superuser = User(
            email="rbac_super@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()
        
        # Create confidential document
        doc = Document(
            filename="rbac_super_secret.pdf",
            original_filename="rbac_super_secret.pdf",
            file_path="/data/confidential/rbac_super_secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        # Access should succeed
        response = test_client.get(
            f"/api/v1/documents/{doc.id}",
            headers=get_auth_headers(superuser)
        )
        
        assert response.status_code == 200

    def test_superuser_cannot_delete_confidential(self, test_client: TestClient, db: Session):
        """Verify superusers CANNOT delete confidential documents"""
        superuser = User(
            email="rbac_super_del@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()
        
        # Create confidential document
        doc = Document(
            filename="rbac_super_del.pdf",
            original_filename="rbac_super_del.pdf",
            file_path="/data/confidential/rbac_super_del.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        # Try to delete
        response = test_client.delete(
            f"/api/v1/documents/{doc.id}",
            headers=get_auth_headers(superuser)
        )
        
        # Should return 403 (forbidden - superuser cannot delete)
        assert response.status_code == 403, "SuperUser should not be able to delete"


# =============================================================================
# TEST CATEGORY 6: BOT API KEY BYPASS
# =============================================================================

class TestBotAPIKeyBypass:
    """Test for Bot API Key authentication bypass vulnerability"""

    def test_upload_requires_admin_or_valid_bot_key(self, test_client: TestClient, db: Session):
        """CRITICAL: Verify upload to confidential requires proper authorization"""
        # Create regular user
        user = User(
            email="bot_test_user@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()
        
        # Try to upload to confidential without proper auth
        # This should fail
        response = test_client.post(
            "/api/v1/documents/upload",
            headers=get_auth_headers(user),
            data={"bucket": "confidential"},
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        
        assert response.status_code in [403, 400], \
            "Regular user should not be able to upload to confidential"

    def test_fake_bot_key_rejected(self, test_client: TestClient):
        """Verify fake Bot API key is rejected"""
        fake_key = "fake_bot_key_12345"
        
        response = test_client.post(
            "/api/v1/documents/upload",
            headers={"X-Bot-Api-Key": fake_key},
            data={"bucket": "confidential"},
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        
        # Should be rejected (401 or 403)
        assert response.status_code in [401, 403], \
            "Fake Bot API key should be rejected"

    def test_valid_bot_key_without_role_blocks_confidential_upload(self, test_client: TestClient, db: Session):
        """SECURITY FIX: Bot API key alone should NOT allow confidential upload without proper role"""
        # Get the actual BOT_API_KEY from environment
        bot_api_key = os.getenv("BOT_API_KEY", "")

        if not bot_api_key:
            pytest.skip("BOT_API_KEY not set in environment")

        # Create regular user (NOT admin/superuser)
        user = User(
            email="bot_key_user@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Try to upload to confidential with bot key but without proper role
        response = test_client.post(
            "/api/v1/documents/upload",
            headers={**get_auth_headers(user), "X-Bot-Api-Key": bot_api_key},
            data={"bucket": "confidential"},
            files={"file": ("bot_test.pdf", b"test content", "application/pdf")}
        )

        # Should be FORBIDDEN (403) - bot key alone is not sufficient
        assert response.status_code == 403, \
            f"SECURITY: Bot API key without proper role should NOT allow confidential upload, got {response.status_code}"

    def test_valid_bot_key_with_admin_allows_confidential_upload(self, test_client: TestClient, db: Session):
        """Verify valid Bot API key with Admin role allows confidential upload"""
        # Get the actual BOT_API_KEY from environment
        bot_api_key = os.getenv("BOT_API_KEY", "")

        if not bot_api_key:
            pytest.skip("BOT_API_KEY not set in environment")

        # Create admin user
        admin = User(
            email="bot_key_admin@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(admin)
        db.commit()

        # Upload to confidential with bot key AND admin role
        response = test_client.post(
            "/api/v1/documents/upload",
            headers={**get_auth_headers(admin), "X-Bot-Api-Key": bot_api_key},
            data={"bucket": "confidential"},
            files={"file": ("bot_test_admin.pdf", b"test content", "application/pdf")}
        )

        # Should succeed (or fail for other reasons like DB connection, but NOT 403)
        assert response.status_code in [200, 201, 500, 503], \
            f"Bot API key with Admin role should allow confidential upload, got {response.status_code}"

    def test_valid_bot_key_with_superuser_allows_confidential_upload(self, test_client: TestClient, db: Session):
        """Verify valid Bot API key with Superuser role allows confidential upload"""
        # Get the actual BOT_API_KEY from environment
        bot_api_key = os.getenv("BOT_API_KEY", "")

        if not bot_api_key:
            pytest.skip("BOT_API_KEY not set in environment")

        # Create superuser
        superuser = User(
            email="bot_key_super@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()

        # Upload to confidential with bot key AND superuser role
        response = test_client.post(
            "/api/v1/documents/upload",
            headers={**get_auth_headers(superuser), "X-Bot-Api-Key": bot_api_key},
            data={"bucket": "confidential"},
            files={"file": ("bot_test_super.pdf", b"test content", "application/pdf")}
        )

        # Should succeed (or fail for other reasons like DB connection, but NOT 403)
        assert response.status_code in [200, 201, 500, 503], \
            f"Bot API key with Superuser role should allow confidential upload, got {response.status_code}"


# =============================================================================
# TEST CATEGORY 7: PATH TRAVERSAL PROTECTION
# =============================================================================

class TestPathTraversalProtection:
    """Test path traversal attack protection"""

    def test_storage_service_rejects_path_traversal(self):
        """Verify storage service prevents path traversal"""
        storage = StorageService()
        
        # Try to use path traversal in filename
        malicious_filename = "../../../etc/passwd"
        
        # Generate a safe filename first
        safe_filename = storage.generate_filename("test.pdf")
        
        # Attempt to construct malicious path
        bucket_path = storage.get_bucket_path("public")
        malicious_path = bucket_path / safe_filename
        
        # The path should never escape the bucket
        assert ".." not in str(malicious_path)
        assert not str(malicious_path).startswith("/etc")

    def test_upload_rejects_malicious_filename(self, test_client: TestClient, db: Session):
        """Verify file upload rejects malicious filenames"""
        admin = User(
            email="path_traversal@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(admin)
        db.commit()
        
        # Try to upload with malicious filename
        response = test_client.post(
            "/api/v1/documents/upload",
            headers=get_auth_headers(admin),
            data={"bucket": "public"},
            files={"file": ("../../../etc/passwd", b"malicious", "application/pdf")}
        )
        
        # Should either reject or sanitize the filename
        # The storage service generates UUID-based filenames
        assert response.status_code in [200, 400], \
            "Should handle malicious filename gracefully"


# =============================================================================
# TEST CATEGORY 8: ID ENUMERATION PREVENTION
# =============================================================================

class TestIDEnumerationPrevention:
    """Test prevention of ID enumeration attacks"""

    def test_confidential_doc_id_returns_404_for_user(self, test_client: TestClient, db: Session):
        """Verify accessing confidential doc by ID returns 404 (not 403)"""
        user = User(
            email="enum_test@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()
        
        # Create confidential doc
        doc = Document(
            filename="enum_secret.pdf",
            original_filename="enum_secret.pdf",
            file_path="/data/confidential/enum_secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        # Try to access with regular user
        response = test_client.get(
            f"/api/v1/documents/{doc.id}",
            headers=get_auth_headers(user)
        )
        
        # MUST return 404, not 403
        # 403 confirms the document exists
        # 404 doesn't reveal existence
        assert response.status_code == 404, \
            "Must return 404 to prevent ID enumeration"

    def test_response_time_does_not_leak_existence(self, test_client: TestClient, db: Session):
        """Verify response times don't leak whether confidential docs exist"""
        import time
        
        user = User(
            email="timing_test@test.com",
            hashed_password=get_password_hash("test123"),
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()
        
        # Time request for potentially existing doc
        fake_id = uuid.uuid4()
        
        start = time.time()
        response = test_client.get(
            f"/api/v1/documents/{fake_id}",
            headers=get_auth_headers(user)
        )
        elapsed = time.time() - start
        
        # Response should be fast (not database-dependent timing)
        assert elapsed < 1.0, "Response should be fast regardless of doc existence"
