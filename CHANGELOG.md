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
- **离线档案提速，默认启用**：`scan` / `special` / `season` / `auto` / `verify` 会先找
  Bangumi 插件的本地档案（`--archive` → `JBMID_ARCHIVE` → Jellyfin `/System/Info` 的 `DataPath`），
  找到就整库走本地；首次运行把 1.4 GB jsonlines 建成 SQLite 索引（约 20 秒，缓存在
  `$JBMID_CACHE` / `~/.cache` / 临时目录），之后集数查询毫秒级。实测 2122 集：verify 40 分钟 →
  18 秒，scan 12 分钟 → 冷启动 2.5 分钟 / 热启动 19 秒。`--no-archive` 可强制走在线 API。
- 离线库没有「续集/前传」关系和标题搜索：这两类请求第一次仍走 API，并写入索引缓存；
  档案里查不到的条目（新番、新条目）自动回落 API，结果与纯在线模式一致（回归对比
  `82 ok / 7 review / 0 to write` 完全相同）。
- 新增 `anchor` 命令：只修一部剧的锚点，`--dry-run` 先看、`--id` 指定、`--clear` 清空。
  取值顺序改为 **集级反查上级条目 > 季级 ID 多数票 > 剧集级 ID > 标题搜索**——每集自己的
  Bangumi ID 只属于一个上级条目，比常被复制的季级元数据可靠；整季元数据没匹配上时靠它兜底。
  实测把凉宫春日的忧郁的 `1372`（小凉宫）纠正为 `1606`，`anchor_unused` 归零。
- `special --clear-borrowed`：番外借用正片集 ID 时清空（判定依据是该 ID 在 Bangumi 的集名与本地
  番外对不上；对得上说明是 Bangumi 记在正片条目下的 OVA，保留）。实测清掉 27 处借用，
  全库 `duplicate` 从 30 降到 3。清空同样写备份，`rollback` 可还原。
- 广播顺序库保护：集数相等、名字相似度低、但库里存的 ID 恰好就是池子本身时（凉宫 2009 播出顺序），
  保留现有顺序不再重排，报告注明 `kept N existing ids`。
- 全库回归：`83 ok / 6 review / 0 to write`（此前 82/7），verify `2095 ids | unknown 0 | dup 3 |
  low-sim 278 | disorder 22 | foreign 5 | anchors 0`。
- 新增 15 个用例（假名、全角、锚点校验、原标题救回、链裁剪正反例、离线档案流式读取、
  五类问题全覆盖、文件名噪声不误报、离线索引与回落、缓存命中、集级反查锚点、广播顺序保护、
  借用 ID 清空），共 44 个。

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
