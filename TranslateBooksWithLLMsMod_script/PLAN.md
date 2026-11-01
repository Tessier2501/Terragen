# Terragen 整书翻译 Pipeline - 交接计划

## 目标与范围

- 输入: 英文小说 txt.
- 输出: 中文 txt.
- 质量目标: 个人阅读级, 术语一致, 上下文连贯, 漏译和误译可控.
- 核心流程: 自动 NER 生成 glossary 草稿 -> 人工核查 -> 阶段 2 `--glossary` 翻译 -> 人工抽章验收.
- 基座: `TranslateBooksWithLLMsMod` (fork, CLI 形态). 不另造翻译, 切窗, 缓存或渲染引擎.
- 非目标: 其它输入输出格式, 双语排版, 自研 Web UI 或多书队列, 自动质量检查模块, LLM judge.
- 质量验收以人工抽读为主.

## 运行环境

```
Terragen/
|-- TranslateBooksWithLLMsMod/          # 翻译引擎 fork, git 子模块
`-- TranslateBooksWithLLMsMod_Script/   # 本项目: PLAN + glossary/
```

- 基座 fork: `Tessier2501/TranslateBooksWithLLMsMod`; upstream: `hydropix/TranslateBooksWithLLMs`.
- 运行必须用 `myenv` 的 Python, 并在基座仓库根目录执行:

```bash
cd TranslateBooksWithLLMsMod
PYTHONPATH=. ~/anaconda3/envs/myenv/bin/python translate.py <args>
```

- 密钥只在 `TranslateBooksWithLLMsMod/.env`; `.env` 永不入库.
- 代码, 注释和提交信息用英文; 改 TBL 优先小补丁, 能回 upstream 就回 upstream.

### 常用流程

```bash
# 阶段 1: 生成 glossary 草稿后停止, 等人工核查
PYTHONPATH=. ~/anaconda3/envs/myenv/bin/python translate.py \
  -i book.txt -sl English -tl Chinese --provider deepseek

# 阶段 2: 人工核查 <书>-glossary.draft.json 后正式翻译
PYTHONPATH=. ~/anaconda3/envs/myenv/bin/python translate.py \
  -i book.txt -sl English -tl Chinese --provider deepseek \
  --glossary <书>-glossary.draft.json

