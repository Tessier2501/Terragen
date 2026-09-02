# Glossary 工作流说明

## 字段约定（单书 / 系列通用）

| 字段 | 说明 |
|---|---|
| `id` | 稳定实体 id（系列库主键） |
| `source` | 源文表面形式（glossary 匹配用） |
| `target` | 规范译名（TBWLLM 注入 + QA 校验用） |
| `aliases` | 同一实体的其他表面形式（QA 覆盖检查用；TBWLLM 忽略） |
| `type` / `category` | 实体类型（character/place/org/term）；category 传给 TBWLLM |
| `gender` | male / female / nonbinary / unknown |
| `lock_level` | `confirmed`（人工锁定，QA 强制校验）或 `suggested`（机器建议，不强制） |
| `confidence` | low / medium / high |
| `frequency` | 全书出现次数（可后续统计回填） |
| `first_seen_book` | 首次出现的书 id（系列库用） |
| `notes` | 人工备注（歧义、译名理由等） |

## 与 TranslateBooksWithLLMs 的兼容性

- `--glossary <file>` 加载器只读取 `source / target / category / gender`，其余字段忽略，因此本模板可直接作为 `--glossary` 输入。
- QA 模块（`Script/qa/qa_checks.py`）读取 `lock_level == "confirmed"` 的条目做术语合规与覆盖检查。

## 流程（单书 MVP）

1. 提取：全书/分章样本跑实体提取（CLI `--auto-glossary` 为一次性临时提取；正式流程待 Web/自定义脚本定案）。
2. 去重合并：同实体多表面形式合并为一个 entry，填 `aliases`。
3. 人工锁定：关键人名/地名/术语置 `lock_level: confirmed` 并审阅 `target`。
4. 注入：`python translate.py --glossary book_glossary.json ...`。
5. QA：翻译完成后跑 `python Script/qa/qa_checks.py --translations units.json --glossary book_glossary.json`。

## 系列扩展（后置）

- 跨书库 = 合并各书 glossary 后的总表，`first_seen_book` 记录出处；新书先以系列库做 seed，只增量提取新实体。
