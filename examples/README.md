# 示例文件

这里放的都是**真实运行输出**的节选，可以直接对照字段，也可以改一改当输入用。
文件为了放进仓库做过裁剪（集数、条目数），完整版由命令自己生成，字段与格式完全一致。

| 文件 | 是什么 | 由谁生成 | 在 README 里的位置 |
| --- | --- | --- | --- |
| [`monogatari-season-map.json`](monogatari-season-map.json) | 17 季手工映射，可直接改用 | 手写 | [7.2 `season`](../README.md#72-season你自己说哪几个-subject-拼成一季) |
| [`scan-report.json`](scan-report.json) | 扫描报告：一条 `ok`、两条 `review`（`weak match` / `size mismatch`） | `jbmid scan --out` | [5.1 第一次跑](../README.md#51-第一次跑) · [7.1 `scan`](../README.md#71-scan自动找锚点) |
| [`backup.json`](backup.json) | 写入备份：两条整列右移（`647→645`）、一条原本为空（`null`） | `jbmid apply --backup` | [5.2 写入与回滚](../README.md#52-写入与回滚) |
| [`special-report.json`](special-report.json) | 番外报告：`match 3/5`，逐集给出 `old` / `bgm_id` | `jbmid special --out` | [7.4 `special`](../README.md#74-special连番外一起修) |
| [`verify-report.json`](verify-report.json) | 体检报告：计数 + 低相似度明细 + 重复登记 | `jbmid verify --out` | [7.6 `verify`](../README.md#76-verify只读体检) |

几点说明：

- **`item_id` 是 Jellyfin 内部的 GUID**，不是密钥；它只在本机有意义，公开出来没用。
- `scan-report.json` 取自修复前的一次真实扫描，所以能同时看到 `ok` 和两种 `review` 的原文
  `reason`；当前库跑出来是 `89 ok / 0 review`。
- `verify-report.json` 里的 `anchor_rows` 是**行列表**，终端那行 `anchors N` 才是
  `unknown` + `unused` 的合计。
- 备份文件就是 `rollback` 的输入，格式是 `[{item_id, series, season, index, name, old, new}]`。

English index: [../README.en.md](../README.en.md) has the same structure; the files here are the
ones linked from 5.1, 5.2, 7.2, 7.4 and 7.6 there.
