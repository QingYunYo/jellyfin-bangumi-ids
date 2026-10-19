# jellyfin-bangumi-ids

[![test](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml/badge.svg)](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml)

> 中文 | [English](README.en.md)

把 Jellyfin 里每一集、每一季的 `ProviderIds.Bangumi` 填对，让 Bangumi 插件的进度同步落到正确的作品上。
只改这一个字段，不动视频文件，不动其他元数据。

## 目录

- [1. 它改什么：两类 ID](#1-它改什么两类-id)
- [2. 安装与 API Key](#2-安装与-api-key)
- [3. 快速开始](#3-快速开始)
- [4. 模式与用法](#4-模式与用法)
- [5. 季级 ID：为什么必须一起修](#5-季级-id为什么必须一起修)
- [6. 用离线档案提速](#6-用离线档案提速)
- [7. 安全性](#7-安全性)
- [8. 常见问题](#8-常见问题)
- [9. 实现](#9-实现)
- [10. 开发](#10-开发)

## 1. 它改什么：两类 ID

Jellyfin 的**每一集**和**每一季**都可以带一个 Bangumi ID，它们管的事不一样：

| 字段 | 决定什么 | 插件怎么用 |
| --- | --- | --- |
| 集的 `ProviderIds.Bangumi` | 这一集在看没看 | 单集进度、`Watched` / `Default` |
| 季的 `ProviderIds.Bangumi` | 「在看」报到哪部作品 | `PlaybackScrobbler` 取这一集的**父级（季）** 当 subject |

所以**只修集不够**。集级全对、季级错位一格时，播放照常、单集状态照常，但「在看」记到了相邻那一季——
而且任何逐集检查都发现不了。本工具两类都查、都修：

```bash
jbmid scan    --library 动漫                   # 集级：按集名对齐，产出报告
jbmid apply   report.json                      # 集级：写回
jbmid anchor  --library 动漫 --seasons --all   # 季级：按集级 ID 投票修季
jbmid verify  --library 动漫                   # 两类一起体检
```

实测（同一集，动画插件日志）：

```text
季级 ID 写死成前一个 part：
  report subject #525565 status Watching     ← 记到了别的 part
清空季级 ID 后（插件退回按这一集自己的 ID 反查）：
  report subject #638497 status Watching     ← 正确
```

典型症状：播完没反应（日志刷 `doesn't have bangumi id`）、进度同步到别的番、TMDB 一季对应 Bangumi
两个条目导致后半季全错、SP 被当正片后整体偏移、手动改完下次刷新又被覆盖。

### 真实错位速查

| 症状 | 工具怎么处理 |
| --- | --- |
| 整季 ID 右移两集 | `scan` 按集名对齐，`apply` 写回（可 `rollback`） |
| 半季没有 ID | `apply` 只补空值，不动已有 |
| 剧集 ID 挂到另一部作品 | 锚点校验 + 季级投票；必要时 `anchor --series` 换锚点 |
| 播出顺序 ≠ 集号顺序 | `verify` 报 `disorder`，交给你确认 |
| 一个本地季对两个条目 | `anchor --seasons --clear-spans` 清空季级 ID（见第 5 章） |
| 集名带 `SP` 被误判成番外 | 已按 `SP\d+` 识别（`（Sp...）` 不再误伤） |

## 2. 安装与 API Key

只依赖 Python 标准库，Python ≥ 3.8：

```bash
pip install git+https://github.com/QingYunYo/jellyfin-bangumi-ids.git
# 本地开发
git clone https://github.com/QingYunYo/jellyfin-bangumi-ids.git
cd jellyfin-bangumi-ids && pip install -e .
```

装完有 `jbmid` 命令（也可 `python -m jellyfin_bangumi_ids`）。Jellyfin 里「控制台 → API 密钥」建一个，
然后：

```bash
export JF_URL=http://127.0.0.1:8096
export JF_API_KEY=你的密钥
jbmid doctor          # 连通性 + 数据源 + 插件状态
```

`doctor` 会告诉你用的是在线 API 还是离线档案、插件是否已开 `TrustExistedBangumiId`。
所有命令都接受 `--url` / `--api-key`，也支持 `--ipv4`（容器里只通 IPv4 时）和 `--timeout`。

## 3. 快速开始

```bash
# 1) 扫库，只生成报告，不写任何东西（--limit 3 先试水）
jbmid scan --library 动漫 --out report.json

# 2) 先干跑，看要写多少集
jbmid apply report.json --dry-run

# 3) 真写（旧值自动备份）
jbmid apply report.json --backup jbmid-backup.json

# 4) 出问题一键回滚
jbmid rollback jbmid-backup.json
```

```text
$ jbmid scan --library 动漫 --limit 3
scanning 3 series from library 动漫
[1/3] OK   2.5次元的诱惑           to write 0
[2/3] OK   86-不存在的战区-        to write 0
[3/3] OK   拔作岛                  to write 0
series ok      : 3
series review  : 0
episodes       : 0 to write
```

三个数字：`series ok` 可以对齐、`series review` 不确定（**不写**，看 `reason`）、`episodes to write` 要改的集数。
报告里每部剧带 `anchor` / `chain` / `notes`，`review` 的会写明原因（如 `size mismatch 25 local vs 51 pool`）。

## 4. 模式与用法

先看一张表。选模式的唯一硬标准是**写不写**——拿不准就加 `--dry-run`。

| 模式 | 干什么 | 输入 | 写不写 |
| --- | --- | --- | --- |
| `scan` | 自动找锚点、按集名对齐整库 | `--library` | 只出报告 |
| `apply` | 把 `scan` / `special` 的报告写进 Jellyfin | 报告 JSON | 写（有 `--dry-run`） |
| `season` | 手工指定「第几季 = 哪几个 subject」 | `--map` JSON | 写（有 `--dry-run`） |
| `auto` | 按标题找条目 + 按集名对齐，一把梭 | `--library` | 写（有 `--dry-run`） |
| `special` | 修 Season 0 / 番外 / OVA | `--library` | 只出报告 |
| `anchor` | 修某部剧的剧集级 / 季级 ID | `--series` 或 `--library` | 写（有 `--dry-run`） |
| `verify` | 体检：集级、季级 ID 对不对 | `--library` | 只读 |
| `protect` | 让插件别覆盖手写 ID | — | 改插件配置 |
| `rollback` | 按备份还原 | 备份 JSON | 写 |
| `doctor` | 连通性 / 数据源 / 插件状态 | — | 只读 |

### 4.1 `scan`：先看清全局，再动手

最常用的入口：逐部剧找锚点、建池、按集名对齐、给出判定，**一个字都不写**。

```bash
jbmid scan --library 动漫 --out report.json   # 全库
jbmid scan --library 动漫 --limit 3            # 先试 3 部
```

看 `series review` 的原因，确认无误后再 `jbmid apply report.json`。

### 4.2 `apply` / `rollback`：报告落库与撤销

```bash
jbmid apply report.json --dry-run                 # 先看要改多少集
jbmid apply report.json --backup jbmid-backup.json
jbmid rollback jbmid-backup.json --dry-run
```

`apply` 只写「新旧不同」的集；`rollback` 按备份逐条还原。两者都有 `--dry-run`。

### 4.3 `season`：季划分对不上时

本地季数 ≠ 链上条目数、或顺序不同时用。JSON 写「第几季 = 哪些 subject」：

```json
{"物语系列": {"1": {"subjects": [140001]}, "14": {"subjects": [475354], "sp": true}}}
```

```bash
jbmid season --map map.json --dry-run
```

`sp: true` 表示这一季按番外处理（对齐 Bangumi 的 `type=1` 集）。

### 4.4 `auto`：一把梭

不指定锚点，按剧名搜条目、按集名对齐，然后直接写：

```bash
jbmid auto --library 动漫 --dry-run
jbmid auto --library 动漫
```

它最省事，也最需要看结果：每部剧都会打印 `method`（`name` / `season-map` / `stored` / `order`）。

### 4.5 `special`：番外、OVA、总集篇

Season 0 和名字含 `番外|OVA|OAD|SP|总集篇|特典` 的集，对齐 Bangumi 的 `type=1` 集：

```bash
jbmid special --library 动漫 --out specials.json
jbmid apply specials.json
jbmid special --library 动漫 --clear-borrowed   # 清掉借用了正片 ID 的番外
```

### 4.6 `anchor`：锚点本身错了

只修一部剧的锚点，也能修季级 ID：

```bash
jbmid anchor --series 物语系列 --dry-run                     # 换剧集级锚点
jbmid anchor --library 动漫 --seasons --all                  # 修季级 ID
jbmid anchor --library 动漫 --seasons --all --clear-spans    # 横跨季清空
```

取值顺序：**集级反查 → 季级多数票 → 剧集自己的 ID → 标题搜索**，都要过标题校验；`--force` 接收可疑值，
`--clear` 清空。

### 4.7 `verify`：只读体检

```bash
jbmid verify --library 动漫
```

一行汇总 + 分类明细，各字段含义见[第 5 章](#5-季级-id为什么必须一起修)。

### 4.8 `protect` / `doctor`

```bash
jbmid protect     # 把 TrustExistedBangumiId 设为 True，刷新不再覆盖
jbmid doctor      # 连通性 / 数据源 / 插件状态
```

两份 README 里的示例输出都来自 `examples/`（真实报告与备份的节选）。

## 5. 季级 ID：为什么必须一起修

Bangumi 插件上报「在看」时，subject 取自**这一集的父级**（季），不是这一集自己的 ID。所以：

- 集级 ID 全对 → 每集看没看是对的；
- 季级 ID 指向隔壁条目 → 「在看」永远记错，而且逐集检查（`verify` 的集名比对）完全看不出来。

`verify` 把两类问题分开报：

```text
offline check: 2095 ids | unknown 0 | dup 3 | low-sim 278 | disorder 22 | foreign 5
               | anchors 0 | season-ids 0 | season-spans 0
```

`season-ids` = 季级 ID 与它自己集级 ID 的多数票不一致；`season-spans` = 一个季横跨两个条目却仍写着
季级 ID。对应的两个修法：

```bash
# 一、按集级 ID 投票修季级 ID（≥60% 且 ≥2 集才写）
jbmid anchor --library 动漫 --seasons --all --dry-run
jbmid anchor --library 动漫 --seasons --all

# 二、一个季横跨两个条目：没有唯一正确的季级 ID，清空它
jbmid anchor --library 动漫 --seasons --all --clear-spans --dry-run
jbmid anchor --library 动漫 --seasons --all --clear-spans
```

```text
$ jbmid anchor --library 动漫 --seasons --all --clear-spans --dry-run
86-不存在的战区-
  season 1   id 302189   -> (cleared) (12/23 episodes) [clear: spanning season]
进击的巨人
  season 3   id 217300   -> (cleared) (12/22 episodes) [clear: spanning season]
17 season id(s) off, 0 written (dry run)
```

**为什么清空而不是挑一个**：一个季里 12 集属于 part A、13 集属于 part B，季级 ID 只能写一个。
写 A，B 的 13 集上报到 A；写 B，A 的 12 集上报到 B。清空后 `PlaybackScrobbler` 退回「用这一集自己的
ID 反查条目」，两边都对——第 1 章那段日志对照就是这个机制。

**安全边界**：`--force` 只放宽「低置信」（少于 2 集、票数不足 60%），**不会**给横跨季写多数票
（直接跳过），否则会把刚清空的那一半写回去。单集季可以用 `--force` 补 ID。

写回走读-改-写：GET 完整条目 → 只改 `ProviderIds.Bangumi` → POST → 回读确认，并检查相邻字段有没有
被连带改掉；改了什么同时写进备份，`rollback` 可还原。季级备份里 `kind` 字段是 `season`。

## 6. 用离线档案提速

装了 Bangumi 插件并跑过「离线数据库更新」后，`{Jellyfin DataPath}/bangumi/archive/` 下有几份
`.jsonlines`。本工具直接读它们，把在线请求换成主键查询：

| 操作 | 在线 API | 离线档案（已建索引） |
| --- | --- | --- |
| `verify` 全库 | 约 40 分钟 | 约 18 秒 |
| `scan` 全库 | 约 12 分钟 | 首次建索引约 2 分钟，之后约 19 秒 |

查找顺序：`--archive DIR` → 环境变量 `JBMID_ARCHIVE` → `/System/Info` 的 `DataPath` 自动探测。
档案找不到或某一集不在档案里，自动回退在线 API。首次使用会在档案目录建一个约 150 MB 的 SQLite 索引
（只读源文件）。档案每 14 天更新一次，太旧时以在线 API 为准。

## 7. 安全性

- **只改一个字段**：`ProviderIds.Bangumi`。不碰文件、不碰其他元数据、不删条目。
- **读-改-写 + 回读**：写前取完整条目，写完回读，并检查相邻字段是否被连带修改。
- **处处有备份**：`apply` / `anchor` / `season` / `special` / `rollback` 都生成备份，一键还原。
- **不确定就不写**：集数对不上、覆盖不足、相似度不够 → 标 `review` 跳过。
- **默认不覆盖手写值**：`apply` 只写「新旧不同」的集；`protect` 让插件也不要覆盖。
- **凭据只在本地**：API Key 和 Bangumi token 只用于发请求，不落盘、不上传。

## 8. 常见问题

**Q1. `HTTP 401`**
用 `Authorization: MediaBrowser Token="密钥"`，不是 `X-Emby-Token`。`jbmid` 已经这样发；自己 curl 时注意。

**Q2. `HTTP 404 ... "Series not found"`**
旧版 Jellyfin 的 `/Shows/{id}/Episodes` 行为不一致。本工具改用
`/Items?ParentId=…&IncludeItemTypes=Episode&Recursive=true`，不依赖那个端点。

**Q3. 扫描很慢**
每部剧要串行请求 Bangumi。接上离线档案（第 6 章）后全库 19 秒；也可以 `--limit` 先扫几部。

**Q4. 同一部番在库里出现两次**
`verify` 的 `duplicate_series` 会列出来（常见于同一份文件被两个库路径收录）。工具两份都改，不删条目。

**Q5. SP / OVA 怎么处理**
默认只修正片：Season 0 和名字含 `番外|OVA|OAD|SP|总集篇|特典` 的集不当正片数。要一起修用 `special`。

**Q6. TMDB 一季 = Bangumi 两个条目**
`scan` 会自动尝试季级对齐（本地每季映射到链上连续一段）。对不上时用 `season` 手工指定，
或用 `--seasons --clear-spans` 清掉季级 ID（第 5 章）。

**Q7. 库是英文剧名还能匹配吗**
能。标题搜索同时用 `Name` 和 `OriginalTitle`，集名对齐也做了括号、`SxxEyy`、`#nn` 等变体切分。

**Q8. `--library` 名字大小写要对吗**
不用。精确匹配 → 忽略大小写 → 唯一子串，三者都失败会列出可用库名。

**Q9. 跑完 `scan` 还要做什么**
`apply report.json` 才是真正写。想确认没写坏跑 `verify`；想防覆盖跑 `protect`。

**Q10. 支持电影 / 剧场版吗**
只针对剧集。电影没有集的概念，不在范围内；条目里夹着的单集剧场版会被季级对齐跳过。

## 9. 实现

数据只来自两处：Jellyfin REST API 和 Bangumi API v0（或第 6 章的离线档案）。

| 用途 | 端点 |
| --- | --- |
| 剧集 / 季 / 集列表 | `/Items`、`/Items/{id}`、`/Items?ParentId=` |
| 条目信息与关联 | `bgm.tv/v0/subjects/{id}`、`/subjects/{id}/subjects`（续集/前传） |
| 集列表 | `bgm.tv/v0/episodes?subject_id=…&type=0`（正片）/ `type=1`（SP） |
| 按标题找条目 | `bgm.tv/v0/search/subjects` |

一次 `scan` 的流程：

1. **找锚点**：取剧集/季上的 Bangumi ID，或按标题搜索；都要过标题校验。
2. **建池**：沿「续集/前传」把相关条目串起来，收集它们的正片集。
3. **对齐集名**：归一化（NFKC、去假名之外的非字母数字）→ 变体切分 → 保序动态规划（相似度 0.45）。
4. **判定**：集数相等，或（规模接近 + 命中率 ≥ 90% + 平均相似度 ≥ 0.55）才写；否则 `review`。
5. **写回**：只写新旧不同的集，写后回读。

**通用性**：除了 Bangumi 插件的 GUID（`protect` 用来定位配置）之外没有写死任何东西——库名、条目、
季结构全部运行期查询，换一个人的库同样能跑。

**它不解决什么**：Bangumi 上没有的条目；集名是纯文件名或没有信息的集；播出顺序与集号顺序不一致的剧
（`verify` 只能报 `disorder`，得你确认）；电影。

## 10. 开发

```bash
PYTHONPATH=src python -m unittest discover -s tests   # 87 个用例，全部离线（未 pip install -e . 时）
```

CI 在 Python 3.8 / 3.10 / 3.12 上跑同一套测试。目录结构：

```text
src/jellyfin_bangumi_ids/
  cli.py       命令行入口（scan/apply/season/auto/special/anchor/verify/rollback/protect/doctor）
  jellyfin.py  Jellyfin 客户端（重试、ProviderIds 读改写）
  bangumi.py   Bangumi API v0 客户端
  offline.py   离线档案后端（只读 + 自动回退在线）
  archive.py   .jsonlines → 只读索引
  scan.py      锚点、续集链、池、对齐、判定
  season_align.py  本地季 → 链上连续条目的保序 DP
  match.py     归一化、变体、相似度、保序 DP
  season.py    手工季节映射
  anchor.py    锚点修复（剧集级 / 季级）
  verify.py    只读体检
  transport.py HTTP、IPv4 强制、重试
```

发版：改 `pyproject.toml` 与 `__init__.py` 的版本号 → 更新 `CHANGELOG.md` → 打注记标签 → 在 GitHub
Release 附 wheel。

## License

MIT
