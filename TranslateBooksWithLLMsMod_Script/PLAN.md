# Terragen 整书翻译 Pipeline - 交接计划

> **状态: 初期测试阶段已通过** (无/有 glossary 译文质量均由用户判定达标).
> 本文档是给新代理的交接基线: 环境, 决策, 流程已定稿; 未完成事项见"下一步 (待办)".
> 历史过程文档与测试产物已清理 (含核对报告, A/B 日志, 测试书, 测量脚本), 不再保留.

## 目标

- 整书翻译 pipeline: 英文小说 -> 中文, txt 输入优先 (EPUB 后置), 调用 DeepSeek API.
- 质量目标: 个人阅读 (非出版级), 越高越好.
- 核心要求: 术语一致性 (glossary 人工锁定), 两阶段人工核查, 断点续译, chunk 级重译, 控制成本, 复用成熟开源基座.

## 仓库与运行环境

```
Terragen/
|-- TranslateBooksWithLLMsMod/          基座 (git 子模组, fork)
|-- TranslateBooksWithLLMsMod_Script/   本项目交付物 (本文档 + qa/ + glossary/)
|-- IndustriesOfEnceladusRewriteCN/     无关子模组 (另一项目)
`-- IndustriesOfEnceladusRewriteCN_Script/  para-translation 工具 (无关项目)
```

- 基座 fork: `Tessier2501/TranslateBooksWithLLMsMod` (origin=自己, upstream=hydropix), HEAD `e44d1d9`.
- 密钥: `TranslateBooksWithLLMsMod/.env` (子模组 .gitignore 保护; 建议仓库外另存副本以防重克隆丢失).
- 运行方式 (必须用 myenv 的 python + 仓库内运行):
  `cd TranslateBooksWithLLMsMod && PYTHONPATH=. ~/anaconda3/envs/myenv/bin/python translate.py ...`
- 环境: conda `myenv` (python 3.14, conda-forge). 本机规则: 装包用 `~/anaconda3/bin/conda` (Freeside 约定), pip 仅兜底.
- 仓库纪律 (fork 内 CLAUDE.md): 代码/注释/提交信息全英文; 密钥永不入库 (走 .env); 改前端须同步 7 个 locale.

## 测试期结论 (基线数据, 供对照)

- 整书试运行 (deepseek-v4-flash): 139 chunks ~12 min, 成本 **$0.054-0.066/本** (官方低谷价).
- 缓存命中率基线: 无 glossary 44.7% (仅 system prompt 命中); glossary 旧结构 34.8% (glossary 块全未命中); **P3 重排后 ~53.8%** (glossary 块稳定命中, 每 chunk 命中 512 -> 896).
- 已知并已修复的坑: 模型 ~3.5-4% 响应缺 `</TRANSLATION>` 闭合标签 (F1/F2/F4); NER 单次坏响应导致 0 术语 (F5 重试); CLI 无 resume (P2); glossary 块位置破坏缓存 (P3).

## 已定结论 (浓缩)

1. **基座** = TranslateBooksWithLLMsMod (fork, CLI 形态); 不用 skill/agent 路线; translate-book 已弃 (其 manifest/glossary schema 思想已吸收).
2. **默认两阶段流程** (fork `e44d1d9`):
   - 阶段 1: `python translate.py -i <书>.txt -sl English -tl Chinese --provider deepseek` -> 自动 NER (空则重试 1 次) -> 写 `<书>-glossary.draft.json` -> **停止**等待人工核查 (修正译名, 删垃圾行, 可补 `lock_level: confirmed`).
   - 阶段 2: 同命令 + `--glossary <草稿>` -> 正式翻译.
   - `--auto-glossary` = 单次模式 (不停止); `--no-auto-glossary` = 完全跳过; `--glossary` 提供文件时自动跳过 auto; resume/refine-only 自动跳过阶段 1.
3. **Provider**: 主用 DeepSeek 官方 `deepseek-v4-flash` (thinking 默认关, 温度 0.3); 硅基流动对照 = `--provider openai --api_endpoint https://api.siliconflow.cn/v1 -m deepseek-ai/DeepSeek-V4-Flash-0731` (需 SF key). 官方自动前缀缓存 (前缀从第 0 token 一致即命中); 低谷时段跑 (北京 09-12 / 14-18 之外) 半价.
4. **成本**: 整书 $0.06-0.2; 输出 token 是成本主导 (控重译量, 禁 thinking, QA 用确定性检查); P3 后 glossary 注入近免费.
5. **Glossary 设计**: 富 schema (source/target/aliases/type/category/gender/lock_level/confidence/frequency/first_seen_book/notes); TBWLLM `--glossary` 只读 source/target/category/gender, 多余字段忽略 - 同一文件可同时服务注入与 QA. 模板见 `glossary/book_glossary.template.json`.
6. **QA**: 确定性检查 (`qa/qa_checks.py`, 纯标准库, 20/20 单测通过): 数字一致性, 锁定术语合规 (lock_level=confirmed), 实体覆盖, 未译英文检测, 长度比异常, 引号配对. 输入格式 `[{"id","source","target"}]`.
7. **维护**: fork + upstream; 小补丁尽量做成 upstream PR.

