# Changelog

版本号从 0.1.0 起，按补丁号递增。

## 0.1.2

- 锚点校验：库里存的 Bangumi ID 也要反查 subject 标题，与本剧名（`Name` / `OriginalTitle`）
  不符时丢弃并退回标题搜索，报告里写明 `ignored implausible series id`。
- 搜索锚点时同时使用 `Name` 与 `OriginalTitle`（实测 88 部库：81 → 87 部命中）。
- 链窗口裁剪：一条链上包含多部作品时，按「锚点向前扩展」的精确集数匹配截断，
  续作单独成剧的库不再被拉成两倍池子（迷途之子、吊带袜天使、命运石之门等 5 部从
  review 转为 ok）。**只用精确集数，且先试续作方向**，避免把前传给吞进来。
- `match.normalize()` 保留假名并做 NFKC 折叠：纯片假名标题不再归一化成空串，
  全角 `８６` 与半角 `86` 等价。
- 新增 `verify --archive DIR`：直接读 Bangumi 插件的离线库（`*.jsonlines`），
  不占 API 配额，整库 2000 集约 15 秒（在线版要 40 分钟且会被限流打断）。
  除集名相似度外新增四项基于顺序与归属的检查：`duplicate`（同一 ID 被两集共用）、
  `disorder`（同一季的 bgm `sort` 不连续）、`foreign_subject`（孤儿条目）、
  `anchor_unused`（剧集级 ID 无人使用），以及 `duplicate_series`（同一部剧在库里登记两份）。
  比对前先洗掉 `S01E01 - [组名]` 这类文件名噪声。
- 新增 8 个用例（假名、全角、锚点校验、原标题救回、链裁剪正反例、离线档案流式读取、
  五类问题全覆盖、文件名噪声不误报），共 34 个。

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
