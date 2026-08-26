# ParaTranz + 本地脚本翻译管线计划

> 目标：把 ParaTranz 当作“更好的 Translation Tracker”使用，但不接入任何自动 workflow / 自动 PR。
>
> ParaTranz 负责：术语表、翻译记忆、网页审校、DeepSeek 机器翻译预填。
> 本地脚本负责：`REPLACE_TRANSLATIONS.gd` ↔ ParaTranz JSON 转换、`version_hash` 管理、最终提交与 PR。

---

## 1. 唯一权威文件

只处理：

```
IndustriesOfEnceladusRewriteCN/HEVLIB_EQUIPMENT_DRIVER_TAGS/REPLACE_TRANSLATIONS.gd
```

根目录的 `IndustriesOfEnceladusRewriteCN/REPLACE_TRANSLATIONS.gd` 是旧副本/易混淆文件，**不纳入 ParaTranz 流程**。

---

## 2. 本地工具目录

建议在 `/home/tessier/Terragen` 下创建：

```
/home/tessier/Terragen/
  tools/para-translation/
    gd_to_json.py       # GD → ParaTranz JSON
    json_to_gd.py       # ParaTranz JSON → GD
    glossary.md         # 术语表源文件
    metadata.json       # 由脚本生成，保存 version_hash 等结构信息
```

脚本放在主 repo，不放进 `IndustriesOfEnceladusRewriteCN` 子模块，避免污染上游 PR。

---

## 3. GD → ParaTranz JSON

`gd_to_json.py` 负责：

1. 读取权威 GD 文件；
2. 只提取 `en` 和 `zh_CN` 两个 locale；
3. 每个条目只导出纯文本：

```json
{
  "SYSTEM_CARGO_AUX_FAB": {
    "en": "SSE Voyager Fabricator",
    "zh_CN": "SSE 旅行者级建造单元"
  }
}
```

4. `version_hash`、key 名、GDScript 结构**全部保留在本地元数据中**，不上传；
5. 把 GDScript 转义解码成人类可读文本，让 ParaTranz 和 LLM 只接触纯文本，不接触 `\n`、`\\n`、`\"` 等转义符。

LLM/平台接触不到：

- `const TRANSLATIONS`
- `version_hash`
- 转义层
- key 名

---

## 4. ParaTranz 项目配置

1. **新建项目**
   - 源语言：`en`
   - 目标语言：`zh_CN`
   - 不启用 GitHub 集成 / 不配置自动同步 / 不配置自动 PR

2. **导入**
   - 上传 `gd_to_json.py` 生成的 JSON 作为源文本；
   - 如果已有 `zh_CN` 翻译，一并导入作为初始译文；
   - 之后只用“手动导入/导出”。

3. **术语表**
   将专有名词录入 ParaTranz Glossary，例如：

   | 英文 | 中文 |
   |---|---|
   | Nakamura Dynamics | 中村动力 |
   | Sin Space Engineering | 辛空间工程 |
   | Rasamama Material Solutions | 拉萨玛玛材料解决方案 |
   | Titan Heavy Industries | 泰坦重工 |
   | Rusatom-Antonoff | 俄原-安东诺夫 |
   | MPU / Mineral Processing Unit | 矿物处理单元 |
   | Remass | 推进剂/反应质量 |
   | Hardpoint | 硬点 |
   | Nanodrone | 纳米无人机 |

4. **接入 DeepSeek**
   - 在 ParaTranz 后台配置机器翻译 API；
   - 先确认平台是否支持 DeepSeek / OpenAI 兼容接口；
   - 如果只支持 OpenAI 格式，通常可填 DeepSeek 的兼容 endpoint，但以平台文档为准。

5. **关闭所有自动化**
   - 关闭 GitHub 同步；
   - 关闭自动推送；
   - 关闭任何“导出后自动提交”类设置。

---

## 5. 日常翻译/审校流程

1. 上游更新后，先拉取最新：

   ```bash
   git -C IndustriesOfEnceladusRewriteCN pull origin main
   ```