## 下一步 (待办, 给新代理)

### 高级设置准备 (正式全书前, 仅计划, 未实施)

> 已读基座 docs: `STYLE_EXTRACTION.md`, `API_KEY_ROTATION.md`, 配套 `CLI.md` / `PROVIDERS.md`.
> 以下只写计划, 暂不交付/不改代码.

### 1. Web UI 建 style preset 后在 CLI 使用

现状:
- Web UI 可生成/保存风格 preset 到 `Custom_Instructions/*.yaml` (`translation`/`refinement` 两个 phase).
- CLI 目前**没有** `--style` / `--custom-instruction` 参数来选择已保存 preset; CLI 只有 `--auto-style` (临时提取, 不保存, 不人工审).

候选方案 (待选型):
- [ ] 方案 A (推荐): 给基座 CLI 增加 `--style <preset.yaml>` / `--custom-instruction` 参数, 复用 `src.utils.custom_instructions.load_custom_instructions`, 把内容写入 `prompt_options['custom_instructions']` / `['refinement_instructions']`; 保留 `--auto-style` 优先级规则. 后续可尝试做 upstream PR.
- [ ] 方案 B: 在本 Script 仓库写薄封装脚本 (如 `scripts/translate_with_style.py`), 读取 Web UI 生成的 YAML, 构造与 Web handler 相同的 `prompt_options`, 直接调用 `src.core.adapters.translate_file` / `refine_file`. 不改基座或只小改.
- [ ] 验收: 用 Web UI 建一个简单 preset, 在 CLI 跑小样本, 日志应出现 `Loaded custom instructions: <file> (phases: translation)` 且译文/润色 prompt 实际包含该风格块.
- [ ] 兼容: 只读 `.yaml/.yml/.txt`; `translation` 与 `refinement` 可单独存在; 需保留 glossary 两阶段流程与 resume 语义.

### 2. 加入 DeepSeek key 轮换

现状:
- 基座支持逗号/换行分隔多 key, 429 自动 round-robin 轮换.
- 当前本地 `.env` 的 `DEEPSEEK_API_KEY` 只有 1 个 key, 轮换未启用.

计划:
- [ ] 准备 2+ 个**不同 DeepSeek 账号**的 key (同账号多 key 不增加配额).
- [ ] 只改本地 `.env` (`DEEPSEEK_API_KEY=key1,key2,...`), 不入库; 仓库外另存副本.
- [ ] 先跑小样本 (几十 chunk 或短章) 验证: 日志出现 `key #n/m`, 429 时换 key 无 sleep; 全部 throttled 时按 `MAX_TRANSLATION_ATTEMPTS`/`AUTO_PAUSE_ON_RATE_LIMIT` 行为暂停并 resume.
- [ ] 若 CLI 调用, 也可临时用 `--deepseek_api_key "k1,k2"` 验证, 不写入 `.env`.

### 3. 对“限流很严重 / 长时间 call 无回应”的影响确认 (只做确认与决策)

