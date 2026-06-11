# OpenTenBase PluginCtl

[English](README.md)

OpenTenBase PluginCtl 是一个面向 OpenTenBase 的插件生命周期治理工具。

它关注插件包的发现、检查、规划、部署、注册、验证、回滚、归档和报告。它不是通用 OpenTenBase 运维平台，不是 Web 控制台，也不是插件市场。

当前支持的命令入口是：

```bash
plugin_ctl
```

## 安装

```bash
git clone https://github.com/iamkuangzhang/opentenbase-plugin_ctl.git
cd opentenbase-plugin_ctl
python -m pip install -e .
```

验证：

```bash
plugin_ctl list
plugin_ctl --help
```

## 接入外部插件

PluginCtl 不要求你把插件复制到它的安装目录。你可以把插件包放在任意位置，只要插件目录里有 `manifest.yml` 或 `plugin.yml`，然后登记这个路径：

```bash
plugin_ctl add /path/to/xxx_plugin
plugin_ctl list
plugin_ctl inspect xxx_plugin
```

这个命令只会把路径写入当前用户的 `~/.plugin_ctl/catalog.json`，插件文件仍然留在原目录。删除登记项：

```bash
plugin_ctl remove xxx_plugin
```

## 5 分钟试用

建议先测试内置的 `pluginctl_smoke_plugin`。它是安全样例插件，用来验证 PluginCtl 自己的生命周期能力。

```bash
plugin_ctl init
plugin_ctl list
plugin_ctl inspect pluginctl_smoke_plugin
plugin_ctl check pluginctl_smoke_plugin
plugin_ctl deploy pluginctl_smoke_plugin
plugin_ctl register pluginctl_smoke_plugin
plugin_ctl verify pluginctl_smoke_plugin
plugin_ctl report
```

回滚会执行 manifest 声明的回滚 SQL。如果只想预览，请先加 `--dry-run`：

```bash
plugin_ctl rollback pluginctl_smoke_plugin --dry-run
plugin_ctl rollback pluginctl_smoke_plugin
plugin_ctl verify pluginctl_smoke_plugin --removed
```

## 交互式插件控制台

直接运行：

```bash
plugin_ctl
```

或者显式进入：

```bash
plugin_ctl shell
```

示例：

```text
OpenTenBase PluginCtl Shell
Type "help" to show commands.
Type "quit" or "exit" to leave.

pluginctl> list
pluginctl> init
pluginctl> add /path/to/xxx_plugin
pluginctl> check pluginctl_smoke_plugin
pluginctl> deploy pluginctl_smoke_plugin
pluginctl> register pluginctl_smoke_plugin
pluginctl> verify pluginctl_smoke_plugin
pluginctl> plugin lint pluginctl_smoke_plugin
pluginctl> plugin diagnose pluginctl_smoke_plugin
pluginctl> plugin archive list
pluginctl> plugins status --json
pluginctl> cluster inspect
pluginctl> report
pluginctl> remove xxx_plugin
pluginctl> quit
```

PluginCtl Shell 是插件生命周期控制台，支持和 `plugin_ctl` 基本一致的命令组；进入 shell 后省略前面的 `plugin_ctl`，直接输入子命令即可。它不是 OpenTenBase 集群控制台，不负责集群启动、停止、初始化或监控。

## 分布式流程

复制并修改拓扑文件：

```bash
plugin_ctl init
```

检查拓扑：

```bash
plugin_ctl cluster inspect
```

预览或执行物理文件分发。`deploy` 必须先有 `cluster.toml`；请先执行 `plugin_ctl init`，或者手动传入 `-f cluster.toml`。

```bash
plugin_ctl deploy pluginctl_smoke_plugin --dry-run
plugin_ctl deploy pluginctl_smoke_plugin
```

预览或执行扩展注册：

```bash
plugin_ctl register pluginctl_smoke_plugin --dry-run
plugin_ctl register pluginctl_smoke_plugin
```

验证：

```bash
plugin_ctl verify pluginctl_smoke_plugin
plugin_ctl plugin consistency pluginctl_smoke_plugin
plugin_ctl report
```

重要边界：

