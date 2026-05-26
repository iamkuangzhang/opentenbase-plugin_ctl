# OpenTenBase PluginCtl

[中文](#中文) | [English](#english)

## 中文

OpenTenBase PluginCtl 是一个面向 OpenTenBase 分布式插件的 CLI-first 生命周期治理工具。

它不是通用数据库运维平台，也不是插件市场。它的核心目标是把 OpenTenBase 插件从“能手动安装”推进到“可检查、可规划、可物理分发、可逻辑激活、可白盒验证、可追踪”的治理闭环。

项目包名仍为 `datanexus`，同时提供 `plugin_ctl` 等兼容入口。

## 主流程冻结

M3 冻结后的主流程为：

```bash
python -m plugin_ctl check <plugin_id>
python -m plugin_ctl deploy <plugin_id> -f cluster.toml --execute
python -m plugin_ctl activate <plugin_id> -f cluster.toml --execute
python -m plugin_ctl verify <plugin_id> -f cluster.toml
python -m plugin_ctl report
```

等价兼容入口：

```bash
python -m datanexus check <plugin_id>
datanexus check <plugin_id>
plugin_ctl check <plugin_id>
opentenbase-pluginctl check <plugin_id>
opentenbase-plugin_ctl check <plugin_id>
```

## 已实现能力

基础发现与报告：

```bash
python -m plugin_ctl list
python -m plugin_ctl inspect <plugin_id>
python -m plugin_ctl check <plugin_id>
python -m plugin_ctl report
python -m plugin_ctl report --json
```

本地 Docker 沙盒生命周期：

```bash
python -m plugin_ctl deploy <plugin_id>
python -m plugin_ctl verify <plugin_id>
python -m plugin_ctl rollback <plugin_id>
python -m plugin_ctl rollback <plugin_id> --execute
python -m plugin_ctl state <plugin_id>
```

分布式 M3 生命周期：

```bash
python -m plugin_ctl deploy <plugin_id> -f cluster.toml
python -m plugin_ctl deploy <plugin_id> -f cluster.toml --execute
python -m plugin_ctl activate <plugin_id> -f cluster.toml
python -m plugin_ctl activate <plugin_id> -f cluster.toml --execute
python -m plugin_ctl verify <plugin_id> -f cluster.toml
python -m plugin_ctl verify <plugin_id> -f cluster.toml --json
```

M3 中各步骤的边界：

- `check`：聚合 `lint / plan / precheck / diagnose`，不执行数据库变更。
- `deploy -f`：只做物理 payload 分发，负责 `.so / .control / .sql` 的 SSH/SCP 分发与 SHA256 对账，不执行 `CREATE EXTENSION`。
- `activate -f`：只做多 CN 逻辑激活，串行执行 `CREATE EXTENSION IF NOT EXISTS <extension_name>;`，然后并发检查 CN 版本一致性，不连接 DN。
- `verify -f`：只做分布式白盒验证，不执行 scp，不执行 `CREATE EXTENSION`，不做 activate。
- `report`：展示本地 action 状态，不替代数据库真实状态。

## Advanced / Debug Commands

以下命令保留给调试、诊断和底层验证使用。普通用户优先使用主流程命令。

```bash
python -m plugin_ctl plugin lint <plugin_id>
python -m plugin_ctl plugin plan <plugin_id>
python -m plugin_ctl plugin precheck <plugin_id>
python -m plugin_ctl plugin diagnose <plugin_id>
python -m plugin_ctl plugin check <plugin_id>
python -m plugin_ctl plugin status <plugin_id>
python -m plugin_ctl plugin roles <plugin_id>
python -m plugin_ctl plugin consistency <plugin_id>
python -m plugin_ctl plugin archive list
python -m plugin_ctl plugin archive inspect <plugin_id>
python -m plugin_ctl plugins status
python -m plugin_ctl cluster inspect -f cluster.toml
python -m plugin_ctl cluster distribute --dry-run -f cluster.toml <plugin_id>
python -m plugin_ctl cluster distribute --execute -f cluster.toml <plugin_id>
python -m plugin_ctl cluster status
python -m plugin_ctl doctor
```

## 安全边界

- `cluster.toml` 是可信管理员配置，不应接受未审计的外部输入。
- 所有 `psql / ssh / scp / docker` 调用使用参数列表，不使用 `shell=True`。
- `extension_name` 会经过 PostgreSQL identifier 校验后才进入 SQL。
- `deploy -f --execute` 会写远端文件系统，但不会执行 `CREATE EXTENSION`。
- `activate -f --execute` 会修改 CN 元数据，但不会分发文件，也不会自动回滚已经成功的 CN。
- `verify -f` 是只读白盒验证，只检查 CN extension 状态、CN/DN 文件 checksum、节点连通性和 prepared transaction 残留。
- `rollback` 是 best-effort，不承诺完整恢复所有分布式状态。
- role hooks 当前只进入 plan、roles、diagnose、archive、consistency，不会自动执行。

## 当前不做

- 自动编译插件源码。
- 自动修复远端节点状态。
- 自动 rollback activate。
- `otb_timeseries` 专用 profile / timeseries 深度验证。
- Web UI。
- 插件市场。
- 自动跨数据库适配。
- 批量部署与批量升级系统。
- 自动创建远端系统目录或自动 sudo。

## 插件与目录

```text
catalog/plugins/      reference manifests
examples/plugins/     bundled example plugins
src/datanexus/        CLI and governance implementation
tests/                unit tests
docs/                 design and release documents
recipes/              smoke verification SQL
```

当前重点插件：

- `dnx_smoke_plugin`：平台生命周期验证插件，适合测试 deploy / verify / rollback / distributed flow。
- `otb_timeseries`：真实插件的 reference manifest。当前发布仓库未携带旧项目完整载荷，因此可用于 runtime installed state 与治理视角展示，但不能证明完整干净环境安装链路。

## 安装

要求：

- Python 3.11+
- Docker，本地沙盒链路需要 OpenTenBase Docker 环境。
- 分布式链路需要可用的 `cluster.toml`、SSH、scp、psql。

安装：

```bash
git clone https://github.com/iamkuangzhang/opentenbase-plugin_ctl.git
cd opentenbase-plugin_ctl
python -m pip install -e .
plugin_ctl list
```

源码运行：

```bash
set PYTHONPATH=src
python -m datanexus list
```

PowerShell：

```powershell
$env:PYTHONPATH = "src"
python -m datanexus list
```

## 测试

```bash
python -m unittest discover -s tests -v
git diff --check
```

## 文档

- [M0_BASELINE.md](docs/M0_BASELINE.md)
- [M1_STATUS.md](docs/M1_STATUS.md)
- [M2_PLUGIN_GOVERNANCE.md](docs/M2_PLUGIN_GOVERNANCE.md)
- [M2_GOVERNANCE_FLOW.md](docs/M2_GOVERNANCE_FLOW.md)
- [M3_ARCHIVE_AND_CONSISTENCY.md](docs/M3_ARCHIVE_AND_CONSISTENCY.md)
- [M3_DISTRIBUTED_LIFECYCLE.md](docs/M3_DISTRIBUTED_LIFECYCLE.md)
- [M3_FINAL_STATUS.md](docs/M3_FINAL_STATUS.md)
- [M4_RELEASE_QUALITY.md](docs/M4_RELEASE_QUALITY.md)
- [RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)

## English

OpenTenBase PluginCtl is a CLI-first lifecycle governance tool for distributed OpenTenBase plugins.

The frozen M3 main flow is:

```bash
python -m plugin_ctl check <plugin_id>
python -m plugin_ctl deploy <plugin_id> -f cluster.toml --execute
python -m plugin_ctl activate <plugin_id> -f cluster.toml --execute
python -m plugin_ctl verify <plugin_id> -f cluster.toml
python -m plugin_ctl report
```

It focuses on plugin package governance, physical distribution, coordinator activation, distributed white-box verification, and local action reporting.

Security notes:

- `cluster.toml` is trusted administrator configuration.
- `deploy -f --execute` writes remote payload files only; it does not run `CREATE EXTENSION`.
- `activate -f --execute` changes coordinator metadata; it does not distribute files and does not connect to datanodes.
- `verify -f` is read-only.
- Automatic build, repair, activate rollback, marketplace, Web UI, and `otb_timeseries`-specific validation are intentionally out of scope for the current M3 freeze.