已查代码结论:
- key 轮换只处理 **HTTP 429**: `handle_rate_limit` 会把该 key 标 throttled 并换下一个; 它**不处理挂起/no response/timeout**, 也不会把长时间无响应的 key 临时移出池.
- DeepSeek provider 的 timeout 路径是: 每次请求超时后重试 (`MAX_TRANSLATION_ATTEMPTS=3`, 每次之间 sleep 2s), 最终返回 `None`; 该 chunk 会被记为 failed, **不是** `RateLimitError`, 所以**不会触发 rate-limit 自动暂停**, 全书可能以 partial 结束, 需要 `--resume` 补失败 chunk.
- 若某个 key 不返回 429 而是一直挂起, 它会继续参与 round-robin, 周期性拖慢/失败, 直到人工移除.
- 超时后重试同一次请求不是幂等的: provider 若其实已处理完第一个请求, 仍可能产生重复 API 调用/费用 (无法从当前代码完全避免).

需用户确认/选择的决策:
- [ ] 若接受“只是时间变长”: 可调大 `REQUEST_TIMEOUT` 或 `MAX_TRANSLATION_ATTEMPTS`, 让慢但最终成功的 call 有更长等待窗口.
- [ ] 若不能接受 failed/partial chunk: 应在正式全书前对“长时间无响应”的 key 做隔离策略 (例如先短 timeout 探活/人工剔除, 或给代码增加 timeout 后临时禁用 key 的机制) — 这项尚未计划实现.
- [ ] 是否需要为“timeout 后临时禁用/降权该 key”加补丁: 若要, 作为独立小实验, 不与 MVP 主线耦合.

### 4. 调查：如果 CLI 要新增参数，是否还需要 Web UI 来建 style preset？

结论：**不需要把 Web UI 作为硬依赖**。Web UI 本质上是 `Custom_Instructions/` 下 YAML preset 的管理/审查界面，相关读写原语都已存在：

- preset 文件格式就是普通 YAML：顶层 `translation:` / `refinement:`，也可带 `description/mode/context/rules` 元数据；旧 `.txt` 仍兼容。
- 已有纯 CLI/本地可复用函数：
  - `src.utils.custom_instructions.load_custom_instructions()`
  - `read_preset()` / `write_preset()`
  - `src.utils.document_sampler.take_distributed_samples()`
  - `src.core.style.extractor.extract_style()`
  - `src.core.style.assembler.assemble_instructions()`
  - `src.core.style.lint.lint_instruction()`
- 因此 CLI 新增能力可覆盖两条路径：
  1. **手动建 preset**：直接写 `Custom_Instructions/xxx.yaml`，或用 `write_preset()` 保存；不需要 Web UI。
  2. **LLM 提取建 preset**：CLI/helper 读取输入书 → 采样 → `extract_style()` → 打印规则/flags 供人工审 → 审后 `write_preset()` 落盘。也不需要 Web UI/额外服务。

计划倾向：
- [ ] 若给 CLI 加参数，优先同时支持 `--style <preset>` 使用已有 preset 和 `--extract-style <input> --save-style <name>` 从书里提取并保存 preset。
- [ ] Web UI 降级为可选工具：只用于可视化勾选/审查 lint flags；不是 CLI 工作流的必经组件。

### 5. 调查：API 轮换是否可多供应商参与、延长 timeout、付费 API 兜底？

现状结论：
- **当前 key 轮换不能跨 provider**。`API_KEY_ROTATION.md` 与代码均显示：一个 provider 的 key 池只接受该 provider 的多个 key（`DEEPSEEK_API_KEY=...` 只能轮 DeepSeek key，不能混入 OpenRouter/OpenAI key）。
- **当前代码没有自动多 provider failover**。`LLMProvider` 一次只绑定一个 provider；`litellm` provider 能路由到不同上游，但本仓库 wrapper 没有实现跨 provider 自动 fallback/轮换。
- **CLI resume 已支持换 provider 作为手动兜底**：`--resume <id> --provider openrouter -m <model>` 可把剩余/失败 chunk 换到另一个 provider 继续翻译；原 prompt_options（style/glossary）从 checkpoint 保留。这是“付费 API 兜底”的现成无代码路径。
- **延长 timeout 可行**：`REQUEST_TIMEOUT` 当前 `300` 秒，调大即延长单次 HTTP 请求等待；`MAX_TRANSLATION_ATTEMPTS` 控制超时/瞬时错误重试次数。
  - 注意：超时重试不触发 key 轮换；一个一直挂起的 key 仍会周期性拖慢并可能造成 failed chunk/partial 输出。
  - 如果只追求“慢但最终成功”，可接受调大 timeout；但若 provider 实际不再处理，只是挂起，调大只会让失败更晚出现。
