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

> 已决定方案如下；未被选中的候选方案已清除。

### 1. Style preset：CLI + LLM 提取建 preset（已决定）

决定：
- **在基座 CLI 增加 style 参数**，不把 Web UI 作为必经环节。
- **采用 LLM 提取建 preset**，即由 CLI/helper 直接调用现有本地提取链路，从输入书生成并保存 YAML preset。
- 生成物仍是 YAML，后续可人工编辑，但不作为主流程。

CLI 形态（计划）：
- `--extract-style <input> [--save-style <name>]`
  - 读取输入书 → `take_distributed_samples()`
  - 调用 `extract_style()`
  - 打印候选规则及 lint flags 供审查
  - 审查后通过 `write_preset()` 保存到 `Custom_Instructions/<name>.yaml`
- `--style <preset.yaml>`
  - 翻译/润色前通过 `load_custom_instructions()` 加载已保存 preset
  - 写入 `prompt_options['custom_instructions']` / `['refinement_instructions']`
- 保留 `--auto-style`：一次性、不保存、不人工审。
- 优先级：显式 `--style` > `--auto-style`；与 `--glossary` 互相独立。

复用组件（已存在，无需 Web UI）：
- `src.utils.custom_instructions.load_custom_instructions()`
- `read_preset()` / `write_preset()`
- `src.utils.document_sampler.take_distributed_samples()`
- `src.core.style.extractor.extract_style()`
- `src.core.style.assembler.assemble_instructions()`
- `src.core.style.lint.lint_instruction()`

### 2. 多 provider/API 路由：OpenAI-compatible 路由池（已决定）

决定：
- **多 provider 轮换机制采用 OpenAI-compatible 路由池方案**。

方案内容：
- 把现有单 provider `KeyPool` 推广为 **OpenAI-compatible 路由池**。
- 每个路由 = `(endpoint, model, api_key)`，例如：
  - DeepSeek 官方：`https://api.deepseek.com/chat/completions` + `deepseek-v4-flash` + key
  - SiliconFlow：`https://api.siliconflow.cn/v1` + `deepseek-ai/DeepSeek-V4-Flash-0731` + key
  - OpenRouter：`https://openrouter.ai/api/v1/chat/completions` + model + key
  - OpenAI paid：`https://api.openai.com/v1/chat/completions` + model + key
- 请求/响应均为 OpenAI chat/completions 格式，路由池只需在 `OpenAICompatibleProvider` 内增加“当前路由”状态：
  - round-robin 选路由
  - 429 时标记该路由 throttled，换下一个可用路由
  - 全部 throttled 时 sleep / 按现有 `RateLimitError` 自动暂停
- DeepSeek 同 provider 多 key 轮换仍作为路由池内的子能力保留；不同账号的 DeepSeek key 可以放进同一个 DeepSeek 路由的多 key 列表，或作为不同路由。

配置形态（待细化）：
```bash
OPENAI_COMPATIBLE_ROUTES=  "endpoint1|model1|key1;endpoint2|model2|key2;..."
```
或保留 CLI 参数组合传入多条路由。

范围与边界：
- 当前只纳入 OpenAI-compatible API。
- Gemini、Poe 等非兼容 provider 暂不进入该路由池；如未来需要，再单独评估。

### 3. 长时间无回应 / 严重限流影响（保留确认结论）

- 路由池/KeyPool 只处理 HTTP 429；timeout/挂起不会自动把该路由移出池。
- DeepSeek timeout 重试耗尽后 chunk 记为 failed，不是 `RateLimitError`，不会自动暂停；全书可能 partial，需 `--resume` 补漏。
- 超时后重试同一请求不是幂等，可能重复计费。
- 若接受“只是时间变长”，可调大 `REQUEST_TIMEOUT` / `MAX_TRANSLATION_ATTEMPTS`；但若 provider 只是挂起不处理，调大只会更晚失败。
- 保留待办：如果正式跑发现 timeout 型坏路由影响明显，再考虑给路由池增加“timeout 临时禁用/降权”机制。

### 4. 系列跨书术语库与顺序翻译（调查与建议方案）

目标：先后翻译系列多本书时，术语库能跨书复用、逐本增量扩充，不一次性处理整个系列。

