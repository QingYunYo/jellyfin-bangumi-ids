# jellyfin-bangumi-ids

[![test](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml/badge.svg)](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml)

> 中文 | [English](README.en.md)

把 Jellyfin 里每一集、每一季的 `ProviderIds.Bangumi` 填对，让 Bangumi 插件的进度同步落到正确的作品上。
只改这一个字段，不动视频文件，不动其他元数据。

**只想先看效果**：跑 `jbmid wizard`（没安装就用 `./jbmid wizard`），选「1 体检」——只看不写。

## 目录

- [1. 安装与快速开始](#1-安装与快速开始)
- [2. 它改什么：两类 ID](#2-它改什么两类-id)
- [3. 模式与用法](#3-模式与用法)
- [4. 季级 ID：为什么必须一起修](#4-季级-id为什么必须一起修)
- [5. 数据源与配置：离线档案、Docker、config](#5-数据源与配置离线档案dockerconfig)
- [6. 安全性](#6-安全性)
- [7. 常见问题](#7-常见问题)
- [8. 实现](#8-实现)
- [9. 开发](#9-开发)
- [License](#license)

## 1. 安装与快速开始

只依赖 Python 标准库，Python ≥ 3.8：

```bash
pip install git+https://github.com/QingYunYo/jellyfin-bangumi-ids.git
```

装不上也不要紧（NAS / Debian 的 Python 常带 PEP 668 保护），克隆下来直接用仓库自带的启动器，
一个系统目录都不碰：

```bash
git clone https://github.com/QingYunYo/jellyfin-bangumi-ids.git
cd jellyfin-bangumi-ids
./jbmid doctor        # 等价于装好后的 jbmid doctor
```

想装进虚拟环境：`python3 -m venv .venv && . .venv/bin/activate && pip install -e .`。

### 1.1 第一次运行：回答三个问题

```bash
./jbmid               # 装过就是 jbmid
```

还没有配置时，它直接进首次设置：先用 `/System/Info/Public` 确认地址可达（不需要 Key），
再问 Key，最后问档案——所以地址写错时不会再让你白输一遍 Key。

1. **Jellyfin 地址**——媒体服务器的地址（默认 8096 端口），**不是 Bangumi 的网址**；
   填 IP 也行，`192.168.1.10:8096` 会自动补成 `http://192.168.1.10:8096`。
2. **Jellyfin API Key**——Jellyfin 控制台 → API 密钥 → 新建。输入时可见，粘错能当场发现；
   回车后只显示打码摘要（`e76c********84d0`），并提示长度是否像 32 位。
3. **离线档案**（可选）——自动探测，找不到可以直接跳过，之后再补。

验证通过后写进 `~/.config/jellyfin-bangumi-ids/config.json`（权限 0600），之后的命令直接用，
**不用再 export 任何变量**。不想让 Key 落盘加 `--no-save-key`；介意肩窥再加 `--hide-key`。

> 目录不可写时它会明说「没保存」并给出 `JBMID_CONFIG_DIR` 的替代写法，不会假装成功。
> 以后要改：`jbmid config`（终端里进编辑菜单），`jbmid config --test` 检查连通性。

连不上时它会按原因分诊：地址类的错就只重问地址，401/403 就只重问 Key，其他情况让你选。

### 1.2 然后：用菜单，或者用子命令

跑起来就是八项菜单，第一次建议「1 体检 → 2 修集级 → 3 修季级」走一遍，出问题用「6 回滚」：

```text
  1  体检（verify + 报告）
  2  修集级 ID（scan → apply）
  3  修季级 ID（anchor --seasons）
  4  修番外 ID（special → apply）
  5  一条龙（sync）
  6  回滚（从备份还原）
  7  单剧（按剧修）
  8  配置（config）
  0  退出
```

每个写操作都先给预览、再问一次：**方括号里既写动作用什么键，也写回车默认选什么**，`0` 永远是返回/取消。
改完会打印备份文件、还原命令和等价的子命令，方便抄进脚本。要进 cron 就别用菜单，直接用 1.3 的子命令。

### 1.3 子命令（脚本或精确控制）

```bash
jbmid scan --library 动漫 --limit 3 --out report.json   # 只出报告；--library 不分大小写，省略=全部库
jbmid apply report.json --dry-run                       # 先干跑
jbmid apply report.json --backup jbmid-backup.json      # 真写，旧值自动备份
jbmid rollback jbmid-backup.json                        # 出问题一键还原
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

`review` 超过一两部时先看第 3 章选模式；ID 写完了插件还报错，看第 4 章（季级）。


## 2. 它改什么：两类 ID

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
| 一个本地季对两个条目 | `anchor --seasons --clear-spans` 清空季级 ID（见第 4 章） |
| 集名带 `SP` 被误判成番外 | 已按 `SP\d+` 识别（`（Sp...）` 不再误伤） |

## 3. 模式与用法

选模式的唯一硬标准是**写不写**——拿不准就加 `--dry-run`。下表按「动不动你的库」分组；
单个模式的细节见 3.1–3.10，**真实修复时怎么排序见 [3.11](#311-综合用法真实修复时的顺序)**。

| 分组 | 模式 | 干什么 | 写不写 |
| --- | --- | --- | --- |
| 入口 | `wizard` | 八项菜单：体检 / 集级 / 季级 / 番外 / 一条龙 / 回滚 / 单剧 / 配置 | 默认只预览 |
| 只读 | `doctor` | 连通性 / 数据源 / 插件状态 | 只读 |
| 只读 | `verify` | 体检：集级、季级 ID 对不对 | 只读 |
| 只出报告 | `scan` | 自动找锚点、按集名对齐整库 | 只出报告 |
| 只出报告 | `special` | 修 Season 0 / 番外 / OVA | 只出报告 |
| 写库 | `apply` | 把 `scan` / `special` 的报告写进 Jellyfin | 写（有 `--dry-run`） |
| 写库 | `season` | 手工指定「第几季 = 哪几个 subject」 | 写（有 `--dry-run`） |
| 写库 | `auto` | 按标题找条目 + 按集名对齐，一把梭 | 写（有 `--dry-run`） |
| 写库 | `anchor` | 修某部剧的剧集级 / 季级 ID | 写（有 `--dry-run`） |
| 写库 | `sync` | 一条龙：scan → apply → 季级 → 番外 → verify | 写（有 `--dry-run`） |
| 回退 | `rollback` | 按备份还原 | 写 |
| 配置 | `protect` | 让插件别覆盖手写 ID | 改插件配置 |
| 配置 | `config` | 记住档案路径 / 服务器地址 | 写配置文件 |

### 3.1 `wizard`：不想背参数就用它

`jbmid wizard` 把常用流程做成菜单，**每个写操作都先给预览、再问一次**，默认答案是「不写」。
还没有配置过时它会先带你做一次设置（地址 / Key / 档案），以后直接进菜单；想重做用 `jbmid setup`：

```bash
jbmid wizard            # 中文菜单（默认）
jbmid wizard --lang en  # 英文菜单
jbmid wizard --write    # 把「确认写入」的默认值改成是（仍然先预览、仍然要你按回车）
jbmid wizard --yes      # 非交互：全部取默认值，写操作一律不执行，只适合冒烟
```

菜单有八项：体检、修集级、修季级、修番外、一条龙、回滚、单剧、配置。启动时先解析服务器地址
（`--url` → `JF_URL` → `config` → 默认）与离线档案（顺序同第 5 章）；找不到档案时不是干问路径，
而是先把尝试过的路径和失败原因打出来，再让你选「手输路径 / 告诉宿主挂载点 / 先用在线」。

番外流程会另外问一句「清空借用正片 ID 的番外？」（默认 `N`，等价于 `--clear-borrowed`）。报告与备份默认写在
`./_local/backups/`（`--backup-dir` / `--out-dir` 可改）；确认写入后还会问一句「写完后刷新这些条目？」（默认 `N`，等价于
`--refresh`）。一次改动超过 50 条时，光按 `y` 不够，要照着数字再敲一遍条数；还原备份同样走这个阈值。每次写入
结束会打印三件事：备份文件、`jbmid rollback <备份>` 的还原命令、以及等价的非交互命令（方便你确认
没问题后抄进 cron）。非交互环境（管道、CI）直接拒绝并返回 2，除非显式 `--yes`。

界面约定：**方括号里写的就是直接回车时的默认值**，而 `0` 永远是「返回 / 退出 / 取消」——
按回车不会替你做任何写操作；子菜单按 `0` 回主菜单（不退出程序），一个流程做完直接回主菜单。

退出码：`0` 正常结束；`1` 连不上 Jellyfin 或 API Key 被拒；`2` 没有可交互终端且没给 `--yes`；
`3` 输入流结束（喂完 stdin 的脚本）；`130` 被 Ctrl-C 打断。出任何错误只打一行结论和该改什么，
想看完整请求就加 `-v`（打印每个 HTTP 请求、状态码与字节数）。

### 3.2 `scan`：先看清全局，再动手

最常用的入口：逐部剧找锚点、建池、按集名对齐、给出判定，**一个字都不写**。

```bash
jbmid scan --library 动漫 --out report.json   # 全库
jbmid scan --library 动漫 --limit 3            # 先试 3 部
```

只想看一两部时用 `--series-id`（Jellyfin 条目 id，可重复）：

```bash
jbmid scan --series-id 9a63c5f950cf05e5ba3796722a403f27
```

看 `series review` 的原因，确认无误后再 `jbmid apply report.json`。

整条链对不上时，`scan` 会退一步：某一季自己存的 Bangumi ID 如果通过标题校验、且集数也对得上，
就先让那一季按自己的条目对齐，剩下的季继续走链，`notes` 里写
`season 2 keeps its own subject 513878 (10/10 episodes)`。这条退路**只在整链失败时**启用——
默认仍先整链，否则「一个季横跨两个条目」会被误拆成「这一季有自己的条目」。

### 3.3 `apply` / `rollback`：报告落库与撤销

```bash
jbmid apply report.json --dry-run                 # 先看要改多少集
jbmid apply report.json --backup jbmid-backup.json
jbmid apply report.json --backup b.json --refresh # 写完顺便刷一次元数据
jbmid rollback jbmid-backup.json --dry-run
```

`apply` 只写「新旧不同」的集；`rollback` 按备份逐条还原。两者都有 `--dry-run`。

`--refresh` 只对**这次真正改过 ID 的集**调 Jellyfin 的刷新（`POST /Items/{id}/Refresh`），
让 Bangumi 插件按新 ID 重写它自己负责的字段（如 `OriginalTitle`）。不传就不刷。实测在
「整季错挂上一季 ID」的场景里，刷新只把 `OriginalTitle` 从上一季的标题改成这一季的，
`Name` / `Overview` / `PremiereDate` 不受影响；锁定字段也不会被覆盖。`season` / `auto` 同样接受
`--refresh`。

### 3.4 `season`：季划分对不上时

本地季数 ≠ 链上条目数、或顺序不同时用。JSON 写「第几季 = 哪些 subject」：

```json
{"物语系列": {"1": {"subjects": [140001]}, "14": {"subjects": [475354], "sp": true}}}
```

```bash
jbmid season --map map.json --dry-run
```

`sp: true` 表示这一季按番外处理（对齐 Bangumi 的 `type=1` 集）。

### 3.5 `auto`：一把梭

不指定锚点，按剧名搜条目、按集名对齐，然后直接写：

```bash
jbmid auto --library 动漫 --dry-run
jbmid auto --library 动漫
```

它最省事，也最需要看结果：每部剧都会打印 `method`（`name` / `season-map` / `stored` / `order`）。

### 3.6 `special`：番外、OVA、总集篇

Season 0 和名字含 `番外|OVA|OAD|SP|总集篇|特典` 的集，对齐 Bangumi 的 `type=1` 集：

```bash
jbmid special --library 动漫 --out specials.json
jbmid apply specials.json
jbmid special --library 动漫 --clear-borrowed   # 清掉借用了正片 ID 的番外
```

### 3.7 `anchor`：锚点本身错了

只修一部剧的锚点，也能修季级 ID：

```bash
jbmid anchor --series 物语系列 --dry-run                     # 换剧集级锚点
jbmid anchor --library 动漫 --seasons --all                  # 修季级 ID
jbmid anchor --library 动漫 --seasons --all --clear-spans    # 横跨季清空
```

取值顺序：**集级反查 → 季级多数票 → 剧集自己的 ID → 标题搜索**，都要过标题校验；`--force` 接收可疑值，
`--clear` 清空。

### 3.8 `verify`：只读体检

```bash
jbmid verify --library 动漫                              # 一行汇总 + 分类明细
jbmid verify --library 动漫 --by-series                  # 按剧聚合，先修哪部一眼看到
jbmid verify --library 动漫 --fail-on season-ids,dup     # 有命中就 exit 1（cron / CI 用）
```

各字段含义见[第 4 章](#4-季级-id为什么必须一起修)；`--fail-on` 可选 `unknown dup low-sim
disorder foreign anchors season-ids season-spans none`。

### 3.9 `protect` / `doctor`

```bash
jbmid protect     # 把 TrustExistedBangumiId 设为 True，刷新不再覆盖
jbmid doctor      # 连通性 / 数据源 / 插件状态
```

`jbmid config`（记住路径）在[第 5 章](#5-数据源与配置离线档案dockerconfig)末尾。

两份 README 里的示例输出都来自 [`examples/`](examples/README.md)（真实报告与备份的节选，附字段说明）。

### 3.10 `sync`：一条龙

把 4.11 那张顺序表里最常一起跑的五步串起来：`scan` → `apply` → `anchor --seasons` → `special` → `verify`。

```bash
jbmid sync --library 动漫 --dry-run              # 五步都只打印，一个字不写
jbmid sync --library 动漫 --refresh              # 真跑，写完顺手刷新改过的集
jbmid sync --series-id 9a63c5f950cf05e5ba3796722a403f27   # 只处理一部
```

只有 `scan` 判 `ok` 的集才会被写；某一步报错就停在那一步，不会带着半成品继续。`--stop-on-review`
让 `scan` 一遇 `review` 就收工；`--fail-on season-ids,dup` 把最后的体检结论变成退出码，适合塞进
cron / CI。`--backup-dir` 与 `--out-dir` 决定备份和中间报告放哪；同名备份已存在时会自动加时间戳
轮换，不会覆盖上一次的还原点，结束时打印全部备份路径。

### 3.11 综合用法：真实修复时的顺序

实际使用时这几个模式是**混着用**的，不是挑一个跑完就完事。第一次上手按这个顺序走一遍：

| 步骤 | 命令 | 为什么排在这 |
| --- | --- | --- |
| 1 摸底 | `jbmid doctor` → `jbmid verify --library 动漫` | 先确认能连、有没有离线档案；`verify` 给出基线（unknown / dup / disorder / season-ids） |
| 2 集级 | `jbmid scan --library 动漫 --out report.json` → `jbmid apply report.json` | 集级 ID 是季级投票的输入，必须先对 |
| 3 季级 | `jbmid anchor --library 动漫 --seasons --all`（有横跨季再加 `--clear-spans`） | 多数票要读第 2 步写好的集级 ID |
| 4 番外 | `jbmid special --library 动漫 --out specials.json` → `jbmid apply specials.json` | 番外借用正片 ID 会污染集级池，所以放在集级稳定之后 |
| 5 复检 | `jbmid verify --library 动漫` | 指标应收敛：`unknown 0`、`season-ids 0`、`season-spans 0`（`dup` 只剩重复条目本身） |
| 6 锁定 | `jbmid protect` | 最后再锁；先锁会让修复期间的手工调整也被挡住 |

四个混合场景：

**A. 新库 / 大修**（`verify` 一屏红）→ 1 → 2 → 3 → 4 → 5 → 6，全走。

**B. 只有几部坏**（`verify` 数字很小）→ `scan`（必要时 `--limit`）→ `apply` → `anchor --seasons` 只看报告、
只修提到的那几季 → `verify` 收尾。不必跑 `special`。

**C. 只有番外不对**（正片都对）→ `special --clear-borrowed` → `apply specials.json` → `verify`。不碰集级。

**D. TMDB 一季 = Bangumi 两个条目** → 先 `scan`（会自动做季级对齐）；仍 `review` 就用 `season --map` 指定；
一个本地季横跨两条目则 `anchor --seasons --all --clear-spans`（清空，不要挑一个）；最后 `verify`。

顺序不能反的三条原因：**集级 → 季级**（投票来源是集级 ID）、**集级 → 番外**（S0 借正片 ID 会让池不干净）、
**修完 → 锁**（`protect` 锁早了会挡住你自己的后续修正）。

## 4. 季级 ID：为什么必须一起修

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
ID 反查条目」，两边都对——第 2 章那段日志对照就是这个机制。

**安全边界**：`--force` 只放宽「低置信」（少于 2 集、票数不足 60%），**不会**给横跨季写多数票
（直接跳过），否则会把刚清空的那一半写回去。单集季可以用 `--force` 补 ID。

写回走读-改-写：GET 完整条目 → 只改 `ProviderIds.Bangumi` → POST → 回读确认，并检查相邻字段有没有
被连带改掉；改了什么同时写进备份，`rollback` 可还原。季级备份里 `kind` 字段是 `season`。

## 5. 数据源与配置：离线档案、Docker、config

装了 Bangumi 插件并跑过「离线数据库更新」后，`{DataPath}/bangumi/archive/` 下有几份
`.jsonlines`。本工具直接读它们，把在线请求换成主键查询：

| 操作 | 在线 API | 离线档案（已建索引） |
| --- | --- | --- |
| `verify` 全库 | 约 40 分钟 | 约 18 秒 |
| `scan` 全库 | 约 12 分钟 | 首次建索引约 2 分钟，之后约 19 秒 |

**怎么指定档案**（按优先级）：

1. `--archive DIR`（每条命令都能加）
2. 环境变量 `JBMID_ARCHIVE`
3. 配置文件：`jbmid config --archive DIR`
4. 仓库内 `_local/archive`（自己拷一份档案时用）
5. `--archive-root DIR` / `JBMID_ARCHIVE_ROOT`：把容器内路径映射到宿主机（见下）
6. Jellyfin `/System/Info` 报告的 `DataPath` 在**当前机器上直接可读**时自动使用
7. `--search-archive` / `JBMID_ARCHIVE_SEARCH=1`：在 `--archive-root` 下做有界搜索（兜底，较慢）

**Jellyfin 跑在 Docker 里**：插件看到的是容器内路径（如 `/config/data/bangumi/archive`），
在宿主机上并不存在。把宿主目录告诉工具，它会自己映射：

```bash
jbmid config --archive-root /volume1/docker/jellyfin   # 换成你的挂载点
jbmid doctor
```

映射规则：整条容器路径拼在宿主目录下 → 去掉第一段 → 只取最后三段（`data/bangumi/archive`），
依次尝试。层数太深仍找不到时加 `--search-archive`（有界搜索：最多 5 层、3 秒）。

**一个坏掉的路径不会中止探测**：`JBMID_ARCHIVE` 指向已删除的目录时，工具记下这条尝试继续往下找，
而不是静默退回在线、让你等 40 分钟。`jbmid doctor` 会打印每一条尝试过的路径和失败原因
（`missing` / `unreadable`），照着补一条 `jbmid config --archive DIR` 即可。

### 5.1 记住路径：`jbmid config`

不用每次敲参数：

```bash
jbmid config --url http://127.0.0.1:8096   # Jellyfin 地址（默认 8096 端口），不是 Bangumi
jbmid config --api-key KEY                 # 存 Key（明文，文件 0600；显示时打码）
jbmid config --archive DIR                 # 档案目录
jbmid config --archive-root DIR            # 宿主机上 Jellyfin 的 data 挂载点
jbmid config --test                        # 用当前配置连一次，打印版本/用户数/库数
jbmid config                               # 终端里进编辑菜单；管道里只打印
jbmid config --unset archive               # 删掉某一项
```

存在 `~/.config/jellyfin-bangumi-ids/config.json`（Windows 为 `%APPDATA%`，`JBMID_CONFIG_DIR` 可改），
权限 0600；API Key 只在 `jbmid setup` / `jbmid config --api-key` 时明文写入，`--no-save-key`
可以完全不落盘，显示时永远打码。文件坏了会打一行原因、把原件改名 `.bad`，下次保存不覆盖它。
取值优先级：`--url` / `--api-key` → `JF_URL` / `JF_API_KEY` → 配置文件 → 默认值。

常用环境变量：

| 变量 | 作用 | 等价参数 |
| --- | --- | --- |
| `JF_URL` | Jellyfin 地址 | `--url` |
| `JF_API_KEY` | Jellyfin API Key（唯一凭据来源，不写进配置文件） | `--api-key` |
| `JBMID_ARCHIVE` | 档案目录 | `--archive` |
| `JBMID_ARCHIVE_ROOT` | 容器路径对应的宿主机目录 | `--archive-root` |
| `JBMID_ARCHIVE_SEARCH` | 非空即开启有界搜索（`0`/`off` 关闭） | `--search-archive` |
| `JBMID_CACHE` | SQLite 索引缓存目录 | 无 |
| `JBMID_CONFIG_DIR` | 配置文件目录 | 无 |

服务器地址的取值顺序：`--url` → `JF_URL` → `jbmid config --url` → 默认 `http://127.0.0.1:8096`。

索引缓存放在 `~/.cache/jellyfin-bangumi-ids/`（`JBMID_CACHE` 可改），约 150 MB，只读源文件；
档案由插件的「离线数据库更新」任务维护（约两周一次，以插件为准），过期时以在线 API 为准。档案里没有的条目（新集、关系图、按标题搜索）
自动回退在线 API。

## 6. 安全性

- **只改一个字段**：`ProviderIds.Bangumi`。不碰文件、不碰其他元数据、不删条目。
- **读-改-写 + 回读**：写前取完整条目，写完回读，并检查相邻字段是否被连带修改。
- **处处有备份**：`apply` / `anchor` / `season` / `special` / `rollback` 都生成备份，一键还原。
- **不确定就不写**：集数对不上、覆盖不足、相似度不够 → 标 `review` 跳过。
- **默认不覆盖手写值**：`apply` 只写「新旧不同」的集；`protect` 让插件也不要覆盖。
- **凭据只在本地**：API Key 和 Bangumi token 只用于发请求，不落盘、不上传。

## 7. 常见问题

**Q1. `HTTP 401`**
用 `Authorization: MediaBrowser Token="密钥"`，不是 `X-Emby-Token`。`jbmid` 已经这样发；自己 curl 时注意。

**Q2. `HTTP 404 ... "Series not found"`**
旧版 Jellyfin 的 `/Shows/{id}/Episodes` 行为不一致。本工具改用
`/Items?ParentId=…&IncludeItemTypes=Episode&Recursive=true`，不依赖那个端点。

**Q3. 扫描很慢**
每部剧要串行请求 Bangumi。接上离线档案（第 5 章）后全库 19 秒；也可以 `--limit` 先扫几部。

**Q4. 同一部番在库里出现两次**
`verify` 的 `duplicate_series` 会列出来（常见于同一份文件被两个库路径收录）。工具两份都改，不删条目。

**Q5. SP / OVA 怎么处理**
默认只修正片：Season 0 和名字含 `番外|OVA|OAD|SP|总集篇|特典` 的集不当正片数。要一起修用 `special`。

**Q6. TMDB 一季 = Bangumi 两个条目**
`scan` 会自动尝试季级对齐（本地每季映射到链上连续一段）。对不上时用 `season` 手工指定，
或用 `--seasons --clear-spans` 清掉季级 ID（第 4 章）。

**Q7. 库是英文剧名还能匹配吗**
能。标题搜索同时用 `Name` 和 `OriginalTitle`，集名对齐也做了括号、`SxxEyy`、`#nn` 等变体切分。

**Q8. `--library` 名字大小写要对吗**
不用。精确匹配 → 忽略大小写 → 唯一子串，三者都失败会列出可用库名。

**Q9. 跑完 `scan` 还要做什么**
`apply report.json` 才是真正写。想确认没写坏跑 `verify`；想防覆盖跑 `protect`。

**Q10. 支持电影 / 剧场版吗**
只针对剧集。电影没有集的概念，不在范围内；条目里夹着的单集剧场版会被季级对齐跳过。

**Q11. 提示 `jbmid: command not found`**
`pip install` 多半被系统的 PEP 668 拦了。直接用仓库里的 `./jbmid`，或建虚拟环境：
`python3 -m venv .venv && . .venv/bin/activate && pip install -e .`，之后 `jbmid` 就在 PATH 里。

**Q12. 向导能放进 cron 吗**
不建议。cron 没有终端，向导会直接拒绝并返回 2；用子命令（如 `jbmid sync --library 动漫`），
或 `jbmid wizard --yes`（全取默认、不会写库，只适合冒烟）。

## 8. 实现

数据只来自两处：Jellyfin REST API 和 Bangumi API v0（或第 5 章的离线档案）。

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

## 9. 开发

```bash
PYTHONPATH=src python -m unittest discover -s tests   # 197 个用例，全部离线（未 pip install -e . 时）
```

CI 在 Python 3.8 / 3.10 / 3.12 上跑同一套测试。目录结构：

```text
src/jellyfin_bangumi_ids/
  cli.py       命令行入口（scan/apply/season/auto/special/anchor/verify/sync/rollback/protect/doctor/config/wizard）
  wizard.py    交互向导（八项菜单，写前预览、批量阈值）
  jellyfin.py  Jellyfin 客户端（重试、ProviderIds 读改写）
  bangumi.py   Bangumi API v0 客户端
  offline.py   离线档案后端（只读 + 自动回退在线）
  archive.py   .jsonlines → 只读索引
  scan.py      锚点、续集链、池、对齐、判定
  season_align.py  本地季 → 链上连续条目的保序 DP
  match.py     归一化、变体、相似度、保序 DP
  season.py    手工季节映射
  anchor.py    锚点修复（剧集级 / 季级）
  verify.py    只读体检（--by-series / --fail-on）
  sync.py      一条龙：scan → apply → 季级 → 番外 → verify
  transport.py HTTP、IPv4 强制、重试
  settings.py  记住档案路径/服务器地址（不存 API Key）
```

发版：改 `pyproject.toml` 与 `__init__.py` 的版本号 → 更新 `CHANGELOG.md` → 打注记标签 → 在 GitHub
Release 附 wheel。

## License

MIT
