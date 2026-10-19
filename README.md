# jellyfin-bangumi-ids

**批量修好 Jellyfin 里 Bangumi 插件的剧集 ID。**

![tests](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml/badge.svg)

> 中文 | [English](README.en.md)

零依赖的命令行工具，修的是 Jellyfin 剧集的 `ProviderIds.Bangumi`。这个 ID 错了，Bangumi 插件要么
根本不上报（日志里 `doesn't have bangumi id`），要么把进度报给另一部番。工具扫描媒体库、
**按集名**（不是按集号）对齐、逐集写回，并留下可一键回滚的备份。

---

## 目录

1. [症状：你可能正需要它](#1-症状你可能正需要它)
2. [它能做什么](#2-它能做什么)
3. [安装](#3-安装)
4. [准备 API Key](#4-准备-api-key)
5. [快速开始](#5-快速开始)
   - [5.1 第一次跑](#51-第一次跑)
   - [5.2 写入与回滚](#52-写入与回滚)
6. [用离线档案提速](#6-用离线档案提速)
7. [写入模式详解](#7-写入模式详解)
   - [7.1 `scan`：自动找锚点](#71-scan自动找锚点)
   - [7.2 `season`：你自己说哪几个 subject 拼成一季](#72-season你自己说哪几个-subject-拼成一季)
   - [7.3 `auto`：最省事，也最需要看结果](#73-auto最省事也最需要看结果)
   - [7.4 `special`：连番外一起修](#74-special连番外一起修)
   - [7.5 `anchor`：只修一部剧的锚点](#75-anchor只修一部剧的锚点)
   - [7.6 `verify`：只读体检](#76-verify只读体检)
   - [7.7 `protect`：防止下次刷新把 ID 覆盖回去](#77-protect防止下次刷新把-id-覆盖回去)
8. [实战：我在自己的动漫库上遇到的错位](#8-实战我在自己的动漫库上遇到的错位)
   - [8.1 整季右移两集](#81-整季右移两集)
   - [8.2 只补了半季](#82-只补了半季)
   - [8.3 剧集 ID 挂到另一部作品上](#83-剧集-id-挂到另一部作品上)
   - [8.4 播出顺序不是集号顺序](#84-播出顺序不是集号顺序)
   - [8.5 一个本地季对两个条目](#85-一个本地季对两个条目)
   - [8.6 残缺季 + 集名完全对不上](#86-残缺季--集名完全对不上)
   - [8.7 名字里带 `SP` 被误伤](#87-名字里带-sp-被误伤)
   - [8.8 没遇到、但工具也防着的情形](#88-没遇到但工具也防着的情形)
9. [安全性](#9-安全性)
10. [常见问题](#10-常见问题)
11. [数据从哪来](#11-数据从哪来)
12. [处理流程](#12-处理流程)
    - [12.1 五步流水线](#121-五步流水线)
    - [12.2 集名对齐长什么样](#122-集名对齐长什么样)
    - [12.3 季级对齐解掉的形状](#123-季级对齐解掉的形状)
    - [12.4 什么情况才会写](#124-什么情况才会写)
13. [通用性：换一个人的库还能用吗](#13-通用性换一个人的库还能用吗)
14. [它不解决什么](#14-它不解决什么)
15. [开发](#15-开发)
    - [15.1 跑测试与 CI](#151-跑测试与-ci)
    - [15.2 目录结构](#152-目录结构)
    - [15.3 发布新版本](#153-发布新版本)
16. [License](#16-license)

---

## 1. 症状：你可能正需要它

- 播完一集，Bangumi 上完全没动静，日志里反复出现
  `item "..." (#...) doesn't have bangumi id, ignored`。
- 进度同步了，但同步到了**别的番**——比如整季的 ID 都指向另一部作品。
- 一部番在 TMDB 是一季，在 Bangumi 被拆成「上半／下半」两个条目，第 12 集之后全错位。
- 特别篇（SP / OVA / 第 0 话）被当成正片，导致后面每一集都偏移一位。
- 手动改了一集 ID，下次刷新元数据又被插件覆盖回去。

## 2. 它能做什么

Jellyfin 的每一集都有一个 `ProviderIds.Bangumi`，Bangumi 插件上报进度时只认这个数字。
本工具负责把这个数字填对，**并且只填这一个字段**。

七个模式，按你库的混乱程度选（每个模式下面都有真实的输入和输出）：

| 模式 | 何时用 | 写不写 |
| --- | --- | --- |
| `scan` | 大部分番是干净的，只有零星几部不对 | 生成报告，`apply` 才写 |
| `season` | Bangumi 的季划分和你的文件夹完全对不上，需要你指定 | 直接写（可 `--dry-run`） |
| `auto` | 想一把梭，让工具自己按标题找条目、按集名对齐 | 直接写（可 `--dry-run`） |
| `special` | 番外 / SP / OVA / 总集篇 也想同步 | 生成报告，`apply` 才写 |
| `anchor` | 某一部剧的锚点（series/season 上的 Bangumi ID）本身就是错的 | 直接写（可 `--dry-run`） |
| `verify` | 修完（或修前）想看看哪些 ID 是坏的 | 只读 |
| `protect` | 改完 ID 之后，让插件别再覆盖 | 改插件设置 |

`apply` 和 `rollback` 是通用的：前者把报告写进 Jellyfin，后者按备份还原。

## 3. 安装

只依赖 Python 标准库，Python ≥ 3.8。

```bash
pip install git+https://github.com/QingYunYo/jellyfin-bangumi-ids.git
# 或者本地开发
git clone https://github.com/QingYunYo/jellyfin-bangumi-ids.git
cd jellyfin-bangumi-ids && pip install -e .
```

装完就有 `jbmid` 命令（也可以 `python -m jellyfin_bangumi_ids`）。

## 4. 准备 API Key

Jellyfin 控制台 → 管理 → API 密钥 → 新建，给它一个名字（比如 `jbmid`）。
然后：

```bash
export JF_URL=http://127.0.0.1:8096
export JF_API_KEY=你的key
jbmid doctor
```

`doctor` 会告诉你 Jellyfin 版本、库列表、bgm.tv 是否连通、插件配置状态，以及离线档案有没有
找到（`archive : …`，读不到时会提示用 `--archive DIR`）。输出长这样：

```text
$ jbmid doctor
data source    : offline archive /path/to/bangumi/archive (episodes=1705871, subjects=694202)
jellyfin  : 12.2.0 (http://127.0.0.1:8096)
archive   : /path/to/bangumi/archive (694202 subjects, 1705871 episodes)
libraries : 8 (电视剧, 电影, 动漫, 动漫电影, 合集, JAV, Playlists, 音乐)
bgm.tv    : ok 0.00s (化物语)
plugin    : TrustExistedBangumiId=True ReportPlaybackStatus=True
```

全绿再往下走。`plugin` 那行就是 `protect` 之后的开关状态。

## 5. 快速开始

### 5.1 第一次跑

```bash
# 1) 扫一遍「动漫」库，生成报告（不写任何东西）
jbmid scan --library 动漫 --out report.json

# 2) 看报告里的三个数字：series ok / series review / episodes to write
#    想先试水就加 --limit 5

# 3) 先干跑，确认要写多少集
jbmid apply report.json --dry-run

# 4) 真写（自动备份旧值到 jbmid-backup.json）
jbmid apply report.json --backup jbmid-backup.json

# 5) 出问题就一键回滚
jbmid rollback jbmid-backup.json
```

第一次跑（只取 3 部试试）的完整输出：

```text
$ jbmid scan --library 动漫 --limit 3
data source    : offline archive /path/to/bangumi/archive (episodes=1705871, subjects=694202)
scanning 3 series from library 动漫
[1/3] OK   2.5次元的诱惑                                to write 0
[2/3] OK   86-不存在的战区-                             to write 0
[3/3] OK   拔作岛                                       to write 0

series ok      : 3
series review  : 0
episodes       : 0 to write
report         : jbmid-report.json
```

整库跑完（89 部）时的最后三行就是判断依据：`89 / 0 / 0` 表示全对、没有要写的；
出现 `review` 的行要人眼看，`to write` 是 `apply` 会动的集数。锚点和整条 TV 链
是怎么来的见 [7.1](#71-scan自动找锚点)。

报告长这样（节选，完整字段见 7.1）：

```json
{
  "library": "动漫",
  "threshold": 0.45,
  "series": [
    {
      "series": "2.5次元的诱惑",
      "seasons": 1,
      "status": "ok",
      "anchor": 410346,
      "anchor_how": "episode-parent",
      "chain": [410346],
      "notes": ["chain trimmed to 1 subject(s)",
                "kept 24 existing ids (library order differs from Bangumi)"],
      "episodes": [
        {"item_id": "69c3…", "season": 1, "index": 1, "name": "异次元的新进生",
         "bgm_id": "1336023", "bgm_name": "来自异次元的新生", "sim": 0.8, "change": false}
      ]
    }
  ],
  "summary": {"series_ok": 3, "series_review": 0, "episodes_to_write": 0}
}
```

> 完整示例是真实报告的节选（一条 `ok`、两条 `review` 的原文 `reason`）：
> [`examples/scan-report.json`](examples/scan-report.json)。

### 5.2 写入与回滚

`apply` 会把报告里 `change: true` 的集逐条写入（单字段写入与回读校验见第 9 章），
每写一条都进备份：

```json
[
 {"item_id": "69c36749e0dfb987a371a1980815c354", "series": "2.5次元的诱惑",
  "season": 1, "index": 2, "name": "…", "old": "1336023", "new": "1336024"}
]
```

> 完整示例：[`examples/backup.json`](examples/backup.json)（整列右移与原本为空的都在）。

回滚就是照着 `old` 写回去，一条命令：

```text
$ jbmid rollback jbmid-backup.json
would restore 33 episodes        # 加 --dry-run 只看不动
```

## 6. 用离线档案提速

Bangumi 插件自带一份离线数据库：在 Jellyfin 里跑一次「离线数据库更新」任务，它会把
subject / episode / 人物档案下到 `{Jellyfin 数据目录}/bangumi/archive/`（Docker 里通常是
`/config/data/bangumi/archive`，约 1.5 GB，两周左右更新一次）。

本工具**默认就会用这份档案**，不需要额外配置：

```bash
jbmid scan --library 动漫            # 自动探测档案，找到就用
jbmid verify --library 动漫          # 同样自动走离线版
jbmid scan --library 动漫 --archive /path/to/archive   # 档案不在默认位置时手动指定
jbmid scan --library 动漫 --no-archive                 # 强制只用在线 API
```

探测顺序：`--archive` → 环境变量 `JBMID_ARCHIVE` → Jellyfin `/System/Info` 里的 `DataPath`。

**第一次会建索引**：1.5 GB 的 jsonlines 过大，不适合每次现读，所以首次运行会在缓存目录
（`$JBMID_CACHE` → `~/.cache/jellyfin-bangumi-ids` → 系统临时目录）生成约 150 MB 的 SQLite
索引，耗时 20 秒左右；之后每次查询在毫秒级。档案更新（文件大小或修改时间变化）后索引自动重建。

**实测收益**（动漫库，2000 多集）：

| 操作 | 在线 API | 离线档案（冷） | 离线档案（热） |
| --- | --- | --- | --- |
| `verify` | 40 分钟（还会被限流打断） | 18 秒 | 18 秒 |
| `scan` | 约 12 分钟 | 2 分半 | 19 秒 |

离线库里没有「续集/前传」关系和标题搜索，这两项第一次仍会调用 API，并缓存进索引——
所以冷启动要拉一遍关系图，第二次开始才是纯离线。档案比线上旧，里面查不到的条目
（新番、刚建的新条目）会自动回落到 API，不会漏掉。

## 7. 写入模式详解

### 7.1 `scan`：自动找锚点

```bash
jbmid scan --library 动漫 --out report.json
jbmid scan --library 动漫 --limit 5          # 先试 5 部
jbmid scan --library 动漫 --no-search        # 只信已有 ID，不按标题搜索
```

锚点优先级：**集级反查（拿每集自己的 ID 反查上级条目）→ 季级 ID 多数票 → 剧集自己的 ID → 按标题搜索**。
越靠前越可信：每集的 ID 只属于一个条目，季级是逐季刮的，剧集级只是一个字段——一次误匹配
或一次刷新就能把它改坏（物语系列挂到 `2098` 就是这么来的）。

两条守卫，缺一不可：

- **已有 ID 也要验**。库里存的 ID 可能是错的（比如整部剧挂到了另一部番上），
  所以拿到 ID 后先取该条目的标题，和你的剧名比一次；不像就丢掉，退回标题搜索。
  不加这道校验，一个错 ID 会让整部剧永远 `review`，甚至被一次刷新直接改写。
- **搜索要过标题守卫**（`无职转生` 能匹配 `无职转生～到了异世界就拿出真本事～`，
  `Andor` 匹配不上 `安德烈和威利的冒险`），否则直接 `review`，不赌。

搜索时**剧名（`Name`）和原标题（`OriginalTitle`）都会用**：中文库的剧名常是译名，
而 bgm 的 `name` 是原名，标题字段对上原名往往一次就中（实测在 88 部库里，
只用剧名命中 81 部，加上原标题到 87 部）。文本归一化同时做了全角折半角
（`８６` → `86`）与保留假名，否则纯片假名标题会被归一化成空串，相似度恒为 0。

**整库跑完的输出**（89 部）：`89 ok / 0 review / 0 to write`，三个数字的含义见 5.1。

**报告里的每一部剧**（节选）由这些字段构成：

| 字段 | 含义 |
| --- | --- |
| `status` | `ok` 或 `review` |
| `reason` | 进 review 的原因（`size mismatch` / `weak match` / `no Bangumi anchor` …） |
| `anchor` / `anchor_how` | 采用的锚点条目，以及它是怎么定的（`episode-parent` / `season-vote` / `series-id` / `search`） |
| `chain` | 从锚点拉出来的整条 TV 链（subject id 列表） |
| `notes` | 对齐细节，如 `season map 1:S1->95225 2:S2->109386` |
| `episodes[]` | 每集的 `old` / `bgm_id` / `bgm_name` / `sim` / `change` |

### 7.2 `season`：你自己说哪几个 subject 拼成一季

当 Bangumi 的条目切分和你的文件夹切分毫无规律时，用这个。写一个 json：

```json
{
  "无职转生～到了异世界就拿出真本事～": {
    "1": {"subjects": [277554]},
    "2": {"subjects": [325585]},
    "3": {"subjects": [373247]},
    "4": {"subjects": [444557]},
    "5": {"subjects": [501963]}
  },
  "物语系列": {
    "4": {"subjects": [68812], "filter": "猫物语（白）"},
    "15": {"subjects": [475354], "filter": "业物语|残酷童话"}
  }
}
```

- 键是**你库里的剧名**，内层键是**季号**（Jellyfin 的 `IndexNumber`）。
- `subjects` 按顺序拼接成一个池子，`filter` 是只保留集名匹配该正则的集，
  `sp: true` 表示把该条目的 SP 也纳入池子（处理「SP 插在正片中间」的情况）。
- 池子和本地集数相等时按顺序写；不等时按集名对齐，命中率不到 100% 就 `review`。

真实例子见 [`examples/monogatari-season-map.json`](examples/monogatari-season-map.json)，其余示例文件见 [`examples/README.md`](examples/README.md)。

**输出**（用上面那份 17 季的 map 跑「物语系列」）：

```text
$ jbmid season --map examples/monogatari-season-map.json --dry-run
[物语系列 S1] ok 15/15 eps, mean sim 0.82
[物语系列 S2] ok 11/11 eps, mean sim 0.86
…
[物语系列 S12] review 12/19 eps, mean sim 0.97
…
seasons ok: 16   review: 1   episodes: 95
would write 0 episodes
```

一季一行，`review` 说明那一季的池子和本地对不上（这季多了 7 集），其余照写。

### 7.3 `auto`：最省事，也最需要看结果

```bash
jbmid auto --library 动漫 --dry-run
jbmid auto --library 动漫 --backup jbmid-backup-auto.json
```

按剧名搜 Bangumi，取候选里标题能对上的，拉整条链，按集名对齐。
命中率 ≥ 80% 直接写；否则若**集数完全相等且剧名带「第 N 季 / Season N」**，
退化成顺序映射并标记 `order-low-confidence`——这条路能吃下「集名是纯日文/纯英文
文件名」的库（比如 `S01E01 - [CASO&DMG] ...`）。

**输出**（节选）：

```text
$ jbmid auto --library 动漫 --dry-run
[ok] 2.5次元的诱惑 subject=410346 method=name cov=100% sim=0.90 -> 24 eps
[ok] 碧蓝之海 subject=235130 method=season-map cov=100% sim=0.88 -> 24 eps
[ok] CLANNAD subject=51 method=name cov=100% sim=0.80 -> 44 eps
[ok] 吊带袜天使 subject=8402 method=name cov=92% sim=0.90 -> 12 eps
…
series ok: 83   review: 6   episodes: 2120
would write 0 episodes
```

`method` 是拿什么认出来的：`name`（标题搜索）、`season-map`（季级对齐）、`stored`（库里已存的
集 ID）、`order`（集数相等时的顺序映射）。

### 7.4 `special`：连番外一起修

正片 ID 都在 Season ≥ 1 里，番外一般挂在 Season 0。前面几种模式都会**跳过**它们，
所以番外永远同步不到 Bangumi。`special` 专门补这一块：

```bash
jbmid special --library 动漫 --out specials.json
jbmid apply specials.json --dry-run
jbmid apply specials.json --backup specials-backup.json
```

它从同一个锚点拉整条链，把每个条目的 `type=1`（SP/OVA/总集篇）拼成一个池子，
再用集名和你的 Season 0 / 集名带 `OVA|SP|番外|总集篇` 的集对齐。

- 名字能对上才写（相似度 ≥ 0.55），对不上的留给人工——不会为了「凑数」硬写。
- 整条链上只有一两个 SP、且数量正好对上时，走顺序映射，但仍要求最低相似度 0.25。
- 输出和 `scan` 完全同构，所以还是用 `apply` / `rollback`，备份照旧。

**输出**（节选）：

```text
$ jbmid special --library 动漫
[11/89] OK      CLANNAD                      match 3/5 sim 0.92
[49/89] OK      轻音少女                       match 2/5 sim 0.79
[51/89] OK      人形电脑天使心                   match 2/4 sim 1.00
series ok      : 13
series review  : 76
specials       : 19 matched
borrowed       : 0 cleared
episodes       : 0 to write
```

极少数 SP 本来就已经对（比如 Bangumi 把 OVA 记成正片），所以 89 部里只有 13 部有可对齐的番外。

报告节选（`match 3/5`、逐集 `old` / `bgm_id`）：[`examples/special-report.json`](examples/special-report.json)。

加 `--clear-borrowed` 还会处理另一种脏数据：番外「借用」了正片某一集 ID（Jellyfin 插件偶尔这么干，
结果番外显示的是正片标题）。判定标准是**拿这个 ID 去 Bangumi 查，集名和本地番外对不上**——
对得上说明它本来就是被 Bangumi 记成正片的 OVA，保留；对不上就清空，宁可空着也不挂错的。
清空同样进备份，`rollback` 能一字不差地还原。

```bash
jbmid special --library 动漫 --clear-borrowed --out specials.json
```

### 7.5 `anchor`：只修一部剧的锚点

剧集级 / 季级的 `Bangumi` 是「锚点」，所有模式都从它出发。锚点错了，整部剧再努力也匹配不上
（典型症状：`review` 里一直挂着同一部剧，原因写着 `size mismatch` 或 `weak match`）。

```bash
# 看它现在挂的是什么、工具认为应该挂什么（不写）
jbmid anchor --library 动漫 --series "凉宫春日的忧郁" --dry-run

# 交给工具自己定：按季里第一集反查上级条目 > 季级 ID 多数票 > 剧集级 ID > 标题搜索
jbmid anchor --library 动漫 --series "凉宫春日的忧郁"

# 你确定是哪个条目，直接指定（会做一次标题校验，不像就拒绝，--force 可绕过）
jbmid anchor --library 动漫 --series "某部剧" --id 1606

# 剧集级 ID 是错的、又不想换一个新的，就清掉
jbmid anchor --library 动漫 --series "某部剧" --clear
```

**输出**：

```text
$ jbmid anchor --library 动漫 --series "凉宫春日的忧郁" --dry-run
凉宫春日的忧郁 (66cd9aade8589fc19b81d5776ffeccd6)
  before : 1606
  after  : 1606 (episode-parent)
already correct, nothing to write
```

这条顺序的来源：**每集自己的 Bangumi ID 只属于一个上级条目**，所以一季里头两集反查出来的条目
比季级元数据（经常是复制来的）可靠，整季元数据没匹配上时也是它兜底（顺序本身见 7.1）。

改动会写进备份（`anchor-backup.json`），格式与集级备份一致，`rollback` 同样能还原。

**季级 ID 也要查**：插件上报「在看」时用的是**季**的 Bangumi ID（`PlaybackScrobbler` 取这一集的父级），
集级 ID 只负责单集状态。所以「集级全对、季级整体错位一格」这种故障，逐集检查永远发现不了：播放照常，
bgm.tv 上却记到了相邻那一季。用集级 ID 投票即可定位：

```bash
# 只报告：哪一季的季级 ID 不是它自己集级 ID 的多数票
jbmid anchor --library 动漫 --seasons --all --dry-run

# 修正（写进备份，`rollback` 可还原）
jbmid anchor --library 动漫 --seasons --all
```

```text
$ jbmid anchor --library 动漫 --seasons --all --dry-run
凉宫春日的忧郁
  season 1   id 1372     -> 1606     (28/28 episodes)
人形电脑天使心
  season 1   id 496276   -> 12       (26/26 episodes)
37 season id(s) off, 0 written (dry run)
```

只写「票数 ≥ 60% 且至少 2 集」的季；其余只报告，`--force` 才会写——但 `--force` 也**不会**给横跨
两个条目的季写多数票（直接跳过），否则会把刚清掉的那一半再次写坏。

**一个本地季横跨两个 Bangumi 条目时，不存在唯一正确的季级 ID**：写哪个，另一半集都会被报成隔壁条目
（86 的第一季 = 两个 part，无职转生的第一季同理）。这类季用 `--clear-spans` 清空季级 ID——清空后
`PlaybackScrobbler` 会退回「用这一集自己的 ID」再反查条目。实测同一集的日志：

```text
清空前：report subject #525565 status Watching   ← 写死的第一 part
清空后：report subject #638497 status Watching   ← 这一集自己所属的 part
```

```bash
# 清空所有横跨两个条目的季（写进备份，`rollback` 可还原）
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


### 7.6 `verify`：只读体检

```bash
jbmid verify --library 动漫 --out check.json
```

把每个有 Bangumi ID 的集拿去反查 `api.bgm.tv`，比对集名，相似度低于阈值的全列出来。
注意这**不等于错了**：文件名式集名、纯翻译差异、英文名条目都会误报，需要人眼扫一遍。

**用离线档案跑（推荐）**：整库十几秒，不占 API 配额；档案在哪、索引怎么建见第 6 章：

```bash
jbmid verify --library 动漫 --archive /path/to/bangumi/archive --out check.json
```

报告节选：[`examples/verify-report.json`](examples/verify-report.json)。

**输出**：

```text
$ jbmid verify --library 动漫
data source    : offline archive /path/to/bangumi/archive
offline check: 2095 ids | unknown 0 | dup 3 | low-sim 278 | disorder 22 | foreign 5 | anchors 0 | season-ids 0 | season-spans 0
```

`check.json` 里除了这些计数，还分门别类列了明细：`season_rows` 是季级 ID 与它集级 ID 多数票不一致的季
（修法见 7.5 的 `--seasons`）；`span_rows` 是**横跨两个条目、却仍写着一个季级 ID** 的季（修法见 7.5 的
`--clear-spans`）——清空之后这些季不再计入 `season-ids`，所以体检结果才能回到「季级也对得上」：

```json
{
  "checked": 2095, "threshold": 0.45,
  "unknown": 0, "duplicate": 3, "low_similarity": 278,
  "disorder": 22, "foreign_subject": 5, "anchor_rows": [], "season_rows": [], "span_rows": [],
  "duplicate_series": [
    {"name": "间谍过家家",
     "paths": ["/strm/Anime/…/间谍过家家 (2022)", "/hdd/Anime/间谍过家家 (2022)"]}
  ],
  "rows": [
    {"series": "2.5次元的诱惑", "bgm_id": 1336030,
     "local": "热爱Cosplay吗？", "bgm": "爱着角色扮演吗？",
     "season": 1, "index": 8, "sim": 0.235, "kind": "low_similarity"}
  ]
}
```

离线版比在线版多查几项，因为顺序比名字可靠：

| 项 | 含义 |
| --- | --- |
| `unknown` | 库里存的 ID 在档案中不存在（过期或写错） |
| `duplicate` | 同一个 bgm 集 ID 被两集共用（多半是 Season 0 特别篇借了正片的 ID） |
| `disorder` | 同一季里 ID 对应的 bgm `sort` 不是 `n, n+1, n+2…` 连续递增（错位/串条） |
| `foreign_subject` | 这一集属于另一个 bgm 条目，且只有它一个（孤儿 ID） |
| `anchor_rows`（终端 `anchors N`） | 报告里是明细行；终端那个 N 是「查不到」（`unknown`）与「没有任何一集在用」（`unused`）的合计 |
| `duplicate_series` | 同一部剧在库里登记了两份（例如 `/hdd` 与 `/strm` 各一套） |

物语系列、凉宫的脏锚点就是 `anchor_rows` 查出来的。

### 7.7 `protect`：防止下次刷新把 ID 覆盖回去

```bash
jbmid protect
```

把 Bangumi 插件的 `TrustExistedBangumiId` 设为 `true`。插件在重新刮削时
会优先信任已存在的 ID，不再按季重算。**改完 ID 之后再执行这一步**。

```text
$ jbmid protect
TrustExistedBangumiId = True
```

## 8. 实战：我在自己的动漫库上遇到的错位

下面每一条都是真实发生过的，场景来自一个 89 部番、2300 多集的动漫库。

### 8.1 整季右移两集

CLANNAD 第二季（After Story）的 20 集 ID 全部指向了下一集（第 1 集挂着第 3 集的 ID）。集名逐集能对上，
所以 `scan` 直接判定 `ok`，报告里这 20 条都是 `change: true`，`apply` 一次写完。

> 特征：相似度正常、集数相等，但 `old` 和 `bgm_id` 整列错开；手工改要 20 次，这里一次结束。

### 8.2 只补了半季

「正相反的你与我」只有前 12 集有 ID，后 13 集是空的。缺 ID 的集在对齐时按空档处理，
`scan` 用集名把后半段对上去，报告里 `old: null`、`bgm_id` 有值，一次补 13 集。

### 8.3 剧集 ID 挂到另一部作品上

「物语系列」的剧集级 `Bangumi` 是 `2098`，对应的是**源氏物語千年紀 Genji**——名字里都有
「物语」，标题守卫也能过，于是整部剧的 ID 全错。工具的处理：季级投票给出正确条目，
`anchor_how: season-vote`，把错 ID 换掉；17 个季再用 `season` map 逐季指定。

> 这就是 `pick_anchor` 顺序的由来：剧集级只有一个字段，错一次就是整部剧。

### 8.4 播出顺序不是集号顺序

凉宫春日 2009 版在本地是按**播出顺序**排的（第 1 集是「竹叶狂想曲」），Bangumi 按集号排。
逐集名字覆盖率只有 22%，整季 13 集被判 `disorder`，进 `review`——**不猜**。

> 这类只靠集名无法恢复顺序，需要你自己排一次，或换用按播出顺序刮削的元数据。

### 8.5 一个本地季对两个条目

命运之夜 UBW：本地 2 季（12 + 13 集），Bangumi 链是 `Fate/Zero`(25) → `UBW`(13) → `UBW S2`(13)，
共 51 集。整池对齐是 25 vs 51，`size mismatch`；季级对齐后：

```text
season map 1:S1->95225 2:S2->109386
```

S1 的 12 集落进第一个条目，S2 落进第二个。同一个形状还在「心理测量者」上出现
（3 季 22/11/8 集，链上夹着 4 个单集剧场版，季级对齐直接跳过剧场版那一段）。

### 8.6 残缺季 + 集名完全对不上

瑞克和莫蒂 7 季，其中一季只有 9 集，集名一个都对不上。工具改用**库里已存的集 ID**
反推：这些 ID 恰好是 Bangumi 那 10 集里少一集的样子，于是把「洞」补在正确位置。

> 三种证据按顺序用：集名相似度 → 已存 ID 的落点 → 集数相等时的顺序映射。

### 8.7 名字里带 `SP` 被误伤

早期版本用 `SP\d*` 识别番外，结果 `Splitting of the Breast` 这种集名里的 `SP` 也被当成分集标记，
一整集被踢出对齐。改成 `SP\d+`（必须带数字）之后，EVA 从 `25/28` 恢复成 `26/26`。

### 8.8 没遇到、但工具也防着的情形

| 你的库可能长这样 | 工具的处理 |
| --- | --- |
| 集名是文件名 `S01E01 - [CASO&DMG] 夏の…` | 变体切分剥掉组名和 `SxxExx` 再比 |
| 集名是 `剧名 - S03E18 - 白夜` | 取分隔符最后一段当标题 |
| 某一季多两集把后面全顶偏 | 按季分段对齐，不跨季位移 |
| 链上夹着单集剧场版 / 未播季 | 季级对齐允许跳过整段，不把池子撑大 |
| 链上把「第二季」误挂进来 | 规模守卫拦下（13 集对 26 集 → `review`） |
| 集名纯日文、纯数字 | 集数相等时走顺序映射，并在报告里标注 |
| 本地顺序与 Bangumi `sort` 不一致 | 该季按集名搜索条目单独对齐（`season rescue`） |
| 正片里混进「…的谈话」这类花絮回 | 按番外剔除，不占正片池 |
| 番外挂在 Season 0 或名字里带 SP/OVA | 正片模式剔除，`special` 模式单独对 `type=1` |
| 同一部剧两份（`/strm` + `/hdd`） | 各自独立扫描，不共享状态；`verify` 会报 `duplicate_series` |

## 9. 安全性

- **只改一个字段**：GET 完整条目 → 只动 `ProviderIds.Bangumi` → POST 回去 → 再 GET 复查，
  并检查 `Name / Overview / PremiereDate / Imdb / Tmdb / Tvdb` 有没有被误伤。
- **写前干跑**：`--dry-run` 会真的读一遍当前 ID，告诉你「会写几集」，不落盘。
- **写前备份**：每次写入都把 `(item_id, 旧值, 新值)` 落到 json，`rollback` 一条命令还原。
- **不合格不写**：集数对不上、集名匹配率不够、锚点标题不符，一律 `review`，一个字都不改。
- 工具不会删除任何条目，也不会改动媒体的文件路径或元数据文本。

## 10. 常见问题

### Q1. `HTTP 401`

Key 不对，或者你给的是别的服务器的 key。`jbmid doctor` 先确认版本能读到。

### Q2. `HTTP 404 ... "Series not found"`

个别 Jellyfin 版本对 `/Shows/{id}/Episodes` 的解析不一致，本工具已改用
`/Items?ParentId=` 取集，不会踩这个坑。

### Q3. 扫描奇慢，每部番卡 20 秒

你的 NAS 有 IPv6 但实际不通，`api.bgm.tv` 的 AAAA 记录还被污染，urllib 每次都等超时。
加 `--ipv4`（或给系统写 `gai.conf` 让 IPv4 优先）。

### Q4. 同一部番在库里出现两次

常见于 `/strm/` 和 `/hdd/` 各挂一份，或者剧名带前缀空格（`新 吊带袜天使`）。`season` 模式的
剧名必须和你库里的名字**完全一致**；`auto` 会按标题模糊找，遇到重名直接报错让你确认。

### Q5. SP / OVA 怎么处理

`scan` 和 `auto` 会把季号 0 和集名含 `OVA|OAD|SP|总集篇|番外|特典|NCOP|NCED` 的集排除出
正片对齐，并计入报告的 `skipped_specials`；番外专用的 `special` 见 7.4，「SP 插在正片第
8.5 集」这种用 `season` 配 `"sp": true`。

### Q6. TMDB 一季 = Bangumi 两个条目

如果两个条目在 Bangumi 上是「续集」关系，`scan` / `auto` 会**自动按季对齐**，不需要你写
map（机制见 12.3）。只有工具自己判不出来（集名全对不上、库里的 ID 也没有）时才用
`season` 模式手工指定。

### Q7. 我的库是英文剧名，还能匹配吗

能，但取决于该条目在 Bangumi 上的集名语言。西文作品（`Rick and Morty`）bgm 上就是英文集名，
逐集相似度可用；日本动画的 `name` 是日文原名、`name_cn` 是中文，英文剧名和两者相似度都是 0。
这时按三种证据依次兜底：**集名**（相似度够高）→ **库里已存的 Bangumi 集 ID** → **集数相等**
（顺序映射），三种都凑不出来才进 `review`。瑞克和莫蒂就靠前两种把 7 季全对上（见 8.6）。

### Q8. `--library` 名字大小写要对吗

不用，按名字精确匹配失败后会忽略大小写、再按唯一子串匹配；实在找不到会列出所有可用库名。

### Q9. 跑完 `scan` 还要做什么

先看 `series review` 那几行：`reason` 写着为什么。确认要写就 `apply`，写完 `verify` 复核，
最后 `protect` 一次。`review` 的条目工具不会碰，可以反复跑。

### Q10. 离线档案会不会过期

会，插件大约两周更新一次。档案里查不到的条目自动回落在线 API（见第 6 章），旧档案最多慢，
不会漏匹配；想强制刷新就跑一次插件里的「离线数据库更新」任务。

### Q11. 支持电影 / 剧场版吗

不支持。工具只处理 TV 链上的集（`type=0`）和 SP（`type=1`），电影不在范围内。

### Q12. 会不会改动我已有的元数据

不会，写入只碰 `ProviderIds.Bangumi` 一个键；回读比对与 `collateral` 判定见第 9 章。

## 11. 数据从哪来

只用三个来源，都不需要额外装东西：

| 来源 | 取什么 | 地址 |
| --- | --- | --- |
| 你的 Jellyfin | 库 / 剧 / 季 / 集，每集的 `Name` 与 `ProviderIds.Bangumi` | 你自己的 `:8096` |
| Bangumi 公开 API | 条目关系、正片集、番外集、集名 | `https://api.bgm.tv/v0`（匿名可读，不要 token） |
| 库里已有的 Bangumi ID | 当锚点，定位「这部剧是哪个条目」 | 从 Jellyfin 读 |

实际用到的接口：

```text
Jellyfin
  GET  /Library/MediaFolders                                      → 库名 → 库 ID
  GET  /Items?IncludeItemTypes=Series&Recursive                   → 全库剧集（带 ProviderIds）
  GET  /Shows/{seriesId}/Seasons                                  → 季
  GET  /Items?ParentId={seasonId}&IncludeItemTypes=Episode&Recursive=true
                                                                  → 每季的集（带 ProviderIds）
  GET  /Items/{itemId}?userId={uid}&Fields=ProviderIds,Path       → 单集完整 DTO
  POST /Items/{itemId}                                            → 回写

Bangumi
  GET  /v0/subjects/{id}/subjects                                 → 续集 / 前传 关系
  GET  /v0/episodes?subject_id={id}&type=0                        → 正片
  GET  /v0/episodes?subject_id={id}&type=1                        → SP / OVA
  POST /v0/search/subjects                                        → 按标题找条目
  GET  /v0/episodes/{id}                                          → 单集详情
```

两点容易误会的地方：

- **不读 TMDB / TVDB 的数据。** 它们只是你刮削的来源，工具看到的是刮削结果落在 Jellyfin
  里的那个集名——所以「TMDB 一季、Bangumi 拆两个条目」是在**集名**层面解决的，与刮削源无关。
- **`sort` 不一定是整数。** Bangumi 的集号可以是 `8.5`、`16.5`（SP 插在正片中间），
  排序按浮点做，不做四舍五入。

## 12. 处理流程

### 12.1 五步流水线

```text
① 找锚点     集级反查 → 季级投票 → 剧集 ID → 标题搜索（顺序见 7.1）
② 拉链       从锚点沿「续集」向后、「前传」向前，去重
③ 建池       链上每个条目取 type=0，丢掉空名，按 sort 排序
④ 对齐       分段 → 变体切分 → 相似度 → 单调最优匹配 → 空档补齐
⑤ 判定       条件见 12.4
⑥ 写回       GET 完整 DTO → 只改一个字段 → POST → 再 GET 回读（见第 9 章）
```

### 12.2 集名对齐长什么样

`scan` / `season` / `auto` / `special` / `anchor` 五种写入模式共用一个核心算法：**按集名对齐，而不是按集号**。

```text
本地集名                      Bangumi 集名
进击的巨人 - S03E18 - 白夜   ⟷  白夜            ✔ 1.00
S01E05 - [Group] 白夜        ⟷  白夜            ✔ 1.00（先剥掉 [组名] 和 SxxExx）
第 14 集                     ⟷  決心            ✘ 0.00 → 交给顺序兜底
```

#### 12.2.1 变体切分

`S01E18 - [Group] 白夜`、`进击的巨人 - S03E18 - 白夜`、`「…」『…』`、`A／B`
都会拆出候选标题，再和 `name_cn` / `name` 逐个比。

#### 12.2.2 单调最优匹配与空档补齐

- *单调*：动态规划求保序的最大总分，不允许第 5 集配到第 3 集。
- *补齐*：两侧剩余空档数量相等时按 1:1 补，处理 `觉悟` ↔ `決心` 这种零相似度但位置确定的翻译差异。

**避免跨季漂移**：本地季数等于链上条目数时，每季只和**自己那个条目**对齐；不等时先做季级
对齐（12.3），失败才整池。整池会让前面某一季少一集就把后面所有季整体位移——最常见的翻车
方式。

### 12.3 季级对齐解掉的形状

给每个本地季和链上每个 subject 算一个**集名指纹相似度矩阵**，再用保序 DP 把「季 → 链上一段
连续 subject」分配下去。允许一个 subject 塞多个本地季、允许链上夹着单集剧场版直接跳过、
允许某一季只是某个 subject 的子集。判据必须是真证据：集名命中率 ≥ 90% 且平均相似度 ≥ 0.55，
或库里已存的 Bangumi 集 ID 全部落在该段且严格递增；任一步对不上就整体放弃，回到整池逻辑。

| 你的库 | Bangumi 链 | 结果 |
| --- | --- | --- |
| 2 季：S1 12 集、S2 13 集 | `Fate/Zero`(25) → `UBW S1`(13) → `UBW S2`(13) | 25 集整池对 51 集会 `size mismatch`；按季对齐后 `1:S1->95225 2:S2->109386` |
| 3 季：22 / 11 / 8 集 | 4 个正片条目 + 中间 4 个单集剧场版 | 剧场版那一段直接跳过，`3:S3->277105` |
| 7 季，其中一季只有 9 集 | 7 个正片条目 + 3 个空条目 | 集名全对不上时用库里已存的集 ID 定位，少的那集补在正确位置 |

报告里的 `notes` 会写明 `season map 1:S1->95225 2:S2->109386`，一眼能看出工具认了哪一段。

还有两种形状不靠「整条链单调」也能救回来：

- **季名在链外**（物语系列把 `花物语` 排在 `终物语` 前面，与 Bangumi 的 `sort` 相反）：整条链
  怎么对齐都会打架。这类季会拿自己的集名去搜条目（`花物语 第变话 …` → 搜「花物语」），并先试
  链上条目里剩下的集（`业物语` 就藏在 `外传季` 被其他季用剩的 3 集里），对齐上就单独写它那一段，
  报告写 `season rescue <查询> -> <subject>`。
- **译名完全对不上**（EVA 的本地集名带英文副标题，Bangumi 只有中文）：只要单调配对覆盖了
  98% 以上本地集、且用掉 ≥ 85% 的池子、池子最多长 3 集，就按顺序认下来，报告写
  `positional match`。差得更多的是凉宫那种播出顺序库，这条不会误触发——它的名字覆盖率只有 22%。

### 12.4 什么情况才会写

两侧集数相等，或（集数规模接近 + 命中率 ≥ 90% + 平均相似度 ≥ 0.55）。
任何一条不满足，该番进 `review`，一条都不会改。

## 13. 通用性：换一个人的库还能用吗

**代码里没有任何「某个人的库」**：零硬编码——没有写死任何 subject id、剧名或集数；唯一的固定
常量是 Bangumi 插件的 GUID `41b59f1b-a6cf-474a-b416-785379cbd856`，只在 `protect` 里用来改
`TrustExistedBangumiId`。没有 Bangumi ID 的库也能跑（走标题搜索）；既没有 ID、标题也搜不到时
报 `no Bangumi anchor`，不乱猜。算法对「别人家的库」的防御见 8.8 的表。

**跨版本、跨环境的兼容**

- 鉴权头双发：`Authorization: MediaBrowser Token="…"` 和 `X-Emby-Token`。
  Jellyfin 10.x 吃前者、部分 12.x 只认后者，实测单发会 401。
- 取集不用 `/Shows/{seasonId}/Episodes`（某些版本返回 404 `Series not found`），
  改用 `/Items?ParentId=`。
- 网络：5xx / 429 / URLError 三次退避重试；单部剧失败只标 `review`，不中断整轮。
  「有 IPv6 但实际不通」每部卡 20 秒的情况见 Q3。运行时依赖见第 3 章（标准库，零依赖）。

**安全与可撤销**：见第 9 章。

## 14. 它不解决什么

1. **集名本身是错的**（整季集名都是从别的番抄来的）——先重刮元数据，工具不会替你猜剧情顺序。
2. **集名没有任何信息**（纯「第 1 集」）且集数与 Bangumi 不等——只能 `review`。
3. **Bangumi 上不存在的条目**——剧场版、特典短片、剧中剧不在 TV 链上，电影也不在处理范围，
   工具不会硬凑。
4. **需要 Bangumi 插件已安装**；`protect` 依赖插件的固定 GUID。
5. 不做刮削、不改集名；`sort` 不是连续整数时的处理见第 11 章。

## 15. 开发

### 15.1 跑测试与 CI

```bash
pip install -e .
python -m unittest discover -s tests -v     # 80 个用例，不联网
```

测试覆盖集名切分、相似度、单调对齐、空档补齐、扫描判定、番外匹配、库名解析、写入与回滚，
以及季级对齐、离线档案索引、锚点取值顺序。

> CI 在每次 push / PR 时自动跑，Python 3.8 / 3.10 / 3.12 三套矩阵，
> 工作流见 `.github/workflows/test.yml`。

### 15.2 目录结构

```text
src/jellyfin_bangumi_ids/
  cli.py           子命令与参数
  jellyfin.py      Jellyfin REST 客户端、单字段写入
  bangumi.py       api.bgm.tv 客户端（关系 / 集 / 搜索）
  offline.py       离线档案后端（与 bangumi.py 同接口）
  archive.py       jsonlines 读取与 SQLite 索引
  scan.py          锚点、拉链、建池、对齐、判定、写入
  season_align.py  季级对齐的保序 DP
  match.py         集名归一化、变体切分、相似度、单调匹配
  season.py        手工 map 模式
  auto.py          标题搜索模式
  anchor.py        锚点诊断与修正
  verify.py        只读体检
  transport.py     重试与 IPv4
tests/             80 个用例，不联网
examples/          真实输出节选：报告 / 备份 / 体检 / 番外 / season map
```

### 15.3 发布新版本

```bash
# 1) 改版本号（pyproject.toml / __init__.py）和 CHANGELOG.md
# 2) 跑测试
python -m unittest discover -s tests
# 3) 提交并打 tag
git commit -am "chore: release v0.1.3"
git tag -a v0.1.3 -m "v0.1.3"
git push origin main --tags
# 4) 在 GitHub 的 Releases 页面用 tag 建一个 release（可附 wheel）
python -m pip wheel . --no-deps -w dist
```

## 16. License

MIT
