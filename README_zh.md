# OpenTenBase PluginCtl

[English](README.md) | [简体中文](README_zh.md)

OpenTenBase PluginCtl 是一个面向 OpenTenBase 插件的命令行工具，用于管理插件在本地 Docker 沙盒和分布式 OpenTenBase 集群中的生命周期。

它关注的是插件交付与治理，而不是泛数据库运维：

- 插件包检查
- 部署计划生成
- 物理载荷分发
- Coordinator 侧扩展激活
- 分布式白盒验证
- 本地生命周期报告

它不是 OpenTenBase 运维平台，不是 Web 控制台，也不是插件市场。

## 当前状态

当前仓库是一个源码发布基线。它已经可以作为 CLI 项目使用，但仍应视为早期工具。

当前主要验证流程是：

```bash
python -m plugin_ctl check <plugin_id>
python -m plugin_ctl deploy <plugin_id> -f cluster.toml --execute
python -m plugin_ctl activate <plugin_id> -f cluster.toml --execute
python -m plugin_ctl verify <plugin_id> -f cluster.toml
python -m plugin_ctl report
```

本地 Docker 沙盒流程仍然保留：

```bash
python -m plugin_ctl deploy <plugin_id>
python -m plugin_ctl verify <plugin_id>
python -m plugin_ctl rollback <plugin_id>
python -m plugin_ctl report
```

## 安装

环境要求：

- Python 3.11+
- `pip`
- Docker，仅本地 OpenTenBase 沙盒流程需要
- `ssh`、`scp`、`psql`，仅分布式集群流程需要

从源码安装：

```bash
git clone https://github.com/iamkuangzhang/opentenbase-plugin_ctl.git
cd opentenbase-plugin_ctl
python -m pip install -e .
```

验证命令行工具：

```bash
plugin_ctl list
python -m plugin_ctl list
```

## 快速开始

查看已声明的插件：

```bash
python -m plugin_ctl list
```

查看某个插件的 manifest：

```bash
python -m plugin_ctl inspect pluginctl_smoke_plugin
```

运行不依赖 Docker 或真实数据库的插件包检查：

```bash
python -m plugin_ctl plugin lint pluginctl_smoke_plugin
python -m plugin_ctl plugin plan pluginctl_smoke_plugin
```

查看本地 action 报告：

```bash
python -m plugin_ctl report
```

## 分布式集群流程

复制集群拓扑样例并按实际环境修改：

```powershell
copy cluster.toml.example cluster.toml
```

Linux/macOS：

```bash
cp cluster.toml.example cluster.toml
```

检查集群拓扑：

```bash
python -m plugin_ctl cluster inspect -f cluster.toml
```

预览物理分发计划：

```bash
python -m plugin_ctl deploy pluginctl_smoke_plugin -f cluster.toml
```

执行物理分发：

```bash
python -m plugin_ctl deploy pluginctl_smoke_plugin -f cluster.toml --execute
```

在 Coordinator 上激活扩展：

```bash
python -m plugin_ctl activate pluginctl_smoke_plugin -f cluster.toml --execute
```

执行分布式白盒验证：

```bash
python -m plugin_ctl verify pluginctl_smoke_plugin -f cluster.toml
```

JSON 输出适合自动化集成：

```bash
python -m plugin_ctl verify pluginctl_smoke_plugin -f cluster.toml --json
python -m plugin_ctl report --json
```

## 主命令说明

### `check`

```bash
python -m plugin_ctl check <plugin_id>
```

执行聚合治理检查，内部组合了插件包 lint、生命周期 plan、部署前 precheck 和 diagnose。

它不会修改数据库，也不会写远端文件系统。但它可能会检查本地 runtime，因此 Docker 或 OpenTenBase 未运行时会报告环境失败。

### `deploy`

本地 Docker 沙盒模式：

```bash
python -m plugin_ctl deploy <plugin_id>
```

分布式物理分发模式：

```bash
python -m plugin_ctl deploy <plugin_id> -f cluster.toml
python -m plugin_ctl deploy <plugin_id> -f cluster.toml --execute
```

带 `-f cluster.toml` 时，`deploy` 只代表物理文件分发：

- `.so` 文件复制到每个节点的 `lib_dir`
- `.control` 和 `.sql` 文件复制到每个节点的 `extension_dir`
- 复制后读取远端 SHA256 并与本地文件对账
- 不执行 `CREATE EXTENSION`

不传 `--execute` 时，命令只生成 dry-run 计划。

### `activate`

```bash
python -m plugin_ctl activate <plugin_id> -f cluster.toml
python -m plugin_ctl activate <plugin_id> -f cluster.toml --execute
```

在 Coordinator 节点上激活扩展元数据。

