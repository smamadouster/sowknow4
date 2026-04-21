"""
Tool Registry for SOWKNOW Agent Tool Calling (Sprint 4.3)

Provides Pydantic-based schemas for the core SOWKNOW tools and a registry
that exposes them in OpenAI-compatible function calling format.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class DocumentSearchTool(BaseModel):
    """Search the SOWKNOW vault using hybrid semantic + keyword matching."""

    query: str = Field(description="Natural language search query")
    bucket: Literal["public", "confidential", "all"] = Field(default="public")
    limit: int = Field(default=10, ge=1, le=100)
    date_from: date | None = Field(
        default=None, description="Filter by date range start"
    )
    date_to: date | None = Field(
        default=None, description="Filter by date range end"
    )
    language: Literal["fr", "en", "auto"] = Field(default="auto")


class VaultClassifyTool(BaseModel):
    """Classify a document as Public or Confidential."""

    document_id: str = Field(description="ID of the document to classify")
    content_snippet: str = Field(
        description="First 500 chars of document content"
    )


class EntityExtractTool(BaseModel):
    """Extract people, organizations, and concepts from document text."""

    text: str = Field(description="Document text to analyze")
    language: Literal["fr", "en"] = Field(default="fr")
    max_entities: int = Field(default=20, ge=1, le=50)


class ToolRegistry:
    """Registry of available SOWKNOW tools with their schemas.

    Provides tool definitions in a format suitable for LLM function calling.
    """

    TOOLS: dict[str, type[BaseModel]] = {
        "document_search": DocumentSearchTool,
        "vault_classify": VaultClassifyTool,
        "entity_extract": EntityExtractTool,
    }

    @classmethod
    def get_tool_schemas(cls) -> list[dict]:
        """Return all tool schemas in OpenAI-compatible function calling format."""
        return [
            cls._build_function_schema(name, model)
            for name, model in cls.TOOLS.items()
        ]

    @classmethod
    def get_tool_schema(cls, tool_name: str) -> dict | None:
        """Return a single tool's schema, or None if not found."""
        model = cls.TOOLS.get(tool_name)
        if model is None:
            return None
        return cls._build_function_schema(tool_name, model)

    @classmethod
    def validate_tool_call(cls, tool_name: str, arguments: dict) -> BaseModel:
        """Validate and parse tool call arguments.

        Raises:
            KeyError: If tool_name is not registered.
            pydantic.ValidationError: If arguments fail validation.
        """
        model = cls.TOOLS.get(tool_name)
        if model is None:
            raise KeyError(f"Unknown tool: {tool_name}")
        return model(**arguments)

    @classmethod
    def _build_function_schema(cls, name: str, model: type[BaseModel]) -> dict:
        """Build an OpenAI-compatible function schema from a Pydantic model."""
        schema = model.model_json_schema()
        # Remove the top-level title that Pydantic adds (not part of function calling spec)
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": (model.__doc__ or "").strip(),
                "parameters": schema,
            },
        }
