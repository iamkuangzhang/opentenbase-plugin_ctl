# OpenTenBase PluginCtl

[English](README.md)

OpenTenBase PluginCtl 是一个面向 OpenTenBase 的命令行优先插件生命周期控制台。

它关注插件包的发现、物理分发、扩展注册、健康检查、回滚和报告。它不是 OpenTenBase 集群运维平台，不是 Web 控制台，也不是插件市场。

公开入口是：

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
plugin_ctl --help
plugin_ctl list
```

## 主流程

普通用户建议先进入交互式控制台：

```bash
plugin_ctl
```

然后输入短命令：

```text
pluginctl> init
pluginctl> new my_plugin
pluginctl> list
pluginctl> list --all
pluginctl> deploy my_plugin
pluginctl> register my_plugin
pluginctl> check my_plugin
pluginctl> quit
```

`init` 会读取当前已经启动的 OpenTenBase 拓扑，并写入 PluginCtl 默认的 `cluster.toml`。它不负责启动、停止、初始化或监控 OpenTenBase 集群。

## 接入已有插件目录

插件不需要复制到 PluginCtl 安装目录。只要某个插件目录里有 `manifest.yml` 或 `plugin.yml`，就可以直接部署：

```text
pluginctl> init
pluginctl> deploy ./my_existing_plugin
pluginctl> register my_existing_plugin
pluginctl> check my_existing_plugin
```

`deploy ./my_existing_plugin` 会先自动把插件加入用户 catalog，再执行部署。插件文件仍然留在原目录。

## 公开命令

在 `plugin_ctl` 交互控制台里，普通用户只需要记住这些：

```text
help
init
new <plugin_id>
list [plugin_id]
list --all
deploy <plugin_id_or_path>
register <plugin_id>
check <plugin_id_or_path>
rollback <plugin_id>
quit
exit
```

需要兼容命令和调试命令时，输入：

```text
help advanced
```

## 命令含义

`new <plugin_id>`：创建一个适合新手学习的插件模板，并自动加入 PluginCtl 管理。

`list`：列出用户自己创建或接入的插件。`list --all`：同时显示内置参考插件。`list <plugin_id>`：查看某个插件的 manifest 和最近操作记录。

`deploy <plugin_id_or_path>`：把插件包文件复制到 OpenTenBase 的 CN/DN 扩展目录。复制前会先显示物理分发计划：`.control` / `.sql` 会进入 `extension_dir`，`.so` 会进入 `lib_dir`，纯 SQL 插件会明确显示没有 library 文件。它还会把隐藏的 PluginCtl 管理 manifest 同步到 `~/.plugin_ctl/packages/<plugin_id>/`，所以其他节点上的 `plugin_ctl list` 也能看到已分发插件，但不会把源码目录复制到用户工作目录。

`register <plugin_id>`：先在 primary coordinator 上做只读预检。如果 `pg_available_extensions` 里没有该扩展，会阻断注册；如果 `pg_extension` 里已经存在，会跳过；否则只执行一次 `CREATE EXTENSION`，再只读检查其他 coordinator 的 `pg_extension` 视图是否一致。

`check <plugin_id_or_path>`：执行一站式插件体检，包括包结构检查、计划、预检查、诊断和当前状态建议。

`rollback <plugin_id>`：执行 manifest 声明的回滚 SQL。它只回滚 SQL 声明的数据库对象，不会删除 CN/DN 节点上的 `.control`、`.sql`、`.so` 物理文件。交互式 shell 中，修改性命令会先显示 dry-run 预览，再询问确认。

## 一站式体检

`check` 可以接已知插件 ID、插件目录或 manifest 路径：

```text
pluginctl> check my_plugin
pluginctl> check ./my_plugin
pluginctl> check ./my_plugin/manifest.yml
```

它会按六段输出：插件包结构、扩展文件、PluginCtl 管理状态、OpenTenBase 集群配置、分布式部署状态、注册与验证状态。

最终状态包括 `NEW`、`READY`、`DEPLOYED`、`REGISTERED`、`BROKEN`、`REMOVED`、`UNKNOWN`。只有 `FAIL` 项会让插件变成 `BROKEN`；`WARN`、`SKIP`、`INFO` 会作为提示和下一步建议展示，不会被当成致命错误。

## 安全边界

只读或近似只读命令包括 `list`、`check`、`help`、`help advanced`。

会修改环境的命令包括：

- `deploy`：显示物理分发计划后，向 CN/DN 节点复制插件文件。
- `register`：先做预检，然后可能在 primary coordinator 上执行 `CREATE EXTENSION`。
- `rollback`：只执行数据库对象回滚 SQL，不删除 CN/DN 上的插件物理文件。

`activate` 仅作为 `register` 的旧兼容别名保留。新的文档和脚本应统一使用 `register`。

## 高级兼容命令

旧命令仍然保留给脚本和调试使用，但不再作为新手主流程：

```bash
plugin_ctl add <plugin_dir_or_manifest>
plugin_ctl remove <plugin_id>
plugin_ctl inspect <plugin_id>
plugin_ctl dev init <plugin_id>
plugin_ctl plugin lint <plugin_id>
plugin_ctl plugin plan <plugin_id>
plugin_ctl plugin precheck <plugin_id>
plugin_ctl plugin diagnose <plugin_id>
plugin_ctl plugin roles <plugin_id>
plugin_ctl plugin consistency <plugin_id>
plugin_ctl plugin archive list
plugin_ctl report
```

## 内置插件

- `pluginctl_smoke_plugin`：安全样例插件，用来测试 PluginCtl 完整生命周期。
- `otb_timeseries`：真实时序插件载荷的参考 manifest，不应由 PluginCtl 做破坏性回滚。
- `otb_*` 旧 manifest：可用于插件包治理检查，不代表生产可用插件包。

## 运行测试

```bash
python -m unittest discover -s tests -v
```

当前推荐的最短流程：

```text
plugin_ctl
pluginctl> init
pluginctl> new my_plugin
pluginctl> deploy my_plugin
pluginctl> register my_plugin
pluginctl> check my_plugin
pluginctl> quit
```