# 断点续译
PYTHONPATH=. ~/anaconda3/envs/myenv/bin/python translate.py --resume cli_xxxxxxxx
```

## 关键既定决策

- 默认两阶段: 先自动 NER 生成 glossary 草稿并停止审核, 再用 `--glossary` 正式翻译.
- `--auto-glossary` = 单次模式; `--no-auto-glossary` = 完全跳过; resume / refine-only 自动跳过阶段 1.
- 主 provider: DeepSeek 官方 `deepseek-v4-flash`, thinking 默认关闭, 温度 0.3.
- glossary 采用富 schema: `id/source/target/aliases/type/category/gender/lock_level/confidence/frequency/first_seen_book/notes`.
- TBL `--glossary` 加载器只读取 `source/target/category/gender`; 多余字段忽略, 因此富 schema 可直接作为 `--glossary` 输入.
- 以下三个改进项进入实施: Style preset CLI, 系列 glossary, OpenAI-compatible 路由池.

## P0: 真实书质量闭环

- [ ] 选一本真实 txt (10-20 章) 跑完整流程: 阶段 1 草稿 -> 人工核查 glossary -> 阶段 2 `--glossary` -> 人工抽 3 章精读验收.
- [ ] 翻译完成后检查日志和 checkpoint, 确认没有 failed chunk; 有失败 chunk 先用 `--resume` 补译.
- [ ] 记录抽读发现的误译, 漏译, 术语不一致和上下文断裂, 作为下一轮改进依据.
- [ ] 验收通过后把结论回填到本计划, 删除已无用的试错记录.

---

# 实施计划 A: Style preset CLI

## A.1 目标

在 TBL CLI 内提供完整的 style preset 闭环:

```text
从输入书提取风格 -> 人工查看候选规则 -> 保存 YAML preset
-> 正式翻译或润色时通过 --style 加载 preset
```

不把 Web UI 作为必经环节, 不新增前端依赖.

## A.2 现有可复用组件

- `src/utils/custom_instructions.py`
  - `load_custom_instructions`
  - `read_preset`
  - `write_preset`
  - `filename_for_name`
  - `is_safe_filename`
- `src/utils/document_sampler.py`
  - `take_distributed_samples`
- `src/core/auto_prep.py`
  - `extract_source_text`
  - `STYLE_MAX_CHARS`, `STYLE_SAMPLE_COUNT`, `STYLE_MIN_SAMPLE_SIZE`
- `src/core/style/extractor.py`
  - `extract_style`
- `src/core/style/assembler.py`
  - `assemble_instructions`
- `src/core/style/lint.py`
  - `lint_instruction` (extractor 已为每条规则生成 `flags`)
- `translate.py`
  - `create_llm_client`
  - `_apply_cli_auto_prep`
  - 现有 `--auto-style`

## A.3 CLI 设计

新增参数:

| 参数 | 说明 |
|---|---|
| `--extract-style <input>` | 独立提取模式. 读取输入书, 采样, 调用 `extract_style`, 打印候选规则和 lint flags, 然后退出. 不翻译. |
| `--save-style <name>` | 仅与 `--extract-style` 搭配. 把提取结果写成 `Custom_Instructions/<slug>.yaml`. |
| `--style <preset.yaml>` | 正式翻译或润色时加载 YAML preset, 注入 translation/refinement instructions. |
| `--style-mode <source|model>` | 可选, 默认 `source`. 对应 `extract_style` 的 mode. |
| `--style-include-flagged` | 保存时保留被 lint 标记的规则; 默认丢弃 flagged rules. |
| `--style-force` | `--save-style` 覆盖同名文件时使用. |

优先级和冲突规则:

1. `--save-style` 不能单独使用, 必须有 `--extract-style`.
2. `--extract-style` 是独立模式, 不能与 `--resume`, `--refine-only`, `--glossary`, `--style`, `--auto-style` 同时使用.
3. `--style` 与 `--auto-style` 同时出现时, 显式 `--style` 优先, 并打印 warning.
4. `--style` 与 `--resume` 不能同时使用; resume 继续使用 checkpoint 中保存的 prompt options.
5. `--style` 与 `--glossary` 互相独立, 可以同时使用.

## A.4 实施步骤

1. 在 `translate.py` 增加 argparse 参数和组合校验.
2. 增加 `_run_style_extraction(args, logger) -> int`:
   - 创建 LLM client, 在 finally 中关闭.
   - 用 `auto_prep.extract_source_text` 读取输入.
   - 用 `take_distributed_samples` 采样.
   - 调用 `extract_style(sample, args.style_mode, args.source_lang, args.target_lang, client, max_chars=STYLE_MAX_CHARS)`.
   - 打印 `summary`, `suggested_name`, `context`, 每条规则的 `dimension`, `instruction`, `evidence`, `flags`.
   - 默认只保留 `flags == []` 的规则; 若使用 `--style-include-flagged`, 保留全部并提示人工复核.
   - 调用 `assemble_instructions` 验证 translation/refinement 非空.
   - 若提供 `--save-style`, 调 `filename_for_name` 得到安全文件名, 用 `write_preset` 写入 `Custom_Instructions/`; 不覆盖时提示使用 `--style-force`.
3. 增加 `_load_style_preset(args, prompt_options, logger)`:
   - 解析 `args.style` 路径; 若传入的是文件名, 在 `Custom_Instructions/` 下查找.
   - 调 `load_custom_instructions`.
   - 写入 `prompt_options["custom_instructions"]` 和 `prompt_options["refinement_instructions"]`.
4. 在主流程接入:
   - 在 glossary gate 之前处理 `--extract-style`; 提取完成后 `sys.exit(0)`.
   - 在构建 `prompt_options` 后, 先加载显式 `--style`.
   - 修改 `_apply_cli_auto_prep`: 若显式 style 已设置且用户又传 `--auto-style`, 打印 warning 并跳过 auto style.
5. 更新 `docs/CLI.md` 和 `docs/` 下相关英文文档.

## A.5 测试计划

- argparse: 各参数组合和冲突校验.
- `--save-style`: 写出 YAML, `read_preset` 能读回 `mode/context/rules/translation/refinement`.
- `--style`: 加载后 `prompt_options` 包含两个 instructions key.
- precedence: `--style` 存在时 ignore `--auto-style`.
- extraction: mock LLM client, 验证 flagged rules 默认被丢弃, `--style-include-flagged` 保留.
- save safety: 非法 preset 名被 `filename_for_name` 处理, 路径不逃出 `Custom_Instructions/`.
- regression: 不传 style 参数时现有 `--auto-style` 行为不变.

## A.6 验收标准

```bash
# 提取并保存
python translate.py -i book.txt --extract-style book.txt --save-style noir

