项目背景与目标

用户希望建立一个“高质量整书翻译”pipeline，主要场景是英文小说 -> 中文，输入最好是 EPUB，调用外部 LLM API。核心目标不是问答，而是：

1. 自动从整本书建立 Glossary / terminology / entity information。
2. 翻译过程中保持人名、地名、组织、专有名词、特殊术语等的一致性。
3. 尽量减少 token 消耗。
4. 能从中断处继续。
5. 最好只对出现问题的 chunk 重译，而不是整本书重翻。
6. 最终输出可正常阅读的 EPUB。
7. 用户希望尽可能利用成熟开源项目，而不是从零实现整个翻译系统。
8. 用户已经将两个候选项目 clone 到本地，并让有权限的 coding agent 接手：
   - TranslateBooksWithLLMs
   - translate-book
   当前任务重点应转向直接检查这两个本地仓库的实际代码，而不是继续凭 GitHub README 推测。

此前比较过的项目

1. TranslateBooksWithLLMs
GitHub: https://github.com/hydropix/TranslateBooksWithLLMs

优势：
- Stars 明显高于另外几个候选项目，因此用户认为其社区采用度值得重视。
- 已经实现 EPUB 处理、chunking、Glossary、LLM API、翻译、checkpoint/resume、EPUB 输出等完整 pipeline。
- 支持外部 API / OpenAI-compatible API 等。
- Glossary 系统明确支持“当前 chunk 只注入相关 glossary entries”，避免每次都发送完整 glossary。
- Auto glossary extraction 有多轮采样机制。
- Windows release 以 .exe 形式提供，但仓库本身是 Python 源码项目，可以直接从源码运行；不需要为了修改而先重新打包 exe。
- 用户目前倾向把它作为主要翻译基座，而不是继续寻找完全不同的项目。

重要缺点/疑点：
- 官方 Glossary 自动提取明确使用“分散采样”：
  - 默认最多处理一定范围文本；
  - 默认抽取约 10 个均匀分布的 excerpts；
  - 每个 excerpt 有字符长度要求；
  - 可重复执行多轮。
- 官方文档表示第二轮通常还能发现约 30–50% 的新实体，并建议运行 2–3 轮直到结果趋于稳定。
- 这意味着分散采样对高频实体比较可靠，但对低频、局部章节才出现的重要实体可能有较高遗漏风险。
- 目前没有证据支持给它一个固定的 glossary recall 百分比。
- 用户已经接受：如果其他方面更好，完全可以直接修改它的 sampler，而不是因为 sampling 策略就放弃项目。

关于分散采样的数学直觉：
如果某实体随机占全文比例 p，单次均匀采样 n 次都没抽到的近似概率为 (1-p)^n。
例如 n=10：
- p=1%：发现概率约 9.6%
- p=5%：发现概率约 40.1%
- p=20%：发现概率约 89.3%
这些只是说明 sampling 的基本遗漏风险，不能当作 TranslateBooksWithLLMs 实际 recall 测试结果。
真正需要关注的是低频实体、集中在少数章节的实体。

用户目前的态度：
“没事，大不了我上手改采样器。TranslateBooksWithLLMs stars 比另外几个多太多了，我觉得这个没有问题。”
因此不要再把“分散采样”作为否定 TranslateBooksWithLLMs 的理由。更合理的是评估：
- sampler 是否容易修改；
- 修改是否能与 upstream 保持同步；
- translate-book 是否在其他核心能力上明显更优。

2. translate-book
GitHub: https://github.com/deusyu/translate-book

优势：
- 很适合拿来研究/改造成自己的 translation pipeline。
- chunk / manifest / glossary / parallel translation / resume 等结构比较明确。
- 有 glossary 自动提取。
- glossary 可以包含 aliases、category、gender、confidence、frequency 等信息。
- 有 chunk-specific glossary。
- 有 top-N 高频术语机制。
- 使用 manifest / SHA256 等机制追踪翻译状态。
- 支持并行翻译。
- 更容易作为代码骨架进行大幅改造。

用户已经把它 clone 到本地。
现在应当直接检查本地代码，而不是只根据 README 评价。

用户此前问过的核心 API / prompt cache 问题

需要区分：

1. API context：
多数 LLM API request 默认是无状态的。
Request 2 不会因为 Request 1 调用过而天然知道 Request 1 的内容。
因此翻译项目必须自己维护 Glossary、translation memory、previous/next context、project state 等。