2. 重新运行 `gd_to_json.py`，生成最新源 JSON。

3. 手动上传到 ParaTranz。

4. ParaTranz 会把“英文已变”或“新增 key”标出来。

5. 对需要更新的条目：
   - 先用 DeepSeek 机器翻译预填；
   - 再人工对照术语表审校；
   - 利用 ParaTranz 的术语高亮和 QA 检查确保专有名词一致。

6. 审校完成后，从 ParaTranz 手动导出 `zh_CN` JSON。

---

## 6. ParaTranz JSON → GD

`json_to_gd.py` 负责：

1. 读取：
   - 原始权威 GD 文件；
   - ParaTranz 导出的 `zh_CN` JSON；
   - 本地 `metadata.json`。

2. 只替换 `zh_CN` 的 `string`。

3. 对新增/缺失的 key，按 `en` 补齐条目。

4. 根据确认策略更新 `version_hash`：
   - 如果该条 `zh_CN` 已针对当前英文重新审校，则把 `version_hash` 更新为当前 `en` 的 hash；
   - 如果只是旧译文未动，不要盲目把 hash 改成一致，否则 Tracker 会误判为“已同步”。

ParaTranz 本身不理解 `version_hash`，这一步必须由本地脚本管理。

---

## 7. 导出后校验

每次生成新的 GD 文件后，建议检查：

```bash
# 1. 看改动是否只涉及 zh_CN
git -C IndustriesOfEnceladusRewriteCN diff -- HEVLIB_EQUIPMENT_DRIVER_TAGS/REPLACE_TRANSLATIONS.gd

# 2. 检查 key 集合是否和 en 一致
# 用脚本校验，确保没有多 key / 少 key

# 3. 检查结构未被破坏
# 可临时用 Translation Tracker（Windows 侧）导入，确认没有解析错误
```

如果只是把 ParaTranz 当更好的 Tracker 用，最终仍建议偶尔用 Translation Tracker 做一次导入验证，但不必作为主要编辑工具。

---

## 8. 提交与 PR（全手动）

1. 在 `IndustriesOfEnceladusRewriteCN` 子模块里新建分支：

   ```bash
   git -C IndustriesOfEnceladusRewriteCN switch -c translation/zh-cn-update
   ```

2. 只提交这一个文件：

   ```bash
   git -C IndustriesOfEnceladusRewriteCN add HEVLIB_EQUIPMENT_DRIVER_TAGS/REPLACE_TRANSLATIONS.gd
   git -C IndustriesOfEnceladusRewriteCN commit -m "Update Chinese translations"
   ```

3. 推送到 fork：

   ```bash
   git -C IndustriesOfEnceladusRewriteCN push origin translation/zh-cn-update
   ```

4. 在 GitHub 网页端手动创建 PR。

PR 中不应出现：

- `tools/`
- `*.json`
- `.env`
- `.github/workflows`
- 根目录旧 `REPLACE_TRANSLATIONS.gd`

---

## 9. 后续维护节奏

| 场景 | 动作 |
|---|---|
| 上游英文更新 | `git pull` → 重新导出源 JSON → 上传 ParaTranz |
| ParaTranz 提示条目变更 | DeepSeek 预翻 → 人工审校 |
| 导出译文 | `json_to_gd.py` 合并回 GD |
| 提交上游 | 手动 commit + push + PR |
| 术语调整 | 维护 ParaTranz Glossary，并同步更新 `glossary.md` |

---

## 结论

这套方案：

- 保留 ParaTranz 最值钱的部分：术语表 + 翻译记忆 + 网页审校 + DeepSeek 预翻译；
- 去掉它最不适合的部分：自动同步、自动 workflow、自动 PR；
- 让本地脚本处理 ParaTranz 不理解的 `version_hash` 和 GDScript 结构；
- 最终对原作者呈现的，仍然只是一份干净的 `REPLACE_TRANSLATIONS.gd` 修改。
