# pdf2md_mineru

基于 [MinerU](https://github.com/opendatalab/MinerU) 的批量 PDF → Markdown 工具，适合把论文、资料批量转成 Obsidian 可用的笔记。

## 项目用途

- 扫描 `input_pdfs/`（支持子文件夹）中的所有 PDF
- 调用 MinerU CLI 逐篇转换
- 每篇 PDF 输出到独立子目录 `output_md/<文件名>/`，避免图片与附件混在一起
- 已转换过的 PDF 默认跳过；失败不中断，并写入日志与汇总报告

## 目录结构

```
pdf2md_mineru/
├── input_pdfs/          # 放入待转换 PDF
├── output_md/           # 转换结果（每篇一个子文件夹）
├── logs/
│   ├── success.log
│   └── failed.log
├── scripts/
│   ├── batch_pdf_to_md.py
│   └── check_env.py
├── conversion_report.md   # 运行后生成
├── README.md
└── requirements.txt
```

## 环境要求

- **Python 3.10 – 3.13**（MinerU 官方推荐）
- 已安装 **MinerU CLI**（`mineru` 命令可用）

### 检查当前环境

```powershell
cd pdf2md_mineru
python scripts/check_env.py
```

### 安装 MinerU（推荐 uv）

```powershell
pip install --upgrade pip
pip install uv
uv pip install -U "mineru[all]"
```

或使用 pip：

```powershell
pip install -U "mineru[all]"
```

首次使用可能需要下载模型，请保持网络畅通。国内用户可设置：

```powershell
$env:MINERU_MODEL_SOURCE = "modelscope"
```

## 如何放 PDF

将 PDF 放入 `input_pdfs/`。支持子目录，例如：

```
input_pdfs/
├── paper-a.pdf
└── books/
    └── chapter-1.pdf
```

**不会修改或删除** `input_pdfs/` 中的任何原始文件。

## 如何运行批处理

在项目根目录 `pdf2md_mineru/` 下执行：

### 安全测试（只处理 1 个 PDF）

```powershell
python scripts/batch_pdf_to_md.py --limit 1
```

### 全量批量（默认跳过已转换）

```powershell
python scripts/batch_pdf_to_md.py
```

### CPU / 轻量模式（pipeline 后端）

无 NVIDIA GPU 时，建议使用 `pipeline` 后端（脚本默认值）。显式指定：

```powershell
python scripts/batch_pdf_to_md.py --backend pipeline
```

扫描版 PDF 可加强 OCR（通过额外参数传给 mineru）：

```powershell
python scripts/batch_pdf_to_md.py --limit 1 --mineru-extra -m ocr -l ch
```

### 覆盖已有结果

```powershell
python scripts/batch_pdf_to_md.py --overwrite
```

## 使用 MinerU API 转换

如果不想在本机下载模型或占用本机 CPU/GPU，可以使用 MinerU 精准提取 API。该方式需要在 MinerU 网站获取 API Token，并会把 PDF 上传到 MinerU 云端处理。

先在当前 PowerShell 会话中设置 Token：

```powershell
$env:MINERU_API_TOKEN = "你的 MinerU API Token"
```

安全测试（只处理 1 个 PDF）：

```powershell
python scripts/batch_pdf_to_md_api.py --limit 1
```

全量批量（默认跳过已转换）：

```powershell
python scripts/batch_pdf_to_md_api.py
```

常用 API 参数：

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `--model-version` | MinerU API 模型，`pipeline` 或 `vlm` | `vlm` |
| `--language` | 文档语言，例如 `en`、`ch` | `en` |
| `--ocr` | 开启 OCR | 关闭 |
| `--batch-size N` | 每批上传文件数，最大 200 | `20` |
| `--timeout N` | 每个批次最长等待秒数 | `3600` |
| `--page-ranges` | 只处理指定页码范围 | 无 |

API 方式会生成 `conversion_report_api.md`。MinerU 返回的结果 zip 会下载并解压到 `output_md/<文件名>/`。

### 常用参数

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `--input` | 输入 PDF 目录 | `input_pdfs` |
| `--output` | 输出目录 | `output_md` |
| `--backend` | MinerU 后端 | `pipeline` |
| `--recursive` / `--no-recursive` | 是否递归子文件夹 | 递归 |
| `--overwrite` | 覆盖已有 Markdown | 否 |
| `--limit N` | 最多处理 N 个 PDF | 无限制 |
| `--mineru-extra` | 传给 `mineru` 的额外参数 | 无 |

## 输出说明

每篇 PDF 对应：

```
output_md/<pdf文件名不含扩展名>/
├── *.md              # 主 Markdown（路径见 conversion_report.md）
├── images/ 等        # MinerU 生成的资源（以实际为准）
└── ...
```

MinerU 可能在子目录中生成 `.md`（例如 `auto/`）。脚本会在输出目录下**递归查找**所有 `.md`，并在 `conversion_report.md` 中记录实际路径。

## 日志与报告

- 成功：`logs/success.log`
- 失败：`logs/failed.log`（含错误摘要）
- 汇总：`conversion_report.md`（成功 / 跳过 / 失败数量与每文件详情）

---

## 常见问题

### 1. `mineru` 命令找不到怎么办？

1. 确认已安装：`uv pip install -U "mineru[all]"` 或 `pip install -U "mineru[all]"`
2. 运行 `python scripts/check_env.py` 查看 PATH
3. Windows：若装在用户目录，把 Python Scripts 目录加入 PATH，例如  
   `%APPDATA%\Python\Python311\Scripts`
4. 新开一个终端后再试 `mineru --version`

### 2. Windows 路径有空格怎么办？

脚本使用 `pathlib` 与 `subprocess` 列表传参，**无需手动加引号**。项目路径若含空格，只要正常 `cd` 到项目目录再运行即可。

### 3. PDF 很大、转换很慢怎么办？

- 先用 `--limit 1` 单篇试跑
- 使用 `pipeline` 后端（默认）
- 可调环境变量（见 [MinerU CLI 文档](https://opendatalab.github.io/MinerU/usage/cli_tools/)），例如 `MINERU_PDF_RENDER_THREADS`
- 超大文件可考虑 MinerU 的 `-s` / `-e` 分页参数：  
  `python scripts/batch_pdf_to_md.py --mineru-extra -s 0 -e 49`

### 4. 扫描版 PDF 识别效果不好怎么办？

- 使用 OCR 模式：`--mineru-extra -m ocr`
- 指定语言：`-l ch`（中文）、`-l en`（英文）等
- 扫描质量差时，可先对 PDF 做预处理（提高 DPI、去噪）

### 5. 输出 Markdown 里图片路径怎么处理（Obsidian）？

MinerU 生成的 `.md` 通常使用**相对路径**引用同目录或子目录下的图片。推荐做法：

1. **整包放入库**：把 `output_md/<文档名>/` 整个文件夹复制或软链接到 Obsidian vault，例如 `Vault/PDF笔记/<文档名>/`
2. 在 Obsidian 中打开该文件夹下的主 `.md` 即可正常显示图片
3. 若希望「一篇 PDF 一篇笔记」，可在 vault 里只保留主 `.md`，但不要单独移动 `.md` 而丢下 `images/` 等资源目录
4. 查看 `conversion_report.md` 中记录的**实际 Markdown 路径**，在 Obsidian 中直接打开该文件

---

## 接入 Obsidian 的推荐目录组织

```
YourVault/
└── Literature/              # 或「PDF笔记」
    ├── paper-a/
    │   ├── paper-a.md       # conversion_report 里记录的实际路径
    │   └── images/
    └── books__chapter-1/    # 来自子目录 PDF 时可能带前缀
        └── ...
```

方式一：**符号链接**（省磁盘）

```powershell
mklink /D "D:\Obsidian\YourVault\Literature\paper-a" "C:\path\to\pdf2md_mineru\output_md\paper-a"
```

方式二：**复制** `output_md` 下对应子文件夹到 vault。

方式三：把 Obsidian vault 直接设在 `output_md` 的父级，用文件夹笔记浏览（适合大量批量导入）。

---

## 参考链接

- MinerU 仓库：<https://github.com/opendatalab/MinerU>
- CLI 说明：<https://opendatalab.github.io/MinerU/usage/cli_tools/>
- 输出文件说明：<https://opendatalab.github.io/MinerU/reference/output_files/>
