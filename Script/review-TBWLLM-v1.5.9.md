# TranslateBooksWithLLMs v1.5.9 代码级核对报告

> 核对对象：`TranslateBooksWithLLMsMod/`（git 子模组，HEAD=`031cb27`，tag `v1.5.9`，remote 指向 upstream hydropix/TranslateBooksWithLLMs）
> 核对方式：全程只读，未修改任何文件、未运行程序。四个检查面并行完成：glossary/采样、prompt/LLM 层、checkpoint/配置、结构/同步风险。
> 依据：各节结论均带 file:line 证据（文件路径相对仓库根）。

## 1. 架构总览

- 双入口：**CLI**（`translate.py`，446 行，argparse 直接驱动）+ **Flask Web 应用**（`src/api` 11 个 blueprint + websocket + `src/web` 模板/JS/7 语言 i18n）。Web 是主界面，CLI 是副通道。
- 核心引擎 `src/core/`：`adapters/`（格式适配 epub/srt/txt/docx + generic_translator）、`chunking/`、`epub/`（约 30 文件，最大）、`docx/`、`glossary/`（store/filter/ner/injector/inflection）、`llm/`（base 抽象基类 + 8 个 provider + factory + thinking + key_pool）、`refine/`（二次润色）、`style/`（样式提取）、`common/`（orchestrator、plain_text_pipeline、parallel）、`sampling.py`、`auto_prep.py`。
- 提示词集中在 `src/prompts/prompts.py`（1232 行）；配置集中在 `src/config.py`（841 行，.env 驱动，67+ 变量）；断点在 `src/persistence/`（checkpoint_manager 987 行 + database）。
- 文档：`docs/` 17 篇专题（GLOSSARY 38KB、STYLE_EXTRACTION 35KB、BACKLOG 46KB）；无 ARCHITECTURE.md/CONTRIBUTING.md；`CLAUDE.md` 是事实上的工程规范（语言政策、密钥安全、**前端任何 UI 字符串改动必须同步 7 个 locale 文件**、根目录禁止临时脚本）。

## 2. Glossary 提取与采样器

- **提取入口**：三条路径全部汇到 `src/core/glossary/ner.py` 的 `suggest_terms`（prompt 驱动的 NER）：
  1. Web `POST /api/glossaries/<gid>/suggest-terms`（`src/api/blueprints/glossary_routes.py:566`，人工审阅后入库）；
  2. CLI `--auto-glossary`（`translate.py:162/329` → `auto_prep.py:197-238`，一次性临时提取、**不落盘**）；
  3. Web 翻译作业的 Auto 下拉（`handlers.py:112-159/596-601`）。
- **分散采样**：`src/utils/document_sampler.py:158-219` `take_distributed_samples`——字符级均匀等距 n 段、边界吸附空白；预算 6000 字符（`auto_prep.py:40` / `glossary_routes.py:50`）、每段下限 500 字符、默认 10 段（Web 上限 50）、全文上限 5M（`document_sampler.py:25`）。**无"多轮"概念**：只做一次 NER，输入截断 6000 字符（`ner.py:109`）。
- **注意**：`src/core/sampling.py` 是另一套 Sample&Compare 文档抽样，与 glossary 无关，勿混淆。
- **改造难度**：采样器已隔离为唯一共享组件 `document_sampler`（3 个调用点：`auto_prep.py:219`、`glossary_routes.py:646`、`custom_instruction_routes.py:392`）；但 **config.py/.env.example 均无采样配置**，全部是模块级常量，改策略必须改代码。per-chapter 的障碍：抽取层把 EPUB 拼成单串、丢失章节边界（`document_sampler.py:85-113`）。评级：full scan=小、per-chapter=中、adaptive=中，**均不必 fork**。

## 3. Glossary 存储与注入

- **存储**：SQLite `data/glossaries.db`（`store.py:28`），表 `glossaries` + `glossary_terms`（source_term/translated_term/category/gender，`store.py:163-185`）。CLI 走 JSON/CSV 文件（`cli_loader.py`）：JSON 接受 `{"terms":[{source,target,category?,gender?}]}` 或裸列表；CSV 必含 source/target 列。
- **注入**：per-chunk **相关子集**（`filter_glossary`，`filter.py:60-123`）；精确匹配（拉丁语 \b 边界、CJK 子串，`filter.py:51-57`），无词形还原（变体靠 `|` 手工声明）；cast block（角色表）全量注入（`injector.py:107-177`）；屈折语追加 `TARGET_INFLECTION_INSTRUCTION`（`inflection.py:23-48`）；全格式共用注入点 `translator.py:35-129`。
- **硬限制**：`GlossaryConfig.max_entries=50` 且不可配置（`translator.py:84` 唯一读取点）——整书术语表超过 50 条会被截断。
- **无纯提取 CLI**：只有 Web suggest-terms 能"只提取不翻译"。