现状与约束：
- 基座 CLI `--glossary` 只读取 `source/target/category/gender`，其他字段忽略；输入是单文件 JSON/CSV。
- 本 `_Script` 的 glossary schema 已预留 `id/aliases/lock_level/confidence/frequency/first_seen_book/notes`，可直接承载系列库。
- 基座没有“系列库”概念；Web UI 的 glossary store 也是单本/单命名空间，不适合直接作为 CLI 顺序翻译主存储。

建议数据形态：
- **主存储 = 单文件 `series_glossary.json`**（采用富 schema）。
- 对每本书生成**只读快照/子集** `book_N.glossary.json`：
  - 系列库中所有 `confirmed` 条目
  - 加该书出现/可能出现的实体
  - 供基座 CLI `--glossary` 消费（只保留 source/target/category/gender，或直接保留富字段，加载器会忽略多余字段）
- 当条目规模增大（如超过数百/上千、需要多人并发编辑）再迁 SQLite；迁移时仍导出 JSON 快照给 CLI 使用。

推荐顺序翻译流程（每本书一个循环，不做一次性的整系列翻译）：
1. **准备**：确认 `series_glossary.json` 已有前书已锁定实体；没有则从第一本开始空库。
2. **Seed**：把系列库中与该书相关的已知实体作为 seed（不是让 NER 从头猜已锁定的译名）。
3. **增量提取**：只对当前书跑 NER；候选结果与系列库比对，过滤掉已存在条目，保留“新实体/新别名/可能冲突”。
4. **人工核查**：审阅新候选，合并别名，解决与旧条目的冲突，确认译名，写回 `series_glossary.json`。
5. **翻译**：导出该书 glossary 快照，执行既有两阶段/单阶段翻译，使用 `--glossary book_N.glossary.json`。
6. **回写统计**：翻译后把 `frequency`、`seen_books`/`last_seen_book` 等更新到系列库。
7. **QA**：该书用 `qa/qa_checks.py` 跑确定性检查；跨书一致性检查对比所有已出书输出中同一 source 的 target 是否一致。

关键设计点：
- **实体去重**：以稳定 `id` 为主键；新增表面形式只作为 alias 合并到已有 entry，不新增重复 source。
- **冲突检测**：同 source 新候选 target 与旧 target 不同时，必须停下人工裁决；不自动覆盖。
- **术语复用**：翻译新书时使用全量 confirmed + 该书相关 suggested/新审条目，避免同一角色在不同书里出现不同译名。
- **增量而非全量 NER**：每本书只需提取“新增部分”；已知实体由系列库注入，不重复消耗 NER 预算。
- **逐本积累**：系列库在每本书完成后只增不重译前书；前书输出不回改，除非后续发现必须修正且用户决定重译。
- **向后兼容**：每本书最终仍是一个普通 JSON glossary 文件，可直接给现有 CLI/QA 使用。

需要的工具（计划新增，不在本阶段实现）：
- `series_glossary.py`（或等价的 CLI 参数）子命令：
  - `init`
  - `extract-new --book <file> --base series_glossary.json --draft <new>.draft.json`
  - `merge --draft <new>.draft.json --base series_glossary.json`
  - `export --book <file> --base series_glossary.json --output <book>.glossary.json`
- 或把这些能力做成基座 CLI 的系列模式，但优先保持独立脚本，减少对 fork 的侵入。


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
- [ ] EPUB 阶段: 输出 XHTML XML 合规自检 (spine 逐个 `etree.fromstring`), 嵌套行内标签漏译检查, zip 解压路径穿越校验, 验证 OPF `dc:language` 输出 zh. EPUB 管线是 upstream 高频改动区, 改动前先 rebase.
- [ ] QA 未译英文检测按源语种参数化 (当前仅 EN->ZH).

**上游同步/回馈**
- [ ] upstream 更新流程: `git -C TranslateBooksWithLLMsMod fetch upstream` -> rebase 本地提交到新 tag -> 冲突高发区: `src/core/epub/translator.py`, `config.py`+`.env.example`, 前端 i18n (7 locale), `translation_routes.py`.
- [ ] 可选: 把 F2/F5/P3 等修复做成 upstream PR 回馈.

## 备忘

- 测试数据, 诊断报告, 测试书均已清理 (git 历史中仍可找回, 勿依赖).
- 重新做样本/采样时保留换行结构 (勿用 `" ".join` 拍平文本, 会导致输出无段落).