# 加载 preset 正式翻译
python translate.py -i book.txt -sl English -tl Chinese --provider deepseek \
  --style Custom_Instructions/noir.yaml

# 显式 style 优先于 auto style
python translate.py -i book.txt --style Custom_Instructions/noir.yaml --auto-style
```

- 生成的 YAML 可人工编辑.
- `--style` 加载后 translation/refinement prompt 中出现 `# STYLE INSTRUCTIONS`.
- 不使用 style 参数时, 原 TBL 行为不变.

---

# 实施计划 B: 系列 glossary

## B.1 目标

为系列小说维护跨书术语库, 保证同一角色, 地名和专有名词在不同书中译名一致, 并逐本增量积累.

## B.2 数据模型

主库 `series_glossary.json`:

```json
{
  "version": 1,
  "series": {
    "id": "series-01",
    "name": "",
    "source_lang": "en",
    "target_lang": "zh-Hans"
  },
  "terms": []
}
```

`terms` 沿用现有富 schema, 并增加系列统计字段:

```text
id, source, target, aliases, type, category, gender,
lock_level, confidence, frequency, first_seen_book,
seen_books, last_seen_book, notes
```

每本书的只读快照:

```text
book_03.glossary.json
```

快照包含本书翻译所需的 confirmed 条目, 并保留富字段. TBL 只读取 `source/target/category/gender`, 其余字段忽略.

## B.3 脚本形态

建议新增独立脚本:

```text
glossary/series_glossary.py
```

子命令:

| 命令 | 作用 |
|---|---|
| `init` | 创建空系列主库 |
| `extract-new` | 从 TBL 生成的单书草稿中筛出系列库尚未收录的新实体和新别名 |
| `merge` | 人工核查后把新条目合并回系列主库, 检测冲突 |
| `export` | 为某本书导出 TBL 可直接消费的只读快照 |
| `stats` | 按书统计 `frequency`, `seen_books`, `last_seen_book` (可选) |

具体接口:

```bash
python glossary/series_glossary.py init \
  --series-id series-01 --series-name "My Series" \
  --output series_glossary.json

python glossary/series_glossary.py extract-new \
  --book book3.txt --book-id book-03 \
  --base series_glossary.json \
  --draft book3-glossary.draft.json \
  --output book3.glossary.new.json

python glossary/series_glossary.py merge \
  --draft book3.glossary.reviewed.json \
  --base series_glossary.json \
  [--dry-run]

python glossary/series_glossary.py export \
  --book book3.txt --book-id book-03 \
  --base series_glossary.json \
  --output book3.glossary.json

python glossary/series_glossary.py stats \
  --book book3.txt --book-id book-03 \
  --base series_glossary.json
```

## B.4 实施步骤

### B.4.1 init

- 校验输出文件不存在.
- 写入 version, series 元数据, 空 terms 数组.
- 原子写入: 先写 `.tmp`, 再 `os.replace`.

