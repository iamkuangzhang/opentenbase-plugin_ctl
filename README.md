# OpenTenBase PluginCtl

[中文](#中文) | [English](#english)

## 中文

OpenTenBase PluginCtl 是一个面向 OpenTenBase 分布式插件的 CLI 优先生命周期治理工具。

它的目标不是做通用数据库运维平台，也不是插件市场，而是把 OpenTenBase 插件从“能安装”推进到“可检查、可计划、可验证、可回滚、可追踪”的治理闭环。

本项目基于 DataNexus 插件治理模型构建。

## 当前定位

- OpenTenBase 专用
- CLI 优先
- 插件治理优先
- 面向分布式插件生命周期
- 当前重点是单插件闭环和样例插件验证

## 已实现能力

基础命令：

```bash
python -m datanexus list
python -m datanexus inspect <plugin_id>
python -m datanexus doctor
python -m datanexus report
python -m datanexus report --json
```

生命周期命令：

```bash
python -m datanexus deploy <plugin_id>
python -m datanexus verify <plugin_id>
python -m datanexus rollback <plugin_id>
python -m datanexus rollback <plugin_id> --execute
python -m datanexus state <plugin_id>
```

插件治理命令：

```bash
python -m datanexus plugin lint <plugin_id>
python -m datanexus plugin plan <plugin_id>
python -m datanexus plugin precheck <plugin_id>
python -m datanexus plugin diagnose <plugin_id>
python -m datanexus plugin check <plugin_id>
python -m datanexus plugin status <plugin_id>
python -m datanexus plugin roles <plugin_id>
python -m datanexus plugin consistency <plugin_id>
python -m datanexus plugin archive list
python -m datanexus plugin archive inspect <plugin_id>
python -m datanexus plugins status
python -m datanexus plugins status --json
```

其中：

- `lint`：只检查 manifest 和插件包文件，不连接数据库。
- `plan`：只生成执行计划，最多执行 `installed_probe` 判断是否已安装。
- `precheck`：部署前只读门禁，检查插件包、连接、版本、目标角色、注册节点和远端临时目录。
- `diagnose`：聚合 `lint / plan / precheck`，给出是否可部署、是否已安装、下一步建议和主要风险。
- `roles`：展示插件包按 coordinator / datanode 映射的治理步骤。
- `consistency`：围绕插件检查 archive、manifest、文件、probe、角色和运行态是否一致。
- `archive`：查询本地插件包治理快照，不替代 action 级别的 `state/report`。

M3 已开始支持声明式 role hooks：`preinstall / postinstall / preuninstall / postuninstall`。当前 hook 只进入规划、lint、archive 和 consistency，不会自动执行。

## 插件结构

```text
catalog/plugins/
examples/plugins/
src/datanexus/
tests/
docs/
recipes/
```

- `catalog/plugins/`：已有插件载荷的 manifest。
- `examples/plugins/`：平台验证用样例插件。
- `src/datanexus/`：DataNexus 平台核心代码。
- `tests/`：平台单元测试。
- `docs/`：M0/M1/M2 阶段文档和问题记录。

## 当前插件

`dnx_smoke_plugin` 是平台生命周期验证插件。它足够简单、安全，可以重复 deploy、verify、rollback。

`otb_timeseries` 是真实 OpenTenBase 插件载荷。当前平台可识别其已安装状态，并可执行 smoke verify；但它没有破坏性 rollback，chunk distribution warning 仍作为独立问题跟踪。

## 推荐使用流程

```bash
python -m datanexus plugin lint dnx_smoke_plugin
python -m datanexus plugin plan dnx_smoke_plugin
python -m datanexus plugin precheck dnx_smoke_plugin
python -m datanexus plugin diagnose dnx_smoke_plugin
python -m datanexus deploy dnx_smoke_plugin
python -m datanexus verify dnx_smoke_plugin
python -m datanexus report
```

如需回滚样例插件：

```bash
python -m datanexus rollback dnx_smoke_plugin
python -m datanexus rollback dnx_smoke_plugin --execute
python -m datanexus verify dnx_smoke_plugin --removed
```

`rollback` 默认是 dry-run。只有显式传入 `--execute` 才会执行 manifest 声明的 `rollback_sql`。

## 本地运行

```bash
cd <repo-dir>
set PYTHONPATH=src
python -m datanexus plugins status
```

PowerShell：

```powershell
cd <repo-dir>
$env:PYTHONPATH = "src"
python -m datanexus plugins status
```

运行测试：

```bash
python -m unittest discover -s tests -v
```

## 语言

人类可读的插件治理命令默认中文输出。

```bash
python -m datanexus plugin status otb_timeseries
python -m datanexus plugin status otb_timeseries --lang en
python -m datanexus plugin status otb_timeseries --lang both
```

JSON 输出保持英文 key，便于自动化集成。

## 阶段状态

- M0：CLI 骨架和基础闭环已冻结。
- M1：`dnx_smoke_plugin` 完成可重复生命周期验证。
- M2：插件治理链路已形成：`lint -> plan -> precheck -> diagnose -> deploy -> verify -> report`。
- M3：开始补齐分布式插件包治理：`archive/state -> roles/hooks -> consistency`。

详细文档：

- [M0_BASELINE.md](docs/M0_BASELINE.md)
- [M1_STATUS.md](docs/M1_STATUS.md)
- [M2_PLUGIN_GOVERNANCE.md](docs/M2_PLUGIN_GOVERNANCE.md)
- [M2_GOVERNANCE_FLOW.md](docs/M2_GOVERNANCE_FLOW.md)
- [M3_ARCHIVE_AND_CONSISTENCY.md](docs/M3_ARCHIVE_AND_CONSISTENCY.md)

## 当前边界

当前不做：

- Web UI
- 插件市场
- 批量部署
- 自动修复
- 跨数据库适配
- 节点同步 / clean
- `otb_timeseries` 破坏性 rollback

## English

OpenTenBase PluginCtl is a CLI-first lifecycle governance tool for OpenTenBase distributed plugins.

It is not a general database operations platform and not a plugin marketplace. Its focus is plugin governance: making OpenTenBase plugins inspectable, plannable, verifiable, rollback-aware, and traceable.

It is built on the DataNexus plugin governance model.

## Positioning

- OpenTenBase only
- CLI first
- Plugin governance first
- Built for distributed plugin lifecycle management
- Current focus: single-plugin lifecycle closure and sample-plugin validation

## Implemented Capabilities

Basic commands:

```bash
python -m datanexus list
python -m datanexus inspect <plugin_id>
python -m datanexus doctor
python -m datanexus report
python -m datanexus report --json
```

Lifecycle commands:

```bash
python -m datanexus deploy <plugin_id>
python -m datanexus verify <plugin_id>
python -m datanexus rollback <plugin_id>
python -m datanexus rollback <plugin_id> --execute
python -m datanexus state <plugin_id>
```

Plugin governance commands:

```bash
python -m datanexus plugin lint <plugin_id>
python -m datanexus plugin plan <plugin_id>
python -m datanexus plugin precheck <plugin_id>
python -m datanexus plugin diagnose <plugin_id>
python -m datanexus plugin check <plugin_id>
python -m datanexus plugin status <plugin_id>
python -m datanexus plugin roles <plugin_id>
python -m datanexus plugin consistency <plugin_id>
python -m datanexus plugin archive list
python -m datanexus plugin archive inspect <plugin_id>
python -m datanexus plugins status
python -m datanexus plugins status --json
```

Meaning:

- `lint`: checks only the manifest and package files. It does not connect to the database.
- `plan`: generates a non-executing lifecycle plan. It may run `installed_probe` only to detect install state.
- `precheck`: runs read-only pre-deploy checks for package files, connectivity, version visibility, target roles, registered nodes, and remote staging readiness.
- `diagnose`: aggregates `lint / plan / precheck` into a user-facing conclusion, next action, and risk summary.
- `roles`: shows role-scoped governance steps for coordinator / datanode targets.
- `consistency`: checks plugin-centered consistency across archive, manifest, package files, probes, roles, and runtime state.
- `archive`: queries local plugin package governance snapshots. It does not replace action-level `state/report`.

M3 also supports declarative role hooks: `preinstall / postinstall / preuninstall / postuninstall`. Hooks are planned, linted, archived, and checked for consistency, but they are not executed automatically.

## Plugin Layout

```text
catalog/plugins/
examples/plugins/
src/datanexus/
tests/
docs/
recipes/
```

- `catalog/plugins/`: manifests for existing plugin payloads.
- `examples/plugins/`: controlled sample plugins for platform validation.
- `src/datanexus/`: DataNexus platform core.
- `tests/`: platform unit tests.
- `docs/`: M0/M1/M2 documents and issue records.

## Current Plugins

`dnx_smoke_plugin` is the platform lifecycle validation plugin. It is small, safe, and repeatable for deploy, verify, and rollback.

`otb_timeseries` is a real OpenTenBase plugin payload. DataNexus can detect its installed state and run smoke verification. It does not have destructive rollback support, and its chunk distribution warning is tracked separately.

## Recommended Flow

```bash
python -m datanexus plugin lint dnx_smoke_plugin
python -m datanexus plugin plan dnx_smoke_plugin
python -m datanexus plugin precheck dnx_smoke_plugin
python -m datanexus plugin diagnose dnx_smoke_plugin
python -m datanexus deploy dnx_smoke_plugin
python -m datanexus verify dnx_smoke_plugin
python -m datanexus report
```

Rollback for the sample plugin:

```bash
python -m datanexus rollback dnx_smoke_plugin
python -m datanexus rollback dnx_smoke_plugin --execute
python -m datanexus verify dnx_smoke_plugin --removed
```

`rollback` defaults to dry-run. It executes only when `--execute` is explicitly provided and the manifest declares `rollback_sql`.

## Local Usage

```bash
cd <repo-dir>
set PYTHONPATH=src
python -m datanexus plugins status
```

PowerShell:

```powershell
cd <repo-dir>
$env:PYTHONPATH = "src"
python -m datanexus plugins status
```

Run tests:

```bash
python -m unittest discover -s tests -v
```

## Language

Human-readable plugin governance commands default to Chinese output.

```bash
python -m datanexus plugin status otb_timeseries
python -m datanexus plugin status otb_timeseries --lang en
python -m datanexus plugin status otb_timeseries --lang both
```

JSON output keeps stable English keys for automation.

## Stage Status

- M0: CLI skeleton and base loop are frozen.
- M1: `dnx_smoke_plugin` has completed repeatable lifecycle validation.
- M2: plugin governance flow is in place: `lint -> plan -> precheck -> diagnose -> deploy -> verify -> report`.
- M3: distributed plugin package governance has started: `archive/state -> roles/hooks -> consistency`.

Documents:

- [M0_BASELINE.md](docs/M0_BASELINE.md)
- [M1_STATUS.md](docs/M1_STATUS.md)
- [M2_PLUGIN_GOVERNANCE.md](docs/M2_PLUGIN_GOVERNANCE.md)
- [M2_GOVERNANCE_FLOW.md](docs/M2_GOVERNANCE_FLOW.md)
- [M3_ARCHIVE_AND_CONSISTENCY.md](docs/M3_ARCHIVE_AND_CONSISTENCY.md)

## Current Boundaries

Not included for now:

- Web UI
- Plugin marketplace
- Batch deploy
- Automatic repair
- Cross-database adapters
- Node sync / clean
- Destructive rollback for `otb_timeseries`
