# Changelog

## Unreleased

- 文档：README 按「症状 → 安装使用 → 实现原理」重排，并新增英文版 `README.en.md`。
- `--library` 解析改为精确 → 忽略大小写 → 唯一子串，失败时列出可用库名。
- `special` 模式的 `reason` 文案统一为英文；新增 5 个库名解析用例（共 21 个）。
- 启用 GitHub Actions：push / PR 跑 3.8 / 3.10 / 3.12 矩阵。

## 1.1.0

- 新增 `special` 子命令：把番外 / SP / OVA / 总集篇 也对上 Bangumi 的 `type=1` 集
  （输出与 `scan` 同构，复用 `apply` / `rollback`）。

## 1.0.0

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
- `doctor`：一条命令自检 Jellyfin 版本、库列表、bgm.tv 连通性和插件配置。
- `--ipv4`：绕开双栈环境下 `api.bgm.tv` AAAA 记录被污染导致的 20 秒超时。
- 写入只碰 `ProviderIds.Bangumi` 一个字段，写后回读复查并检测相邻字段是否被误伤。
