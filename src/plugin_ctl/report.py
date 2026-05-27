from __future__ import annotations

from .state_store import StateRecord


def _text(record: StateRecord, key: str) -> str:
    return str(record.metadata.get(key, ""))


def row_for_record(record: StateRecord) -> list[str]:
    return [
        record.timestamp,
        record.plugin_id,
        record.action,
        "yes" if record.ok else "no",
        _text(record, "version"),
        _text(record, "stage"),
        _text(record, "returncode"),
        _text(record, "duration_ms"),
        _text(record, "stdout_summary"),
        _text(record, "stderr_summary"),
        record.detail,
    ]


def latest_by_plugin_action(records: list[StateRecord]) -> list[list[str]]:
    latest_by_key: dict[tuple[str, str], list[str]] = {}
    for record in records:
        latest_by_key[(record.plugin_id, record.action)] = [
            record.plugin_id,
            record.action,
            "yes" if record.ok else "no",
            str(record.metadata.get("version", "")),
            str(record.metadata.get("stage", "")),
            str(record.metadata.get("returncode", "")),
            str(record.metadata.get("duration_ms", "")),
            str(record.metadata.get("stdout_summary", "")),
            str(record.metadata.get("stderr_summary", "")),
            record.timestamp,
            record.detail,
        ]
    return sorted(latest_by_key.values(), key=lambda row: (row[0], row[1]))


def latest_by_plugin_action_json(records: list[StateRecord]) -> list[dict[str, object]]:
    latest_by_key: dict[tuple[str, str], StateRecord] = {}
    for record in records:
        latest_by_key[(record.plugin_id, record.action)] = record

    result: list[dict[str, object]] = []
    for record in sorted(latest_by_key.values(), key=lambda item: (item.plugin_id, item.action)):
        result.append(
            {
                "plugin_id": record.plugin_id,
                "action": record.action,
                "ok": record.ok,
                "version": record.metadata.get("version", ""),
                "stage": record.metadata.get("stage", ""),
                "returncode": record.metadata.get("returncode", ""),
                "duration_ms": record.metadata.get("duration_ms", ""),
                "detail": record.detail,
                "timestamp": record.timestamp,
            }
        )
    return result