传入 `--execute` 后，会按 Coordinator 顺序串行执行：

```sql
CREATE EXTENSION IF NOT EXISTS <extension_name>;
```

随后会检查所有 Coordinator 上的扩展版本是否一致。

该命令不复制文件，也不连接 Datanode。

### `verify`

本地 smoke 验证：

```bash
python -m plugin_ctl verify <plugin_id>
```

分布式白盒验证：

```bash
python -m plugin_ctl verify <plugin_id> -f cluster.toml
```

分布式验证是只读的，会检查：

- Coordinator 上 extension 是否安装、版本是否一致
- CN/DN SQL 连通性
- CN/DN 上物理 payload 文件的 SHA256
- `pg_prepared_xacts` 中是否存在 prepared transaction 残留

### `report`

```bash
python -m plugin_ctl report
python -m plugin_ctl report --json
```

展示 PluginCtl 写入的本地 action 记录。它适合做 CLI 审计记录，但不能替代真实数据库状态验证。

## 高级命令

以下命令用于排查问题和底层检查。普通用户优先使用主流程命令。

```bash
python -m plugin_ctl plugin lint <plugin_id>
python -m plugin_ctl plugin plan <plugin_id>
python -m plugin_ctl plugin precheck <plugin_id>
python -m plugin_ctl plugin diagnose <plugin_id>
python -m plugin_ctl plugin status <plugin_id>
python -m plugin_ctl plugin roles <plugin_id>
python -m plugin_ctl plugin consistency <plugin_id>
python -m plugin_ctl plugin archive list
python -m plugin_ctl plugin archive inspect <plugin_id>
python -m plugin_ctl plugins status
python -m plugin_ctl cluster distribute --dry-run -f cluster.toml <plugin_id>
python -m plugin_ctl cluster distribute --execute -f cluster.toml <plugin_id>
python -m plugin_ctl cluster status
python -m plugin_ctl doctor
```

## 插件包结构

插件由 manifest 和 payload 文件组成。

示例：

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

manifest 负责声明：

- 插件 ID 和版本
- 目标数据库
- payload 根目录
- install、verify、smoke、rollback SQL
- installed 和 removed probe
- 分布式角色要求
- 可选生命周期 hooks

## 仓库结构

```text
catalog/plugins/       插件 payload 的 reference manifests
examples/plugins/      内置示例插件和 legacy payload fixtures
recipes/               smoke 验证 SQL
src/plugin_ctl/        Python 包实现
tests/                 单元测试
docs/                  设计与状态文档
cluster.toml.example   分布式集群拓扑样例
```

## 内置插件

### `pluginctl_smoke_plugin`

一个小型示例插件，用于验证 PluginCtl 自身能力。它支持 deploy、verify、rollback 和 removed verification。

第一次测试工具时建议先使用它。

### `otb_timeseries`

真实 OpenTenBase 时序插件的 reference manifest。它适合用于治理视角和已安装状态检查，但当前发布仓库不应被视为该插件完整干净安装链路的证明。

## 安全边界

重要假设：

- `cluster.toml` 是可信管理员配置。
- PluginCtl 不把拓扑文件当作未可信输入处理。
- `deploy -f --execute` 会通过 `scp` 写远端 payload 文件。
- `activate -f --execute` 会通过 `CREATE EXTENSION` 修改 Coordinator 元数据。
- `verify -f` 是只读验证。
- rollback 是 best-effort，且必须显式传入 `--execute` 才会执行。

实现层面的安全边界：

- `psql`、`ssh`、`scp`、`docker` 都使用参数列表调用。
- 不使用 `shell=True`。
- extension name 会经过 PostgreSQL identifier 校验后再生成 SQL。
- 不自动创建远端系统目录。
- 不自动使用 `sudo`。

## 当前不做

PluginCtl 当前不实现：

- 自动编译插件源码
- 自动修复远端节点状态
- 自动 rollback Coordinator 激活
- Web UI
- 插件市场
- 批量部署和批量升级编排
- OpenTenBase 之外的跨数据库支持
- `otb_timeseries` 专用深度验证 profile

## 开发

运行测试：

```bash
python -m unittest discover -s tests -v
```

检查空白字符问题：

```bash
git diff --check
```

当前测试基线：

```text
109 unit tests
```

## 文档

- [M3 Distributed Lifecycle](docs/M3_DISTRIBUTED_LIFECYCLE.md)
- [M3 Final Status](docs/M3_FINAL_STATUS.md)
- [M3 Archive And Consistency](docs/M3_ARCHIVE_AND_CONSISTENCY.md)
- [M2 Plugin Governance](docs/M2_PLUGIN_GOVERNANCE.md)
- [Release Checklist](docs/RELEASE_CHECKLIST.md)