- **同 provider 多 key 可作为付费兜底的一部分**：如果多个 key 来自不同账号，其中一个付费/稳定、一个免费/易限流，它们会 round-robin 使用；当前不支持“只把付费 key 当后备，优先用免费 key”的优先级策略。

决策：**多 provider 轮换机制已定为必要功能**，不再是“可选/后置扩展”。

- [ ] 需在正式全书 MVP 前完成设计并至少实现一种可行机制。
- [ ] 目标：主 provider（如 DeepSeek）触发 rate limit / timeout / 持续失败时，系统能自动把当前或后续 chunk 交给备用 provider（如 OpenRouter/OpenAI paid），减少人工介入。
- [ ] 验收：模拟主 provider 限流/不可用，确认任务不会停在原 provider 空转；备用 provider 能继续翻译，checkpoint、glossary、style 均保持一致。

潜在的实现方式（按侵入性/复杂度从低到高排列，待选型）：

1. **外部网关/代理方案（最低侵入）**
   - 使用 OpenRouter、自建 LiteLLM proxy 等作为统一 API 入口。
   - 多 provider 的 key/模型/fallback 策略全部放在网关侧。
   - 基座仍只看到单一 provider，代码几乎不改。
   - 优点：实现快、CLI/Web 都直接受益。
   - 缺点：依赖外部网关/代理；若要求“基座自身控制轮换”，它不满足。

2. **OpenAI-compatible 路由池（最接近当前单 provider key 轮换，推荐优先评估）**
   - 核心思路：当前 `KeyPool` 轮换的是“同一 provider 的多个 key”；把它推广为轮换“多个 OpenAI-compatible 路由”，每个路由 = `(endpoint, model, api_key)`。
   - 可覆盖 DeepSeek 官方、SiliconFlow、OpenRouter、OpenAI 等：它们都走 OpenAI chat/completions 格式，请求/响应结构相同。
   - 对 429 的处理可以完全复用现有 `handle_rate_limit` 思路：标记该路由 throttled → 换下一个可用路由；全部 throttled 时 sleep / 暂停。
   - 优点：与现有单 provider 轮换心智一致；不需要为每个 provider 单独写适配；代码改动集中在 OpenAI-compatible provider 内。
   - 缺点：只适用于 OpenAI-compatible API；Gemini、Poe 等非兼容 provider 不能直接放进同一路由池。
   - 建议配置形态（待细化）：
     - `OPENAI_COMPATIBLE_ROUTES=endpoint1|model1|key1;endpoint2|model2|key2`
     - 或继续用环境变量/CLI 传入多条 `--api_endpoint/-m/--*_api_key` 组合。

3. **Job 级自动 resume 兜底脚本（较低侵入）**
   - 在本 `_Script` 仓库写 wrapper：启动主 provider 翻译，捕获 `RateLimitError` / partial / 失败退出码后，自动用 `--resume <id> --provider <backup> -m <model>` 继续剩余 chunk。
   - 优点：复用现成 resume 能力，不需要改翻译引擎。
   - 缺点：不是 per-request 无缝轮换，只能在一个 provider 跑不动后切换；粒度较粗。

4. **核心 fallback provider 层（较深侵入，最接近原生多 provider 轮换）**
   - 在 `src/core/llm` 新增类似 `FallbackProvider` / `MultiProviderLLMClient` 的包装层。
   - 每个请求按配置顺序尝试主 provider → 备用 provider；只有主 provider 失败/超时/429 后才走备用。
   - 需要接入 `translate_file` / `refine_file` 及 TXT/SRT/EPUB/DOCX 各管线的 `prompt_options`、checkpoint、日志、成本记录。
   - 优点：真正自动、按 chunk 切换；适合作为正式全书测试的主路径。
   - 缺点：改动面大，必须处理各 provider 的模型名、endpoint、key、thinking 参数差异，以及与 resume 的交互。