## 4. 翻译 prompt 构造与缓存适配

- **消息结构**：`[system, user]` 两条。system（`prompts.py:304-337`）= 角色+style+原则+输出格式，**job 级逐字节稳定且在首位**；user（`prompts.py:355-368`）= 前一译文上下文 → glossary → 当前 chunk。
- **死参数**：`context_before`/`context_after` 全链路传入但从未插值进 prompt（grep 证实）；实际只有"前一译文末 25 词"入 prompt（`translator.py:380-382`）。即当前实现**没有前后章节上下文**。
- **前缀稳定性**：system message 是稳定前缀（好）；user message 从第 0 token 起逐 chunk 变化（差）。唯一例外：Plain Text 重试会改 system 尾部（`prompts.py:98-118`），破坏该路径前缀稳定。
- **无 provider 缓存集成**：`cache_control`/`cached_tokens`/`prompt_cache_hit_tokens` 全仓库零匹配；`LLMResponse`（`src/core/llm/base.py:39-48`）无缓存字段。只能依赖 DeepSeek/硅基流动侧**自动前缀缓存**（前缀从第 0 token 一致即命中）。
- **缓存适配评估（改动量小～中）**：主缺口 = user prompt 可变块（前一译文+glossary）排在最前，截断跨 chunk 前缀——重排（固定块前置）为 `prompts.py` 一处改动；cast 块埋在 user prompt 中段且 `injector.py` docstring 与实现矛盾；补 LLMResponse 缓存字段 + usage 解析为小改动。

## 5. LLM 层与提供商切换

- provider 列表（CLI）：ollama/gemini/openai/openrouter/mistral/deepseek/poe/nim/litellm（`translate.py:144`）。
- **thinking**：DeepSeek 默认关闭（`DEEPSEEK_DISABLE_THINKING=true`，`config.py:366`；`deepseek.py:221-222` 发送 `thinking={"type":"disabled"}`）；temperature=0.3（`config.py:292`）；openai-compatible 路径连 temperature 都不发（`openai.py:100-104`）。
- **硅基流动 = 纯配置切换，零代码改动**：
  - 方案 A：`--provider deepseek` + `DEEPSEEK_API_ENDPOINT` 必须写全路径 `/v1/chat/completions`（deepseek.py 不做路径归一化）；注意模型串含 "deepseek-v4" 会触发 thinking 参数；factory 不透传 api_endpoint 给 deepseek（`factory.py:145-150`）。
  - **方案 B（推荐）**：`--provider openai --api_endpoint https://api.siliconflow.cn/v1 --model deepseek-ai/DeepSeek-V4-Flash-0731`（`openai.py:48-79` 自动补全路径）。
  - Web endpoint 白名单随 .env 配置放行（`endpoint_validator.py:50-59/111-120`）。
- **usage 丢弃**：所有 provider 只读 `prompt_tokens`/`completion_tokens`（`deepseek.py:264-277`、`openai.py:136-153`），`prompt_cache_hit_tokens` 被丢弃——**测量缓存命中率需要补丁 P1**。

## 6. Checkpoint/断点续译（resume）

- **机制**：三层粒度。SQLite `data/jobs.db`：`translation_jobs`（status/progress/translation_context JSON）+ `checkpoint_chunks`（每 chunk 一行 original/translated/chunk_data/status）；磁盘 `data/uploads/<id>/`：`xhtml_states/*.json`（EPUB/DOCX 文件内逐 chunk 状态）+ `translated_files/`（已译 XHTML）+ 输入备份。密钥落库前剥离（`database.py:14-27`）。
- **恢复**：精确跳转——TXT/SRT 依据 chunk status 推导 pending（`generic_translator.py:339`，跳过 completed、重译 failed）；EPUB 用文件指针 + unfinished 门票重入（`translator.py:1161-1190`、`xhtml_translator.py:955-956`）。**唯一恢复入口：Web `POST /api/resume/<id>`**（`translation_routes.py:489-576`）；限流自动恢复循环（`handlers.py:1044-1104`）。
- **chunk 级重译**：failed/untranslated 自动重译原生支持；**无"指定任意 chunk"命令**（需手工删 `checkpoint_chunks` 行或改 `xhtml_states` JSON 的 chunk_statuses[i]='pending'）；`token_aligned` 块刻意不可重译（`xhtml_translation_state.py:26-34`）。
- **状态内容**：含已译文本、glossary 快照（prompt_options）、时间戳、model_name、逐 chunk 状态；**不含 API 费用**（OpenRouter cost 仅内存，`handlers.py:550-561`）、不含每 chunk 模型版本。
- **CLI 缺口（关键）**：`translate.py` 无任何 resume/retranslate 参数，每次运行生成新 `translation_id`（`translate.py:337`）；CLI 中断后 job 卡在 `running` 状态无法进入可恢复列表（`database.py:480` 过滤 paused/interrupted/error/partial）。refine 阶段无 checkpoint（`epub_refiner.py` 明言 no resume in v1）；输入重新分块后 checkpoint 整体失效。
- **配置**：chunk 大小 `MAX_TOKENS_PER_CHUNK=450`（可热重载）、provider/model/base_url、重试/并行/限流自动恢复齐备；**无采样轮数/策略配置**。

