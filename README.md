# jellyfin-bangumi-ids

**批量修好 Jellyfin 里 Bangumi 插件的剧集 ID。**

![tests](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml/badge.svg)

> 中文 | [English](README.en.md)

零依赖的命令行工具，修的是 Jellyfin 剧集的 `ProviderIds.Bangumi`。这个 ID 错了，Bangumi 插件要么
根本不上报（日志里 `doesn't have bangumi id`），要么把进度报给另一部番。工具扫描媒体库、
**按集名**（不是按集号）对齐、逐集写回，并留下可一键回滚的备份。

---

## 症状：你可能正需要它

- 播完一集，Bangumi 上完全没动静，日志里反复出现
  `item "..." (#...) doesn't have bangumi id, ignored`。
- 进度同步了，但同步到了**别的番**——比如整季的 ID 都指向另一部作品。
- 一部番在 TMDB 是一季，在 Bangumi 被拆成「上半／下半」两个条目，第 12 集之后全错位。
- 特别篇（SP / OVA / 第 0 话）被当成正片，导致后面每一集都偏移一位。
- 手动改了一集 ID，下次刷新元数据又被插件覆盖回去。

## 它能做什么

Jellyfin 的每一集都有一个 `ProviderIds.Bangumi`，Bangumi 插件上报进度时只认这个数字。
本工具负责把这个数字填对，**并且只填这一个字段**。

六个模式，按你库的混乱程度选（下面「模式详解」有完整说明）：

| 模式 | 何时用 | 命令 |
| --- | --- | --- |
| `scan` | 大部分番是干净的，只有零星几部不对 | `jbmid scan` → `jbmid apply` |
| `season` | Bangumi 的季划分和你的文件夹完全对不上，需要你指定 | `jbmid season --map map.json` |
| `auto` | 想一把梭，让工具自己按标题找条目、按集名对齐 | `jbmid auto` |
| `special` | 番外 / SP / OVA / 总集篇 也想同步 | `jbmid special` → `jbmid apply` |
| `verify` | 修完（或修前）想看看哪些 ID 是坏的，**只读不写** | `jbmid verify` |
| `anchor` | 某一部剧的锚点（series/season 上的 Bangumi ID）本身就是错的 | `jbmid anchor --series "剧名"` |

## 安装

只依赖 Python 标准库，Python ≥ 3.8。

```bash
pip install git+https://github.com/QingYunYo/jellyfin-bangumi-ids.git
# 或者本地开发
git clone https://github.com/QingYunYo/jellyfin-bangumi-ids.git
cd jellyfin-bangumi-ids && pip install -e .
```

装完就有 `jbmid` 命令（也可以 `python -m jellyfin_bangumi_ids`）。

## 准备 API Key

Jellyfin 控制台 → 管理 → API 密钥 → 新建，给它一个名字（比如 `jbmid`）。
然后：

```bash
export JF_URL=http://127.0.0.1:8096
export JF_API_KEY=你的key
jbmid doctor
```

`doctor` 会告诉你 Jellyfin 版本、库列表、bgm.tv 是否连通、插件配置状态。
四项全绿再往下走。

## 快速开始

```bash
# 1) 扫一遍「动漫」库，生成报告（不写任何东西）
jbmid scan --library 动漫 --out report.json

# 2) 看看报告里哪些是 ok、哪些要人工看
#    series ok / series review / episodes to write 三个数字就是结论

# 3) 先干跑，确认要写多少集
jbmid apply report.json --dry-run

# 4) 真写（自动备份旧值到 jbmid-backup.json）
jbmid apply report.json --backup jbmid-backup.json

# 5) 出问题就一键回滚
jbmid rollback jbmid-backup.json
```

> `scan` 会先用**已有的** Bangumi ID 当锚点，顺「续集」关系把整条 TV 链拉出来，
> 再用链上所有正片的集名和你的库对齐。所以它天然能处理「一部番被拆成多个条目」
> 的情况——只要整条链的总集数和你的库对得上。

## 用离线库提速（推荐）

Bangumi 插件自带一份离线数据库：在 Jellyfin 里跑一次「离线数据库更新」任务，它会把
subject / episode / 人物档案下到 `{Jellyfin 数据目录}/bangumi/archive/`（Docker 里通常是
`/config/data/bangumi/archive`，约 1.4 GB，两周左右更新一次）。

本工具**默认就会用这份档案**，不需要额外配置：

