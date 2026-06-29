# pdf2md-mineru — Reference

Detailed flags, installation, troubleshooting, and Obsidian integration. Read this only when `SKILL.md` is not enough.

## Installation

### Local CLI backend (MinerU on this machine)

Python 3.10–3.13 required.

```bash
pip install --upgrade pip
pip install uv
uv pip install -U "mineru[all]"
# or, without uv:
pip install -U "mineru[all]"
```

First run may download models. Mainland-China users can prefer ModelScope:

```powershell
$env:MINERU_MODEL_SOURCE = "modelscope"
```

Verify with `python scripts/check_env.py` (checks Python version, `uv`, and `mineru --version`).

### Cloud API backend

Only needs `requests` (already a common dependency) and a token from the MinerU website:

```powershell
$env:MINERU_API_TOKEN = "<token>"   # current PowerShell session only
```

```bash
export MINERU_API_TOKEN="<token>"   # current shell session only
```

The API uploads PDFs to `https://mineru.net/api/v4`, polls per batch, and downloads a result zip that is extracted into `output_md/<name>/`.

## Full flag reference

### batch_pdf_to_md.py (Local CLI)

| Flag | Meaning | Default |
| --- | --- | --- |
| `--input` | Input PDF folder | `input_pdfs` |
| `--output` | Output folder | `output_md` |
| `--backend` | MinerU backend | `pipeline` |
| `--recursive` / `--no-recursive` | Recurse into subfolders | recurse |
| `--overwrite` | Re-convert even if `.md` exists | off |
| `--limit N` | Process at most N PDFs | unlimited |
| `--mineru-extra ...` | Extra args passed to `mineru` (must come last) | none |

`--mineru-extra` examples: `-m ocr -l ch` (OCR + Chinese), `-s 0 -e 49` (pages 0–49).

### batch_pdf_to_md_api.py (Cloud API)

| Flag | Meaning | Default |
| --- | --- | --- |
| `--input` | Input PDF folder | `input_pdfs` |
| `--output` | Output folder | `output_md` |
| `--token` | MinerU API token | `$MINERU_API_TOKEN` |
| `--model-version` | `pipeline` or `vlm` | `vlm` |
| `--language` | Document language, e.g. `en`, `ch` | `en` |
| `--ocr` | Enable OCR | off |
| `--no-formula` | Disable formula recognition | formula on |
| `--no-table` | Disable table recognition | table on |
| `--page-ranges` | e.g. `"1-10"` or `"2,4-6"` | none |
| `--extra-format` | Repeatable: `docx`, `html`, `latex` | none |
| `--recursive` / `--no-recursive` | Recurse into subfolders | recurse |
| `--overwrite` | Re-download even if `.md` exists | off |
| `--limit N` | Process at most N PDFs | unlimited |
| `--batch-size N` | Files per API batch (≤200) | 20 |
| `--poll-interval N` | Seconds between status checks | 10 |
| `--timeout N` | Max seconds to wait per batch | 3600 |

## Behavior notes

- **One folder per PDF**: `output_md/<stem>/`. Nested input PDFs get a `parent__child` stem so names never collide.
- **Skip logic**: a PDF is skipped if its output folder already contains any `.md` (unless `--overwrite`). This makes batches resumable.
- **Markdown discovery**: the scripts recursively search the output folder for `.md`, preferring a file whose name matches the PDF, and ignoring auxiliary files like `*_layout.md`, `*_span.md`, `*_model.md`, `*_middle.md`.
- **Failures don't stop the batch**: each error is logged to `logs/failed.log` and recorded in the report; processing continues.
- **Source safety**: input PDFs are only read, never modified or deleted.

## Troubleshooting

**`mineru` command not found** — Install (see above), re-run `python scripts/check_env.py`, ensure the Python Scripts dir is on PATH (Windows e.g. `%APPDATA%\Python\Python311\Scripts`), then open a new terminal and try `mineru --version`.

**Paths with spaces** — Handled automatically (the scripts use `pathlib` + list-form `subprocess`). Just `cd` into the project and run.

**Large / slow PDFs** — Test with `--limit 1`, use the `pipeline` backend, tune MinerU env vars (e.g. `MINERU_PDF_RENDER_THREADS`), or split pages via `--mineru-extra -s 0 -e 49`.

**Poor scan recognition** — Use OCR: local `--mineru-extra -m ocr -l ch`; cloud `--ocr --language ch`. Improve scan DPI/denoise upstream if quality is bad.

**Cloud API token missing** — Script exits with code 2 asking for the token. Set `MINERU_API_TOKEN` or pass `--token`.

**Cloud API timeouts** — Increase `--timeout`, reduce `--batch-size`, or raise `--poll-interval`.

## Obsidian integration

MinerU `.md` files reference images by **relative path** to a sibling folder. Keep the whole `output_md/<name>/` folder together.

- **Symlink** the folder into the vault (saves disk):
  ```powershell
  mklink /D "D:\Obsidian\YourVault\Literature\paper-a" "C:\path\to\output_md\paper-a"
  ```
- **Or copy** the `output_md/<name>/` folder into the vault.
- **Or** set the vault's parent at `output_md`.

Open the main `.md` recorded in the report; do not move a `.md` away from its `images/` folder.

## References

- MinerU repo: https://github.com/opendatalab/MinerU
- CLI docs: https://opendatalab.github.io/MinerU/usage/cli_tools/
- Output files: https://opendatalab.github.io/MinerU/reference/output_files/
