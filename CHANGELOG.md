# Changelog

版本号从 0.1.0 起，按补丁号递增。

## 关于 `v1.1.0`

第一次对外发布时用的是 `v1.1.0` 这个标签，当时还没定下 `0.1.x` 的编号规则，两者冲突。
为了编号自洽，该标签和它对应的 GitHub Release 都已删除——代码本身还在历史里（`43cdc20`，
也就是下面 `0.1.1` 一节描述的内容），只是不再单独打标签、不再单独发 release。

因此 `0.1.1` 从未正式发布过，公开的版本序列是 `0.1.0` → `0.1.2` → `0.1.3`。从 `0.1.2` 起恢复按补丁号发布。

## 0.1.3（2026-10-19）

- `anchor --seasons`：按每个季的集级 ID 投票，修正**季级** Bangumi ID。Bangumi 插件上报「在看」
  读的是季的 ID（`PlaybackScrobbler` 取父级），集级 ID 全对、季级错位一格时逐集检查完全看不出来：
  播放照常，bgm.tv 却记到相邻那一季。只写票数 ≥60% 且至少 2 集的季，其余只报告；`--all` 走整库。
- `verify` 增加 `season_rows`（季级 ID 与集级多数票不一致的季）与终端计数 `season-ids`。
- `scan` 的 summary 增加 `season_mismatch`，命中时在 `notes` 里写明「季级 ID -> 期望值」。
- 文档重排（只改文档，不动代码）：中文 README 改成 1–16 章的四级标题结构，章首加目录锚点；
  「模式详解」的七个模式各自展开为 7.1–7.7，每个模式都附真实输入与终端输出，并在合适位置给出
  报告 / 备份 / season map 的 JSON 实例；新增第 8 章「实战：我在自己的动漫库上遇到的错位」
  （8 类真实案例）与 12.1–12.4 子节；FAQ 全部编号（Q1–Q12）。英文版同步同一结构。
- `examples/` 收成一组真实输出节选：`scan-report.json`（含 ok / weak match / size mismatch）、
  `backup.json`、`special-report.json`、`verify-report.json`，加上原有的 17 季 season map，
  并新增 `examples/README.md` 索引；两篇 README 在对应小节链接到这些文件。
- 文档去重（只改文档，不动代码）：同一机制原先在「模式详解」「处理流程」「通用性」「安全性」
  和 FAQ 里各讲一遍，现在各留一个正本、其余改为指针——锚点优先级只留在 7.1（7.5、8.3、12.1
  改为引用），写回流程只留在第 9 章（5.2、12.1⑥、Q12、13 改为引用），季级对齐只留在 12.3
  （7.2、Q6 改为引用），番外匹配只留在 7.4（Q5 改为引用），网络与运行时依赖只留在 Q3 与第 3 章；
  第 8 章案例里的引用块、14 章的「电影」重复项、7.1 的重复终端输出一并合并。
  中文 README 865→835 行、英文 946→918 行；标题与目录锚点、FAQ 编号（Q1–Q12）、JSON 示例、
  `examples/` 链接均未改动，锚点已逐条校验可达。另外把 8.1 里的 CLANNAD 季号与英文版对齐
  （真实备份里那 20 条全是第二季），英文版原本就是对的。

## 0.1.2

- **季级对齐（`scan` / `auto`）**：本地季数和链上条目数不再必须相等。给每个本地季和链上每个
  subject 算一张集名指纹相似度矩阵，再用保序 DP 把「季 → 一段连续 subject」分配下去：
  允许一个 subject 里塞多个本地季（UBW 两季对 `Fate/Zero` + `UBW S1` + `UBW S2` 三个条目）、
  允许链上夹着的单集剧场版整段跳过（心理测量者）、允许某一季只是某个 subject 的子集
  （瑞克和莫蒂第 5 季只有 9 集）。
  判据只认真证据——集名命中率 ≥ 90% 且平均相似度 ≥ 0.55，或库里已存的 Bangumi 集 ID 全部落在
  该段且严格递增（瑞克和莫蒂集名全对不上时，靠已存 ID 认出「少的是第 6 集」）。纯按位置猜不算
  证据。任一步对不上就**整体放弃**，回落原来的整池逻辑与原来的 review 文案。
  报告 `notes` 会写 `season map 1:S1->95225 2:S2->109386`。
