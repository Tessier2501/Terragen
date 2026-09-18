# Glossary 工作流说明

## 字段约定 (单书 / 系列通用)

| 字段 | 说明 |
|---|---|
| `id` | 稳定实体 id (系列库主键) |
| `source` | 源文表面形式 (glossary 匹配用) |
| `target` | 规范译名 (TBL 注入用) |
| `aliases` | 同一实体的其他表面形式 (系列库匹配与合并用; TBL 忽略) |
| `type` / `category` | 实体类型 (character/place/org/term); category 传给 TBL |
| `gender` | male / female / nonbinary / unknown |
| `lock_level` | `confirmed` (人工锁定, 系列库合并/导出时优先) 或 `suggested` (机器建议) |
| `confidence` | low / medium / high |
| `frequency` | 全书出现次数 (可后续统计回填) |
| `first_seen_book` | 首次出现的书 id (系列库用) |
| `notes` | 人工备注 (歧义, 译名理由等) |

## 与 TranslateBooksWithLLMs 的兼容性

- `--glossary <file>` 加载器只读取 `source / target / category / gender`, 其余字段忽略.
- 因此本模板可直接作为 `--glossary` 输入.
- 系列库的合并与导出逻辑不放在 TBL 核心内, 由独立脚本处理.

## 流程 (单书 MVP)

1. 提取 (自动, 阶段 1): 默认 CLI 先自动 NER 生成草稿 `<输入名>-glossary.draft.json` 并停止, 等待人工核查.
2. 去重合并: 核查时把同实体多表面形式合并为一个 entry, 填 `aliases`.
3. 人工锁定: 关键人名/地名/术语置 `lock_level: confirmed` 并审阅 `target`.
4. 注入: `python translate.py ... --glossary <核查后的草稿>` (阶段 2).
5. 抽读验收: 人工抽章检查术语一致性和上下文连贯性.

## 系列扩展

- 主库为 `series_glossary.json`, 以稳定 `id` 去重.
- 新书先以系列库做 seed, 只增量提取新实体和新别名.
- 每本书导出只读快照 `book_N.glossary.json` 供 TBL `--glossary` 使用.
- 详细实施步骤见 `../PLAN.md` 的 "实施计划 B: 系列 glossary".
