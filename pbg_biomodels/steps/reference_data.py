"""``ReferenceDataStep`` — load an external CSV trajectory as a numeric_result.

CSV layout: a header row, a ``time`` column (first column, or any column named
``time``/``t`` case-insensitively), and one column per species. The values are
emitted on the ``result`` port in the canonical ``numeric_result`` shape so a
reference dataset can be compared and overlaid exactly like a simulator engine.
"""
from __future__ import annotations

import csv
from typing import Any, ClassVar, Dict, List

from process_bigraph import Step


def load_reference_csv(path: str) -> Dict[str, Any]:
    """Parse a reference CSV into ``{time, columns, values}``.

    The time column is detected by header name (``time``/``t``, case-insensitive)
    and otherwise defaults to the first column.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = [row for row in reader if row and any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError(f"Reference CSV {path!r} is empty")

    header = [h.strip() for h in rows[0]]
    lowered = [h.lower() for h in header]
    time_idx = next((i for i, h in enumerate(lowered) if h in ("time", "t")), 0)

    species_cols = [h for i, h in enumerate(header) if i != time_idx]
    species_idx = [i for i in range(len(header)) if i != time_idx]

    times: List[float] = []
    values: List[List[float]] = []
    for row in rows[1:]:
        times.append(float(row[time_idx]))
        values.append([float(row[i]) for i in species_idx])

    return {"time": times, "columns": species_cols, "values": values}


class ReferenceDataStep(Step):
    """Emit an external reference trajectory (CSV) as a ``numeric_result``.

    Config:
        csv_path: path to the reference CSV (preferred), or
    Inputs:
        csv_path: runtime path (overrides config), so a loader can feed it.
    """

    config_schema: ClassVar[Dict[str, Any]] = {
        "csv_path": {"_type": "string", "_default": ""},
    }

    def inputs(self) -> Dict[str, str]:
        return {"csv_path": "string"}

    def outputs(self) -> Dict[str, str]:
        return {"result": "numeric_result"}

    def update(self, state: Dict[str, Any]) -> Dict[str, Any]:
        path = (state or {}).get("csv_path") or self.config.get("csv_path") or ""
        if not path:
            raise ValueError("ReferenceDataStep: no csv_path provided.")
        return {"result": load_reference_csv(path)}