- `auto` 也会把剧集/季上已存的 Bangumi ID 当成候选（原先只按标题搜），标题是译名、搜不到条目的
  剧不再直接 `review`；`auto` 在整池对齐漏集时（coverage < 100%）也会尝试季级对齐，覆盖到每一集
  的方案优先。
- `match.align_scores()`：把 `align()` 的保序 DP 抽出来，可以直接喂预先算好的相似度矩阵
  （季级对齐要对同一张矩阵复用窗口末端的补洞逻辑）。
- 实测（动漫库 89 部，离线档案）：`scan` 83 ok / 6 review → **86 ok / 3 review**，`to_write 0`，
  仅 3 部变化；清空全库重跑时为 81 ok / 8 review → 84 ok / 5 review。当时多库合计 124 部：
  `scan` 84 ok / 40 review → **87 ok / 37 review**，只有 3 部变化
  （命运之夜 无限剑制 25 集 vs 51 集池、心理测量者 41 vs 48、瑞克和莫蒂 70 vs 91 全部从
  `size mismatch` 转为 ok），**零退化**，`to_write 0`（映射与库里已有 ID 完全一致，不需要改任何东西）。
  `auto` 73 ok / 51 review → **84 ok / 40 review**，其中 4 部由 review 转 ok（钢之炼金术师 FA、
  进击的巨人、瑞克和莫蒂、心理测量者），7 部改用季级对齐后多覆盖 1–2 集，仍然 `would write 0`。
- 锚点校验：库里存的 Bangumi ID 也要反查 subject 标题，与本剧名（`Name` / `OriginalTitle`）
  不符时丢弃并退回标题搜索，报告里写明 `ignored implausible series id`。
- 搜索锚点时同时使用 `Name` 与 `OriginalTitle`（实测 88 部库：81 → 87 部命中）。
- 链窗口裁剪：一条链上包含多部作品时，按「锚点向前扩展」的精确集数匹配截断，
  续作单独成剧的库不再被拉成两倍池子（迷途之子、吊带袜天使、命运石之门等 5 部从
  review 转为 ok）。**只用精确集数，且先试续作方向**，避免把前传给吞进来。
- `match.normalize()` 保留假名并做 NFKC 折叠：纯片假名标题不再归一化成空串，
  全角 `８６` 与半角 `86` 等价。
- 新增 `verify --archive DIR`：直接读 Bangumi 插件的离线库（`*.jsonlines`），
  不占 API 配额，整库 2000 多集约 18 秒（在线版要 40 分钟且会被限流打断）。
  除集名相似度外新增四项基于顺序与归属的检查：`duplicate`（同一 ID 被两集共用）、
  `disorder`（同一季的 bgm `sort` 不连续）、`foreign_subject`（孤儿条目）、
  `anchor_unused`（剧集级 ID 无人使用），以及 `duplicate_series`（同一部剧在库里登记两份）。
  比对前先洗掉 `S01E01 - [组名]` 这类文件名噪声。
- **离线档案提速，默认启用**：`scan` / `special` / `season` / `auto` / `verify` 会先找
  Bangumi 插件的本地档案（`--archive` → `JBMID_ARCHIVE` → Jellyfin `/System/Info` 的 `DataPath`），
  找到就整库走本地；首次运行把 1.5 GB jsonlines 建成 SQLite 索引（约 20 秒，缓存在
  `$JBMID_CACHE` / `~/.cache` / 临时目录），之后集数查询毫秒级。实测 2000 多集：verify 40 分钟 →
  18 秒，scan 12 分钟 → 冷启动 2.5 分钟 / 热启动 19 秒。`--no-archive` 可强制走在线 API。
- 离线库没有「续集/前传」关系和标题搜索：这两类请求第一次仍走 API，并写入索引缓存；
  档案里查不到的条目（新番、新条目）自动回落 API，结果与纯在线模式一致（回归对比
  `82 ok / 7 review / 0 to write` 完全相同）。
- 新增 `anchor` 命令：只修一部剧的锚点，`--dry-run` 先看、`--id` 指定、`--clear` 清空。
  取值顺序改为 **集级反查上级条目 > 季级 ID 多数票 > 剧集级 ID > 标题搜索**——每集自己的
  Bangumi ID 只属于一个上级条目，比常被复制的季级元数据可靠；整季元数据没匹配上时靠它兜底。
  实测把凉宫春日的忧郁的 `1372`（小凉宫）纠正为 `1606`，`anchor_unused` 归零。
  顺序在代码里落实并由 `tests/test_anchor.py` 固定：能过标题校验的剧集 ID 不再压过季级投票。
