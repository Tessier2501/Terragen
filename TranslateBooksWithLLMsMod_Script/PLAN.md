# Terragen 整书翻译 Pipeline — 交接计划

> **状态：初期测试阶段已通过**（无/有 glossary 译文质量均由用户判定达标）。
> 本文档是给新代理的交接基线：环境、决策、流程已定稿；未完成事项见"下一步（待办）"。
> 历史过程文档与测试产物已清理（含核对报告、A/B 日志、测试书、测量脚本），不再保留。

## 目标

- 整书翻译 pipeline：英文小说 → 中文，txt 输入优先（EPUB 后置），调用 DeepSeek API。
- 质量目标：个人阅读（非出版级），越高越好。
- 核心要求：术语一致性（glossary 人工锁定）、两阶段人工核查、断点续译、chunk 级重译、控制成本、复用成熟开源基座。

## 仓库与运行环境

```
Terragen/
├── TranslateBooksWithLLMsMod/          基座（git 子模组，fork）
├── TranslateBooksWithLLMsMod_Script/   本项目交付物（本文档 + qa/ + glossary/）
├── IndustriesOfEnceladusRewriteCN/     无关子模组（另一项目）
└── IndustriesOfEnceladusRewriteCN_Script/  para-translation 工具（无关项目）
```

- 基座 fork：`Tessier2501/TranslateBooksWithLLMsMod`（origin=自己，upstream=hydropix），HEAD `e44d1d9`。
- 密钥：`TranslateBooksWithLLMsMod/.env`（子模组 .gitignore 保护；建议仓库外另存副本以防重克隆丢失）。
- 运行方式（必须用 myenv 的 python + 仓库内运行）：
  `cd TranslateBooksWithLLMsMod && PYTHONPATH=. ~/anaconda3/envs/myenv/bin/python translate.py ...`
- 环境：conda `myenv`（python 3.14，conda-forge）。本机规则：装包用 `~/anaconda3/bin/conda`（Freeside 约定），pip 仅兜底。
- 仓库纪律（fork 内 CLAUDE.md）：代码/注释/提交信息全英文；密钥永不入库（走 .env）；改前端须同步 7 个 locale。

## 测试期结论（基线数据，供对照）

- 整书试运行（deepseek-v4-flash）：139 chunks ≈ 12 min，成本 **$0.054–0.066/本**（官方低谷价）。
- 缓存命中率基线：无 glossary 44.7%（仅 system prompt 命中）；glossary 旧结构 34.8%（glossary 块全未命中）；**P3 重排后 ~53.8%**（glossary 块稳定命中，每 chunk 命中 512 → 896）。
- 已知并已修复的坑：模型 ~3.5–4% 响应缺 `</TRANSLATION>` 闭合标签（F1/F2/F4）；NER 单次坏响应导致 0 术语（F5 重试）；CLI 无 resume（P2）；glossary 块位置破坏缓存（P3）。

## 已定结论（浓缩）

1. **基座** = TranslateBooksWithLLMsMod（fork，CLI 形态）；不用 skill/agent 路线；translate-book 已弃（其 manifest/glossary schema 思想已吸收）。
2. **默认两阶段流程**（fork `e44d1d9`）：
   - 阶段 1：`python translate.py -i <书>.txt -sl English -tl Chinese --provider deepseek` → 自动 NER（空则重试 1 次）→ 写 `<书>-glossary.draft.json` → **停止**等待人工核查（修正译名、删垃圾行、可补 `lock_level: confirmed`）。
   - 阶段 2：同命令 + `--glossary <草稿>` → 正式翻译。
   - `--auto-glossary` = 单次模式（不停止）；`--no-auto-glossary` = 完全跳过；`--glossary` 提供文件时自动跳过 auto；resume/refine-only 自动跳过阶段 1。
