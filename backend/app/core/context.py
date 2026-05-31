"""Request-scoped context variables for user identity.

These are set by middleware (``set_rls_context``) so that downstream
service code can access the current user without threading ``user_id``
through every function signature.
"""

from contextvars import ContextVar

current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)
current_user_role: ContextVar[str | None] = ContextVar(
    "current_user_role", default=None
)
