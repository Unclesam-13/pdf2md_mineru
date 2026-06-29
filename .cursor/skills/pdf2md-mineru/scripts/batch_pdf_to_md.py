#!/usr/bin/env python3
"""
Batch convert PDF files to Markdown using MinerU CLI.

Each PDF is written to its own subdirectory under the output folder so that
images, tables, and formulas do not collide across documents.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# Project root: pdf2md_mineru/ (parent of scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "input_pdfs"
DEFAULT_OUTPUT = PROJECT_ROOT / "output_md"
LOGS_DIR = PROJECT_ROOT / "logs"
SUCCESS_LOG = LOGS_DIR / "success.log"
FAILED_LOG = LOGS_DIR / "failed.log"
REPORT_FILE = PROJECT_ROOT / "conversion_report.md"


@dataclass
class PdfJob:
    """One PDF conversion job."""

    pdf_path: Path
    output_dir: Path
    relative_input: Path  # path under input root, for reporting


@dataclass
class JobResult:
    """Outcome of processing a single PDF."""

    job: PdfJob
    status: str  # ok | skip | fail
    message: str = ""
    markdown_paths: list[Path] = field(default_factory=list)
    returncode: int | None = None


def resolve_path(path_str: str, default: Path) -> Path:
    """Resolve CLI path; relative paths are under project root."""
    path = Path(path_str)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def find_pdfs(input_dir: Path, recursive: bool) -> list[Path]:
    """Collect PDF files from input directory."""
    if not input_dir.is_dir():
        return []

    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdfs = sorted(p for p in input_dir.glob(pattern) if p.is_file())
    # Case-insensitive .PDF on Windows
    if recursive:
        pdfs.extend(
            p
            for p in input_dir.glob("**/*.PDF")
            if p.is_file() and p not in pdfs
        )
    else:
        pdfs.extend(
            p for p in input_dir.glob("*.PDF") if p.is_file() and p not in pdfs
        )
    return sorted(set(pdfs))


def build_jobs(input_dir: Path, output_dir: Path, pdfs: Iterable[Path]) -> list[PdfJob]:
    """Map each PDF to a dedicated output subdirectory."""
    jobs: list[PdfJob] = []
    input_dir = input_dir.resolve()
    for pdf in pdfs:
        pdf = pdf.resolve()
        try:
            rel = pdf.relative_to(input_dir)
        except ValueError:
            rel = pdf.name
        # One folder per PDF stem; nested PDFs still get unique stems via parent prefix
        if isinstance(rel, Path) and len(rel.parts) > 1:
            stem_key = "__".join(rel.with_suffix("").parts)
        else:
            stem_key = pdf.stem
        out_subdir = output_dir / stem_key
        jobs.append(
            PdfJob(
                pdf_path=pdf,
                output_dir=out_subdir,
                relative_input=rel if isinstance(rel, Path) else Path(str(rel)),
            )
        )
    return jobs


def find_markdown_files(output_dir: Path, preferred_stem: str) -> list[Path]:
    """
    Search output directory for Markdown files.

    MinerU may nest results (e.g. auto/xxx.md); we search recursively and
    prefer a file whose stem matches the original PDF name.
    """
    if not output_dir.is_dir():
        return []

    all_md = sorted(output_dir.rglob("*.md"))
    if not all_md:
        return []

    preferred = [p for p in all_md if p.stem == preferred_stem]
    if preferred:
        return preferred

    # Exclude obvious debug/auxiliary names if multiple exist
    def is_main_md(path: Path) -> bool:
        name = path.stem.lower()
        skip_tokens = ("_layout", "_span", "_model", "_middle")
        return not any(token in name for token in skip_tokens)

    main_candidates = [p for p in all_md if is_main_md(p)]
    return main_candidates if main_candidates else all_md


def output_has_markdown(output_dir: Path) -> bool:
    """True if conversion output already contains at least one .md file."""
    return bool(find_markdown_files(output_dir, ""))


def ensure_logs_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def append_log(log_path: Path, line: str) -> None:
    ensure_logs_dir()
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


def run_mineru(
    pdf_path: Path,
    output_dir: Path,
    backend: str,
    extra_args: list[str],
) -> subprocess.CompletedProcess[str]:
    """Invoke MinerU CLI for a single PDF."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "mineru",
        "-p",
        str(pdf_path),
        "-o",
        str(output_dir),
        "-b",
        backend,
        *extra_args,
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def process_job(
    job: PdfJob,
    backend: str,
    overwrite: bool,
    extra_args: list[str],
) -> JobResult:
    """Convert one PDF or skip if already done."""
    preferred_stem = job.pdf_path.stem
    existing_md = find_markdown_files(job.output_dir, preferred_stem)

    if existing_md and not overwrite:
        return JobResult(
            job=job,
            status="skip",
            message="Markdown already exists",
            markdown_paths=existing_md,
        )

    try:
        completed = run_mineru(job.pdf_path, job.output_dir, backend, extra_args)
    except FileNotFoundError:
        return JobResult(
            job=job,
            status="fail",
            message=(
                "mineru command not found. Install with: "
                "pip install -U \"mineru[all]\" (or uv pip install -U \"mineru[all]\")"
            ),
            returncode=-1,
        )

    md_files = find_markdown_files(job.output_dir, preferred_stem)
    stdout_tail = (completed.stdout or "").strip()[-2000:]
    stderr_tail = (completed.stderr or "").strip()[-2000:]

    if completed.returncode != 0:
        detail = stderr_tail or stdout_tail or f"exit code {completed.returncode}"
        return JobResult(
            job=job,
            status="fail",
            message=detail,
            markdown_paths=md_files,
            returncode=completed.returncode,
        )

    if not md_files:
        return JobResult(
            job=job,
            status="fail",
            message=(
                "MinerU finished but no .md file was found under output directory. "
                f"stdout: {stdout_tail[:500]} stderr: {stderr_tail[:500]}"
            ),
            markdown_paths=[],
            returncode=completed.returncode,
        )

    return JobResult(
        job=job,
        status="ok",
        message="converted",
        markdown_paths=md_files,
        returncode=completed.returncode,
    )


