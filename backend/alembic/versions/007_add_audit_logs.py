"""Convert audit_logs to range-partitioned table; add auditaction lowercase values;
add confidential access trigger.

Revision ID: add_audit_logs_007
Revises: add_minimax_enum_006
Create Date: 2026-02-26

P0-4:
- Adds lowercase enum values to auditaction (user_created, confidential_accessed …)
- Converts audit_logs to PARTITION BY RANGE (created_at) with quarterly partitions
- Creates log_confidential_access() trigger function on documents
- Re-creates indexes on partitioned table
"""

from alembic import op


revision = "add_audit_logs_007"
down_revision = "add_minimax_enum_006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add lowercase auditaction values
    for value in (
        "user_created", "user_updated", "user_deleted",
        "confidential_accessed", "confidential_uploaded", "confidential_deleted",
        "admin_login", "settings_changed", "system_action",
    ):
        op.execute(
            f"ALTER TYPE sowknow.auditaction ADD VALUE IF NOT EXISTS '{value}'"
        )

    # 2. Convert audit_logs to partitioned (skip if already partitioned)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_partitioned_table pt
                JOIN pg_class c ON c.oid = pt.partrelid
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE n.nspname = 'sowknow' AND c.relname = 'audit_logs'
            ) THEN
                -- Rename old table
                ALTER TABLE sowknow.audit_logs RENAME TO audit_logs_old;

                -- Create partitioned table
                CREATE TABLE sowknow.audit_logs (
                    id            uuid        NOT NULL DEFAULT gen_random_uuid(),
                    user_id       uuid        REFERENCES sowknow.users(id) ON DELETE SET NULL,
                    action        sowknow.auditaction NOT NULL,
                    resource_type varchar(100),
                    resource_id   varchar(255),
                    details       text,
                    ip_address    varchar(45),
                    user_agent    varchar(512),
                    created_at    timestamptz NOT NULL DEFAULT now(),
                    updated_at    timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at);

                -- Partitions
                CREATE TABLE sowknow.audit_logs_2026_q1 PARTITION OF sowknow.audit_logs
                    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
                CREATE TABLE sowknow.audit_logs_2026_q2 PARTITION OF sowknow.audit_logs
                    FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
                CREATE TABLE sowknow.audit_logs_2026_q3 PARTITION OF sowknow.audit_logs
                    FOR VALUES FROM ('2026-07-01') TO ('2027-01-01');

                -- Copy data
                INSERT INTO sowknow.audit_logs
                    (id, user_id, action, resource_type, resource_id,
                     details, ip_address, user_agent, created_at, updated_at)
                SELECT id, user_id, action, resource_type, resource_id,
                       details, ip_address, user_agent, created_at, updated_at
                FROM sowknow.audit_logs_old;

                DROP TABLE sowknow.audit_logs_old;

                -- Indexes
                CREATE INDEX ix_sowknow_audit_logs_user_id
                    ON sowknow.audit_logs (user_id);
                CREATE INDEX ix_sowknow_audit_logs_action
                    ON sowknow.audit_logs (action);
                CREATE INDEX ix_sowknow_audit_logs_created_at
                    ON sowknow.audit_logs (created_at);
                CREATE INDEX ix_sowknow_audit_logs_resource_type
                    ON sowknow.audit_logs (resource_type);
                CREATE INDEX ix_sowknow_audit_logs_resource_id
                    ON sowknow.audit_logs (resource_id);
            END IF;
        END
        $$
    """)

    # 3. log_confidential_access trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION sowknow.log_confidential_access()
        RETURNS TRIGGER LANGUAGE plpgsql AS $func$
        BEGIN
            IF NEW.bucket::text IN ('confidential', 'CONFIDENTIAL') THEN
                INSERT INTO sowknow.audit_logs
                    (user_id, action, resource_type, resource_id,
                     details, ip_address)
                VALUES (
                    NULLIF(current_setting('app.user_id', true), '')::uuid,
                    'confidential_accessed'::sowknow.auditaction,
                    'document',
                    NEW.id::text,
                    'Confidential document accessed',
                    current_setting('app.client_ip', true)
                );
            END IF;
            RETURN NEW;
        END;
        $func$
    """)

    # 4. Trigger on documents
    op.execute("""
        DROP TRIGGER IF EXISTS trigger_log_confidential_access
          ON sowknow.documents
    """)
    op.execute("""
        CREATE TRIGGER trigger_log_confidential_access
            AFTER INSERT OR UPDATE ON sowknow.documents
            FOR EACH ROW
            EXECUTE FUNCTION sowknow.log_confidential_access()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trigger_log_confidential_access "
        "ON sowknow.documents"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS sowknow.log_confidential_access CASCADE"
    )
