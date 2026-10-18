# jellyfin-bangumi-ids

**批量修好 Jellyfin 里 Bangumi 插件的剧集 ID。**

> English: a zero-dependency CLI that repairs the `ProviderIds.Bangumi` of your
> Jellyfin episodes. When those ids are wrong, the Bangumi plugin either refuses
> to report ("doesn't have bangumi id") or reports your progress to the wrong
> subject. This tool scans your library, aligns episodes by **episode titles**
> (not by episode numbers), writes the ids back one by one, and keeps a backup
> you can roll back with a single command.

---

## 症状：你可能正需要它

- 播完一集，Bangumi 上完全没动静，日志里反复出现
  `item "..." (#...) doesn't have bangumi id, ignored`。
- 进度同步了，但同步到了**别的番**——比如整季的 ID 都指向另一部作品。
- 一部番在 TMDB 是一季，在 Bangumi 被拆成「上半／下半」两个条目，第 12 集之后全错位。
- 特别篇（SP / OVA / 第 0 话）被当成正片，导致后面每一集都偏移一位。
- 手动改了一集 ID，下次刷新元数据又被插件覆盖回去。

## 它怎么干活

Jellyfin 的每一集都有一个 `ProviderIds.Bangumi`，Bangumi 插件上报进度时只认这个数字。
本工具负责把这个数字填对，**并且只填这一个字段**。

四种模式，按你库的混乱程度选：

| 模式 | 何时用 | 命令 |
| --- | --- | --- |
| `scan` | 大部分番是干净的，只有零星几部不对 | `jbmid scan` → `jbmid apply` |
| `season` | Bangumi 的季划分和你的文件夹完全对不上，需要你指定 | `jbmid season --map map.json` |
| `auto` | 想一把梭，让工具自己按标题找条目、按集名对齐 | `jbmid auto` |
| `special` | 番外 / SP / OVA / 总集篇 也想同步 | `jbmid special` → `jbmid apply` |
| `verify` | 修完（或修前）想看看哪些 ID 是坏的，**只读不写** | `jbmid verify` |

`scan` / `season` / `auto` 三种写入模式共用一个核心算法：**按集名对齐，而不是按集号**。

```
本地集名             Bangumi 集名
进击的巨人 - S03E18 - 白夜   ⟷  白夜            ✔ 1.00
S01E05 - [Group] 白夜        ⟷  白夜            ✔ 1.00（先剥掉 [组名] 和 SxxExx）
第 14 集                     ⟷  決心            ✘ 0.00 → 交给顺序兜底
```

对齐是**单调最优匹配**（保序），再用「两侧空档等长就 1:1 补齐」处理翻译差异
（比如 `觉悟` vs `決心`）。

**避免跨季漂移**：当本地季数正好等于 Bangumi 链上的条目数时，每季只和**自己那个条目**
对齐；否则（比如一部番被拆成 6 个条目、你库里有 3 季）才把整条链当成一个池子。
整池对齐会让前面某一季少一集把后面所有季整体位移——这是这类工具最常见的翻车方式。

**什么时候才会写**：两侧集数相等，或（集数规模接近 + 命中率 ≥ 90% + 平均相似度 ≥ 0.55）。
任何一条不满足，该番进 `review`，一条都不会改。

## 安装

只依赖 Python 标准库，Python ≥ 3.8。

```bash
pip install git+https://github.com/<you>/jellyfin-bangumi-ids.git
# 或者本地开发
git clone https://github.com/<you>/jellyfin-bangumi-ids.git
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

## 模式详解

### 1. `scan`：自动找锚点

```bash
jbmid scan --library 动漫 --out report.json
jbmid scan --library 动漫 --limit 5          # 先试 5 部
jbmid scan --library 动漫 --no-search        # 只信已有 ID，不按标题搜索
```

锚点优先级：**剧集自己的 Bangumi ID → 某一季的 Bangumi ID → 按标题搜索**。
搜索来的锚点必须通过标题守卫（`无职转生` 能匹配
`无职转生～到了异世界就拿出真本事～`，`Andor` 匹配不上`安德烈和威利的冒险`），
否则直接 `review`，不赌。

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

### 5. `verify`：只读体检

```bash
jbmid verify --library 动漫 --out check.json
```

把每个有 Bangumi ID 的集拿去反查 `api.bgm.tv`，比对集名。
相似度低于阈值的全列出来——注意这**不等于错了**：文件名式集名、
纯翻译差异、英文名条目都会误报，需要人眼扫一遍。

### 6. `protect`：防止下次刷新把 ID 覆盖回去

```bash
jbmid protect
```

把 Bangumi 插件的 `TrustExistedBangumiId` 设为 `true`。插件在重新刮削时
会优先信任已存在的 ID，不再按季重算。**改完 ID 之后再执行这一步**。

## 安全性

- **只改一个字段**：GET 完整条目 → 只动 `ProviderIds.Bangumi` → POST 回去 →
  再 GET 复查，并检查 `Name / Overview / PremiereDate` 等字段有没有被误伤。
- **写前干跑**：`--dry-run` 会真的读一遍当前 ID，告诉你「会写几集」，不落盘。
- **写前备份**：每次写入都把 `(item_id, 旧值, 新值)` 落到 json，`rollback` 一条命令还原。
- **不合格不写**：集数对不上、集名匹配率不够、锚点标题不符，一律 `review`，
  一个字都不改。
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
正是 `season` 模式的用武之地：第 1 季指向第一个 subject，第 2 季指向第二个。
如果两个条目在 Bangumi 上是「续集」关系，`scan` 模式也能自动拼起来。

## 已知限制

- 只处理**剧集（Episode）**，电影不支持。
- 不做刮削、不改集名。集名本身就是错的（比如整季集名都是另一部番的），
  先修好元数据再来跑本工具。
- Bangumi 的 `sort` 不是连续整数（如 8.5）时，池子按 `sort` 排序，不做四舍五入。
- 需要 Bangumi 插件已安装；`protect` 子命令依赖插件的固定 GUID。

## 开发

```bash
pip install -e .
python -m unittest discover -s tests -v     # 13 个用例，不联网
```

测试覆盖集名切分、相似度、单调对齐、空档补齐、扫描判定、写入与回滚。

## License

MIT
