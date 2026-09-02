# Terragen 整书翻译 Pipeline 计划

> 状态：核对与试运行完成（run1–4 见 `Script/ab/logs/`）；修复批 + P3 已实现并推送 fork `9f9b35d`；glossary 默认开启；下一步整书 P3 版对比与单书 MVP。

## 目标

- 高质量整书翻译 pipeline：英文小说 → 中文，EPUB 进/出，调用外部 LLM API。
- 质量目标：个人阅读（非出版级），越高越好。
- 核心要求：全书术语一致性、断点续译、chunk 级重译、控制成本、尽量复用成熟开源。

## 仓库布局

- Terragen 根目录只放克隆的仓库（git 子模组）：
  - `TranslateBooksWithLLMsMod/`（v1.5.9）：**主基座**——自包含应用，多 provider、checkpoint、glossary、EPUB 处理齐备 (如比较麻烦可回退到仅txt)，在此基础上做本地改动。
  - `translate-book/`：**已移除**（子模组已删）；其设计思想（manifest/run_state 状态追踪、手编 glossary schema）已记录在核对报告中。
- `Script/`：所有工作文件的交付位置（本计划、para-translation 工具 (不属于本项目)、后续调研与实现产物）。

## 已定结论

### 1. 基座选择：TranslateBooksWithLLMs

- 以 TranslateBooksWithLLMs 为运行基座：config + API key 即可跑通，自带 checkpoint/resume、glossary、deepseek provider。
- **运行形态：CLI**（不用 exe，源码直接跑）；**输入优先 txt**，EPUB 有问题直接回退仅 txt。
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
- glossary 默认开启：CLI 默认执行 auto-glossary（提取失败自动重试 1 次）；`--no-auto-glossary` 可关闭；`--glossary` 提供人工锁定文件时自动跳过 auto。

### 5. 架构

EPUB → parser → chunking → glossary discovery → glossary DB → translation → QA → EPUB 重建。

- 翻译每 chunk 输入：system + 固定排序完整 glossary + 少量前后文 + 当前 chunk。
- glossary 是 translation memory / 术语库，不用 RAG。

### 6. QA（确定性检查，成本≈0）

数字一致性、锁定术语合规、实体覆盖、未译英文检测、chunk 长度异常、标点/引号/段落一致、EPUB 结构完整。

### 7. 维护方式

- git fork + upstream 维护本地改动；sampler 抽象为独立策略（distributed / chapter / full / adaptive），默认保持 upstream 行为，尽量做成 upstream PR 以降低同步成本。

## 下一步行动

1. ✅ 代码级核对 TranslateBooksWithLLMs → `Script/review-TBWLLM-v1.5.9.md`。
2. ✅ **P1 补丁 + A/B 类试运行完成**：P1 推 fork（`a656e39`）；整书/样本试运行 run1–4 记录于 `Script/ab/logs/`（成本 $0.054–0.066/本，命中率 34.8–53.8%）。
3. ✅ **P2 补丁**（CLI resume 命令）已完成并推送至 fork（`a656e39`）；补丁由子模组 git 历史管理（原 `Script/patches/` 备份已删除）。
4. 单书 MVP：txt 输入，选一本 10–20 章的真实小说跑通最小闭环，记录每章成本与质量。
5. 确定性 QA 模块（Script/ 侧）。
6. 验收：抽 3 章人工精读。

## 潜在改进 / 修复（试运行 + 外部 review 对照）

> 依据：① 整书试运行 `run1-flash`（deepseek-v4-flash，139 chunks / 12:11，输入 156,854 / 输出 52,215 token，命中率 44.7%，成本 $0.054 低谷价）；② 同类项目 review（`/mnt/c/Users/35723/Downloads/review-2026-09-01.md`，22 本书实测命中 58–88%）。

### 缓存与成本

- ✅ **P3 已实现（fork `9f9b35d`）**：user prompt 中 glossary 固定块前置、可变块置尾（prompts.py 两处）。验证（run4，24 chunk 样本）：每 chunk 命中从 512（仅 system）升至 896（system+glossary），命中率 53.8%；整书预估 glossary 注入成本从 +$0.012 降至 ≈+$0.001。
- **链式增长前缀（更大收益，可选路线）**：前缀 = 已译前文"只增不减"，相邻请求共享近全前缀（外部项目最高 88% 命中、输入 97% 为前缀但几乎全命中）。与 P3 重排二选一或叠加，先对照再定。
- **对照实验做参数 ablation**：前缀长度 × 命中率 × 术语漂移 × 流畅度，不同体量书 × 多档前缀长度，出数据再定默认值（外部项目 32k 前缀即未经对照翻倍的拍脑袋值）。
- **chunk 大小调参**：试运行 450 token → 139 chunks；纯散文在云端大上下文可用 1500–2000 token，减少请求数并改善 chunk 内一致性，作为对照参数之一。

### 质量与一致性

- **跨 chunk 术语漂移设为质量评估专项**：当前上下文仅"前一译文末 25 词"，`context_before/after` 为死参数，一致性依赖 glossary 锁定；若 `book-flash.txt` 评估发现漂移，将"长前文上下文"提为补丁。
- ✅ **标签缺失问题已根因定位并修复（fork `9f9b35d`）**：deepseek-v4-flash 约 3.5–4% 响应发出 `<TRANSLATION>` 后未闭合就停止；提取器要求闭合标签 → 失败 → raw fallback 把裸标签写进输出（run1/2/3 输出各含 5/5/6 处 `<TRANSLATION>` 残留，已确认）。修复：F2 extractor 容忍"有开标签无闭合"（取开标签后内容）；F1 fallback 剥离前导标签；F4 providers 记录 finish_reason；run4 样本 0 次 fallback。
- ✅ **NER 空结果重试（F5）**：`auto_glossary` 提取为空时重试 1 次（run2 曾因单次坏响应得到 0 术语，重试请求近同前缀、缓存便宜）。

### 安全与卫生

- **补 Terragen 根目录 .gitignore**（`.env*`、`__pycache__`、运行输出）——根目录现无 ignore 规则；密钥只允许存在于子模组 `.env`（已被其 .gitignore 覆盖），根目录任何含 key 文件无保护（外部项目 P0-1：配置变体漏忽略，零提交时 `git add .` 即永久入库）。

### 稳健性

- ✅ **P2 resume 输入 hash 校验已实现（fork `9f9b35d`）**：resume 时若原输入文件与保留的 checkpoint 上传副本 hash 不一致则告警，防止源文/译文错位（外部项目 P1-1）。
- **QA 未译英文检测按源语种参数化**：当前仅 EN→ZH；引入其他源语种时按语种分功能词表，勿混表（外部项目 P1-3）。
- **成本/命中数据按 run 单独归档对比**：当前 per-run 日志 + summary 已正确，多 run 对比时勿跨 run 累加（外部项目 P1-2）。

### EPUB 阶段（后置验证项）

- **输出内容文档 XML 合规自检**：spine 逐个 `etree.fromstring` 断言（外部项目 P0-2：22 本全部 method=html 非法 XHTML，换设备才暴露）。
- **嵌套行内标签漏译检查**（外部项目 P3-2）。
- **zip 解压路径穿越校验**（外部项目 P3-4）。
- **验证 OPF 元数据**：基座 `EPUB_TRANSLATE_METADATA_ENABLED` 已内置，验证 `dc:language` 正确输出为 zh（外部项目 P3-3）。
