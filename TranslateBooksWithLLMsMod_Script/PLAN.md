# Terragen 整书翻译 Pipeline - 交接计划

## 目标与范围

- 输入：英文小说 **txt**；输出：中文 txt。
- 首本验证规模：10-20 章；质量目标为个人阅读级，越高越好。
- 核心要求：术语一致、上下文连贯、漏译/误译可控、两阶段人工核查、可抽章验收。
- 基座：`TranslateBooksWithLLMsMod`（fork，CLI 形态）；只在直接影响译文质量的地方做小改造。
- 非目标：其它输入输出格式、双语排版、自研 Web UI / 队列，以及不直接提升译文质量的工程化功能。
- QA 主路径坚持确定性检查，不把 LLM judge 作为漏译/术语一致性的质量门。

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

- 密钥只在 `TranslateBooksWithLLMsMod/.env`；`.env` 永不入库。
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

## 待办

### P0：真实书质量闭环

- [ ] 选一本真实 txt（10-20 章）跑完整流程：阶段 1 草稿 -> 人工核查 glossary -> 阶段 2 `--glossary` -> QA -> 用户抽 3 章精读验收。
- [ ] QA 输入构建：从 `TranslateBooksWithLLMsMod/data/jobs.db` 的 `checkpoint_chunks` 重建逐 chunk `[{id,source,target}]`，喂给 `qa/qa_checks.py`。
- [ ] 翻译后先确认没有失败 chunk；有失败 chunk 先补译，再做 QA 和抽章验收。
- [ ] 记录用户抽章发现的误译、漏译、术语不一致和上下文断裂问题，作为下一轮质量改进依据。
- [ ] 验收通过后把真实结论回填到本计划，删除已无用的试错记录。

### P1：改进

- [ ] **Style preset CLI**：在 TBL CLI 增加 `--extract-style` / `--save-style` / `--style`，复用现有 `custom_instructions`、`document_sampler`、`style.extractor`、`style.lint`；显式 `--style` 优先于 `--auto-style`，与 `--glossary` 独立。
- [ ] **系列 glossary**：主存储单文件 `series_glossary.json`；每本书导出只读快照供 `--glossary` 使用；实体以稳定 `id` 去重，新 alias 合并到已有 entry；先做 `extract-new / merge / export` 薄脚本，不侵入 TBL 核心。
- [ ] **OpenAI-compatible 路由池**：支持 `(endpoint, model, api_key)` 轮换；429/timeout 切换路由并重试同一 chunk；401/402/404 等 fatal 错误直接失败；空响应/拒答不盲目重试。

## 实验（小样本，以译文质量为判断标准）

- [ ] **链式增长前缀**：前缀 = 已译前文只增不减；小样本对比上下文连贯性、指代一致性和用户抽读质量。
- [ ] **chunk 大小调参**：当前 450，纯散文样本对比 1500-2000；观察段落打断、上下文断裂和重译后的语义偏差。
- [ ] **provider 对照**：DeepSeek 官方 vs 硅基流动同模型，用同一批样本盲评术语、忠实度和流畅度。

## 质量注意

- 采样/重切文本时必须保留换行结构，不要用 `" ".join` 拍平文本，否则段落结构会丢失，直接影响译文可读性。