### B.4.2 extract-new

- 输入 `--draft` 必须是 TBL 阶段 1 生成的 `{"terms": [...]}` 文件.
- 读取系列库, 建立匹配索引:
  - `source.casefold()`
  - 每个 alias 的 `casefold()`
- 遍历草稿:
  - 若 source 或 alias 已存在, 跳过.
  - 若同一实体已存在但 target 不同, 写入 `conflicts`.
  - 新实体生成稳定 `id`: 对 source 做 slug, 冲突时追加 `-2`, `-3`.
  - 默认填 `lock_level: "suggested"`, `confidence: "medium"`, `first_seen_book: <book-id>`, `seen_books: []`.
- 输出 `bookN.glossary.new.json`, 包含 `terms` 和 `conflicts`.
- 该步骤不调用 LLM, 不重复实现 NER.

### B.4.3 merge

- 人工核查 `bookN.glossary.new.json`, 修正 target, 合并 aliases, 必要时标 `lock_level: confirmed`.
- `merge` 按 `id` 优先匹配, 其次 source/alias 匹配.
- 合并规则:
  - 新条目直接加入.
  - 已有条目: 合并 aliases, 补空字段, 更新 notes.
  - 已有 confirmed target 与新 target 不同: 默认拒绝合并, 列出冲突并退出非零状态.
  - `--dry-run`: 只打印将新增和将更新的条目.
- 成功时原子写回系列主库.
- 绝不自动覆盖 confirmed target.

### B.4.4 export

- 读取系列主库和当前书文本.
- 选择导出条目:
  - 所有 `lock_level == confirmed` 且 `source` 或任一 alias 在本书文本中出现; 或
  - `first_seen_book == <book-id>`.
- 匹配时先原文大小写不敏感搜索, 再对台词等标点边界做简单正则.
- 输出富 schema 快照, 并在顶层写 `book` 元数据:

```json
{
  "version": 1,
  "book": {"book_id": "book-03", "source_file": "book3.txt"},
  "terms": []
}
```

- 快照可直接传给 TBL `--glossary`.

### B.4.5 stats

- 统计每个导出 term 的 `source` 和 aliases 在书中出现次数.
- 更新 `frequency`, `seen_books`, `last_seen_book`.
- 原子写回主库.

## B.5 测试计划

- `init`: 创建和重复创建.
- `extract-new`: 新实体, 已有 source, 已有 alias, target 冲突.
- `merge`: 新增, alias 合并, confirmed target 冲突拒绝, `--dry-run`.
- `export`: 只导出本书出现或本书首见的 confirmed 条目, 输出可被 TBL loader 读取.
- `stats`: frequency 和 seen_books 更新.
- 原子写入: 失败时主库保持不变.

## B.6 验收标准

- 翻译前一本书时可能不加载系列库; 从第二本开始默认加载.
- 每本书先生成新候选, 人工核查后 merge, 再 export, 再翻译.
- 同一 source 在系列各书中使用同一 target.
- 不修改 TBL `src/core/glossary/` 核心代码.

---

# 实施计划 C: OpenAI-compatible 路由池

## C.1 目标

把现有单 provider 的 API key 轮换扩展为多路由池:

```text
Route = (name, endpoint, model, api_key)
```

支持多个 OpenAI-compatible endpoint 之间自动切换, 在 429 和 timeout 时隔离坏路由, 提高长书翻译的可用性.

## C.2 现有基础

- `src/core/llm/key_pool.py`: 单 provider 多 key 轮换.
- `src/core/llm/rate_limit_handler.py`: 429 处理和 KeyPool 节流.
- `src/core/llm/providers/openai.py`: OpenAI-compatible 请求循环.
- `src/core/llm/providers/deepseek.py`: DeepSeek 专用请求循环.
- `src/core/llm/exceptions.py`: `RateLimitError`, `ContextOverflowError`.

## C.3 数据模型