3. **Provider**：主用 DeepSeek 官方 `deepseek-v4-flash`（thinking 默认关，温度 0.3）；硅基流动对照 = `--provider openai --api_endpoint https://api.siliconflow.cn/v1 -m deepseek-ai/DeepSeek-V4-Flash-0731`（需 SF key）。官方自动前缀缓存（前缀从第 0 token 一致即命中）；低谷时段跑（北京 09–12 / 14–18 之外）半价。
4. **成本**：整书 $0.06–0.2；输出 token 是成本主导（控重译量、禁 thinking、QA 用确定性检查）；P3 后 glossary 注入近免费。
5. **Glossary 设计**：富 schema（source/target/aliases/type/category/gender/lock_level/confidence/frequency/first_seen_book/notes）；TBWLLM `--glossary` 只读 source/target/category/gender，多余字段忽略——同一文件可同时服务注入与 QA。模板见 `glossary/book_glossary.template.json`。
6. **QA**：确定性检查（`qa/qa_checks.py`，纯标准库，20/20 单测通过）：数字一致性、锁定术语合规（lock_level=confirmed）、实体覆盖、未译英文检测、长度比异常、引号配对。输入格式 `[{"id","source","target"}]`。
7. **维护**：fork + upstream；小补丁尽量做成 upstream PR。

## 下一步（待办，给新代理）

**MVP 闭环（主线）**
- [ ] 选一本真实书（txt，10–20 章）跑正式 MVP：阶段 1 建草稿 → **人工核查** glossary → 阶段 2 `--glossary` 翻译 → `qa/qa_checks.py` 跑确定性 QA → 用户抽 3 章精读验收。
- [ ] QA 输入构建：翻译输出的逐 chunk 源文/译文对应可从 `TranslateBooksWithLLMsMod/data/jobs.db`（`checkpoint_chunks`）重建为 units JSON 后喂 QA（数据目录已被清理，正式跑会重新生成）。
- [ ] 成本/命中记录：正式翻译保留 stdout 日志（P1 补丁在日志输出每 chunk `cache hit/miss`），按 run 单独归档；多 run 对比勿跨 run 累加。如需汇总工具，重写（可参考 git 历史中已删的 summarize/compare 逻辑，或直接 grep 日志）。

**验证/实验（可选）**
- [ ] 整书 P3 版对照跑：验证整书命中率 ~55–60%、成本回落、输出无裸标签。
- [ ] chunk 大小调参对照（450 → 1500–2000，纯散文）。
- [ ] 链式增长前缀实验（前缀=已译前文只增不减，目标更高命中率；先小样本对照再定，勿拍脑袋定参数）。
- [ ] 硅基流动对照（输出价更低，需 SF key）。

**后置扩展**
- [ ] 系列（多本书）：跨书术语库（单文件 JSON，大了迁 SQLite）——新书以系列库做 seed、只增量提取、merge 新别名、跨书冲突检测、跨书 QA；schema 已预留 `first_seen_book`/`lock_level`。
- [ ] EPUB 阶段：输出 XHTML XML 合规自检（spine 逐个 `etree.fromstring`）、嵌套行内标签漏译检查、zip 解压路径穿越校验、验证 OPF `dc:language` 输出 zh。EPUB 管线是 upstream 高频改动区，改动前先 rebase。
- [ ] QA 未译英文检测按源语种参数化（当前仅 EN→ZH）。

**上游同步/回馈**
- [ ] upstream 更新流程：`git -C TranslateBooksWithLLMsMod fetch upstream` → rebase 本地提交到新 tag → 冲突高发区：`src/core/epub/translator.py`、`config.py`+`.env.example`、前端 i18n（7 locale）、`translation_routes.py`。
- [ ] 可选：把 F2/F5/P3 等修复做成 upstream PR 回馈。

## 备忘

- 测试数据、诊断报告、测试书均已清理（git 历史中仍可找回，勿依赖）。
- 重新做样本/采样时保留换行结构（勿用 `" ".join` 拍平文本，会导致输出无段落）。
