---
name: pdf2md-mineru
description: Batch-convert PDF files to Obsidian-ready Markdown using MinerU, either locally (CLI) or via the MinerU cloud API. Use when the user wants to turn PDFs (papers, books, scans) into Markdown, mentions MinerU, pdf2md, batch PDF conversion, or extracting text/tables/formulas/images from PDFs.
---

# pdf2md-mineru

Batch convert every PDF in an input folder into Markdown (plus images, tables, formulas), one output subfolder per PDF, with skip-on-existing, per-file logging, and a summary report. Two interchangeable backends:

- **Local CLI** (`batch_pdf_to_md.py`) — runs MinerU on this machine. No upload, no token. Needs the `mineru` command and (for speed) models/GPU.
- **Cloud API** (`batch_pdf_to_md_api.py`) — uploads PDFs to MinerU cloud, polls, downloads result zips. No local models, but needs a `MINERU_API_TOKEN` and sends files to the cloud.

The scripts in `scripts/` are self-contained and bundled with this skill. Run them with `python`. They never modify or delete source PDFs.

## Choose the backend

1. **Has `mineru` installed locally / wants files to stay on-device** → Local CLI.
2. **No local models, fine with cloud upload, has an API token** → Cloud API.

If unsure, ask the user. Default to **Local CLI** when `mineru` is on PATH, otherwise suggest Cloud API.

## Workflow

Copy this checklist and track progress:

```
- [ ] Step 1: Confirm backend (local CLI vs cloud API)
- [ ] Step 2: Check environment / token
- [ ] Step 3: Confirm PDFs are in the input folder
- [ ] Step 4: Safe test on 1 PDF (--limit 1)
- [ ] Step 5: Run full batch
- [ ] Step 6: Review report + logs, report results to user
```

### Step 2 — Check environment

Local CLI: verify Python 3.10–3.13 and the `mineru` command.

```bash
python scripts/check_env.py
```

Cloud API: ensure `requests` is installed and the token is set (current shell session only):

```powershell
$env:MINERU_API_TOKEN = "<the user's MinerU API token>"
```

```bash
# macOS/Linux
export MINERU_API_TOKEN="<the user's MinerU API token>"
```

Never hard-code or commit the token. If it is missing, ask the user for it.

### Step 3 — Input PDFs

PDFs go in `input_pdfs/` (subfolders supported, scanned recursively). A nested PDF `books/ch1.pdf` produces an output folder `books__ch1/`. Confirm at least one `.pdf` exists before running.

### Step 4 — Safe test first (always)

Run on a single PDF before committing to a full batch, so failures surface cheaply:

```bash
# Local CLI
python scripts/batch_pdf_to_md.py --limit 1

# Cloud API
python scripts/batch_pdf_to_md_api.py --limit 1
```

Confirm the test produced a `.md` (path is listed in the report) before continuing.

### Step 5 — Full batch

Already-converted PDFs are skipped by default (resumable). Use `--overwrite` to redo.

```bash
# Local CLI (pipeline backend is default; best for CPU / no GPU)
python scripts/batch_pdf_to_md.py

# Cloud API (vlm model is default)
python scripts/batch_pdf_to_md_api.py
```

### Step 6 — Review results

- Per-PDF detail + summary table:
  - Local: `conversion_report.md`
  - Cloud API: `conversion_report_api.md`
- Logs: `logs/success.log`, `logs/failed.log`
- Output: `output_md/<pdf-name>/` containing the main `.md` and asset folders (e.g. `images/`). MinerU may nest the `.md` (e.g. under `auto/`); the report records the actual path.

Exit code is non-zero if any file failed. Summarize OK / SKIP / FAIL counts to the user and surface failure notes from the report.

## Common options

Both scripts share: `--input`, `--output`, `--limit N`, `--overwrite`, `--recursive/--no-recursive`.

Local CLI extras:
- `--backend pipeline` (default; CPU-friendly) or another MinerU backend.
- `--mineru-extra ...` — pass-through to `mineru`, e.g. scanned docs: `--mineru-extra -m ocr -l ch`; page range: `--mineru-extra -s 0 -e 49`.

Cloud API extras:
- `--model-version vlm|pipeline` (default `vlm`), `--language en|ch|...`, `--ocr`,
  `--no-formula`, `--no-table`, `--page-ranges "1-10"`, `--extra-format docx|html|latex`,
  `--batch-size N` (≤200), `--timeout N`, `--poll-interval N`, `--token`.

For the full flag reference, troubleshooting, and Obsidian integration, see [reference.md](reference.md).

## Quick recipes

- Scanned Chinese PDF (local): `python scripts/batch_pdf_to_md.py --mineru-extra -m ocr -l ch`
- English papers via cloud with OCR: `python scripts/batch_pdf_to_md_api.py --language en --ocr`
- Re-convert everything: add `--overwrite`.
- First time / smoke test: always add `--limit 1`.
