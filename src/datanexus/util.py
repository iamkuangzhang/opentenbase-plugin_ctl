from __future__ import annotations

from typing import Iterable, Sequence


def render_table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    rows = [list(row) for row in rows]
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(str(cell)))

    def fmt_row(row: Sequence[str]) -> str:
        return "  ".join(str(cell).ljust(widths[idx]) for idx, cell in enumerate(row))

    lines = [fmt_row(headers), fmt_row(["-" * w for w in widths])]
    lines.extend(fmt_row(row) for row in rows)
    return "\n".join(lines)

