# 示例文件

这里放的都是**真实运行输出**的节选，可以直接对照字段，也可以改一改当输入用。
文件为了放进仓库做过裁剪（集数、条目数），完整版由命令自己生成，字段与格式完全一致。

| 文件 | 是什么 | 由谁生成 | 在 README 里的位置 |
| --- | --- | --- | --- |
| [`scan-report.json`](scan-report.json) | 扫描报告：`ok` 条目，含一条 `season_issues`（季级 ID 缺失，集级投票 12:11 分属两条目） | `jbmid scan --out` | [3. 快速开始](../README.md#3-快速开始) · [4.1 `scan`](../README.md#41-scan先看清全局再动手) |
| [`scan-review.json`](scan-review.json) | 扫描报告：两条 `review`，`no Bangumi anchor` 与 `size mismatch 4 local vs 12 pool` | `jbmid scan --out` | [4.1 `scan`](../README.md#41-scan先看清全局再动手) |
| [`backup.json`](backup.json) | 写入备份：两条整列右移（`647→645`）、一条原本为空（`null→…`） | `jbmid apply --backup` | [4.2 `apply`](../README.md#42-apply--rollback报告落库与撤销) |
| [`season-backup.json`](season-backup.json) | 季级备份：`kind: season`，`anchor --seasons` 清空横跨季时写出 | `jbmid anchor --seasons --all` | [5. 季级 ID](../README.md#5-季级-id为什么必须一起修) |
| [`monogatari-season-map.json`](monogatari-season-map.json) | 17 季手工映射，可直接改用 | 手写 | [4.3 `season`](../README.md#43-season季划分对不上时) |
| [`special-report.json`](special-report.json) | 番外报告：`match` 逐集给出 `old` / `bgm_id` | `jbmid special --out` | [4.5 `special`](../README.md#45-special番外ova总集篇) |
| [`verify-report.json`](verify-report.json) | 体检报告：计数 + `low_similarity` / `disorder` / `foreign_subject` 明细 + 重复登记 | `jbmid verify --out` | [4.7 `verify`](../README.md#47-verify只读体检) |

几点说明：

- **`item_id` 是 Jellyfin 内部的 GUID**，不是密钥；只在本机有意义，公开出来没用。
- `scan-report.json` 那一条 `season_issues` 是真实样例：季级 ID 为空，23 集里 12 集指向 `331887`、11 集指向
  `302189`，`expected` 是多数票。但它**横跨两个条目**，所以 `summary` 里算进 `season_spans: 1` 而不是
  `season_mismatch`；这种季要 `anchor --seasons --clear-spans` 清空，写任何一个都会让另一半报错（见 README 第 5 章）。
- `scan-review.json` 取自另一个库的真实扫描，用来看 `review` 的 `reason` 长什么样；`series ok` 为 0 是正常的
  ——那批剧大多没设过锚点。
- `verify-report.json` 里的 `anchor_rows` 是**行列表**，终端那行 `anchors N` 才是 `unknown` + `unused` 的合计。
- 当前库的 `season_rows` / `span_rows` 都是空数组——季级 ID 已经修完了；字段一直保留，出问题时才会有内容。
- 备份就是 `rollback` 的输入：集级是 `[{item_id, series, season, index, name, old, new}]`，季级多一个 `kind: season`。

English index: [../README.en.md](../README.en.md) mirrors this structure; the files here are linked from
3, 4.1, 4.2, 4.3, 4.5 and 4.7 there.
