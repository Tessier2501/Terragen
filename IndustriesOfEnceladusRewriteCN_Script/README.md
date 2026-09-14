# IndustriesOfEnceladusRewriteCN 翻译管线

把 `REPLACE_TRANSLATIONS.gd` 与 ParaTranz 平台之间做双向转换的本地工具。

权威源文件只有一个：

```
../IndustriesOfEnceladusRewriteCN/HEVLIB_EQUIPMENT_DRIVER_TAGS/REPLACE_TRANSLATIONS.gd
```

脚本不处理子模块根目录下可能出现的旧副本。

## 目录与状态文件

| 文件 | 作用 | 是否提交 |
|---|---|---|
| `gd_format.py` | GDScript 翻译字典的解析/渲染、路径定位 | 是 |
| `gd_to_json.py` | GD → ParaTranz JSON | 是 |
| `json_to_gd.py` | ParaTranz JSON → GD | 是 |
| `metadata.json` | 上一次成功导出/合并的本地基线：源文件 SHA、每个 key 的 en/zh `version_hash` | 否（本地保留，勿删） |
| `out/paratranz_source.json` | **当前全量** key + 最新英文原文，用于 ParaTranz Create/Update File | 否 |
| `out/paratranz_changes.json` | 本次变更报告：`added` / `changed` / `removed` / `untranslated` / `stale` | 否 |
| `out/paratranz_initial_translation.json` | 首次建项目用的初始译文快照 | 否 |
| `out/paratranz_export.json` | 从 ParaTranz 导出的原始数据，供 `json_to_gd.py` 合并 | 否 |
| `out/archive/<source_sha256>/` | 自动归档的旧 metadata / 旧导出，防止基线丢失 | 否 |

`paratranz_source.json` 永远是当前全量快照，不是只含 diff。ParaTranz 通过它更新已有 key 的原文；已被删除的 key 会从快照中消失，`removed` 清单只在本地报告中列出。

## Stage 语义（重要）

ParaTranz 的 stage 是平台工作流状态，最终 checked 状态为 5。本地脚本不修改平台 stage，只读取导出 JSON 中的 stage：

- `stage >= --review-stage`（默认 5）的条目才会被 `json_to_gd.py` 视为可写回：写入译文并更新 `version_hash`。
- `stage < 5` 的 changed 条目会保留旧中文和旧 hash，并出现在 `still out-of-sync after this plan` 中，等后续继续处理。
- 源文更新后，ParaTranz 如果把 changed 键重置为 0，就按正常“翻译 → 审校 → 5”走；added 键天然是 0。
- 如果 ParaTranz 更新 source 后没有自动重置 changed 键，请手动把 changed 项重置到 0 再开始翻译。否则它们会停留在旧的 stage 5，而旧译文会被本地 `stale_reviewed` 保护拦下，不能写回（除非人工确认后使用 `--accept-unchanged`）。
- 对“只需更新 hash、译文确实无需改动”的特殊条目，人工审阅确认后才用 `--accept-unchanged KEY` 放行，允许旧的译文字符串配合新的 en hash 写回。

## 首次建项目

```bash
cd IndustriesOfEnceladusRewriteCN_Script

# 只计算，不写任何文件
python3 gd_to_json.py --check

# 生成导入文件
python3 gd_to_json.py
```

此时生成 `out/paratranz_source.json` 和带现有译文的 `out/paratranz_initial_translation.json`。在 ParaTranz 新建 en → zh_CN 项目后：

1. 用 Create File 上传 `paratranz_source.json`。
2. 用 Import Translation 导入 `paratranz_initial_translation.json`。

首次之后**不要再导 initial 文件**。

## 源文更新后的日常流程

1. 更新子模块并确认干净：

   ```bash
   git -C ../IndustriesOfEnceladusRewriteCN pull --ff-only
   git -C ../IndustriesOfEnceladusRewriteCN status --short
   ```

2. 先只读预览本次差异：

   ```bash
   python3 gd_to_json.py --check
   ```

   重点看 `added`、`changed`、`removed`、`untranslated`、`stale` 五类。

3. 正式生成 ParaTranz 更新文件：

   ```bash
   python3 gd_to_json.py
   ```

   会写 `out/`、推进 `metadata.json`，并把旧基线归档到 `out/archive/<old_sha>/`。

