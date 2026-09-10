# Terragen 整书翻译 Pipeline - 交接计划

## 目标与范围

- 输入：英文小说 **txt**；输出：中文 txt。
- 首本验证规模：10-20 章；质量目标为个人阅读级，越高越好。
- 核心要求：术语一致性、两阶段人工核查、断点续译、chunk 级重译、成本可控。
- 基座：`TranslateBooksWithLLMsMod`（fork，CLI 形态）；不另造翻译、切窗、缓存、渲染、占位符引擎。
- 非目标：TXT 以外的输入输出格式、双语排版、自研 Web UI / 多书队列、LLM judge 作为 QA 主依据。当前只做 txt。

## 运行环境

```
Terragen/
|-- TranslateBooksWithLLMsMod/          # 翻译引擎 fork，git 子模块
`-- TranslateBooksWithLLMsMod_Script/   # 本项目：PLAN + qa/ + glossary/
```

- 基座 fork：`Tessier2501/TranslateBooksWithLLMsMod`；upstream：`hydropix/TranslateBooksWithLLMs`；当前 HEAD `e44d1d9`。
- 运行必须用 `myenv` 的 Python，并在基座仓库根目录执行：

```bash
cd TranslateBooksWithLLMsMod
PYTHONPATH=. ~/anaconda3/envs/myenv/bin/python translate.py <args>
```

- 密钥只在 `TranslateBooksWithLLMsMod/.env`；`.env` 永不入库，建议仓库外另存一份以防重克隆丢失。
- 代码、注释、提交信息用英文；改 TBL 优先小补丁，能回 upstream 就回 upstream。

### 常用流程

```bash
# 阶段 1：生成 glossary 草稿后停止，等人工核查
PYTHONPATH=. ~/anaconda3/envs/myenv/bin/python translate.py \
  -i book.txt -sl English -tl Chinese --provider deepseek

# 阶段 2：人工核查 <书>-glossary.draft.json 后正式翻译
PYTHONPATH=. ~/anaconda3/envs/myenv/bin/python translate.py \
  -i book.txt -sl English -tl Chinese --provider deepseek \
  --glossary <书>-glossary.draft.json

# 断点续译
PYTHONPATH=. ~/anaconda3/envs/myenv/bin/python translate.py --resume cli_xxxxxxxx

