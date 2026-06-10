# OpenTenBase PluginCtl

[绠€浣撲腑鏂嘳(#绠€浣撲腑鏂? | [English](#english)

## 绠€浣撲腑鏂?
OpenTenBase PluginCtl 鏄竴涓潰鍚?OpenTenBase 鐨勫垎甯冨紡鎻掍欢鐢熷懡鍛ㄦ湡绠＄悊宸ュ叿銆?
瀹冪殑閲嶇偣涓嶆槸鍋氶€氱敤鏁版嵁搴撹繍缁村钩鍙帮紝涔熶笉鏄?Web 鎺у埗鍙版垨鎻掍欢甯傚満锛岃€屾槸甯姪鐢ㄦ埛鎶?PostgreSQL / OpenTenBase 鎻掍欢浠庘€滄湁涓€鍫嗘枃浠跺拰 SQL鈥濇帹杩涘埌鈥滃彲妫€鏌ャ€佸彲瑙勫垝銆佸彲閮ㄧ讲銆佸彲娉ㄥ唽銆佸彲楠岃瘉銆佸彲杩借釜鈥濈殑宸ョ▼鍖栨彃浠跺寘銆?
褰撳墠鐗堟湰瀹氫綅锛歚v0.1.0` source release銆傚畠宸茬粡鍙互浣滀负 CLI 宸ュ叿璇曠敤锛屼絾浠嶅睘浜庢棭鏈熺増鏈紝涓嶅缓璁洿鎺ュ綋浣滅敓浜х幆澧冭嚜鍔ㄥ寲鍙戝竷绯荤粺銆?
### 瀹冭兘鍋氫粈涔?
- 鍙戠幇鍜屾煡鐪嬫彃浠?manifest銆?- 闈欐€佹壂鎻?PostgreSQL 鎻掍欢婧愮爜锛岃瘎浼拌縼绉诲埌 OpenTenBase 鐨勫垎甯冨紡椋庨櫓銆?- 妫€鏌ユ彃浠跺寘缁撴瀯鏄惁鍚堟牸銆?- 鐢熸垚閮ㄧ讲銆侀獙璇併€佸洖婊氳鍒掋€?- 瀵规湰鍦?OpenTenBase Docker / Linux 鐜鎵ц瀹夊叏鏍蜂緥鎻掍欢鐨?deploy / verify / rollback銆?- 鍦ㄥ垎甯冨紡鎷撴墤涓嬪垎鍙戞彃浠剁墿鐞嗘枃浠躲€?- 鍙湪 primary coordinator 涓婃墽琛屼竴娆℃墿灞曟敞鍐岋紝鐒跺悗鍙楠岃瘉鍏朵粬 coordinator 鐨勬墿灞曡鍥俱€?- 鍋氬垎甯冨紡鐧界洅楠岃瘉锛屽寘鎷?CN/DN 杩炴帴銆佹墿灞曠増鏈€乸ayload 鏂囦欢 checksum銆乸repared transaction 娈嬬暀绛夈€?- 璁板綍鎻掍欢 action state銆乤rchive銆乺eport銆?- 鎸?coordinator / datanode / all 瑙掕壊灞曠ず鎻掍欢娌荤悊璁″垝銆?
### 瀹冧笉鏄粈涔?
PluginCtl 褰撳墠涓嶆槸锛?
- OpenTenBase 闆嗙兢杩愮淮骞冲彴
- Web UI
- 鎻掍欢甯傚満
- 澶氭暟鎹簱閫傞厤灞?- 鎵归噺閮ㄧ讲鍜岃嚜鍔ㄥ崌绾х郴缁?- 鑷姩淇宸ュ叿
- 鐢熶骇绾у洖婊氱郴缁?
### 瀹夎

鐜瑕佹眰锛?
- Python 3.11+
- pip
- Docker锛屽彲閫夛紝浠呯敤浜庢湰鍦?OpenTenBase 娌欑娴佺▼
- `psql`銆乣ssh`銆乣scp`锛屽彲閫夛紝浠呯敤浜庡垎甯冨紡闆嗙兢娴佺▼

浠庢簮鐮佸畨瑁咃細

```bash
git clone https://github.com/iamkuangzhang/opentenbase-plugin_ctl.git
cd opentenbase-plugin_ctl
python -m pip install -e .
```

楠岃瘉鍛戒护鏄惁鍙敤锛?
```bash
opentenbase-pluginctl list
```

鎺ㄨ崘浣跨敤 `opentenbase-pluginctl`銆俙python -m plugin_ctl` 淇濈暀缁欏紑鍙戝拰璋冭瘯浣跨敤銆?
### 5 鍒嗛挓璇曠敤

鍐呯疆鐨?`pluginctl_smoke_plugin` 鏄竴涓畨鍏ㄦ牱渚嬫彃浠讹紝鐢ㄦ潵楠岃瘉 PluginCtl 鑷繁鐨勭敓鍛藉懆鏈熻兘鍔涖€傚缓璁厛鐢ㄥ畠璇曪紝涓嶈涓€寮€濮嬪氨鎷跨湡瀹炰笟鍔℃彃浠跺仛鐮村潖鎬у疄楠屻€?
```bash
opentenbase-pluginctl list
opentenbase-pluginctl inspect pluginctl_smoke_plugin
opentenbase-pluginctl check pluginctl_smoke_plugin
opentenbase-pluginctl deploy pluginctl_smoke_plugin
opentenbase-pluginctl verify pluginctl_smoke_plugin
opentenbase-pluginctl report
```

鏇寸粏鐨勬不鐞嗗懡浠わ紝渚嬪 `plugin lint`銆乣plugin plan`銆乣plugin precheck`銆乣plugin diagnose`锛屽彲浠ュ湪闇€瑕佹帓鏌ラ棶棰樻椂鍗曠嫭杩愯銆?
濡傛灉瑕佹墽琛屽洖婊氾紝蹇呴』鏄惧紡鍔?`--execute`锛?
```bash
opentenbase-pluginctl rollback pluginctl_smoke_plugin
opentenbase-pluginctl rollback pluginctl_smoke_plugin --execute
opentenbase-pluginctl verify pluginctl_smoke_plugin --removed
```

### 浜や簰寮忔彃浠舵帶鍒跺彴

濡傛灉浣犳洿鍠滄绫讳技 `pgxc_ctl` 鐨勪氦浜掓柟寮忥紝鍙互鐩存帴杩涘叆 PluginCtl Shell锛?
```bash
plugin_ctl
```

涔熷彲浠ユ樉寮忚繘鍏ワ細

```bash
plugin_ctl shell
opentenbase-pluginctl shell
```

杩涘叆鍚庡彲浠ヨ緭鍏ョ煭鍛戒护锛屼笉蹇呮瘡娆″啓瀹屾暣鍓嶇紑锛?
```text
OpenTenBase PluginCtl Shell
Type "help" to show commands.
Type "quit" or "exit" to leave.

pluginctl> list
pluginctl> check pluginctl_smoke_plugin
pluginctl> deploy pluginctl_smoke_plugin
pluginctl> verify pluginctl_smoke_plugin
pluginctl> report
pluginctl> quit
```

PluginCtl Shell 鏄彃浠剁敓鍛藉懆鏈熸帶鍒跺彴锛岀敤鏉ョ鐞嗘彃浠剁殑鍙戠幇銆佹鏌ャ€侀儴缃层€侀獙璇併€佸洖婊氬拰鎶ュ憡銆傚畠涓嶆槸 OpenTenBase 闆嗙兢鎺у埗鍙帮紝涓嶈礋璐ｉ泦缇ゅ惎鍔ㄣ€佸仠姝€佸垵濮嬪寲鎴栫洃鎺с€?
### 鍒嗗竷寮忔彃浠跺寘娴佺▼

鍏堝鍒跺苟淇敼鎷撴墤鏂囦欢锛?
```bash
cp cluster.toml.example cluster.toml
```

Windows PowerShell锛?
```powershell
Copy-Item cluster.toml.example cluster.toml
```

妫€鏌ユ嫇鎵戯細

```bash
opentenbase-pluginctl cluster inspect -f cluster.toml
```

鎺ㄨ崘鐨勫畬鏁村垎甯冨紡娴佺▼锛?
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

杩欓噷鏈変笁涓噸瑕佽竟鐣岋細

- `deploy -f cluster.toml` 榛樿 dry-run锛屽彧灞曠ず鐗╃悊鏂囦欢鍒嗗彂璁″垝銆?- `deploy -f cluster.toml --execute` 鍙垎鍙戞枃浠讹紝涓嶆墽琛?`CREATE EXTENSION`銆?- `register -f cluster.toml --execute` 鍙湪 `cluster.toml` 涓涓€涓?coordinator 涓婃墽琛屼竴娆?`CREATE EXTENSION`锛岀劧鍚庡彧璇绘鏌ュ叾浠?coordinator 鐨?`pg_extension` 瑙嗗浘銆?
### 甯哥敤鍛戒护

#### 鎻掍欢鍙戠幇

```bash
opentenbase-pluginctl list
opentenbase-pluginctl inspect <plugin_id>
```

#### 婧愮爜杩佺Щ椋庨櫓璇勪及

```bash
opentenbase-pluginctl assess <pg_extension_source_path>
opentenbase-pluginctl assess <pg_extension_source_path> --json
```

`assess` 涓嶇紪璇戜唬鐮併€佷笉杩炴帴鏁版嵁搴撱€佷笉淇敼鏂囦欢銆傚畠浼氶潤鎬佹鏌ワ細

- 鏄惁瀛樺湪 `.control` 鏂囦欢
- 鏄惁瀛樺湪 SQL 瀹夎鎴栧崌绾ф枃浠?- `LANGUAGE C` 鍑芥暟鏄惁鏄惧紡澹版槑 `SHIPPABLE` 鎴?`NOT SHIPPABLE`
- C 浠ｇ爜閲屾槸鍚﹀瓨鍦?`SPI_execute` 椋庢牸鐨勫姩鎬佸缓琛?DDL
- 浜嬪姟鎺у埗銆佺郴缁?catalog 璁块棶绛夐渶瑕佸垎甯冨紡瀹℃煡鐨勯闄╃偣

#### 鎻掍欢娌荤悊

```bash
opentenbase-pluginctl check <plugin_id>
opentenbase-pluginctl plugin lint <plugin_id>
opentenbase-pluginctl plugin plan <plugin_id>
opentenbase-pluginctl plugin precheck <plugin_id>
opentenbase-pluginctl plugin diagnose <plugin_id>
opentenbase-pluginctl plugin status <plugin_id>
opentenbase-pluginctl plugins status
```

#### 鐢熷懡鍛ㄦ湡

```bash
opentenbase-pluginctl deploy <plugin_id>
opentenbase-pluginctl verify <plugin_id>
opentenbase-pluginctl rollback <plugin_id>
opentenbase-pluginctl rollback <plugin_id> --execute
opentenbase-pluginctl verify <plugin_id> --removed
```

#### 鍒嗗竷寮忔彃浠舵不鐞?
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

#### 褰掓。鍜屾姤鍛?
```bash
opentenbase-pluginctl plugin archive list
opentenbase-pluginctl plugin archive inspect <plugin_id>
opentenbase-pluginctl state <plugin_id>
opentenbase-pluginctl report
opentenbase-pluginctl report --json
```

#### 杩愯鏃舵鏌?
```bash
opentenbase-pluginctl doctor
opentenbase-pluginctl cluster status
```

杩欎簺鍛戒护鍙綔涓烘彃浠剁鐞嗙殑鏀拺锛屼笉鏄负浜嗘妸 PluginCtl 鍋氭垚娉涢泦缇ゅ贰妫€骞冲彴銆?
### 鎻掍欢鍖呯粨鏋?
鏍蜂緥鎻掍欢鐩綍锛?
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

manifest 閫氬父澹版槑锛?
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
- 鍙€?role hooks

### 鍐呯疆鎻掍欢

#### `pluginctl_smoke_plugin`

瀹夊叏鏍蜂緥鎻掍欢锛岀敤浜庨獙璇?PluginCtl 鐨?deploy / verify / rollback / removed verify / archive / consistency 娴佺▼銆?
杩欐槸鎺ㄨ崘鐨勫叆闂ㄦ祴璇曟彃浠躲€?
#### `otb_timeseries`

鐪熷疄 OpenTenBase 鏃跺簭鎻掍欢鐨?reference manifest銆傚畠鐢ㄤ簬灞曠ず鐪熷疄涓氬姟鎻掍欢鐨勬不鐞嗗拰鐘舵€佹鏌ワ紝浣嗗綋鍓嶅彂甯冧粨搴撲笉鎶婂畠澹版槑涓哄畬鏁?bundled package銆?
娉ㄦ剰锛氫笉瑕佸 `otb_timeseries` 鎵ц鐮村潖鎬?rollback銆?
### 浠撳簱缁撴瀯

```text
catalog/plugins/       reference manifests
examples/plugins/      bundled sample plugins and fixtures
recipes/               smoke verification SQL
src/plugin_ctl/        Python implementation
tests/                 unit tests
docs/                  design and release documents
cluster.toml.example   distributed topology example
```

### 瀹夊叏杈圭晫

鍙鎴栬繎浼煎彧璇诲懡浠わ細

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

浼氫慨鏀规暟鎹簱鎴栨枃浠剁郴缁熺殑鍛戒护锛?
- `deploy <plugin_id>`锛氭湰鍦版ā寮忎細鎵ц瀹夎 SQL銆?- `deploy <plugin_id> -f cluster.toml --execute`锛氫細閫氳繃 `scp` 鍒嗗彂杩滅▼鏂囦欢銆?- `register <plugin_id> -f cluster.toml --execute`锛氫細鍦?primary coordinator 涓婃墽琛?`CREATE EXTENSION`銆?- `rollback <plugin_id> --execute`锛氫細鎵ц manifest 澹版槑鐨?`rollback_sql`銆?
褰撳墠 role hooks 鍙繘鍏?plan / roles / diagnose锛屼笉浼氳嚜鍔ㄦ墽琛屻€傛湭鏉ュ鏋滄敮鎸佹墽琛?hook锛屼篃蹇呴』瑕佹眰鏄惧紡鍙傛暟锛屼緥濡?`--execute-hooks`銆?
### 寮€鍙?
杩愯娴嬭瘯锛?
```bash
python -m unittest discover -s tests -v
```

妫€鏌ョ┖鐧介敊璇細

```bash
git diff --check
```

褰撳墠娴嬭瘯鍩虹嚎锛?
```text
132 tests
```

### 鏂囨。

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
git clone https://github.com/iamkuangzhang/opentenbase-plugin_ctl.git
cd opentenbase-plugin_ctl
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

### Interactive Plugin Console

If you prefer a `pgxc_ctl`-like interactive workflow, start PluginCtl Shell:

```bash
plugin_ctl
```

You can also enter it explicitly:

```bash
plugin_ctl shell
opentenbase-pluginctl shell
```

Inside the shell, use short commands without repeating the full CLI prefix:

```text
OpenTenBase PluginCtl Shell
Type "help" to show commands.
Type "quit" or "exit" to leave.

pluginctl> list
pluginctl> check pluginctl_smoke_plugin
pluginctl> deploy pluginctl_smoke_plugin
pluginctl> verify pluginctl_smoke_plugin
pluginctl> report
pluginctl> quit
```

PluginCtl Shell is a plugin lifecycle console for discovery, checks, deployment, verification, rollback, and reporting. It is not an OpenTenBase cluster console and does not start, stop, initialize, or monitor the cluster.

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
132 tests
```

### Documentation

- [M3 Distributed Lifecycle](docs/M3_DISTRIBUTED_LIFECYCLE.md)
- [M3 Final Status](docs/M3_FINAL_STATUS.md)
- [M3 Archive And Consistency](docs/M3_ARCHIVE_AND_CONSISTENCY.md)
- [M2 Plugin Governance](docs/M2_PLUGIN_GOVERNANCE.md)
- [Release Checklist](docs/RELEASE_CHECKLIST.md)
