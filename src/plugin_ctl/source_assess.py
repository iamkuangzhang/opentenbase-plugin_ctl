from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True, slots=True)
class AssessItem:
    check: str
    status: str
    detail: str
    path: str = ""
    line: int = 0


SQL_FUNCTION_RE = re.compile(
    r"create\s+(?:or\s+replace\s+)?function\b.*?\blanguage\s+c\b.*?;",
    re.IGNORECASE | re.DOTALL,
)
SHIPPABLE_RE = re.compile(r"\b(?:not\s+)?shippable\b", re.IGNORECASE)
C_DDL_RE = re.compile(
    r"\b(?:SPI_execute|SPI_exec|SPI_execute_with_args|DirectFunctionCall\w*)\s*\([^;]*\b(create|drop|alter)\s+table\b",
    re.IGNORECASE | re.DOTALL,
)
TRANSACTION_RE = re.compile(r"\b(commit|rollback|start\s+transaction|begin\s+transaction)\b", re.IGNORECASE)
TEMP_TABLE_RE = re.compile(r"\bcreate\s+(?:temporary|temp)\s+table\b", re.IGNORECASE)
SYSTEM_TABLE_RE = re.compile(r"\bpg_(?:class|proc|attribute|extension|namespace|depend|type)\b", re.IGNORECASE)


def assess_source(source_path: Path) -> list[AssessItem]:
    root = source_path.resolve()
    if not root.exists():
        return [AssessItem("source_path", "fail", "path does not exist", str(source_path))]
    if not root.is_dir():
        return [AssessItem("source_path", "fail", "source path must be a directory", str(source_path))]

    items: list[AssessItem] = [AssessItem("source_path", "pass", "directory exists", str(root))]
    control_files = sorted(root.rglob("*.control"))
    sql_files = sorted([*root.rglob("*.sql"), *root.rglob("*.sql.in")])
    c_files = sorted([*root.rglob("*.c"), *root.rglob("*.h")])

    items.append(
        AssessItem(
            "control_file",
            "pass" if control_files else "fail",
            f"{len(control_files)} control file(s) found" if control_files else "missing PostgreSQL extension .control file",
            _relative_list(root, control_files),
        )
    )
    items.append(
        AssessItem(
            "sql_files",
            "pass" if sql_files else "warn",
            f"{len(sql_files)} SQL file(s) found" if sql_files else "no SQL install/update files found",
            _relative_list(root, sql_files),
        )
    )
    items.append(
        AssessItem(
            "c_sources",
            "pass" if c_files else "warn",
            f"{len(c_files)} C/C header file(s) found" if c_files else "no C source files found; SQL-only plugin",
            _relative_list(root, c_files),
        )
    )

    for sql_file in sql_files:
        items.extend(_assess_sql_file(root, sql_file))
    for c_file in c_files:
        items.extend(_assess_c_file(root, c_file))

    if not any(item.check == "c_function_shippable" for item in items):
        items.append(AssessItem("c_function_shippable", "pass", "no LANGUAGE C functions found"))
    if not any(item.check == "c_dynamic_table_ddl" for item in items):
        items.append(AssessItem("c_dynamic_table_ddl", "pass", "no C-side dynamic table DDL found"))
    return items


def assess_items_json(items: list[AssessItem]) -> list[dict[str, object]]:
    return [
        {
            "check": item.check,
            "status": item.status,
            "detail": item.detail,
            "path": item.path,
            "line": item.line,
        }
        for item in items
    ]


def _assess_sql_file(root: Path, path: Path) -> list[AssessItem]:
    text = _read_text(path)
    rel = _relative(root, path)
    items: list[AssessItem] = []
    for match in SQL_FUNCTION_RE.finditer(text):
        statement = match.group(0)
        line = _line_number(text, match.start())
        if SHIPPABLE_RE.search(statement):
            items.append(AssessItem("c_function_shippable", "pass", "LANGUAGE C function declares SHIPPABLE/NOT SHIPPABLE", rel, line))
        else:
            items.append(AssessItem("c_function_shippable", "warn", "LANGUAGE C function lacks explicit SHIPPABLE/NOT SHIPPABLE", rel, line))
    if TEMP_TABLE_RE.search(text):
        items.append(AssessItem("sql_temp_table", "warn", "temporary table usage may behave differently across CN/DN execution", rel, _line_number(text, TEMP_TABLE_RE.search(text).start())))  # type: ignore[union-attr]
    if TRANSACTION_RE.search(text):
        items.append(AssessItem("sql_transaction_control", "warn", "transaction control in extension SQL needs distributed review", rel, _line_number(text, TRANSACTION_RE.search(text).start())))  # type: ignore[union-attr]
    if SYSTEM_TABLE_RE.search(text):
        items.append(AssessItem("sql_system_catalog_access", "warn", "system catalog access should be reviewed for distributed metadata semantics", rel, _line_number(text, SYSTEM_TABLE_RE.search(text).start())))  # type: ignore[union-attr]
    return items


def _assess_c_file(root: Path, path: Path) -> list[AssessItem]:
    text = _read_text(path)
    rel = _relative(root, path)
    items: list[AssessItem] = []
    for match in C_DDL_RE.finditer(text):
        items.append(AssessItem("c_dynamic_table_ddl", "fail", "C code appears to execute dynamic table DDL; this is high risk on DN", rel, _line_number(text, match.start())))
    if TRANSACTION_RE.search(text):
        items.append(AssessItem("c_transaction_control", "warn", "C code mentions transaction control; review coordinator/datanode semantics", rel, _line_number(text, TRANSACTION_RE.search(text).start())))  # type: ignore[union-attr]
    if SYSTEM_TABLE_RE.search(text):
        items.append(AssessItem("c_system_catalog_access", "warn", "C code references PostgreSQL catalogs; review OpenTenBase metadata broadcast behavior", rel, _line_number(text, SYSTEM_TABLE_RE.search(text).start())))  # type: ignore[union-attr]
    return items


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _relative_list(root: Path, paths: list[Path]) -> str:
    return ", ".join(_relative(root, path) for path in paths[:8]) + (" ..." if len(paths) > 8 else "")


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1
