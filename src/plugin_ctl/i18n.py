from __future__ import annotations

import os


SUPPORTED_LANGS = {"zh", "en", "both"}

LABELS = {
    "plugin": ("插件", "Plugin"),
    "version": ("版本", "Version"),
    "package_ok": ("包合格", "Package OK"),
    "env_ready": ("环境就绪", "Environment ready"),
    "installed_state": ("安装状态", "Installed state"),
    "lifecycle_ready": ("生命周期就绪", "Lifecycle ready"),
    "distributed_ready": ("分布式适配", "Distributed ready"),
    "last_deploy": ("最近部署", "Last deploy"),
    "last_verify": ("最近验证", "Last verify"),
    "last_rollback": ("最近回滚", "Last rollback"),
    "notes": ("备注", "Notes"),
    "next_action": ("下一步", "Next action"),
    "conclusion": ("结论", "Conclusion"),
    "recommendation": ("建议", "Recommendation"),
    "check": ("检查项", "Check"),
    "status": ("状态", "Status"),
    "detail": ("详情", "Detail"),
    "deploy_plan": ("部署计划", "Deploy plan"),
    "verify_plan": ("验证计划", "Verify plan"),
    "rollback_plan": ("回滚计划", "Rollback plan"),
    "removed_verify_plan": ("移除验证计划", "Removed verify plan"),
    "target_roles": ("目标角色", "Target roles"),
    "risk": ("风险", "Risk"),
}

VALUES = {
    "installed": ("已安装", "installed"),
    "not_installed": ("未安装", "not installed"),
    "unknown": ("未知", "unknown"),
    "yes": ("是", "yes"),
    "no": ("否", "no"),
    "warning": ("警告", "warning"),
    "pass": ("通过", "pass"),
    "warn": ("警告", "warning"),
    "fail": ("失败", "fail"),
    "ready": ("就绪", "ready"),
    "not ready": ("未就绪", "not ready"),
    "deploy": ("部署", "deploy"),
    "verify": ("验证", "verify"),
    "rollback": ("回滚", "rollback"),
    "fix_manifest": ("修 manifest", "fix manifest"),
    "fix_environment": ("修环境", "fix environment"),
    "review": ("复核", "review"),
}

MESSAGES = {
    "keep_current_verify_when_needed": ("保持当前状态，按需验证。", "Keep current state; verify when needed."),
    "run_verify_to_confirm": ("建议执行 verify 确认插件功能。", "Run verify to confirm plugin behavior."),
    "ready_to_deploy": ("可以执行 deploy。", "Ready to deploy."),
    "resolve_readiness_gaps": ("先处理未就绪项，再执行生命周期操作。", "Resolve readiness gaps before lifecycle actions."),
    "diagnose_conclusion_fix_manifest": ("插件包不合格，先修 manifest。", "Package is not ready; fix the manifest first."),
    "diagnose_conclusion_fix_environment": ("环境未就绪，先修环境。", "Environment is not ready; fix the environment first."),
    "diagnose_conclusion_deploy": ("插件包和环境都就绪，建议 deploy。", "Package and environment are ready; deploy."),
    "diagnose_conclusion_verify": ("插件已安装，建议 verify。", "Plugin is installed; verify current behavior."),
    "diagnose_conclusion_review": ("状态正常，当前不需要继续执行生命周期动作。", "Status is healthy; no lifecycle action is required now."),
    "diagnose_conclusion_unknown": ("安装状态未知，先补齐 manifest 或 installed_probe。", "Installed state is unknown; fix the manifest or installed_probe first."),
}


def normalize_lang(lang: str | None) -> str:
    candidate = lang or os.environ.get("plugin_ctl_LANG") or "zh"
    if candidate not in SUPPORTED_LANGS:
        return "zh"
    return candidate


def _select(pair: tuple[str, str], lang: str) -> str:
    zh, en = pair
    if lang == "en":
        return en
    if lang == "both":
        return f"{zh} / {en}"
    return zh


def text(key: str, lang: str) -> str:
    return _select(LABELS.get(key, (key, key)), lang)


def value(key: str, lang: str) -> str:
    return _select(VALUES.get(key, (key, key)), lang)


def message(key: str, lang: str) -> str:
    return _select(MESSAGES.get(key, (key, key)), lang)
