"""Tests for XLSX extraction batching fix (Phase 1.1)."""
import pytest


class TestXlsxExtraction:
    """Verify that XLSX rows are batched to prevent chunk explosion."""

    @pytest.mark.asyncio
    async def test_xlsx_batches_rows(self, tmp_path):
        """A 100-row spreadsheet should produce ~2 blocks, not 100 lines."""
        from app.services.text_extractor import text_extractor
        from openpyxl import Workbook

        file_path = tmp_path / "test.xlsx"
        wb = Workbook()
        ws = wb.active
        for i in range(100):
            ws.append([f"cell-{i}-a", f"cell-{i}-b"])
        wb.save(file_path)

        result = await text_extractor._extract_from_xlsx(str(file_path))
        assert "error" not in result
        lines = result["text"].splitlines()
        # Each batch is 50 rows; 100 rows → 2 batches + sheet header
        # Batches are separated by blank lines, so total non-empty blocks ≈ 3
        non_empty_blocks = [blk for blk in result["text"].split("\n\n") if blk.strip()]
        assert len(non_empty_blocks) >= 2  # at least sheet header + 1 batch
        assert len(non_empty_blocks) <= 4  # not 100 separate chunks

    @pytest.mark.asyncio
    async def test_xlsx_empty_sheet(self, tmp_path):
        """Empty spreadsheet returns empty text."""
        from app.services.text_extractor import text_extractor
        from openpyxl import Workbook

        file_path = tmp_path / "empty.xlsx"
        wb = Workbook()
        wb.save(file_path)

        result = await text_extractor._extract_from_xlsx(str(file_path))
        assert result["text"] == ""