```bash
jbmid scan --library 动漫            # 自动探测档案，找到就用
jbmid verify --library 动漫          # 同样自动走离线版
jbmid scan --library 动漫 --archive /path/to/archive   # 档案不在默认位置时手动指定
jbmid scan --library 动漫 --no-archive                 # 强制只用在线 API
```

探测顺序：`--archive` → 环境变量 `JBMID_ARCHIVE` → Jellyfin `/System/Info` 里的 `DataPath`。

**第一次会建索引**：1.4 GB 的 jsonlines 过大，不适合每次现读，所以首次运行会在缓存目录
（`$JBMID_CACHE` → `~/.cache/jellyfin-bangumi-ids` → 系统临时目录）生成约 100 MB 的 SQLite
索引，耗时 20 秒左右；之后每次查询在毫秒级。档案更新（文件大小或修改时间变化）后索引自动重建。

**实测收益**（动漫库，2122 集）：

| 操作 | 在线 API | 离线档案（冷） | 离线档案（热） |
| --- | --- | --- | --- |
| `verify` | 40 分钟（还会被限流打断） | 18 秒 | 18 秒 |
| `scan` | 约 12 分钟 | 2 分半 | 19 秒 |

离线库里没有「续集/前传」关系和标题搜索，这两项第一次仍会调用 API，并缓存进索引——
所以冷启动要拉一遍关系图，第二次开始才是纯离线。档案比线上旧，里面查不到的条目
（新番、刚建的新条目）会自动回落到 API，不会漏掉。

## 模式详解

### 1. `scan`：自动找锚点

```bash
jbmid scan --library 动漫 --out report.json
jbmid scan --library 动漫 --limit 5          # 先试 5 部
jbmid scan --library 动漫 --no-search        # 只信已有 ID，不按标题搜索
```

锚点优先级：**剧集自己的 Bangumi ID → 某一季的 Bangumi ID → 按标题搜索**。

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

### 2. `season`：你自己说哪几个 subject 拼成一季

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

真实例子见 [`examples/monogatari-season-map.json`](examples/monogatari-season-map.json)。

### 3. `auto`：最省事，也最需要看结果

```bash
jbmid auto --library 动漫 --dry-run
jbmid auto --library 动漫 --backup jbmid-backup-auto.json
```

按剧名搜 Bangumi，取候选里标题能对上的，拉整条链，按集名对齐。
命中率 ≥ 80% 直接写；否则若**集数完全相等且剧名带「第 N 季 / Season N」**，
退化成顺序映射并标记 `order-low-confidence`——这条路能吃下「集名是纯日文/纯英文
文件名」的库（比如 `S01E01 - [CASO&DMG] ...`）。

### 4. `special`：连番外一起修

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

加 `--clear-borrowed` 还会处理另一种脏数据：番外「借用」了正片某一集 ID（Jellyfin 插件偶尔这么干，
结果番外显示的是正片标题）。判定标准是**拿这个 ID 去 Bangumi 查，集名和本地番外对不上**——
对得上说明它本来就是被 Bangumi 记成正片的 OVA，保留；对不上就清空，宁可空着也不挂错的。
清空同样进备份，`rollback` 能一字不差地还原。

```bash
jbmid special --library 动漫 --clear-borrowed --out specials.json
```

### 5. `anchor`：只修一部剧的锚点

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

选 `--id` 的优先级不是拍脑袋：**每集自己的 Bangumi ID 只属于一个上级条目**，所以拿一季里头两集
反查出来的条目，比季级元数据（经常是复制来的）可靠。整季元数据没匹配上时，这一条就是兜底。

### 6. `verify`：只读体检

```bash
jbmid verify --library 动漫 --out check.json
```

把每个有 Bangumi ID 的集拿去反查 `api.bgm.tv`，比对集名。
相似度低于阈值的全列出来——注意这**不等于错了**：文件名式集名、
纯翻译差异、英文名条目都会误报，需要人眼扫一遍。

**用离线库跑（推荐）**：Bangumi 插件自带一份离线档案（`{配置目录}/data/bangumi/archive/`），
读它不占 API 配额，整个库 2000 多集十几秒跑完：

```bash
jbmid verify --library 动漫 --archive /path/to/bangumi/archive --out check.json
```

离线版比在线版多查几项，因为顺序比名字可靠：

