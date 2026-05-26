# M3 Archive And Consistency

## 定位

M3 的目标是把 OpenTenBase PluginCtl 从“单插件生命周期闭环”推进到“分布式插件包治理”。本阶段仍然坚持插件为中心，不做泛集群巡检，不做自动修复。

M3 新增能力是只读或状态记录型能力：

- 插件包 archive/state 查询
- 插件 coordinator / datanode / all 角色映射
- 插件一致性检查

## Archive / State 模型

`plugin archive` 用来记录插件包治理状态，不替代 `state/report`，而是补上“包级别可追踪记录”。

Archive record 字段包括：

- `plugin_id`
- `version`
- `manifest_path`
- `manifest`
- `payload`
- `roles`
- `package_state`
- `installed_at`
- `status`
- `checksum`
- `target_roles`
- `latest_actions`
- `runtime_metadata`
- `updated_at`

其中：

- `state/report` 记录每次 action 的结果。
- `archive` 记录插件包当前治理视角下的快照。
- `checksum` 基于 manifest 和声明的 SQL 文件计算，用来发现 manifest 或包文件变更。
- `manifest.kind` 用于区分完整归档包和引用型 manifest。
- `package_state.payload_complete` 用于说明发布仓库里是否真的带齐了 manifest 声明的载荷文件。

当前 archive 文件存放在 `.datanexus/archive.json`，属于本地运行态数据，不提交到 Git。

## 分角色治理

M3 将 manifest 中的 `distributed.required_roles` 映射到插件治理步骤：

- `coordinator`：通常负责 `installed_probe`、`install_sql`、`verify_sql`、`rollback_sql`
- `datanode`：当前先检查 payload presence 和目标角色声明
- `all`：保留为后续 role hook / package sync 方向

M3 也开始支持声明式 role hooks：

- `preinstall`
- `postinstall`
- `preuninstall`
- `postuninstall`

示例：

```yaml
hooks:
  preinstall:
    coordinator:
      - examples/plugins/dnx_smoke_plugin/payload/hooks/preinstall.sql
  postinstall:
    coordinator:
      - examples/plugins/dnx_smoke_plugin/payload/hooks/postinstall.sql
```

当前 role hooks 只进入规划、lint、archive 和 consistency，不会自动执行。后续如要执行，必须显式纳入 deploy / rollback 的安全流程。

命令：

```bash
python -m plugin_ctl plugin roles <plugin_id>
python -m plugin_ctl plugin roles <plugin_id> --json
```

该命令只解释插件会作用到哪些角色，不执行 deploy / verify / rollback。

## 一致性检查

`plugin consistency` 是插件中心的一致性检查，不是节点巡检。

检查内容包括：

- manifest / package lint 中发现的文件或声明问题
- archive record 是否存在
- archive package state 是否完整
- archive checksum 是否与当前 manifest/package 一致
- archive version 是否与 manifest 一致
- runtime installed state 是否可通过 `installed_probe` 验证
- archive status 与 runtime installed state 是否一致
- manifest 声明角色是否能被当前集群支持
- archive 中记录的远端 payload 路径是否还能在运行容器中看到

命令：

```bash
python -m plugin_ctl plugin consistency <plugin_id>
python -m plugin_ctl plugin consistency <plugin_id> --json
```

该命令允许输出 warning / fail，但不会自动修复。

## 当前插件视角

`dnx_smoke_plugin`：

- 平台生命周期验证插件
- 包结构完整
- 支持真实 deploy / verify / rollback --execute / verify --removed
- 适合用于 archive、roles、consistency 的安全回归

`otb_timeseries`：

- 真实业务插件样例
- 当前发布仓库是平台仓库，不包含旧项目里的完整 `src/otb_timeseries` 载荷
- 因此 archive 会把它表达为 `reference_manifest`，而不是完整归档包
- 可通过 `installed_probe` 识别真实环境中已安装的 `otb_ts.version()`
- 不支持破坏性 rollback
- chunk distribution warning 仍作为独立问题跟踪

## M3 边界

当前不做：

- Web UI
- 插件市场
- 批量 deploy
- 版本升级系统
- cluster start
- 自动修复
- 跨数据库适配
- 对 `otb_timeseries` 做破坏性 rollback

## 下一步建议

M3 后续可以继续做：

- role hook 规范：`preinstall / postinstall / preuninstall / postuninstall`
- package archive 的 inspect/detail 增强
- 基于 archive 的插件包导出和回放计划
- 插件包文件在 coordinator/datanode 上的只读存在性检查
- 针对 `otb_timeseries` 的干净环境安装验证，而不是只依赖 already deployed 路径