## 7. upstream 同步风险

- 781 commits（112 merge），2025-05-22 → 2026-08-24，月均约 50；**单一维护者 hydropix 占 769/781（98.5%）**；近 3 周（08-02 → 08-24）发 10 个版本（v1.5.0 → v1.5.9）；无 CHANGELOG、无 CONTRIBUTING；CI 强制 tag 与 `__version__` 一致。
- **高频变更**（近 100 commits）：`src/__version__.py` 17、`src/core/epub/translator.py` 11、`translation_interface.html` 10、`xhtml_translator.py` 10、`config.py` 10、`translation_routes.py` 9、`.env.example` 9、`plain_text_pipeline.py` 8、7 个 locale 各 7。
- **最易冲突 5 处**：① `src/core/epub/translator.py` ② `src/config.py` + `.env.example` ③ Web 前端 + 7 语言 i18n（一次 UI 改动 = 8+ 文件）④ `src/api/blueprints/translation_routes.py` + `handlers.py` ⑤ `tests/characterization/golden/*.json`。
- **扩展点**：无 plugin/hook 机制（src 下 plugin 零命中）；provider 注册硬编码（`factory.py` if/elif 链，新增 provider 按 BACKLOG 记录需跨 34 文件）；采样器参数可配但算法硬编码；真正可用的扩展点是**数据层**（glossary JSON/CSV、`Custom_Instructions/` YAML 样式预设、67+ .env 变量）。
- **评级：高**。但所需本地改动均为小改动、可隔离（见下）。

## 8. 需求差距清单

| 需求 | 现状 | 差距 |
|---|---|---|
| 整书术语一致性 | glossary 注入齐备 | 50 条上限偏小；提取入口在 Web |
| 分散采样改 per-chapter/full | 组件已隔离 | 需改代码（小/中），配置项缺失 |
| 断点续译 | Web 有、CLI 无 | **CLI 需补 resume 命令（补丁 P2）** |
| chunk 级重译 | failed 自动重译 | 无任意 chunk 命令（手动改 DB） |
| prompt 缓存友好 | system 稳定、user 可变块前置 | 重排即可（补丁 P3，小） |
| 硅基流动切换 | 配置即可 | 零代码改动 |
| 成本测量 | usage 丢缓存字段 | **补丁 P1** |
| 上下文一致性 | 只有前 25 词 | context_before/after 是死参数，需实现 |

## 9. 已定决策与补丁清单（用户批准）

**决策**：
- 运行形态：**CLI 路线**（不用 exe，源码直接跑；批量/低谷时段调度方便）。
- 输入格式：**优先 txt**；EPUB 如有问题直接回退 txt-only（EPUB 管线是 upstream 高频改动区 + token_aligned 不可重译限制）。
- 补丁提交于 fork（`Tessier2501/TranslateBooksWithLLMsMod`，commit `a656e39`），子模组随 fork main 更新；原 `Script/patches/` 备份已删除。

**补丁清单**：
- **P1（已批准，A/B 前置）**：读取 `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`——`LLMResponse`（`llm/base.py:39-48`）加字段 + `deepseek.py:264-277`、`openai.py:136-153` usage 解析 + 透传到日志/stats。
- **P2（走 CLI 必须）**：CLI resume 命令——复用 `CheckpointManager` 与 `data/jobs.db`，按输入文件+设置定位未完成任务，补 `translate.py` 参数（如 `--resume <id>`）。
- **P3（可选优化）**：user prompt 重排，固定块（glossary 按固定排序）前置、可变块（前一译文、chunk）置尾，最大化跨 chunk 缓存命中（`prompts.py` 一处）。
- **P4（按需）**：采样策略 per-chapter/full——改 `document_sampler.py` + 2 处接线；per-chapter 需先在抽取层保留章节边界（或走 txt 时自行分章）。

**repo 规范备忘（patch 阶段必须遵守，见仓库 CLAUDE.md）**：入库内容一律英文；禁止硬编码 API key（一律 .env）；前端改动同步 7 个 locale；根目录不放临时脚本（放 `tests/standalone/` 或 `scripts/`）。

## 10. 后续行动

1. 打 P1 补丁 → 20-chunk A/B（官方 vs 硅基流动、flash vs pro；记录 input/cached/output tokens、耗时、质量抽样）。
2. 打 P2 补丁（CLI resume）→ 单书 MVP（txt 输入，10–20 章真实小说）。
3. 确定性 QA 模块（Script/ 侧独立实现）。
4. 验收：抽 3 章人工精读。