- `unknown_id`：库里存的 ID 在档案中不存在（过期或写错）
- `duplicate`：同一个 bgm 集 ID 被两集共用（多半是 Season 0 特别篇借了正片的 ID）
- `disorder`：同一季里 ID 对应的 bgm `sort` 不是 `n, n+1, n+2…` 连续递增（错位/串条）
- `foreign_subject`：这一集属于另一个 bgm 条目，且只有它一个（孤儿 ID）
- `anchor_unused`：剧集级 Bangumi ID 没有任何一集在用——物语系列、凉宫的脏锚点就是这么查出来的
- `duplicate_series`：同一部剧在库里登记了两份（例如 `/hdd` 与 `/strm` 各一套）

### 7. `protect`：防止下次刷新把 ID 覆盖回去

```bash
jbmid protect
```

把 Bangumi 插件的 `TrustExistedBangumiId` 设为 `true`。插件在重新刮削时
会优先信任已存在的 ID，不再按季重算。**改完 ID 之后再执行这一步**。

## 安全性

- **只改一个字段**：GET 完整条目 → 只动 `ProviderIds.Bangumi` → POST 回去 → 再 GET 复查，
  并检查 `Name / Overview / PremiereDate / Imdb / Tmdb / Tvdb` 有没有被误伤。
- **写前干跑**：`--dry-run` 会真的读一遍当前 ID，告诉你「会写几集」，不落盘。
- **写前备份**：每次写入都把 `(item_id, 旧值, 新值)` 落到 json，`rollback` 一条命令还原。
- **不合格不写**：集数对不上、集名匹配率不够、锚点标题不符，一律 `review`，一个字都不改。
- 工具不会删除任何条目，也不会改动媒体的文件路径或元数据文本。

## 常见问题

**`HTTP 401`**
Key 不对，或者你给的是别的服务器的 key。`jbmid doctor` 先确认版本能读到。

**`HTTP 404 ... "Series not found"`**
个别 Jellyfin 版本对 `/Shows/{id}/Episodes` 的解析不一致，本工具已改用
`/Items?ParentId=` 取集，不会踩这个坑。

**扫描奇慢，每部番卡 20 秒**
你的 NAS 有 IPv6 但实际不通，`api.bgm.tv` 的 AAAA 记录还被污染，urllib 每次都等超时。
加 `--ipv4`（或给系统写 `gai.conf` 让 IPv4 优先）。

**同一部番在库里出现两次**
常见于 `/strm/` 和 `/hdd/` 各挂一份，或者剧名带前缀空格（`新 吊带袜天使`）。
`season` 模式的剧名必须和你库里的名字**完全一致**；`auto` 模式会按标题模糊找，
遇到重名会直接报错让你确认。

**SP / OVA 怎么处理**
`scan` 和 `auto` 会把季号 0 和集名含 `OVA|OAD|SP|总集篇|番外|特典|NCOP|NCED`
的集排除出对齐，并计入报告的 `skipped_specials`。若是「SP 插在正片第 8.5 集」
这种，用 `season` 模式配 `"sp": true`。

**TMDB 一季 = Bangumi 两个条目**
如果两个条目在 Bangumi 上是「续集」关系，`scan` / `auto` 会**自动按季对齐**：先给每个本地季
在链上找它对应的那一段 subject，再逐季比集名（见「处理流程 ④」），不需要你写 map。
只有工具自己判不出来（集名全对不上、库里的 ID 也没有）时才需要 `season` 模式手工指定。

**我的库是英文剧名，还能匹配吗**
能，但取决于该条目在 Bangumi 上的集名语言。西文作品（`Rick and Morty`）bgm 上就是英文集名，
逐集相似度可用；日本动画的 `name` 是日文原名、`name_cn` 是中文，英文剧名和两者相似度都是 0。
这时工具依赖三种证据：**集名**（相似度够高）→ **库里已存的 Bangumi 集 ID**（每集 ID 落在哪个
subject 的池子里）→ **集数相等**（顺序映射）。瑞克和莫蒂就是靠前两种证据把 7 季全对上的：
第 5 季只有 9 集、集名一个都对不上，但库里已有的 ID 恰好是 Bangumi 那 10 集里少一集的样子，
工具据此把「洞」补在了正确位置。三种证据都凑不出来才会进 `review`。

**`--library` 名字大小写要对吗**
不用，按名字精确匹配失败后会忽略大小写、再按唯一子串匹配；实在找不到会列出所有可用库名。

## 数据从哪来

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
  里的那个集名。所以「TMDB 一季、Bangumi 拆两个条目」这种错位，是在**集名**层面解决的，
  不需要知道你用的是哪个刮削源。