def log_result(result: JobResult) -> None:
    """Append success or failure line to log files."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pdf = result.job.pdf_path
    md_info = ", ".join(str(p) for p in result.markdown_paths) if result.markdown_paths else "n/a"

    if result.status == "ok":
        append_log(SUCCESS_LOG, f"{ts}\t{pdf}\t{result.job.output_dir}\t{md_info}")
    elif result.status == "fail":
        append_log(
            FAILED_LOG,
            f"{ts}\t{pdf}\t{result.job.output_dir}\t{result.message}",
        )


def print_progress(index: int, total: int, pdf_name: str, tag: str, extra: str = "") -> None:
    if tag == "Processing":
        print(f"[{index}/{total}] Processing: {pdf_name}", flush=True)
        return
    line = f"{tag} {pdf_name}"
    if extra:
        line += f" — {extra}"
    print(line, flush=True)


def write_report(
    results: list[JobResult],
    input_dir: Path,
    output_dir: Path,
    backend: str,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    """Write conversion_report.md at project root."""
    total = len(results)
    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skip")
    failed = sum(1 for r in results if r.status == "fail")

    lines = [
        "# PDF → Markdown Conversion Report",
        "",
        f"- **Generated (UTC):** {finished_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Started (UTC):** {started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Input directory:** `{input_dir}`",
        f"- **Output directory:** `{output_dir}`",
        f"- **Backend:** `{backend}`",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Total processed | {total} |",
        f"| Success | {ok} |",
        f"| Skipped (already converted) | {skipped} |",
        f"| Failed | {failed} |",
        "",
        "## Details",
        "",
    ]

    for r in results:
        pdf = r.job.pdf_path.name
        rel = r.job.relative_input
        status_label = {"ok": "OK", "skip": "SKIP", "fail": "FAIL"}.get(r.status, r.status.upper())
        lines.append(f"### [{status_label}] `{rel}`")
        lines.append("")
        lines.append(f"- **PDF:** `{r.job.pdf_path}`")
        lines.append(f"- **Output folder:** `{r.job.output_dir}`")
        if r.markdown_paths:
            lines.append("- **Markdown file(s):**")
            for md in r.markdown_paths:
                lines.append(f"  - `{md}`")
        else:
            lines.append("- **Markdown file(s):** _none found_")
        if r.message and r.status != "ok":
            lines.append(f"- **Note:** {r.message[:500]}")
        lines.append("")

    lines.extend(
        [
            "## Logs",
            "",
            f"- Success log: `{SUCCESS_LOG}`",
            f"- Failed log: `{FAILED_LOG}`",
            "",
        ]
    )

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch convert PDFs to Markdown using MinerU CLI.",
    )
    parser.add_argument(
        "--input",
        default="input_pdfs",
        help="Input folder containing PDF files (default: input_pdfs)",
    )
    parser.add_argument(
        "--output",
        default="output_md",
        help="Output folder for Markdown and assets (default: output_md)",
    )
    parser.add_argument(
        "--backend",
        default="pipeline",
        help="MinerU backend (default: pipeline)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-convert even if output folder already contains .md files",
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Recursively scan subfolders for PDFs (default: True)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N PDFs (use --limit 1 for a safe first test)",
    )
    parser.add_argument(
        "--mineru-extra",
        nargs=argparse.REMAINDER,
        default=[],
        help="Extra arguments passed to mineru after -b (e.g. -m ocr -l ch)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_dir = resolve_path(args.input, DEFAULT_INPUT)
    output_dir = resolve_path(args.output, DEFAULT_OUTPUT)
    ensure_logs_dir()

    pdfs = find_pdfs(input_dir, args.recursive)
    if not pdfs:
        print(
            f"No PDF files found in '{input_dir}'.\n"
            "Place your .pdf files in the input_pdfs folder (subfolders are supported "
            "when --recursive is enabled), then run this script again.",
            file=sys.stderr,
        )
        return 0

    if args.limit is not None and args.limit > 0:
        pdfs = pdfs[: args.limit]

    jobs = build_jobs(input_dir, output_dir, pdfs)
    total = len(jobs)
    started_at = datetime.now(timezone.utc)
    results: list[JobResult] = []

    print(f"Found {total} PDF(s). Output: {output_dir}")
    print(f"Backend: {args.backend}")
    if args.mineru_extra:
        print(f"Extra mineru args: {args.mineru_extra}")
    print("")

    for idx, job in enumerate(jobs, start=1):
        print_progress(idx, total, job.pdf_path.name, "Processing")
        result = process_job(
            job,
            backend=args.backend,
            overwrite=args.overwrite,
            extra_args=args.mineru_extra,
        )
        results.append(result)
        log_result(result)

        if result.status == "ok":
            print_progress(idx, total, job.pdf_path.name, "[OK]")
        elif result.status == "skip":
            print_progress(idx, total, job.pdf_path.name, "[SKIP]", result.message)
        else:
            print_progress(idx, total, job.pdf_path.name, "[FAIL]", result.message[:200])

    finished_at = datetime.now(timezone.utc)
    write_report(results, input_dir, output_dir, args.backend, started_at, finished_at)

    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skip")
    failed = sum(1 for r in results if r.status == "fail")
    print("")
    print(f"Done. OK={ok} SKIP={skipped} FAIL={failed}")
    print(f"Report: {REPORT_FILE}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