新增 `src/core/llm/route_pool.py`:

```python
@dataclass(frozen=True)
class RouteConfig:
    name: str
    endpoint: str
    model: str
    api_key: str
    disable_thinking: bool = False
    extra_payload: Mapping[str, object] = field(default_factory=dict)
```

路由状态:

```text
throttled_until: monotonic 时间戳
suspect_until: monotonic 时间戳
consecutive_failures: int
last_failure_kind: str
last_error: str
```

`RoutePool` 公开方法:

```text
async acquire() -> RouteConfig
async has_available() -> bool
async time_until_available() -> float
async mark_throttled(route_name, seconds)
async mark_suspect(route_name, seconds)
async report_success(route_name)
async report_failure(route_name, failure_kind)
```

使用 `asyncio.Lock` 保护状态, 与现有 `KeyPool` 的并发模型一致.

## C.4 配置形式

新增 `.env` 变量:

```bash
OPENAI_COMPATIBLE_ROUTES="deepseek|https://api.deepseek.com/chat/completions|deepseek-v4-flash|env:DEEPSEEK_API_KEY;siliconflow|https://api.siliconflow.cn/v1|deepseek-ai/DeepSeek-V4-Flash-0731|env:SILICONFLOW_API_KEY"
```

格式:

```text
name|endpoint|model|api_key_or_env:VAR[|disable_thinking]
```

- 多条路由用分号分隔.
- `env:VAR` 从环境变量读取真实 key, 避免 key 出现在命令行参数里.
- 若 `.env` 中已有单 provider 配置, 不设置 `OPENAI_COMPATIBLE_ROUTES` 时保持旧行为.
- 可保留 CLI `--api_endpoint` / `--openai_api_key` 作为单路由回退.

## C.5 Provider 集成

### C.5.1 OpenAICompatibleProvider

- 新增可选参数 `routes: Optional[list[RouteConfig]] = None`.
- 未提供 routes 时, 完全走现有单路由逻辑.
- 提供 routes 时:
  - 用 `RoutePool` 选路由.
  - 每条路由有独立 endpoint, model, key, extra_payload.
  - `payload["model"] = route.model`.
  - `payload.update(route.extra_payload)`.
  - DeepSeek 官方路由用 `extra_payload={"thinking": {"type": "disabled"}}`.

### C.5.2 请求循环

在 `generate` 内替换为统一的失败分类重试循环:

```text
attempt = 0
rate_limit_events = 0

while attempt < MAX_TRANSLATION_ATTEMPTS:
    route = await route_pool.acquire()
    try:
        response = await post(route)
    except TimeoutException:
        await route_pool.mark_suspect(route, ROUTE_SUSPECT_SECONDS)
        attempt += 1
        continue
    except ConnectError / NetworkError:
        await route_pool.mark_suspect(route, ROUTE_SUSPECT_SECONDS)
        attempt += 1
        continue

    if status == 429:
        rate_limit_events += 1
        await route_pool.mark_throttled(route, wait_time_from_headers)
        continue

    if status in (401, 402, 403, 404, 400):
        raise ProviderFatalError(route, status, body)

    if 500 <= status < 600:
        await route_pool.mark_suspect(route, ROUTE_SUSPECT_SECONDS)
        attempt += 1
        continue

    result = parse_response()
    if result is empty or refusal:
        return None  # content failure, 不盲目重试

    await route_pool.report_success(route)
    return result

if rate_limit_events > 0 and not await route_pool.has_available():
    raise RateLimitError(...)
return None
```

`ROUTE_SUSPECT_SECONDS` 和 `ROUTE_THROTTLE_SECONDS` 放进 `src/config.py`, 给出环境变量默认值.

### C.5.3 DeepSeek provider

- 短剧阶段保留 `DeepSeekProvider` 原行为.
- 路由池先服务 `--provider openai`.
- DeepSeek 官方通过一条 `--provider openai` 路由接入, 使用 `extra_payload` 禁用 thinking.
- 后续再把 `DeepSeekProvider` 内部委派给 route-aware 基类, 避免重复请求循环.

