# Final Assembly 定稿装配 CLI · v0.2.2

Assemble approved blocks without rewriting. Verify the actual files before delivery.

把你已选定的正文、表格和结尾装成 Markdown 与 Word 文档。程序重新读取实际文件，核对顺序、文字、格式、链接和每个表格单元格。离线运行，不需要模型或服务。

## 安装与使用

需要 Python 3.11+。在你选择的磁盘创建虚拟环境，安装本目录：

```text
python -m venv /your-disk/assembly-env
/your-disk/assembly-env/bin/python -m pip install /path/to/final-assembly
```

Windows 使用 `assembly-env/Scripts/python.exe`，命令入口在 `assembly-env/Scripts/final-assembly.exe`。安装、临时目录及 pip 缓存可通过 Python/pip 的环境变量选择磁盘；工具的装配暂存文件直接创建在你指定的输出父目录。

```text
final-assembly --workspace /your/materials preview manifest.json
final-assembly --workspace /your/materials build manifest.json --out-dir delivery-v1
final-assembly --workspace /your/materials verify delivery-v1/manifest.snapshot.json --file delivery-v1/final.docx
```

`--workspace` 是材料与输出的边界，默认当前目录；所有相对 CLI 路径以它为基准。源文件路径相对 manifest。安装目录可在别处。路径含空格时使用引号。拒绝越界路径及 symlink/junction。源码运行可用 `python -B -m final_assembly`；PowerShell 辅助入口为 `scripts/run.ps1`，不会切换你的当前目录。

首次体验：在项目目录执行 `python -m final_assembly build examples/common-markdown/manifest.json --out-dir exports/first-run`。示例是明确标注的离线批准材料。想看失败与恢复，执行 `python scripts/demo.py`。

## 交付内容

每次 `build` 使用新的输出目录，已有交付不会被覆盖：

- `final.md`：包含每个批准块的原始字节。
- `final.docx`：排好基础版式的文档。
- `manifest.snapshot.json` 与 `sources/`：当前及历史源文快照，整个交付目录移走后仍能复验。
- `reconciliation.json`：实际文件的哈希、逐块/逐格/链接检查，以及失败位置。

两份文件都实际回读通过后，交付目录才出现。退出码 `0` 通过，`2` 输入或环境错误，`3` 文件对账失败。`verify --report new-report.json` 可另存本次核验。没有任何模型充当保真裁判。

## 怎样记录批准

完整例子：[manifest](examples/approved/manifest.json)。每块记录 `id`、章节 `section`、顺序 `order`、`source.path`、`source.origin`、`approved` 和原文 UTF-8 字节的 `sha256`。新版本用 `replaces` 指向旧块 ID；旧源文保留并继续检查。

用户明确选用该内容即为批准，不需要重复确认。哈希证明字节一致，不是身份签名。漂移时恢复批准版或记录新的批准版本，不要自动重算旧哈希来消除错误。未批准块、丢失来源、重复有效顺序、替换冲突和循环均报错。

## Markdown 支持

使用 CommonMark 解析，支持：

- ATX/Setext 标题、段落、软换行和显式换行。
- **粗体**、斜体、删除线、行内代码，可嵌套并组合在链接文字内。
- 单层列表，每项一段；编号按 CommonMark 渲染规则从原起始值连续递增，包含从 `0.` 开始的列表。
- 单层引用、围栏/缩进代码块；代码文本保留，语言提示不生成语法高亮。
- 矩形 pipe 表格，左/中/右对齐、转义竖线、空单元格。
- 绝对 HTTP(S)/mailto 链接；普通金额、下划线、转义、实体字符。

Markdown 原始字节始终保留。DOCX 比较的是标准解析后的内容：例如软换行变为空格、`&amp;` 变为 `&`，列表 `1. / 1.` 渲染为 `1. / 2.`。表格缺列或多列会报错，不允许解析器静默补齐或丢弃。

当前不支持嵌套列表/引用、交互任务列表、图片、HTML、分隔线、公式渲染或合并单元格；会明确报错或按 CommonMark 普通文字语义处理未启用的扩展符号。相对/锚点链接、链接标题属性拒绝导出，避免搬移后失效或遗漏含义。源文件为 UTF-8 无 BOM。

DOCX 使用独立 ZIP/OOXML reader 读取保存后的文本、结构、粗斜体/删除线/代码样式、列对齐及超链接关系。它验证本工具导出的格式，不承诺导入任意 Word 文档；经过 Word 再保存产生的新结构可能返回不支持。

**内容通过不等于排版通过。** 每一份交付的 `visual_layout_checked` 默认 `false`；只能对实际渲染且逐页检查过的具体文件另行记录视觉证据。需要视觉验收时，请渲染实际交付文件并逐页检查；源码中的合成测试不证明任意文稿都已经通过排版验收。

## Skill 与引用包

运行 `python scripts/package.py` 会在 `dist/0.2.2` 生成源码包和独立 Skill 包。压缩包只包含运行代码、用法、测试与示例；不包含开发 prompt、缓存、输出、个人路径或本机环境脚本。Skill 包自带 runner 和 CLI 源码，解压后安装其 `requirements.txt`，再放到你的 Agent 支持的 Skill 目录即可。此仓库不会自动安装或修改全局配置。

[Skill](skills/final-assembly/SKILL.md) 保留批准决策、替换历史和错误恢复规则。runner 相对自身定位，不依赖安装机器上的固定目录。发布包可以放在与用户材料完全不同的目录。

`import-pack PACK --out-dir imported` 可读取示例 [ContextPack](examples/reference-pack.json)，逐条保留 `exactText` 与来源；输出清单全部未批准。该文件导入协议不表示已连接宿主聊天记录。

## 开发验证

```text
python scripts/validate.py
python scripts/package.py --out-dir dist/my-build
```

项目不需要模型；没有为确定性装配增加 API/CLI 模型调用。支持范围与限制以实际测试和运行输出为准。

许可证为 MIT；第三方依赖单独安装并保留各自许可证。
