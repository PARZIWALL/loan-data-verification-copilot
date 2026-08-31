"""CSV parsing and file validation."""

from __future__ import annotations

import csv
import io
from typing import Any


def parse_csv_rows(file_obj: Any) -> list[dict[str, Any]]:
    """Parse uploaded CSV content into row dictionaries with header names."""
    raw_content = file_obj.file.read()
    if not raw_content:
        raise ValueError("Uploaded file is empty.")

    text = raw_content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV file is missing a header row.")

    rows: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        if row is None:
            continue
        clean_row = {str(key): (value.strip() if isinstance(value, str) else value) for key, value in row.items() if key is not None}
        if not any((value not in (None, "")) for value in clean_row.values()):
            continue
        rows.append({"row_number": row_number, "data": clean_row})
    return rows