## C.6 失败分类

新增 `src/core/llm/failures.py`:

```python
class FailureKind(str, Enum):
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    CONTENT = "content"
    FATAL = "fatal"
    UNKNOWN = "unknown"
```

分类规则:

| 情况 | 类型 | 处理 |
|---|---|---|
| 429 | rate_limit | 标记 route throttled, 换路由, 不消耗 transient 次数 |
| timeout | transient | 标记 route suspect, 换路由, 重试同一 chunk |
| connect/network error | transient | 同上 |
| 5xx | transient | 同上 |
| 空响应, refusal | content | 不盲目重试, 最多换一条不同路由重试一次 |
| 401/402/403/404/400 | fatal | 直接失败, 标记当前 chunk failed |

## C.7 观测性与日志

新增结构化日志 event:

```text
llm_route_selected
llm_route_switch
llm_route_suspect
llm_route_throttled
llm_route_fatal
llm_route_exhausted
```

每条日志包含:

- route name
- endpoint host
- model
- attempt
- failure kind
- elapsed seconds
- 是否发生切换

不得输出 api_key.

## C.8 实施步骤

1. 新增 `RouteConfig`, `RoutePool`, `FailureKind`, `ProviderFatalError` 和单元测试. 此阶段不改变 provider 行为.
2. 新增 `.env` 解析和配置校验.
3. 改造 `OpenAICompatibleProvider`: routes 缺省时保持旧逻辑; routes 非空时走 RoutePool.
4. 改造请求循环, 接入 429 / timeout / 5xx / fatal / content 分类.
5. 在 `translate.py` 接入 route 配置; 若 `OPENAI_COMPATIBLE_ROUTES` 存在且 `--provider openai`, 打印已启用路由数量, 不打印 key.
6. 增加 route 切换日志和失败统计.
7. 用 mock route 做集成测试; 然后在 SiliconFlow 上做小样本对照.

## C.9 测试计划

- `RoutePool`: round-robin, throttled 跳过, suspect 跳过, all unavailable 时返回最早可用.
- 429: route A 返回 429, 自动切 route B, A 被标记 throttled.
- timeout: route A 超时, route B 成功, A 被标记 suspect.
- 5xx: 同上, 消耗 transient attempt.
- fatal: 404 直接抛出 `ProviderFatalError`, 不继续重试.
- content: 空响应不盲目重试.
- exhausted: 全部路由不可用且预算耗尽 -> `RateLimitError` 或 chunk failed.
- config: `env:VAR` 解析, 重复 route name, 缺少 key, 非法 endpoint.
- regression: 单路由和无 `OPENAI_COMPATIBLE_ROUTES` 时行为与旧版一致.

## C.10 验收标准

- 配置两条路由, 一条 429 或 timeout, 另一条正常; 翻译自动完成或明确进入 failed 状态.
- 单 provider 旧配置无需修改即可继续运行.
- 坏路由会被临时隔离, 不会反复占用重试预算.
- 日志能回答: 当前用哪条路由, 为什么切换, 最终失败原因是什么.

---

## 实验 (小样本, 以译文质量为判断标准)

- [ ] **链式增长前缀**: 前缀 = 已译前文只增不减; 小样本对比上下文连贯性, 指代一致性和用户抽读质量.
- [ ] **chunk 大小调参**: 当前 450, 纯散文样本对比 1500-2000; 观察段落打断, 上下文断裂和重译后的语义偏差.
- [ ] **provider 对照**: DeepSeek 官方 vs 硅基流动同模型, 用同一批样本盲评术语, 忠实度和流畅度.

## 质量注意

- 采样和重切文本时必须保留换行结构, 不要用 `" ".join` 拍平文本, 否则段落结构会丢失, 直接影响译文可读性.
- glossary 的人工核查是质量关键路径; 不要用自动 NER 草稿直接替代人工确认.