- `deploy` 永远要求集群配置。它不再回退到旧的本地 install SQL 逻辑。
- `deploy` 只分发插件载荷文件，不执行 `CREATE EXTENSION`；`deploy --dry-run` 只预览。
- `register` 只在 `cluster.toml` 中第一个 coordinator 上执行一次 `CREATE EXTENSION`，然后只读检查其他 coordinator 的 `pg_extension` 视图；`register --dry-run` 只预览。
- `activate` 仅作为 `register` 的旧兼容别名保留。新的文档和脚本应统一使用 `register`。

## 命令清单

插件发现：

```bash
plugin_ctl add <plugin_dir_or_manifest>
plugin_ctl remove <plugin_id>
plugin_ctl list
plugin_ctl inspect <plugin_id>
plugin_ctl plugin add <plugin_dir_or_manifest>
plugin_ctl plugin remove <plugin_id>
```

源码迁移评估：

```bash
plugin_ctl assess <pg_extension_source_path>
plugin_ctl assess <pg_extension_source_path> --json
```

插件治理：

```bash
plugin_ctl check <plugin_id>
plugin_ctl plugin lint <plugin_id>
plugin_ctl plugin plan <plugin_id>
plugin_ctl plugin precheck <plugin_id>
plugin_ctl plugin diagnose <plugin_id>
plugin_ctl plugin status <plugin_id>
plugin_ctl plugins status
```

生命周期：

```bash
plugin_ctl deploy <plugin_id>
plugin_ctl verify <plugin_id>
plugin_ctl rollback <plugin_id> --dry-run
plugin_ctl rollback <plugin_id>
plugin_ctl verify <plugin_id> --removed
```

分布式插件治理：

```bash
plugin_ctl init
plugin_ctl cluster inspect
plugin_ctl deploy <plugin_id> --dry-run
plugin_ctl deploy <plugin_id>
plugin_ctl register <plugin_id> --dry-run
plugin_ctl register <plugin_id>
plugin_ctl verify <plugin_id>
plugin_ctl plugin roles <plugin_id>
plugin_ctl plugin consistency <plugin_id>
plugin_ctl cluster distribute <plugin_id> --dry-run
plugin_ctl cluster distribute <plugin_id>
```

归档和报告：

```bash
plugin_ctl plugin archive list
plugin_ctl plugin archive inspect <plugin_id>
plugin_ctl state <plugin_id>
plugin_ctl report
plugin_ctl report --json
```

运行时检查：

```bash
plugin_ctl doctor
plugin_ctl cluster status
```

## 内置插件

- `pluginctl_smoke_plugin`：安全样例插件，推荐用于完整生命周期测试。
- `otb_timeseries`：真实 OpenTenBase 时序插件的 reference manifest。不要对它执行破坏性 rollback。
- 其他 legacy `otb_*` manifest：适合做插件包治理检查，不代表生产可用插件包。

## 仓库结构

```text
catalog/plugins/       reference manifests
examples/plugins/      bundled sample plugins and fixtures
recipes/               smoke verification SQL
src/plugin_ctl/        Python implementation
tests/                 unit tests
docs/                  design and release documents
cluster.toml.example   distributed topology example
```

## 安全边界

只读或近似只读命令包括 `list`、`inspect`、`assess`、`plugin lint`、`plugin plan`、`plugin precheck`、`plugin diagnose`、`plugin roles`、`plugin consistency`、`plugin archive list`、`plugin archive inspect`、`plugins status`、`verify -f` 和 `report`。

会修改数据库或文件系统的命令：

- `add <plugin_dir_or_manifest>` 和 `remove <plugin_id>` 只修改本地 PluginCtl 用户 catalog。
- `init` 会读取 `pgxc_node` 并写入默认集群配置；它不会启动或停止 OpenTenBase。
- `deploy <plugin_id>` 会通过 `scp` 分发远程文件，不执行 `CREATE EXTENSION`；`deploy --dry-run` 只预览。
- `register <plugin_id>` 会在 primary coordinator 上执行 `CREATE EXTENSION`；`register --dry-run` 只预览。
- `rollback <plugin_id>` 会执行 manifest 声明的回滚 SQL；`rollback --dry-run` 只预览。

当前 role hooks 只进入计划和展示，不会自动执行。

## 开发

```bash
python -m unittest discover -s tests -v
git diff --check
```

当前测试基线：

```text
147 tests
```