# 确定性 QA（在 TranslateBooksWithLLMsMod_Script/ 下）
python qa/qa_checks.py --translations units.json --glossary book_glossary.json
```

## 关键既定决策

- 默认两阶段：先自动 NER 生成 glossary 草稿并停止审核，再用 `--glossary` 正式翻译。
- `--auto-glossary` = 单次模式；`--no-auto-glossary` = 完全跳过；resume / refine-only 自动跳过阶段 1。
- 主 provider：DeepSeek 官方 `deepseek-v4-flash`，thinking 默认关闭，温度 0.3。
- glossary 采用富 schema：`id/source/target/aliases/type/category/gender/lock_level/confidence/frequency/first_seen_book/notes`。
- TBL `--glossary` 加载器只读取 `source/target/category/gender`；多余字段忽略，因此同一文件可同时服务注入与 QA。
- QA 主路径坚持确定性检查，不把 LLM judge 作为漏译/术语一致性的质量门。

## 待办

### P0：真实书 MVP 闭环

- [ ] 选一本真实 txt（10-20 章）跑完整流程：阶段 1 草稿 -> 人工核查 glossary -> 阶段 2 `--glossary` -> QA -> 用户抽 3 章精读验收。
- [ ] QA 输入构建：从 `TranslateBooksWithLLMsMod/data/jobs.db` 的 `checkpoint_chunks` 重建逐 chunk `[{id,source,target}]`，喂给 `qa/qa_checks.py`。
- [ ] 每个 run 单独归档 stdout；保留 cache hit/miss、成本、失败 chunk 数，不跨 run 累加。
- [ ] 验收通过后把真实结论回填到本计划，删除已无用的试错记录。

### P1：确认有价值的改进项

- [ ] **CLI 成本预检**：复用 `src/core/pricing/estimator.py` 与 `pricing_data.py`，新增 `--estimate-only`（或独立小脚本）；打印 chunk 数、input/output token 区间、成本区间，不写 checkpoint。后续可在此基础上做实际试译前 N chunk 的 pilot。
- [ ] **resume 失效判定**：checkpoint 记录 `source_sha256`、`chunker_config_hash`（至少含 `max_tokens_per_chunk`、token counter、context mode）；不匹配时拒绝 resume 或重建 chunk 表，避免旧 `chunk_index` 错位复用。
- [ ] **run 级 usage 持久化**：每次 LLM 调用记录 `prompt_tokens / completion_tokens / cache_hit / cache_miss / failure_kind`；按 run 汇总，`--resume` 后的新旧 run 分开统计。
- [ ] **失败与重试报告**：翻译完成后生成汇总：failed chunks、空响应/缺闭合标签、retry 次数；先看该报告再看 `qa_checks.py`。
- [ ] **密钥自检**：新增 `qa/check_secrets.py`（或 TBL `scripts/` 下等价脚本），提交前扫描 tracked files 的疑似 key 模式。
- [ ] **系列书隔离**：系列翻译每本书用独立 CLI 进程，不共享模块级全局状态；现在不需要自建多书队列。

### 后续路线：已定方向、待实现

- [ ] **Style preset CLI**：在 TBL CLI 增加 `--extract-style` / `--save-style` / `--style`，复用现有 `custom_instructions`、`document_sampler`、`style.extractor`、`style.lint`；显式 `--style` 优先于 `--auto-style`，与 `--glossary` 独立。
- [ ] **OpenAI-compatible 路由池**：在 `OpenAICompatibleProvider` 内支持 `(endpoint, model, api_key)` 路由轮换；429/timeout 为 transient，切换路由并重试同一 chunk；401/402/404 等 fatal fail fast；空响应/拒答为 content，不盲目重试。
- [ ] **timeout 策略**：按 p95/p99 定 `REQUEST_TIMEOUT`，默认不宜过长；timeout 必须触发路由隔离/切换，不能只靠调大超时；日志记录 route index、失败分类、attempt、是否发生切换。
- [ ] **系列 glossary**：主存储单文件 `series_glossary.json`；每本书导出只读快照供 `--glossary` 使用；实体以稳定 `id` 去重，新 alias 合并到已有 entry；先做 `extract-new / merge / export` 薄脚本，不侵入 TBL 核心。

## 实验（小样本、不拍脑袋）

- 基线：整书试运行约 139 chunks / 12 min / `$0.054-0.066/本`；cache hit：无 glossary 44.7%，旧 glossary 34.8%，P3 约 53.8%。目标 55-60%。
- [ ] **链式增长前缀**：前缀 = 已译前文只增不减；小样本对照 cache hit、prompt token 总量、用户抽读质量。不要用单次金额定参，注意服务端缓存预热会反转结果。
- [ ] **chunk 大小调参**：当前 450，纯散文样本对比 1500-2000；同时观察打断段落、重译率和成本。
- [ ] **硅基流动对照**：`--provider openai --api_endpoint https://api.siliconflow.cn/v1 -m deepseek-ai/DeepSeek-V4-Flash-0731`，需 SF key。

## 维护与备忘

- upstream 更新流程：`git -C TranslateBooksWithLLMsMod fetch upstream` -> rebase 本地提交；优先保持本地补丁小而集中，便于做 upstream PR。
- 采样/重切文本时必须保留换行结构，不要用 `" ".join` 拍平文本。
- 成本日志按 run 归档；多 run 对比不要跨 run 累加。
- 已完成的历史测试、修复记录和候选方案不再保留；git 历史可查。