5. **Provider pool 抽象（可配合 4 使用）**
   - 在现有 `KeyPool` 基础上抽象出“provider 条目池”：每个条目 = provider + model + api_key(s) + endpoint + 优先级/后备语义。
   - 支持免费优先、付费兜底、同 provider 多 key 轮换、跨 provider 有序 fallback 等策略。
   - 作为方案 4 的内部实现基础，可让配置更统一。

倾向路线：

- [ ] 短期/MVP：优先评估/实施方案 2（OpenAI-compatible 路由池），因为它最接近当前单 provider key 轮换，能覆盖 DeepSeek/SiliconFlow/OpenRouter/OpenAI paid 等常用付费/备用 API。
- [ ] 若短期不想改基座，可先用方案 3（脚本自动 resume）验证“DeepSeek 为主 + 付费 API 兜底”的完整链路；它不是最终形态，但能先跑通。
- [ ] 中期：若需要非 OpenAI-compatible provider（如 Gemini/Poe）参与，或需要更无缝的按请求 fallback，再实施方案 4 + 5。
- [ ] 方案 1 可作为不依赖基座代码的备选，但不如 2/4 贴近当前 CLI 工作流。

**MVP 闭环 (主线)**
- [ ] 选一本真实书 (txt, 10-20 章) 跑正式 MVP: 阶段 1 建草稿 -> **人工核查** glossary -> 阶段 2 `--glossary` 翻译 -> `qa/qa_checks.py` 跑确定性 QA -> 用户抽 3 章精读验收.
- [ ] QA 输入构建: 翻译输出的逐 chunk 源文/译文对应可从 `TranslateBooksWithLLMsMod/data/jobs.db` (`checkpoint_chunks`) 重建为 units JSON 后喂 QA (数据目录已被清理, 正式跑会重新生成).
- [ ] 成本/命中记录: 正式翻译保留 stdout 日志 (P1 补丁在日志输出每 chunk `cache hit/miss`), 按 run 单独归档; 多 run 对比勿跨 run 累加. 如需汇总工具, 重写 (可参考 git 历史中已删的 summarize/compare 逻辑, 或直接 grep 日志).

**验证/实验 (可选)**
- [ ] 整书 P3 版对照跑: 验证整书命中率 ~55-60%, 成本回落, 输出无裸标签.
- [ ] chunk 大小调参对照 (450 -> 1500-2000, 纯散文).
- [ ] 链式增长前缀实验 (前缀=已译前文只增不减, 目标更高命中率; 先小样本对照再定, 勿拍脑袋定参数).
- [ ] 硅基流动对照 (输出价更低, 需 SF key).

**后置扩展**
- [ ] 系列 (多本书): 跨书术语库 (单文件 JSON, 大了迁 SQLite) - 新书以系列库做 seed, 只增量提取, merge 新别名, 跨书冲突检测, 跨书 QA; schema 已预留 `first_seen_book`/`lock_level`.
- [ ] EPUB 阶段: 输出 XHTML XML 合规自检 (spine 逐个 `etree.fromstring`), 嵌套行内标签漏译检查, zip 解压路径穿越校验, 验证 OPF `dc:language` 输出 zh. EPUB 管线是 upstream 高频改动区, 改动前先 rebase.
- [ ] QA 未译英文检测按源语种参数化 (当前仅 EN->ZH).

**上游同步/回馈**
- [ ] upstream 更新流程: `git -C TranslateBooksWithLLMsMod fetch upstream` -> rebase 本地提交到新 tag -> 冲突高发区: `src/core/epub/translator.py`, `config.py`+`.env.example`, 前端 i18n (7 locale), `translation_routes.py`.
- [ ] 可选: 把 F2/F5/P3 等修复做成 upstream PR 回馈.

## 备忘

- 测试数据, 诊断报告, 测试书均已清理 (git 历史中仍可找回, 勿依赖).
- 重新做样本/采样时保留换行结构 (勿用 `" ".join` 拍平文本, 会导致输出无段落).
