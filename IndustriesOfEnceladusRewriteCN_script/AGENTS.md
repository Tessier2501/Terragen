# AGENTS.md

## 项目目标

将权威翻译源 `../IndustriesOfEnceladusRewriteCN/HEVLIB_EQUIPMENT_DRIVER_TAGS/REPLACE_TRANSLATIONS.gd` 与 ParaTranz 的 en → zh_CN 项目保持同步。本目录负责解析、导出、合并和本地基线维护。

## 代码结构

- `gd_format.py`：解析和渲染 GDScript 翻译字典，并提供 metadata 与文件工具。
- `gd_to_json.py`：把权威 GD 文件导出为 ParaTranz JSON，同时生成变更报告并推进本地基线。
- `json_to_gd.py`：把 ParaTranz 原始导出合并回权威 GD 文件。

## 文件布局

脚本的输入输出文件统一放在项目根目录：

- `metadata.json`：源文件哈希和逐 key 同步状态。
- `paratranz_source.json`：当前全量 key 与英文原文，用于 ParaTranz Create/Update File。
- `paratranz_initial_translation.json`：首次导入用的译文快照。
- `paratranz_changes.json`：最近一次导出的变更报告。
- `paratranz_export.json`：ParaTranz 原始导出，供合并使用。
- `archive/<source_sha256>/`：历史基线与导出归档。

## 日常流程

1. 更新子模块源码：

   ```bash
   git -C ../IndustriesOfEnceladusRewriteCN pull --ff-only
   git -C ../IndustriesOfEnceladusRewriteCN status --short
   ```

2. 预览导出差异：

   ```bash
   python3 gd_to_json.py --check
   ```

3. 生成根目录下的源文件、变更报告和 metadata：

   ```bash
   python3 gd_to_json.py
   ```

4. 在 ParaTranz 上传 `paratranz_source.json`，处理 `added` 和 `changed` 条目，把完成审校的条目推进到 stage 5，并清理 `removed` 清单中的 key。

5. 从 ParaTranz 导出原始数据，保存为根目录下的 `paratranz_export.json`。

6. 预览合并计划：

   ```bash
   python3 json_to_gd.py
   ```

7. 执行写回：

   ```bash
   python3 json_to_gd.py --write
   ```

8. 检查改动：

   ```bash
   git -C ../IndustriesOfEnceladusRewriteCN diff -- HEVLIB_EQUIPMENT_DRIVER_TAGS/REPLACE_TRANSLATIONS.gd
   ```

## 合并规则

- ParaTranz 中 `stage >= 5` 的条目会写入 `zh_CN` 并更新 `version_hash`。
- 原文变化的条目从 stage 0 开始新一轮翻译和审校，最终推进到 stage 5。
- 原文变化且译文保持原字符串时，人工确认后使用 `--accept-unchanged KEY`。
- ParaTranz 导出包含历史 key 时，使用 `--strict-key-set` 将这些 key 视为错误。
- 合并操作以 `zh_CN` 块为目标，并同步更新 `metadata.json`。