2. Prompt caching：
“API 无状态”不等于“每次都重新计算所有 input token”。
现代 API provider 可能提供 prompt caching/context caching。
如果多个 request 的 prefix 相同，例如：

SYSTEM
STYLE
FIXED GLOSSARY
CURRENT CHUNK

那么前面的固定内容可能命中 provider 的 prompt cache。

关键点：
- cache 通常依赖 prefix 稳定。
- 如果每个 chunk 都动态改变 glossary，那么 prefix 可能频繁变化，降低 cache reuse。
- 因此“每次只发送当前 chunk relevant glossary”虽然减少了 raw input token，但不一定是总成本最优。
- “每次发送完整固定 glossary”虽然 raw input token 更多，但如果 provider 对 cached input 收费极低，则可能因为高 cache hit 而更便宜。
- 实际结果高度依赖具体 provider 的 caching 规则、minimum cacheable prefix、TTL、收费方式等。

此前提出的三种结构：

A. Dynamic glossary
system + 当前 chunk 命中的 glossary + chunk
优点：raw input token 少
缺点：prefix 变化多，cache hit 可能低

B. Fixed glossary
system + 完整 glossary + chunk
优点：prefix 稳定，理论上 cache-friendly
缺点：raw input token 大

C. Fixed glossary + stable ordering
system + 固定 style + 固定排序的完整 glossary + chunk
最有利于保持完全稳定 prefix，因此理论上最适合 prompt cache。

用户问：“translate-book 这种 skill 命中比较高吗？”
此前回答的结论：
- 不能仅凭项目名称/架构断言 translate-book 的 cache hit 更高。
- cache hit 取决于实际 API provider、请求构造方式、prefix 是否稳定。
- 应该直接检查两个项目本地代码中的 LLM request construction，尤其是：
  - system prompt
  - glossary injection
  - context injection
  - current chunk
  - 是否保持顺序稳定
  - 是否使用 provider 特有 cache 参数
- 最好实际做 20 chunks 的 A/B 测试，记录：
  - input tokens
  - cached input tokens
  - output tokens
  - cache hit rate
  - latency
  - total cost

这是当前一个重要待调查点。

用户对“修改源码后难以同步 upstream”的担忧

用户意识到 TranslateBooksWithLLMs 更新很快，如果直接手改源码，未来同步新功能可能困难。

此前建议：
- 不要直接复制代码后永久 fork。
- 应使用 Git fork + upstream。
- 尽量把自己的修改限制成小而独立的 patch。
- 尤其 sampler 是很适合隔离的修改。
- 理想结构：
  upstream TranslateBooksWithLLMs
      |
      -> user fork
          |
          -> small local patches
- 可以：
  git remote add upstream ...
  git fetch upstream
  git merge upstream/main
- 不需要每个 upstream release 都立即同步。
- 最好把 sampler 抽象成独立策略：
  distributed
  chapter
  full
  adaptive
- 默认保持 upstream 行为，用户自己的配置选择新 sampler。
- 如果实现足够通用，可以将 sampler strategy 做成 upstream PR，从而未来不再需要维护本地 patch。
- 不建议一开始大改整个 translation engine。

用户对 exe 的疑问

TranslateBooksWithLLMs 的 release 有 Windows .exe，但仓库本身包含 Python source/build/deployment 等内容。
因此：
- 修改源码后可以直接从源码运行；
- 不需要重新打包 exe；
- Docker 也是可选的开发方式；
- 只有最终希望得到独立 exe 时才需要重新打包。
用户已经接受这种方式。

推荐的总体架构思路

用户之前使用/开发过基于 LightRAG 的结构化问答项目，觉得其 token 消耗很大。
用户现在认为“整书高质量翻译”不应该需要 LightRAG 式的动态检索。

核心架构应该是：

EPUB
 -> parser
 -> semantic chunking
 -> glossary/entity discovery
 -> persistent glossary DB
 -> translation
 -> QA
 -> EPUB reconstruction

翻译时每个 chunk 最好获得：
- system prompt
- style instructions
- relevant glossary / terminology
- 少量 previous/next context
- current chunk

而不是每次：
- 整本书 RAG
- 大量 nodes
- relationships
- dynamic retrieval
- 大量重复上下文

Glossary 应被视为：
- translation memory
- terminology database
- entity resolution layer
而不是传统 RAG knowledge base。

