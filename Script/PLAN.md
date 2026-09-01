# Terragen 整书翻译 Pipeline 计划

> 状态：调研已定稿（provider、成本、glossary 设计），下一步执行 20-chunk A/B 测试与单书 MVP。

## 目标

- 高质量整书翻译 pipeline：英文小说 → 中文，EPUB 进/出，调用外部 LLM API。
- 质量目标：个人阅读（非出版级），越高越好。
- 核心要求：全书术语一致性、断点续译、chunk 级重译、控制成本、尽量复用成熟开源。

## 仓库布局

- Terragen 根目录只放克隆的仓库（git 子模组）：
  - `TranslateBooksWithLLMs/`（v1.5.9）：**主基座**——自包含应用，多 provider、checkpoint、glossary、EPUB 处理齐备 (如比较麻烦可回退到仅txt)，在此基础上做本地改动。
  - `translate-book/`：**设计参考**——不直接作为运行底座；借鉴其 manifest/run_state 状态追踪与手编 glossary schema。
- `Script/`：所有工作文件的交付位置（本计划、para-translation 工具 (不属于本项目)、后续调研与实现产物）。

## 已定结论

### 1. 基座选择：TranslateBooksWithLLMs

- 以 TranslateBooksWithLLMs 为运行基座：config + API key 即可跑通，自带 checkpoint/resume、glossary、deepseek provider。
- translate-book 不作为运行底座：它没有 LLM client，翻译由外部 agent 驱动，需要 agent 运行时，且 agent 循环有额外 token 开销。
- 成本结论：框架本身不决定成本（决定性因素是输出量、缓存命中率、提取策略）；skill/agent 方式的成本优势未实现也未证实，不作为选择依据。
- 从 translate-book 借用：manifest/run_state 状态追踪（chunk 级重译、断点续译）与手编 glossary schema。

### 2. LLM 提供商：DeepSeek 官方为主，硅基流动对照

- 主用 DeepSeek 官方 API `deepseek-v4-flash`（non-thinking 模式）。
- 备选/对照：硅基流动 `deepseek-ai/DeepSeek-V4-Flash-0731`（输出价更低；另托管 GLM-5.2、Kimi-K3 等模型可作质量备选）。
- 均为 OpenAI 兼容 API：官方 base `https://api.deepseek.com`，硅基流动 base `https://api.siliconflow.cn/v1`，配置切换即可。

价格（每百万 token；官方为低谷价）：

| 计费项 | DeepSeek 官方（低谷） | 硅基流动 |
|---|---|---|
| 输入·缓存命中 | $0.007 | $0.028 |
| 输入·未命中 | $0.22 | $0.14 |
| 输出 | $0.66 | $0.28 |

- 官方磁盘上下文缓存全自动：请求前缀从第 0 个 token 起完全一致即命中，命中价约为未命中的 1/31。
- 批量翻译放在低谷时段跑（北京时间工作日 09:00–12:00、14:00–18:00 之外，含周末），价格减半。
- 翻译禁用 thinking 模式（推理 token 同样计费，成本放大 3–10 倍）。
- 用响应中的 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 验证缓存命中率。

### 3. 成本

- 10 万词整书一次跑通 ≈ $0.06–0.2（当前价格，按 90% 缓存命中计）。
- 成本主导项是输出 token：控制重译量、禁用 thinking、QA 用确定性检查是三大省钱手段。
- Prompt 结构：固定顺序完整 glossary + chunk 置尾，前缀稳定以最大化缓存命中。

### 4. Glossary：单书与系列分开设计

- 实体 schema 预留 `lock_level`（suggested/confirmed）与 `first_seen_book` 字段，先按系列可扩展设计，避免日后迁移。
- 单书（MVP）：全书提取 → 去重合并 → 人工锁定关键实体（人名/地名/术语）→ 翻译时按固定顺序注入 → QA 检查锁定术语变体。
- 系列：跨书术语库（单文件 JSON，大了迁 SQLite）；新书用已知实体做 seed → 只增量提取新实体 → merge（新别名并入已有实体）→ 冲突检测（同一形式跨书指代不同实体时带当前书上下文或人工裁决）→ 跨书 QA 检查锁定术语一致性。
- 系列的增量提取是跨书成本优化的关键：每本书只找新实体，不重复全书提取。

### 5. 架构

EPUB → parser → chunking → glossary discovery → glossary DB → translation → QA → EPUB 重建。

- 翻译每 chunk 输入：system + 固定排序完整 glossary + 少量前后文 + 当前 chunk。
- glossary 是 translation memory / 术语库，不用 RAG。

### 6. QA（确定性检查，成本≈0）

数字一致性、锁定术语合规、实体覆盖、未译英文检测、chunk 长度异常、标点/引号/段落一致、EPUB 结构完整。

### 7. 维护方式

- git fork + upstream 维护本地改动；sampler 抽象为独立策略（distributed / chapter / full / adaptive），默认保持 upstream 行为，尽量做成 upstream PR 以降低同步成本。

## 下一步行动

1. 20-chunk A/B 测试：官方 vs 硅基流动、flash vs pro；记录 input/cached/output tokens、耗时与译文质量抽样。
2. 代码级核对 TranslateBooksWithLLMs：sampler 改造点、glossary 存储与注入实现、checkpoint/resume、prompt 顺序与缓存适配。
3. 单书 MVP：选一本 10–20 章的真实小说跑通最小闭环，记录每章成本与质量。
4. 验收：抽 3 章人工精读。