4. 在 ParaTranz 中：
   - 用 `out/paratranz_source.json` 执行 Create/Update File；
   - 处理 `added`、`changed`；
   - **changed 键应重置到 stage 0（未翻译）后重新翻译/审校，并最终走完流程到达 stage 5（checked/完成）**；added 键本来就是 stage 0；
   - 不要手工把仍带旧译文的条目直接点成 5。本地脚本只合并 `stage >= 5` 的条目，5 是“已 checked”的合并门槛，不是跳过流程的快捷键；
   - 确认 `removed` 键已从项目删除或废弃；
   - 完成后导出原始数据，保存为 `out/paratranz_export.json`。

5. 先做 dry run，不写 GD：

   ```bash
   python3 json_to_gd.py
   ```

   如果输出里有：

   ```
   reviewed entries identical to the current GD translation ...
   ```

   说明这些 changed 键虽然 stage 达标，但译文字符串与当前 GD 旧译文完全相同，脚本默认不会把它们错误标成已同步。

   - 如果确实应该保持同一译文，人工确认后把该 key 传给 `--accept-unchanged`；
   - 否则请回到 ParaTranz 更新译文后重新导出。

6. 实际写回：

   ```bash
   python3 json_to_gd.py --write
   # 如需显式确认个别保持不变：
   # python3 json_to_gd.py --write --accept-unchanged KEY1 --accept-unchanged KEY2
   ```

   写回时脚本会重建整个 `zh_CN` 块：

   - 已审校条目：写入新译文，`version_hash` 更新为当前 en hash；
   - 未审校的 changed 条目：保留旧译文和旧 hash，仍列在 `still out-of-sync after this plan`；
   - 新增且未翻译的 key：写入英文占位 + `version_hash = 0`；
   - 当前 en 已不存在的 key：从 `zh_CN` 删除。

7. 检查 diff 与测试：

   ```bash
   git -C ../IndustriesOfEnceladusRewriteCN diff -- \
     HEVLIB_EQUIPMENT_DRIVER_TAGS/REPLACE_TRANSLATIONS.gd

   python3 -m unittest discover -s tests -v
   ```

   确认改动只在 `zh_CN`，然后直接提交个人 fork；这是个人仓库，不需要 PR 流程。

## 参数说明

- `--check` / `gd_to_json.py`：只计算和打印，不写文件；用于正式运行前预览。
- `--emit-initial`：更新模式下额外生成初始快照；changed/added 条目会写成空译文，避免旧译文被误导入。
- `--review-stage N`：本地合并门槛；只有 `stage >= N` 的条目才会写回并更新 hash。默认 5，即 ParaTranz 的 checked/完成状态；不是用来手工跳级的。
- `--accept-unchanged KEY`：允许原文已变、但译文确实可以保持字符串不变的 key 更新 hash；可重复。
- `--strict-key-set`：ParaTranz 导出中含当前 en 之外的旧 key 时直接报错；默认只警告并忽略这些旧 key。
- `--gd/--out-dir/--metadata/--export`：覆盖默认路径；默认路径对当前布局和旧布局都能自动定位。

## 故障排查

- `metadata source hash does not match current GD file`：源文在上次导出后又被修改过。先跑一次 `gd_to_json.py` 重建基线。
- `ParaTranz export is missing current en keys`：ParaTranz 项目还没有同步最新 `paratranz_source.json`，或导出不完整。重新上传 source 后再导出。
- `ParaTranz original does not match current en text`：导出文件是旧的（或上传的 source 不是最新）。重新上传 `out/paratranz_source.json` 并重新导出。
- `reviewed entries ... identical to the current GD translation`：不要直接加 `--accept-unchanged` 图省事；先人工确认该译文确实适用于新英文。
- 误跑第二次 `gd_to_json.py` 导致 changes 清空：从 `out/archive/<old_sha>/metadata.json` 恢复基线，或查看归档旧 source。
- 默认 `--gd` 找不到：显式传 `--gd /path/to/REPLACE_TRANSLATIONS.gd`；正常当前目录布局下无需传。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试使用临时目录和临时 GD 文件，不会碰真实 `metadata.json`、`out/` 或子模块。
