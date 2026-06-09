# OpenTenBase PluginCtl

[简体中文](#简体中文) | [English](#english)

## 简体中文

OpenTenBase PluginCtl 是一个面向 OpenTenBase 的分布式插件生命周期管理工具。

它的重点不是做通用数据库运维平台，也不是 Web 控制台或插件市场，而是帮助用户把 PostgreSQL / OpenTenBase 插件从“有一堆文件和 SQL”推进到“可检查、可规划、可部署、可注册、可验证、可追踪”的工程化插件包。

当前版本定位：`v0.1.0` source release。它已经可以作为 CLI 工具试用，但仍属于早期版本，不建议直接当作生产环境自动化发布系统。

### 它能做什么

- 发现和查看插件 manifest。
- 静态扫描 PostgreSQL 插件源码，评估迁移到 OpenTenBase 的分布式风险。
- 检查插件包结构是否合格。
- 生成部署、验证、回滚计划。
- 对本地 OpenTenBase Docker / Linux 环境执行安全样例插件的 deploy / verify / rollback。
- 在分布式拓扑下分发插件物理文件。
- 只在 primary coordinator 上执行一次扩展注册，然后只读验证其他 coordinator 的扩展视图。
- 做分布式白盒验证，包括 CN/DN 连接、扩展版本、payload 文件 checksum、prepared transaction 残留等。
- 记录插件 action state、archive、report。
- 按 coordinator / datanode / all 角色展示插件治理计划。

### 它不是什么

PluginCtl 当前不是：

- OpenTenBase 集群运维平台
- Web UI
- 插件市场
- 多数据库适配层
- 批量部署和自动升级系统
- 自动修复工具
- 生产级回滚系统

### 安装

环境要求：

- Python 3.11+
- pip
- Docker，可选，仅用于本地 OpenTenBase 沙箱流程
- `psql`、`ssh`、`scp`，可选，仅用于分布式集群流程

从源码安装：

```bash
git clone https://github.com/iamkuangzhang/opentenbase-pluginctl.git
cd opentenbase-pluginctl
python -m pip install -e .
```

验证命令是否可用：

```bash
opentenbase-pluginctl list
```

推荐使用 `opentenbase-pluginctl`。`python -m plugin_ctl` 保留给开发和调试使用。

### 5 分钟试用

内置的 `pluginctl_smoke_plugin` 是一个安全样例插件，用来验证 PluginCtl 自己的生命周期能力。建议先用它试，不要一开始就拿真实业务插件做破坏性实验。

```bash
opentenbase-pluginctl list
opentenbase-pluginctl inspect pluginctl_smoke_plugin
opentenbase-pluginctl check pluginctl_smoke_plugin
opentenbase-pluginctl deploy pluginctl_smoke_plugin
opentenbase-pluginctl verify pluginctl_smoke_plugin
opentenbase-pluginctl report
```

更细的治理命令，例如 `plugin lint`、`plugin plan`、`plugin precheck`、`plugin diagnose`，可以在需要排查问题时单独运行。

如果要执行回滚，必须显式加 `--execute`：

```bash
opentenbase-pluginctl rollback pluginctl_smoke_plugin
opentenbase-pluginctl rollback pluginctl_smoke_plugin --execute
opentenbase-pluginctl verify pluginctl_smoke_plugin --removed
```

### 分布式插件包流程

先复制并修改拓扑文件：

```bash
cp cluster.toml.example cluster.toml
```

Windows PowerShell：

```powershell
Copy-Item cluster.toml.example cluster.toml
```

检查拓扑：

```bash
opentenbase-pluginctl cluster inspect -f cluster.toml
```

推荐的完整分布式流程：

```bash
opentenbase-pluginctl assess ./pg_extension_source/
opentenbase-pluginctl check pluginctl_smoke_plugin
opentenbase-pluginctl deploy pluginctl_smoke_plugin -f cluster.toml
opentenbase-pluginctl deploy pluginctl_smoke_plugin -f cluster.toml --execute
opentenbase-pluginctl register pluginctl_smoke_plugin -f cluster.toml
opentenbase-pluginctl register pluginctl_smoke_plugin -f cluster.toml --execute
opentenbase-pluginctl verify pluginctl_smoke_plugin -f cluster.toml
opentenbase-pluginctl plugin consistency pluginctl_smoke_plugin
opentenbase-pluginctl report
```

这里有三个重要边界：

- `deploy -f cluster.toml` 默认 dry-run，只展示物理文件分发计划。
- `deploy -f cluster.toml --execute` 只分发文件，不执行 `CREATE EXTENSION`。
- `register -f cluster.toml --execute` 只在 `cluster.toml` 中第一个 coordinator 上执行一次 `CREATE EXTENSION`，然后只读检查其他 coordinator 的 `pg_extension` 视图。

### 常用命令

#### 插件发现

```bash
opentenbase-pluginctl list
opentenbase-pluginctl inspect <plugin_id>
```

#### 源码迁移风险评估

```bash
opentenbase-pluginctl assess <pg_extension_source_path>
opentenbase-pluginctl assess <pg_extension_source_path> --json
```

`assess` 不编译代码、不连接数据库、不修改文件。它会静态检查：

- 是否存在 `.control` 文件
- 是否存在 SQL 安装或升级文件
- `LANGUAGE C` 函数是否显式声明 `SHIPPABLE` 或 `NOT SHIPPABLE`
- C 代码里是否存在 `SPI_execute` 风格的动态建表 DDL
- 事务控制、系统 catalog 访问等需要分布式审查的风险点

#### 插件治理

```bash
opentenbase-pluginctl check <plugin_id>
opentenbase-pluginctl plugin lint <plugin_id>
opentenbase-pluginctl plugin plan <plugin_id>
opentenbase-pluginctl plugin precheck <plugin_id>
opentenbase-pluginctl plugin diagnose <plugin_id>
opentenbase-pluginctl plugin status <plugin_id>
opentenbase-pluginctl plugins status
```

#### 生命周期

```bash
opentenbase-pluginctl deploy <plugin_id>
opentenbase-pluginctl verify <plugin_id>
opentenbase-pluginctl rollback <plugin_id>
opentenbase-pluginctl rollback <plugin_id> --execute
opentenbase-pluginctl verify <plugin_id> --removed
```

#### 分布式插件治理

```bash
opentenbase-pluginctl cluster inspect -f cluster.toml
opentenbase-pluginctl deploy <plugin_id> -f cluster.toml
opentenbase-pluginctl deploy <plugin_id> -f cluster.toml --execute
opentenbase-pluginctl register <plugin_id> -f cluster.toml
opentenbase-pluginctl register <plugin_id> -f cluster.toml --execute
opentenbase-pluginctl verify <plugin_id> -f cluster.toml
opentenbase-pluginctl plugin roles <plugin_id>
opentenbase-pluginctl plugin consistency <plugin_id>
```

#### 归档和报告

```bash
opentenbase-pluginctl plugin archive list
opentenbase-pluginctl plugin archive inspect <plugin_id>
opentenbase-pluginctl state <plugin_id>
opentenbase-pluginctl report
opentenbase-pluginctl report --json
```

#### 运行时检查

```bash
opentenbase-pluginctl doctor
opentenbase-pluginctl cluster status
```

这些命令只作为插件管理的支撑，不是为了把 PluginCtl 做成泛集群巡检平台。

### 插件包结构

样例插件目录：

```text
examples/plugins/pluginctl_smoke_plugin/
  manifest.yml
  payload/
    sql/
      install.sql
      verify.sql
      rollback.sql
    hooks/
      preinstall.sql
      postinstall.sql
      preuninstall.sql
      postuninstall.sql
```

manifest 通常声明：

- `plugin_id`
- `name`
- `version`
- `database`
- `targets`
- `payload`
- `install_sql`
- `verify_sql`
- `rollback_sql`
- `installed_probe`
- `removed_probe`
- `distributed`
- 可选 role hooks

### 内置插件

#### `pluginctl_smoke_plugin`

安全样例插件，用于验证 PluginCtl 的 deploy / verify / rollback / removed verify / archive / consistency 流程。

这是推荐的入门测试插件。

#### `otb_timeseries`

真实 OpenTenBase 时序插件的 reference manifest。它用于展示真实业务插件的治理和状态检查，但当前发布仓库不把它声明为完整 bundled package。

注意：不要对 `otb_timeseries` 执行破坏性 rollback。

### 仓库结构

```text
catalog/plugins/       reference manifests
examples/plugins/      bundled sample plugins and fixtures
recipes/               smoke verification SQL
src/plugin_ctl/        Python implementation
tests/                 unit tests
docs/                  design and release documents
cluster.toml.example   distributed topology example
```

### 安全边界

只读或近似只读命令：

- `list`
- `inspect`
- `assess`
- `plugin lint`
- `plugin plan`
- `plugin precheck`
- `plugin diagnose`
- `plugin roles`
- `plugin consistency`
- `plugin archive list`
- `plugin archive inspect`
- `plugins status`
- `verify -f`
- `report`

会修改数据库或文件系统的命令：

- `deploy <plugin_id>`：本地模式会执行安装 SQL。
- `deploy <plugin_id> -f cluster.toml --execute`：会通过 `scp` 分发远程文件。
- `register <plugin_id> -f cluster.toml --execute`：会在 primary coordinator 上执行 `CREATE EXTENSION`。
- `rollback <plugin_id> --execute`：会执行 manifest 声明的 `rollback_sql`。

当前 role hooks 只进入 plan / roles / diagnose，不会自动执行。未来如果支持执行 hook，也必须要求显式参数，例如 `--execute-hooks`。

### 开发

运行测试：

```bash
python -m unittest discover -s tests -v
```

检查空白错误：

```bash
git diff --check
```

当前测试基线：

```text
120 tests
```

### 文档

- [M3 Distributed Lifecycle](docs/M3_DISTRIBUTED_LIFECYCLE.md)
- [M3 Final Status](docs/M3_FINAL_STATUS.md)
- [M3 Archive And Consistency](docs/M3_ARCHIVE_AND_CONSISTENCY.md)
- [M2 Plugin Governance](docs/M2_PLUGIN_GOVERNANCE.md)
- [Release Checklist](docs/RELEASE_CHECKLIST.md)

---

## English

OpenTenBase PluginCtl is a CLI tool for distributed plugin lifecycle governance on OpenTenBase.

It is not a general-purpose OpenTenBase operations platform, a Web console, or a plugin marketplace. Its purpose is to turn PostgreSQL / OpenTenBase plugin payloads into packages that can be inspected, planned, deployed, registered, verified, archived, and audited.

Current status: `v0.1.0` source release. It is usable as an early CLI baseline, but it should not be treated as a production-grade automation system yet.

### What It Does

- Discovers and inspects plugin manifests.
- Statically assesses PostgreSQL extension source trees for OpenTenBase migration risks.
- Lints plugin package structure.
- Builds deploy, verify, and rollback plans.
- Runs local deploy / verify / rollback flows for the bundled smoke plugin.
- Distributes plugin payload files across a declared OpenTenBase topology.
- Registers extension metadata once on the primary coordinator, then verifies coordinator views with read-only queries.
- Runs distributed white-box verification for coordinator/datanode connectivity, extension versions, payload checksums, and prepared transaction residue.
- Records action state, archive metadata, and reports.
- Shows role-scoped governance plans for coordinator / datanode / all targets.

### What It Is Not

PluginCtl is currently not:

- an OpenTenBase cluster operations platform
- a Web UI
- a plugin marketplace
- a multi-database adapter
- a batch deployment and upgrade system
- an automatic repair tool
- a production-grade rollback system

### Installation

Requirements:

- Python 3.11+
- pip
- Docker, optional, for the local OpenTenBase sandbox flow
- `psql`, `ssh`, and `scp`, optional, for distributed cluster operations

Install from source:

```bash
git clone https://github.com/iamkuangzhang/opentenbase-pluginctl.git
cd opentenbase-pluginctl
python -m pip install -e .
```

Verify the CLI:

```bash
opentenbase-pluginctl list
```

`opentenbase-pluginctl` is the recommended command. `python -m plugin_ctl` is kept for development and debugging.

### 5-Minute Trial

The bundled `pluginctl_smoke_plugin` is a safe sample plugin for testing PluginCtl itself. Use it before trying real business plugins.

```bash
opentenbase-pluginctl list
opentenbase-pluginctl inspect pluginctl_smoke_plugin
opentenbase-pluginctl check pluginctl_smoke_plugin
opentenbase-pluginctl deploy pluginctl_smoke_plugin
opentenbase-pluginctl verify pluginctl_smoke_plugin
opentenbase-pluginctl report
```

Lower-level governance commands such as `plugin lint`, `plugin plan`, `plugin precheck`, and `plugin diagnose` can be run separately when troubleshooting.

Rollback requires explicit execution:

```bash
opentenbase-pluginctl rollback pluginctl_smoke_plugin
opentenbase-pluginctl rollback pluginctl_smoke_plugin --execute
opentenbase-pluginctl verify pluginctl_smoke_plugin --removed
```

### Distributed Plugin Package Workflow

Copy and edit the topology file:

```bash
cp cluster.toml.example cluster.toml
```

Windows PowerShell:

```powershell
Copy-Item cluster.toml.example cluster.toml
```

Inspect the topology:

```bash
opentenbase-pluginctl cluster inspect -f cluster.toml
```

Recommended distributed workflow:

```bash
opentenbase-pluginctl assess ./pg_extension_source/
opentenbase-pluginctl check pluginctl_smoke_plugin
opentenbase-pluginctl deploy pluginctl_smoke_plugin -f cluster.toml
opentenbase-pluginctl deploy pluginctl_smoke_plugin -f cluster.toml --execute
opentenbase-pluginctl register pluginctl_smoke_plugin -f cluster.toml
opentenbase-pluginctl register pluginctl_smoke_plugin -f cluster.toml --execute
opentenbase-pluginctl verify pluginctl_smoke_plugin -f cluster.toml
opentenbase-pluginctl plugin consistency pluginctl_smoke_plugin
opentenbase-pluginctl report
```

Important boundaries:

- `deploy -f cluster.toml` is dry-run by default.
- `deploy -f cluster.toml --execute` distributes files only; it does not run `CREATE EXTENSION`.
- `register -f cluster.toml --execute` runs `CREATE EXTENSION` once on the first coordinator in `cluster.toml`, then checks other coordinators through read-only `pg_extension` queries.

### Common Commands

#### Discovery

```bash
opentenbase-pluginctl list
opentenbase-pluginctl inspect <plugin_id>
```

#### Source Migration Assessment

```bash
opentenbase-pluginctl assess <pg_extension_source_path>
opentenbase-pluginctl assess <pg_extension_source_path> --json
```

`assess` does not compile code, connect to a database, or modify files. It statically checks:

- `.control` file presence
- SQL install/update file presence
- `LANGUAGE C` functions without explicit `SHIPPABLE` or `NOT SHIPPABLE`
- C-side dynamic table DDL through `SPI_execute`-style calls
- transaction-control and system-catalog access patterns that need distributed review

#### Governance

```bash
opentenbase-pluginctl check <plugin_id>
opentenbase-pluginctl plugin lint <plugin_id>
opentenbase-pluginctl plugin plan <plugin_id>
opentenbase-pluginctl plugin precheck <plugin_id>
opentenbase-pluginctl plugin diagnose <plugin_id>
opentenbase-pluginctl plugin status <plugin_id>
opentenbase-pluginctl plugins status
```

#### Lifecycle

```bash
opentenbase-pluginctl deploy <plugin_id>
opentenbase-pluginctl verify <plugin_id>
opentenbase-pluginctl rollback <plugin_id>
opentenbase-pluginctl rollback <plugin_id> --execute
opentenbase-pluginctl verify <plugin_id> --removed
```

#### Distributed Governance

```bash
opentenbase-pluginctl cluster inspect -f cluster.toml
opentenbase-pluginctl deploy <plugin_id> -f cluster.toml
opentenbase-pluginctl deploy <plugin_id> -f cluster.toml --execute
opentenbase-pluginctl register <plugin_id> -f cluster.toml
opentenbase-pluginctl register <plugin_id> -f cluster.toml --execute
opentenbase-pluginctl verify <plugin_id> -f cluster.toml
opentenbase-pluginctl plugin roles <plugin_id>
opentenbase-pluginctl plugin consistency <plugin_id>
```

#### Archive And Reporting

```bash
opentenbase-pluginctl plugin archive list
opentenbase-pluginctl plugin archive inspect <plugin_id>
opentenbase-pluginctl state <plugin_id>
opentenbase-pluginctl report
opentenbase-pluginctl report --json
```

#### Runtime Checks

```bash
opentenbase-pluginctl doctor
opentenbase-pluginctl cluster status
```

These commands support plugin management. They are not meant to turn PluginCtl into a generic cluster monitoring platform.

### Plugin Package Layout

Example:

```text
examples/plugins/pluginctl_smoke_plugin/
  manifest.yml
  payload/
    sql/
      install.sql
      verify.sql
      rollback.sql
    hooks/
      preinstall.sql
      postinstall.sql
      preuninstall.sql
      postuninstall.sql
```

A manifest typically declares:

- `plugin_id`
- `name`
- `version`
- `database`
- `targets`
- `payload`
- `install_sql`
- `verify_sql`
- `rollback_sql`
- `installed_probe`
- `removed_probe`
- `distributed`
- optional role hooks

### Included Plugins

#### `pluginctl_smoke_plugin`

A safe sample plugin used to validate PluginCtl's deploy / verify / rollback / removed verify / archive / consistency flow.

This is the recommended first test plugin.

#### `otb_timeseries`

A reference manifest for a real OpenTenBase time-series plugin. It is useful for governance and state checks, but the current published repository does not claim it as a complete bundled package.

Do not run destructive rollback against `otb_timeseries`.

### Repository Layout

```text
catalog/plugins/       reference manifests
examples/plugins/      bundled sample plugins and fixtures
recipes/               smoke verification SQL
src/plugin_ctl/        Python implementation
tests/                 unit tests
docs/                  design and release documents
cluster.toml.example   distributed topology example
```

### Safety Boundary

Read-only or mostly read-only commands:

- `list`
- `inspect`
- `assess`
- `plugin lint`
- `plugin plan`
- `plugin precheck`
- `plugin diagnose`
- `plugin roles`
- `plugin consistency`
- `plugin archive list`
- `plugin archive inspect`
- `plugins status`
- `verify -f`
- `report`

Commands that modify the database or filesystem:

- `deploy <plugin_id>`: local mode runs install SQL.
- `deploy <plugin_id> -f cluster.toml --execute`: copies remote files through `scp`.
- `register <plugin_id> -f cluster.toml --execute`: runs `CREATE EXTENSION` on the primary coordinator.
- `rollback <plugin_id> --execute`: runs the manifest-declared `rollback_sql`.

Role hooks are currently planned and displayed in plan / roles / diagnose only. If hook execution is added in the future, it must require an explicit flag such as `--execute-hooks`.

### Development

Run tests:

```bash
python -m unittest discover -s tests -v
```

Check whitespace errors:

```bash
git diff --check
```

Current test baseline:

```text
120 tests
```

### Documentation

- [M3 Distributed Lifecycle](docs/M3_DISTRIBUTED_LIFECYCLE.md)
- [M3 Final Status](docs/M3_FINAL_STATUS.md)
- [M3 Archive And Consistency](docs/M3_ARCHIVE_AND_CONSISTENCY.md)
- [M2 Plugin Governance](docs/M2_PLUGIN_GOVERNANCE.md)
- [Release Checklist](docs/RELEASE_CHECKLIST.md)