- `special --clear-borrowed`：番外借用正片集 ID 时清空（判定依据是该 ID 在 Bangumi 的集名与本地
  番外对不上；对得上说明是 Bangumi 记在正片条目下的 OVA，保留）。实测清掉 27 处借用，
  全库 `duplicate` 从 30 降到 3。清空同样写备份，`rollback` 可还原。
- 广播顺序库保护：集数相等、名字相似度低、但库里存的 ID 恰好就是池子本身时（凉宫 2009 播出顺序），
  保留现有顺序不再重排，报告注明 `kept N existing ids`。
- 全库回归：`83 ok / 6 review / 0 to write`（此前 82/7），verify `2095 ids | unknown 0 | dup 3 |
  low-sim 278 | disorder 22 | foreign 5 | anchors 0`。
- **链外季救援（`season rescue`）**：本地顺序与 Bangumi `sort` 相反时（物语系列把 `花物语`
  排在 `终物语` 前），整条链的任何单调对齐都会互相打架。这类季改为拿自己的集名搜条目，
  并先试链上条目里被其他季用剩的集，命中后单独对齐那一段。实测把物语系列的 `花物语`(5)、
  `历物语`(12)、`业物语`(3) 全部认出，覆盖率 82% → 100%。
- **顺序认定（`positional match`）**：本地集名带英文副标题、与 Bangumi 中文译名几乎不重合时
  （新世纪福音战士），只要单调配对覆盖 ≥ 98% 本地集、用掉 ≥ 85% 的池子、池子最多长 3 集，
  就按顺序采纳并在报告里写明。广播顺序库（凉宫，覆盖率 22%）不会误触发。
- 正片里混进的「…的谈话」花絮回按番外剔除（人形电脑天使心 26 集里那 2 集），
  本地集数因此与 Bangumi 一致，65% → 100% 覆盖。
- 全库回归（动漫库 89 部、离线档案）：`scan` 86 ok / 3 review → **89 ok / 0 review / 0 to write**，
  三部 review 全部转 ok 且库里 ID 一处未改；`verify` 维持 `2095 ids | dup 3 | low-sim 278 |
  disorder 22 | foreign 5 | anchors 0`；`auto --dry-run` 仍 `would write 0`。
- `SP` 番外标记要求至少一位数字（`SP1`/`SP02`）：原先的 `SP\d*` 允许零位，
  把 EVA 第 16 话 `致死之疾，然后…（Splitting of the Breast）` 的 `（Sp` 当成了 SP 标记，
  整集被剔出正片池。全库确认只有这一处误伤，修正后 EVA 26 集全覆盖，`positional match` 不再触发。
- 新增用例覆盖花絮谈话、顺序认定、链外季救援、SP 标记需带数字、锚点取值顺序，共 71 个。

## 0.1.1

- 新增 `special` 子命令：把番外 / SP / OVA / 总集篇 也对上 Bangumi 的 `type=1` 集
  （输出与 `scan` 同构，复用 `apply` / `rollback`）。
- README 按「症状 → 安装使用 → 实现原理」重排，并新增英文版 `README.en.md`。
- `--library` 解析改为精确 → 忽略大小写 → 唯一子串，失败时列出可用库名。
- `special` 模式的 `reason` 文案统一为英文。
- 启用 GitHub Actions：push / PR 跑 3.8 / 3.10 / 3.12 矩阵。

## 0.1.0

首个公开版本。

- `scan` / `apply`：以已有的 Bangumi ID 为锚点，顺「续集」关系拉整条 TV 链，
  用集名做保序最优对齐，集数或匹配率不达标就进 `review` 不写入。
- `season`：手工把「本地第 N 季」映射到若干 Bangumi subject，支持正则过滤和
  `sp: true` 纳入 SP。
- `auto`：按剧名搜索并通过标题守卫，主干仍是集名对齐，集数相等且剧名带季标记时
  退化为顺序映射并标注低置信。
- `verify`：只读体检，逐个反查 `api.bgm.tv` 比对集名。
- `rollback`：按备份文件逐条还原旧值。
- `protect`：把插件的 `TrustExistedBangumiId` 置为 true，避免重新刮削覆盖手改 ID。
