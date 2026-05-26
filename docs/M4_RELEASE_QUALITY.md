# M4 Release Quality

## 目标

M4 第一阶段目标是让 OpenTenBase PluginCtl 达到“可以给别人安装、理解、试用、验证”的开源产品化水平。本阶段不做 Web、插件市场、批量 deploy、版本升级、cluster start 或自动修复。

## 安全执行边界

命令按风险分为三类。

只读命令：

```bash
python -m plugin_ctl list
python -m plugin_ctl inspect <plugin_id>
python -m plugin_ctl plugin lint <plugin_id>
python -m plugin_ctl plugin plan <plugin_id>
python -m plugin_ctl plugin precheck <plugin_id>
python -m plugin_ctl plugin diagnose <plugin_id>
python -m plugin_ctl plugin status <plugin_id>
python -m plugin_ctl plugin check <plugin_id>
python -m plugin_ctl plugin roles <plugin_id>
python -m plugin_ctl plugin consistency <plugin_id>
python -m plugin_ctl plugin archive list
python -m plugin_ctl plugin archive inspect <plugin_id>
python -m plugin_ctl plugins status
python -m plugin_ctl doctor
python -m plugin_ctl cluster status
python -m plugin_ctl report
python -m plugin_ctl state <plugin_id>
```

会修改数据库或本地状态的命令：

```bash
python -m plugin_ctl deploy <plugin_id>
python -m plugin_ctl verify <plugin_id>
python -m plugin_ctl rollback <plugin_id> --execute
python -m plugin_ctl verify <plugin_id> --removed
```

说明：

- `deploy` 会复制 payload 到容器临时目录并执行 `install_sql`。
- `verify` 会执行 smoke SQL，并写入本地 `.datanexus/state.json`。
- `rollback` 默认 dry-run，只有传入 `--execute` 才会执行 `rollback_sql`。
- `rollback` 是 best-effort，因为数据库对象、函数、schema、分布式表和节点状态不一定能被一个脚本完全恢复。
- `report/state/archive` 读取或写入的是本地 `.datanexus/` 运行态记录，不是远端数据库元数据的权威替代。

## Role Hook 策略

当前支持 manifest 声明：

- `preinstall`
- `postinstall`
- `preuninstall`
- `postuninstall`

这些 hook 当前只出现在：

- `plugin plan`
- `plugin roles`
- `plugin diagnose`
- `plugin archive`
- `plugin consistency`

当前不会自动执行 hook。未来如果支持执行，必须引入显式参数，例如：

```bash
python -m plugin_ctl deploy <plugin_id> --execute-hooks
python -m plugin_ctl rollback <plugin_id> --execute --execute-hooks
```

在没有显式参数前，hook 只能作为治理计划和一致性检查的一部分。

## 命令分组

Discovery:

- `list`
- `inspect`

Governance:

- `plugin lint`
- `plugin plan`
- `plugin precheck`
- `plugin diagnose`
- `plugin status`
- `plugin check`
- `plugins status`

Lifecycle:

- `deploy`
- `verify`
- `rollback`

Archive:

- `plugin archive list`
- `plugin archive inspect`

Distributed:

- `plugin roles`
- `plugin consistency`

Reporting:

- `state`
- `report`

Runtime:

- `doctor`
- `cluster status`

## 安装方式

要求：

- Python 3.11+
- Docker 可用
- 本地 OpenTenBase Docker 环境可用时才能运行真实 deploy / verify / precheck

推荐开发安装：

```bash
git clone https://github.com/iamkuangzhang/opentenbase-plugin_ctl.git
cd opentenbase-plugin_ctl
python -m pip install -e .
```

安装后可以使用两个入口：

```bash
plugin_ctl list
datanexus list
```

也可以不安装，直接设置 `PYTHONPATH`：

```bash
set PYTHONPATH=src
python -m plugin_ctl list
```

PowerShell：

```powershell
$env:PYTHONPATH = "src"
python -m plugin_ctl list
```

## 本地 OpenTenBase Docker 连接

默认连接参数：

- container: `opentenbaseDN1`
- host: `127.0.0.1`
- port: `30004`
- user: `opentenbase`
- database: `postgres`

可先运行：

```bash
python -m plugin_ctl doctor
python -m plugin_ctl cluster status
```

## 5 分钟试用流程

```bash
python -m plugin_ctl list
python -m plugin_ctl plugin lint dnx_smoke_plugin
python -m plugin_ctl plugin plan dnx_smoke_plugin
python -m plugin_ctl plugin precheck dnx_smoke_plugin
python -m plugin_ctl deploy dnx_smoke_plugin
python -m plugin_ctl verify dnx_smoke_plugin
python -m plugin_ctl plugin diagnose dnx_smoke_plugin
python -m plugin_ctl report
```

如需回滚样例插件：

```bash
python -m plugin_ctl rollback dnx_smoke_plugin
python -m plugin_ctl rollback dnx_smoke_plugin --execute
python -m plugin_ctl verify dnx_smoke_plugin --removed
```

## 插件说明

`dnx_smoke_plugin` 是 bundled package。它包含完整 manifest、payload、install SQL、verify SQL、rollback SQL 和 role hooks，适合演示完整生命周期。

`otb_timeseries` 是 reference manifest。当前发布仓库不携带旧项目中的完整 `src/otb_timeseries` 载荷，因此它可以展示 runtime installed state 和分布式治理视角，但不能证明完整干净安装链路。

## 测试

```bash
python -m unittest discover -s tests -v
```

M4 第一阶段要求所有现有测试继续通过。
