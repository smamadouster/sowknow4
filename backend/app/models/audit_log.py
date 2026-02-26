"""audit_log.py — re-export of the AuditLog model from audit.py.

This alias module exists so that code and QA checks that import from
``app.models.audit_log`` work alongside the canonical ``app.models.audit``.
"""

from app.models.audit import AuditLog, AuditAction  # noqa: F401

__all__ = ["AuditLog", "AuditAction"]
