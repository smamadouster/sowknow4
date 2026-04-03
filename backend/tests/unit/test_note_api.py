import pytest
from app.models.note import Note, NoteBucket


class TestNoteModel:
    def test_bucket_enum_values(self):
        assert NoteBucket.PUBLIC.value == "public"
        assert NoteBucket.CONFIDENTIAL.value == "confidential"

    def test_note_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(Note)
        column_names = [c.key for c in mapper.column_attrs]
        required = ["id", "user_id", "title", "content", "bucket", "created_at", "updated_at"]
        for col in required:
            assert col in column_names, f"Missing column: {col}"

    def test_note_table_name(self):
        assert Note.__tablename__ == "notes"