- **`sort` 不一定是整数。** Bangumi 的集号可以是 `8.5`、`16.5`（SP 插在正片中间），
  排序按浮点做，不做四舍五入。

## 处理流程

```text
① 找锚点     剧的 ID → 某一季的 ID → 按剧名搜索
② 拉链       从锚点沿「续集」向后、「前传」向前，去重
③ 建池       链上每个条目取 type=0，丢掉空名，按 sort 排序
④ 对齐       分段 → 变体切分 → 相似度 → 单调最优匹配 → 空档补齐
⑤ 判定       集数相等，或（规模相近 + 命中率 ≥ 90% + 平均相似度 ≥ 0.55）
⑥ 写回       GET 完整 DTO → 只改一个字段 → POST → 再 GET 回读比对
```

**① 锚点**是最便宜也最可靠的信号；一个都没有时才按标题搜索，且搜索结果必须过标题守卫
（归一化后互相包含），否则直接 `review`，不赌。

**④ 对齐**里几个细节：

- *分段*：本地季数 == 链上条目数时，每季只和自己那个条目对齐，避免跨季位移。
- *季级对齐*（季数和条目数不相等时）：给每个本地季和链上每个 subject 算一个**集名指纹
  相似度矩阵**，再用保序 DP 把「季 → 链上一段连续 subject」分配下去。允许一个 subject 里塞
  多个本地季、允许链上夹着单集剧场版直接被跳过、允许某一季只是某个 subject 的子集。
  判据必须是真证据，纯按位置猜不算：集名命中率 ≥ 90% 且平均相似度 ≥ 0.55，或库里已存的
  Bangumi 集 ID 全部落在该段且严格递增。中途任一步对不上就整体放弃，回到整池逻辑。
- *变体切分*：`S01E18 - [Group] 白夜`、`进击的巨人 - S03E18 - 白夜`、`「…」『…』`、
  `A／B` 都会拆出候选标题，再和 `name_cn` / `name` 逐个比。
- *单调*：动态规划求保序的最大总分，不允许第 5 集配到第 3 集。
- *补齐*：两侧剩余空档数量相等时按 1:1 补，处理 `觉悟` ↔ `決心` 这种零相似度但位置确定的翻译差异。

**⑥ 写回**只动 `ProviderIds.Bangumi` 一个键，写完回读，并检查
`Name / Overview / PremiereDate / Imdb / Tmdb / Tvdb` 有没有被误伤（`collateral`）。

### 对齐长什么样

`scan` / `season` / `auto` / `special` 四种写入模式共用一个核心算法：**按集名对齐，而不是按集号**。

```
本地集名             Bangumi 集名
进击的巨人 - S03E18 - 白夜   ⟷  白夜            ✔ 1.00
S01E05 - [Group] 白夜        ⟷  白夜            ✔ 1.00（先剥掉 [组名] 和 SxxExx）
第 14 集                     ⟷  決心            ✘ 0.00 → 交给顺序兜底
```

对齐是**单调最优匹配**（保序），再用「两侧空档等长就 1:1 补齐」处理翻译差异
（比如 `觉悟` vs `決心`）。

**避免跨季漂移**：当本地季数正好等于 Bangumi 链上的条目数时，每季只和**自己那个条目**
对齐。数目不相等时先做一次季级对齐（见上），成功就按季各对各的条目；失败才把整条链当成
一个池子。整池对齐会让前面某一季少一集把后面所有季整体位移——这是这类工具最常见的翻车方式。

季级对齐解掉的典型形状：

| 你的库 | Bangumi 链 | 结果 |
| --- | --- | --- |
| 2 季：`[UBW]` S1 12 集、S2 13 集 | `Fate/Zero`(25) → `UBW S1`(13) → `UBW S2`(13) | 25 集整池对 51 集会 `size mismatch`；按季对齐后 `S1→95225 S2→109386` |
| 3 季：22 / 11 / 8 集 | 4 个正片条目 + 中间 4 个单集剧场版 | 剧场版那一段直接跳过，`S3→277105` |
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

**什么时候才会写**：两侧集数相等，或（集数规模接近 + 命中率 ≥ 90% + 平均相似度 ≥ 0.55）。
任何一条不满足，该番进 `review`，一条都不会改。

## 通用性：换一个人的库还能用吗

**代码里没有任何「某个人的库」**

