"""Enable Row-Level Security on documents and collections tables.

Revision ID: add_rls_009
Revises: add_coll_confidential_008
Create Date: 2026-02-26

P2-9:
- Enables RLS on sowknow.documents
- Enables RLS on sowknow.collections
- Creates documents_access_policy (public docs visible to all; confidential to owner/admin)
- Creates collections_access_policy (private visible to owner; public visible to all)
- Creates superuser_bypass policy (admin role bypasses all restrictions)

The middleware sets app.user_id and app.user_role PostgreSQL session variables
before executing queries. See backend/app/middleware/rls.py.
"""

from alembic import op


revision = "add_rls_009"
down_revision = "add_coll_confidential_008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable RLS
    op.execute("ALTER TABLE sowknow.documents  ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sowknow.collections ENABLE ROW LEVEL SECURITY")

    # Documents access policy
    op.execute("""
        DROP POLICY IF EXISTS documents_access_policy ON sowknow.documents
    """)
    op.execute("""
        CREATE POLICY documents_access_policy ON sowknow.documents
        USING (
            bucket::text IN ('PUBLIC', 'public')
            OR uploaded_by::text = current_setting('app.user_id', true)
            OR current_setting('app.user_role', true)
                IN ('admin', 'ADMIN', 'superuser', 'SUPERUSER')
        )
    """)

    # Collections access policy
    op.execute("""
        DROP POLICY IF EXISTS collections_access_policy ON sowknow.collections
    """)
    op.execute("""
        CREATE POLICY collections_access_policy ON sowknow.collections
        USING (
            user_id::text = current_setting('app.user_id', true)
            OR visibility::text IN ('PUBLIC', 'public')
            OR current_setting('app.user_role', true)
                IN ('admin', 'ADMIN', 'superuser', 'SUPERUSER')
        )
    """)

    # Admin bypass on documents
    op.execute("""
        DROP POLICY IF EXISTS superuser_bypass ON sowknow.documents
    """)
    op.execute("""
        CREATE POLICY superuser_bypass ON sowknow.documents
        USING (
            current_setting('app.user_role', true) IN ('admin', 'ADMIN')
        )
    """)

    # Admin bypass on collections
    op.execute("""
        DROP POLICY IF EXISTS superuser_bypass ON sowknow.collections
    """)
    op.execute("""
        CREATE POLICY superuser_bypass ON sowknow.collections
        USING (
            current_setting('app.user_role', true) IN ('admin', 'ADMIN')
        )
    """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS superuser_bypass ON sowknow.collections"
    )
    op.execute(
        "DROP POLICY IF EXISTS superuser_bypass ON sowknow.documents"
    )
    op.execute(
        "DROP POLICY IF EXISTS collections_access_policy ON sowknow.collections"
    )
    op.execute(
        "DROP POLICY IF EXISTS documents_access_policy ON sowknow.documents"
    )
    op.execute("ALTER TABLE sowknow.collections DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sowknow.documents   DISABLE ROW LEVEL SECURITY")
