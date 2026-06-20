from __future__ import annotations

import os

from . import en, zh_cn


SUPPORTED_LANGS = {"zh", "zh_cn", "en", "both"}


def _catalog(lang: str):
    return zh_cn if lang in {"zh", "zh_cn"} else en


def normalize_lang(lang: str | None) -> str:
    candidate = lang or os.environ.get("PLUGIN_CTL_LANG") or os.environ.get("plugin_ctl_LANG") or "en"
    candidate = candidate.lower().replace("-", "_")
    if candidate not in SUPPORTED_LANGS:
        return "en"
    return "zh" if candidate == "zh_cn" else candidate


def _select(key: str, section: str, lang: str) -> str:
    normalized = normalize_lang(lang)
    if normalized == "both":
        zh_value = getattr(zh_cn, section).get(key, key)
        en_value = getattr(en, section).get(key, key)
        return f"{zh_value} / {en_value}"
    return getattr(_catalog(normalized), section).get(key, key)


def text(key: str, lang: str) -> str:
    return _select(key, "LABELS", lang)


def value(key: str, lang: str) -> str:
    return _select(key, "VALUES", lang)


def message(key: str, lang: str, **kwargs: object) -> str:
    template = _select(key, "MESSAGES", lang)
    return template.format(**kwargs) if kwargs else template


def command_help(command: str, lang: str) -> str:
    normalized = normalize_lang(lang)
    if normalized == "both":
        zh_value = zh_cn.COMMAND_HELP.get(command, command)
        en_value = en.COMMAND_HELP.get(command, command)
        return f"{zh_value} / {en_value}"
    return getattr(_catalog(normalized), "COMMAND_HELP").get(command, command)


def resource_keys(section: str) -> dict[str, set[str]]:
    return {
        "en": set(getattr(en, section)),
        "zh": set(getattr(zh_cn, section)),
    }