- 零硬编码：没有写死任何 subject id、剧名或集数。唯一的固定常量是 Bangumi 插件的 GUID
  `41b59f1b-a6cf-474a-b416-785379cbd856`，那是插件作者定的，只在 `protect` 里用来改
  `TrustExistedBangumiId`。
- 没有 Bangumi ID 的库也能跑（走标题搜索）；既没有 ID、标题也搜不到时，明确报
  `no Bangumi anchor`，不会乱猜。

**算法对「别人家的库」的防御**

| 你的库可能长这样 | 工具的处理 |
| --- | --- |
| 集名是文件名 `S01E01 - [CASO&DMG] 夏の…` | 变体切分剥掉组名和 `SxxExx` 再比 |
| 集名是 `剧名 - S03E18 - 白夜` | 取分隔符最后一段当标题 |
| TMDB 一季 / Bangumi 拆上下部 | 拉续集链，再按集名指纹做季级对齐；仍对不上就 `review` |
| 某一季多两集把后面全顶偏 | 按季分段对齐，不跨季位移 |
| 链上夹着单集剧场版 / 未播季 | 季级对齐允许跳过整段，不把池子撑大 |
| 链上把「第二季」误挂进来 | 规模守卫拦下（13 集对 26 集 → `review`） |
| 集名纯日文、纯数字 | 集数相等时走顺序映射，并在报告里标注 |
| 本地顺序与 Bangumi `sort` 不一致 | 该季按集名搜索条目单独对齐（`season rescue`） |
| 本地集名带英文副标题、译名不同 | 覆盖 98% 本地 + 85% 池子时按顺序认定（`positional match`） |
| 正片里混进「…的谈话」这类花絮回 | 按番外剔除，不占正片池 |
| 番外挂在 Season 0 或名字里带 SP/OVA | 正片模式剔除，`special` 模式单独对 `type=1` |
| 同一部剧两份（`/strm` + `/hdd`） | 各自独立扫描，不共享状态 |

**跨版本、跨环境的兼容**

- 鉴权头双发：`Authorization: MediaBrowser Token="…"` 和 `X-Emby-Token`。
  Jellyfin 10.x 吃前者、部分 12.x 只认后者，实测单发会 401。
- 取集不用 `/Shows/{seasonId}/Episodes`（某些版本返回 404 `Series not found`），
  改用 `/Items?ParentId=`。
- 网络：5xx / 429 / URLError 三次退避重试；单部剧失败只标 `review`，不中断整轮；
  `--ipv4` 专治「有 IPv6 但实际不通、AAAA 还被污染」导致每部卡 20 秒的情况。
- Python ≥ 3.8，零第三方依赖，`pip install` 完就有 `jbmid`。

**安全与可撤销**

- 只改一个字段，写后回读校验。
- `--dry-run` 真读真算，不落盘。
- 每次写入落 `(item_id, 旧值, 新值)`，`rollback` 一条命令还原。
- 所有模糊判断最终都收敛到 `review`，而不是猜一个看起来成功的结果。

## 它不解决什么

1. **集名本身是错的**（整季集名都是从别的番抄来的）——先重刮元数据，工具不会替你猜剧情顺序。
2. **集名没有任何信息**（纯「第 1 集」）且集数与 Bangumi 不等——只能 `review`。
3. **Bangumi 上不存在的条目**——剧场版、特典短片、剧中剧不在 TV 链上，工具不会硬凑。
4. **电影**不在处理范围。
5. **需要 Bangumi 插件已安装**；`protect` 依赖插件的固定 GUID。
6. 不做刮削、不改集名；Bangumi 的 `sort` 不是连续整数（如 8.5）时按浮点排序，不做四舍五入。

## 开发

```bash
pip install -e .
python -m unittest discover -s tests -v     # 21 个用例，不联网
```

测试覆盖集名切分、相似度、单调对齐、空档补齐、扫描判定、番外匹配、库名解析、写入与回滚。

> CI 在每次 push / PR 时自动跑，Python 3.8 / 3.10 / 3.12 三套矩阵，
> 工作流见 `.github/workflows/test.yml`。

### 发布新版本

```bash
# 1) 改版本号（pyproject.toml / __init__.py）和 CHANGELOG.md
# 2) 跑测试
python -m unittest discover -s tests
# 3) 提交并打 tag
git commit -am "chore: release v0.1.2"
git tag -a v0.1.2 -m "v0.1.2"
git push origin main --tags
# 4) 在 GitHub 的 Releases 页面用 tag 建一个 release（可附 wheel）
python -m pip wheel . --no-deps -w dist
```

## License

MIT