理想 glossary schema 可以比简单 source -> target 更丰富，例如：

{
  source: "Jon Snow",
  canonical: "琼恩·雪诺",
  aliases: ["Jon", "Snow"],
  type: "character",
  gender: "male",
  notes: "...",
  confidence: ...
}

也就是说：
多个表面形式 -> 一个 canonical entity -> 一个稳定译名。

用户此前提出的“更完整 glossary discovery”想法

不要认为随机采样必须一次性完美。
可以：
- sampler discovery
- 全文 candidate scan
- LLM disambiguation
- 人工确认/locking
- translation
- post-translation QA
- 发现漏项后局部重新翻译

但用户现在已经表示可以直接改 sampler，所以优先调查现有代码能否很容易地改为：
- per chapter sampling
- sliding window
- full sequential scan
- adaptive sampling
而不是立即另写一整套 glossary builder。

QA 是值得自行增加的模块

现有项目如果翻译核心已经成熟，用户更值得自己写的是 deterministic QA，而不是重新写 LLM translation engine。

建议检查：
1. 数字一致性：
   3、2024、17.5% 等
2. glossary compliance：
   locked term 是否出现变体
3. entity coverage：
   source entity 是否在 translation 中消失
4. untranslated English detection：
   防止整句残留，但注意合法英文专名/对话
5. chunk length anomaly：
   source 320 words -> target 70 words 之类的异常
6. punctuation / quote / paragraph consistency
7. EPUB structural integrity

QA 应尽量使用 Python / deterministic checks，减少 LLM token。

当前最重要的实际任务

用户现在准备将：
- TranslateBooksWithLLMs
- translate-book
clone 到本地，并让有权限的 agent 接手。

因此下一步不应该继续泛泛介绍第三方项目，而应该直接对两个本地仓库做代码级比较。

优先调查：

A. TranslateBooksWithLLMs
1. 找到 glossary extraction 的真实入口。
2. 找到 distributed sampling 的具体函数。
3. 确认改成 per-chapter / full scan / adaptive scan 的最小修改范围。
4. 看 glossary 存储结构。
5. 看 glossary matching/injection 的实际实现。
6. 看 translation API request 的实际 prompt 顺序。
7. 看是否支持 provider prompt caching 或 cache_control。
8. 看 checkpoint/resume。
9. 看是否可以通过配置而非 fork 修改 sampler。
10. 看 upstream 更新时哪些文件最容易产生 merge conflict。

B. translate-book
1. 找到 glossary extraction 入口。
2. 确认其 discovery 是全书扫描、sampling、chunk-based extraction，还是其他方式。
3. 找到 glossary 注入 translation prompt 的代码。
4. 判断其 prompt prefix 是否稳定。
5. 看是否存在 translation memory。
6. 看 chunk 状态/manifest/resume 的实现。
7. 看 API provider / OpenAI-compatible implementation。
8. 看 parallelization。
9. 看输出 EPUB 的方式。
10. 判断它相比 TranslateBooksWithLLMs 缺少哪些实际能力。

尤其要验证此前不能确定的事实：
- translate-book 的 glossary discovery 是否真的覆盖全文；
- epublate 的 extractor 是否全文扫描（目前不需要优先研究，除非两个本地项目都不合适）；
- translate-book 是否真的更 cache-friendly；
- 两个项目的实际 token/caching strategy。

最终希望得到的不是“哪个项目功能更多”，而是一个明确的决策：

例如：

TranslateBooksWithLLMs:
- 现成能力：X
- 缺失能力：Y
- 需要自己改：A/B
- 修改规模：小/中/大
- upstream sync 风险：低/中/高
- cache friendliness：...
- 推荐程度：...

translate-book:
- 现成能力：X
- 缺失能力：Y
- 需要自己改：A/B
- 修改规模：小/中/大
- upstream sync 风险：...
- cache friendliness：...
- 推荐程度：...

然后根据实际代码给出：
“选 TranslateBooksWithLLMs / 选 translate-book / 两者取其一部分”
而不是再根据 README 的功能列表做推测。

用户当前已经明确倾向：
- 优先考虑 TranslateBooksWithLLMs，因为 stars 显著更多；
- 不介意修改 sampler；
- 但非常在意未来同步 upstream；
- 在意 API token 成本；
- 在意 prompt cache 是否能够命中；
- 不希望重复实现 EPUB、chunking、translation、checkpoint 等成熟功能。