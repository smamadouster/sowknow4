"""Add audit_logs table for admin action and confidential access tracking

Revision ID: 011
Revises: 010
Create Date: 2026-02-26

The AuditLog ORM model (app/models/audit.py) and admin.py endpoints
were written but no migration ever created the underlying table.
This migration fills that gap.
"""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the auditaction enum type
    op.execute("""
        DO $
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type t
                           JOIN pg_namespace n ON n.oid = t.typnamespace
                           WHERE t.typname = 'auditaction'
                           AND n.nspname = 'sowknow') THEN
                CREATE TYPE sowknow.auditaction AS ENUM (
                    'user_created',
                    'user_updated',
                    'user_deleted',
                    'user_role_changed',
                    'user_status_changed',
                    'confidential_accessed',
                    'confidential_uploaded',
                    'confidential_deleted',
                    'admin_login',
                    'settings_changed',
                    'system_action'
                );
            END IF;
        END $;
    """)

    # Create the audit_logs table
    op.execute("""
        CREATE TABLE IF NOT EXISTS sowknow.audit_logs (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID        REFERENCES sowknow.users(id) ON DELETE SET NULL,
            action      sowknow.auditaction NOT NULL,
            resource_type VARCHAR(100) NOT NULL,
            resource_id VARCHAR(255),
            details     TEXT,
            ip_address  VARCHAR(45),
            user_agent  VARCHAR(512),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # Indexes matching the ORM model (index=True on these columns)
    op.create_index("ix_audit_logs_user_id",       "audit_logs", ["user_id"],       schema="sowknow")
    op.create_index("ix_audit_logs_action",         "audit_logs", ["action"],         schema="sowknow")
    op.create_index("ix_audit_logs_resource_type",  "audit_logs", ["resource_type"],  schema="sowknow")
    op.create_index("ix_audit_logs_resource_id",    "audit_logs", ["resource_id"],    schema="sowknow")


def downgrade() -> None:
    op.drop_index("ix_audit_logs_resource_id",   table_name="audit_logs", schema="sowknow")
    op.drop_index("ix_audit_logs_resource_type", table_name="audit_logs", schema="sowknow")
    op.drop_index("ix_audit_logs_action",        table_name="audit_logs", schema="sowknow")
    op.drop_index("ix_audit_logs_user_id",       table_name="audit_logs", schema="sowknow")
    op.execute("DROP TABLE IF EXISTS sowknow.audit_logs")
    op.execute("DROP TYPE IF EXISTS sowknow.auditaction")
