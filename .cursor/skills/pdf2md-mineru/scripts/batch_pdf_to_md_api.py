#!/usr/bin/env python3
"""
Batch convert PDF files to Markdown using MinerU Precision Extract API.

This script uploads local PDFs through MinerU's signed upload API, polls for
results, downloads the result zip, and extracts each PDF into its own output
folder.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests


# Force UTF-8 on Windows consoles so non-ASCII file names (e.g. umlauts,
# Chinese characters) do not crash print() with the legacy GBK codec.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "input_pdfs"
DEFAULT_OUTPUT = PROJECT_ROOT / "output_md"
LOGS_DIR = PROJECT_ROOT / "logs"
SUCCESS_LOG = LOGS_DIR / "success.log"
FAILED_LOG = LOGS_DIR / "failed.log"
REPORT_FILE = PROJECT_ROOT / "conversion_report_api.md"

API_BASE = "https://mineru.net/api/v4"
MAX_BATCH_SIZE = 200


@dataclass
class PdfJob:
    pdf_path: Path
    output_dir: Path
    relative_input: Path
    data_id: str


@dataclass
class JobResult:
    job: PdfJob
    status: str  # ok | skip | fail
    message: str = ""
    markdown_paths: list[Path] = field(default_factory=list)
    full_zip_url: str = ""


def resolve_path(path_str: str, default: Path) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def find_pdfs(input_dir: Path, recursive: bool) -> list[Path]:
    if not input_dir.is_dir():
        return []

    pattern = "**/*" if recursive else "*"
    return sorted(
        p
        for p in input_dir.glob(pattern)
        if p.is_file() and p.suffix.lower() == ".pdf"
    )


def stem_key_for_pdf(input_dir: Path, pdf: Path) -> tuple[str, Path]:
    try:
        rel = pdf.resolve().relative_to(input_dir.resolve())
    except ValueError:
        rel = Path(pdf.name)

    if len(rel.parts) > 1:
        stem_key = "__".join(rel.with_suffix("").parts)
    else:
        stem_key = pdf.stem
    return stem_key, rel


def make_data_id(index: int, rel: Path) -> str:
    digest = hashlib.sha1(str(rel).encode("utf-8")).hexdigest()[:12]
    return f"pdf2md_{index}_{digest}"


def build_jobs(input_dir: Path, output_dir: Path, pdfs: Iterable[Path]) -> list[PdfJob]:
    jobs: list[PdfJob] = []
    for index, pdf in enumerate(pdfs, start=1):
        stem_key, rel = stem_key_for_pdf(input_dir, pdf)
        jobs.append(
            PdfJob(
                pdf_path=pdf.resolve(),
                output_dir=output_dir / stem_key,
                relative_input=rel,
                data_id=make_data_id(index, rel),
            )
        )
    return jobs


def find_markdown_files(output_dir: Path, preferred_stem: str) -> list[Path]:
    if not output_dir.is_dir():
        return []

    all_md = sorted(output_dir.rglob("*.md"))
    if not all_md:
        return []

    preferred = [p for p in all_md if p.stem == preferred_stem]
    if preferred:
        return preferred

    def is_main_md(path: Path) -> bool:
        name = path.stem.lower()
        skip_tokens = ("_layout", "_span", "_model", "_middle")
        return not any(token in name for token in skip_tokens)

    main_candidates = [p for p in all_md if is_main_md(p)]
    return main_candidates if main_candidates else all_md


def ensure_logs_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def append_log(log_path: Path, line: str) -> None:
    ensure_logs_dir()
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


def api_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def validate_api_response(payload: dict, action: str) -> dict:
    if payload.get("code") != 0:
        raise RuntimeError(f"{action} failed: {payload.get('msg', payload)}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"{action} returned invalid data: {payload}")
    return data


def create_upload_batch(
    token: str,
    jobs: list[PdfJob],
    model_version: str,
    language: str,
    enable_formula: bool,
    enable_table: bool,
    is_ocr: bool,
    page_ranges: str | None,
    extra_formats: list[str],
) -> tuple[str, list[str]]:
    files = []
    for job in jobs:
        item: dict[str, object] = {
            "name": job.pdf_path.name,
            "data_id": job.data_id,
            "is_ocr": is_ocr,
            "language": language,
        }
        if page_ranges:
            item["page_ranges"] = page_ranges
        files.append(item)

    body: dict[str, object] = {
        "files": files,
        "model_version": model_version,
        "language": language,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
    }
    if extra_formats:
        body["extra_formats"] = extra_formats

    response = requests.post(
        f"{API_BASE}/file-urls/batch",
        headers=api_headers(token),
        json=body,
        timeout=60,
    )
    response.raise_for_status()
    data = validate_api_response(response.json(), "create upload batch")
    batch_id = data.get("batch_id")
    file_urls = data.get("file_urls")
    if not isinstance(batch_id, str) or not isinstance(file_urls, list):
        raise RuntimeError(f"create upload batch returned invalid data: {data}")
    if len(file_urls) != len(jobs):
        raise RuntimeError(
            f"expected {len(jobs)} upload URLs, got {len(file_urls)}"
        )
    return batch_id, [str(url) for url in file_urls]


def upload_files(jobs: list[PdfJob], file_urls: list[str]) -> None:
    for job, file_url in zip(jobs, file_urls, strict=True):
        print(f"Uploading: {job.relative_input}", flush=True)
        with job.pdf_path.open("rb") as fh:
            response = requests.put(file_url, data=fh, timeout=300)
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"upload failed for {job.relative_input}: HTTP {response.status_code}"
            )


def poll_batch(
    token: str,
    batch_id: str,
    timeout_seconds: int,
    poll_interval: int,
) -> list[dict]:
    deadline = time.time() + timeout_seconds
    last_state_summary = ""

    while True:
        response = requests.get(
            f"{API_BASE}/extract-results/batch/{batch_id}",
            headers=api_headers(token),
            timeout=60,
        )
        response.raise_for_status()
        data = validate_api_response(response.json(), "query batch result")
        extract_result = data.get("extract_result")
        if not isinstance(extract_result, list):
            raise RuntimeError(f"query batch result returned invalid data: {data}")

        states: dict[str, int] = {}
        for item in extract_result:
            state = str(item.get("state", "unknown"))
            states[state] = states.get(state, 0) + 1

        state_summary = ", ".join(f"{state}={count}" for state, count in sorted(states.items()))
        if state_summary != last_state_summary:
            print(f"Batch {batch_id}: {state_summary}", flush=True)
            last_state_summary = state_summary

        unfinished = [
            item
            for item in extract_result
            if item.get("state") not in ("done", "failed")
        ]
        if not unfinished:
            return extract_result

        if time.time() >= deadline:
            raise TimeoutError(f"timed out waiting for batch {batch_id}")
        time.sleep(poll_interval)


def download_and_extract_zip(url: str, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "mineru_result.zip"

    with requests.get(url, stream=True, timeout=300) as response:
        response.raise_for_status()
        with zip_path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)

    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(output_dir)

    return sorted(output_dir.rglob("*.md"))


def result_item_key(item: dict) -> str:
    data_id = item.get("data_id")
    if isinstance(data_id, str) and data_id:
        return data_id
    file_name = item.get("file_name")
    return str(file_name or "")


def apply_batch_results(jobs: list[PdfJob], api_results: list[dict]) -> list[JobResult]:
    by_key = {result_item_key(item): item for item in api_results}
    results: list[JobResult] = []

    for job in jobs:
        item = by_key.get(job.data_id) or by_key.get(job.pdf_path.name)
        if not item:
            results.append(JobResult(job=job, status="fail", message="missing API result"))
            continue

        state = item.get("state")
        if state != "done":
            message = str(item.get("err_msg") or f"state={state}")
            results.append(JobResult(job=job, status="fail", message=message))
            continue

        full_zip_url = str(item.get("full_zip_url") or "")
        if not full_zip_url:
            results.append(JobResult(job=job, status="fail", message="missing full_zip_url"))
            continue

        try:
            md_paths = download_and_extract_zip(full_zip_url, job.output_dir)
        except Exception as exc:  # noqa: BLE001 - report per-file API failures and continue
            results.append(JobResult(job=job, status="fail", message=str(exc)))
            continue

        if not md_paths:
            results.append(
                JobResult(
                    job=job,
                    status="fail",
                    message="downloaded result zip but no .md file was found",
                    full_zip_url=full_zip_url,
                )
            )
            continue

        preferred = find_markdown_files(job.output_dir, job.pdf_path.stem)
        results.append(
            JobResult(
                job=job,
                status="ok",
                message="converted via MinerU API",
                markdown_paths=preferred,
                full_zip_url=full_zip_url,
            )
        )

    return results


def log_result(result: JobResult) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md_info = ", ".join(str(p) for p in result.markdown_paths) if result.markdown_paths else "n/a"

    if result.status == "ok":
        append_log(
            SUCCESS_LOG,
            f"{ts}\tAPI\t{result.job.pdf_path}\t{result.job.output_dir}\t{md_info}",
        )
    elif result.status == "fail":
        append_log(
            FAILED_LOG,
            f"{ts}\tAPI\t{result.job.pdf_path}\t{result.job.output_dir}\t{result.message}",
        )


def write_report(
    results: list[JobResult],
    input_dir: Path,
    output_dir: Path,
    model_version: str,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    total = len(results)
    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skip")
    failed = sum(1 for r in results if r.status == "fail")

    lines = [
        "# PDF -> Markdown API Conversion Report",
        "",
        f"- **Generated (UTC):** {finished_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Started (UTC):** {started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Input directory:** `{input_dir}`",
        f"- **Output directory:** `{output_dir}`",
        f"- **MinerU API model:** `{model_version}`",
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

    for result in results:
        status_label = {"ok": "OK", "skip": "SKIP", "fail": "FAIL"}.get(
            result.status,
            result.status.upper(),
        )
        lines.append(f"### [{status_label}] `{result.job.relative_input}`")
        lines.append("")
        lines.append(f"- **PDF:** `{result.job.pdf_path}`")
        lines.append(f"- **Output folder:** `{result.job.output_dir}`")
        if result.full_zip_url:
            lines.append(f"- **Result zip URL:** `{result.full_zip_url}`")
        if result.markdown_paths:
            lines.append("- **Markdown file(s):**")
            for md in result.markdown_paths:
                lines.append(f"  - `{md}`")
        else:
            lines.append("- **Markdown file(s):** _none found_")
        if result.message and result.status != "ok":
            lines.append(f"- **Note:** {result.message[:500]}")
        lines.append("")

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")


def chunked(items: list[PdfJob], size: int) -> Iterable[list[PdfJob]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch convert PDFs to Markdown using MinerU Precision Extract API.",
    )
    parser.add_argument("--input", default="input_pdfs", help="Input PDF folder")
    parser.add_argument("--output", default="output_md", help="Output folder")
    parser.add_argument("--token", default=os.getenv("MINERU_API_TOKEN"), help="MinerU API token")
    parser.add_argument("--model-version", default="vlm", choices=("pipeline", "vlm"))
    parser.add_argument("--language", default="en", help="MinerU language value, e.g. en or ch")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR mode")
    parser.add_argument("--no-formula", action="store_true", help="Disable formula recognition")
    parser.add_argument("--no-table", action="store_true", help="Disable table recognition")
    parser.add_argument("--page-ranges", default=None, help='Page ranges, e.g. "1-10" or "2,4-6"')
    parser.add_argument("--extra-format", action="append", default=[], choices=("docx", "html", "latex"))
    parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--overwrite", action="store_true", help="Re-download even if Markdown exists")
    parser.add_argument("--limit", type=int, default=None, metavar="N")
    parser.add_argument("--batch-size", type=int, default=20, help="Files per API batch, max 200")
    parser.add_argument("--poll-interval", type=int, default=10, help="Seconds between result checks")
    parser.add_argument("--timeout", type=int, default=3600, help="Seconds to wait per batch")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.token:
        print(
            "MINERU_API_TOKEN is not set. Set it first or pass --token.",
            file=sys.stderr,
        )
        return 2

    input_dir = resolve_path(args.input, DEFAULT_INPUT)
    output_dir = resolve_path(args.output, DEFAULT_OUTPUT)
    batch_size = max(1, min(args.batch_size, MAX_BATCH_SIZE))

    pdfs = find_pdfs(input_dir, args.recursive)
    if args.limit is not None and args.limit > 0:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        print(f"No PDF files found in '{input_dir}'.", file=sys.stderr)
        return 0

    all_jobs = build_jobs(input_dir, output_dir, pdfs)
    results: list[JobResult] = []
    pending_jobs: list[PdfJob] = []
    for job in all_jobs:
        existing_md = find_markdown_files(job.output_dir, job.pdf_path.stem)
        if existing_md and not args.overwrite:
            result = JobResult(
                job=job,
                status="skip",
                message="Markdown already exists",
                markdown_paths=existing_md,
            )
            results.append(result)
            continue
        pending_jobs.append(job)

    started_at = datetime.now(timezone.utc)
    print(f"Found {len(all_jobs)} PDF(s). Pending API conversion: {len(pending_jobs)}")
    print(f"Output: {output_dir}")
    print(f"Model: {args.model_version}")
    print("")

    for batch_index, jobs in enumerate(chunked(pending_jobs, batch_size), start=1):
        print(f"Submitting API batch {batch_index}: {len(jobs)} file(s)", flush=True)
        try:
            batch_id, file_urls = create_upload_batch(
                token=args.token,
                jobs=jobs,
                model_version=args.model_version,
                language=args.language,
                enable_formula=not args.no_formula,
                enable_table=not args.no_table,
                is_ocr=args.ocr,
                page_ranges=args.page_ranges,
                extra_formats=args.extra_format,
            )
            print(f"Batch ID: {batch_id}", flush=True)
            upload_files(jobs, file_urls)
            api_results = poll_batch(
                token=args.token,
                batch_id=batch_id,
                timeout_seconds=args.timeout,
                poll_interval=args.poll_interval,
            )
            batch_results = apply_batch_results(jobs, api_results)
        except Exception as exc:  # noqa: BLE001 - keep processing later batches
            batch_results = [
                JobResult(job=job, status="fail", message=str(exc)) for job in jobs
            ]

        for result in batch_results:
            results.append(result)
            log_result(result)
            tag = {"ok": "[OK]", "skip": "[SKIP]", "fail": "[FAIL]"}.get(
                result.status,
                result.status.upper(),
            )
            extra = f" - {result.message}" if result.message and result.status != "ok" else ""
            print(f"{tag} {result.job.relative_input}{extra}", flush=True)

    for result in results:
        if result.status == "skip":
            log_result(result)

    finished_at = datetime.now(timezone.utc)
    write_report(
        results,
        input_dir,
        output_dir,
        args.model_version,
        started_at,
        finished_at,
    )

    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skip")
    failed = sum(1 for r in results if r.status == "fail")
    print("")
    print(f"Done. OK={ok} SKIP={skipped} FAIL={failed}")
    print(f"Report: {REPORT_FILE}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
