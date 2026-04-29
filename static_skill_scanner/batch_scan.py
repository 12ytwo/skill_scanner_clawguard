from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .aggregator import aggregate, render_markdown
from .analyzer_factory import build_default_analyzers
from .normalizer import build_skill_model
from .parser import cleanup_workspace, parse_input


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XLSX = PACKAGE_ROOT / "testdata.xlsx"
DEFAULT_DATA_DIR = PACKAGE_ROOT / "data"
DEFAULT_REPO_CACHE = DEFAULT_DATA_DIR / "repo_cache"
DEFAULT_RESULTS_DIR = PACKAGE_ROOT / "results"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch-scan repositories from testdata.xlsx")
    parser.add_argument("--xlsx", default=str(DEFAULT_XLSX), help="Path to xlsx dataset file")
    parser.add_argument("--repo-cache", default=str(DEFAULT_REPO_CACHE), help="Repository cache directory")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Directory for scan outputs")
    parser.add_argument("--limit-repos", type=int, default=5, help="Maximum repositories to process")
    parser.add_argument("--limit-skills-per-repo", type=int, default=20, help="Maximum SKILL.md roots to scan in each repo")
    parser.add_argument("--refresh", action="store_true", help="Delete cached repos and re-clone")
    parser.add_argument("--skip-clone", action="store_true", help="Only scan repos already in cache")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    xlsx_path = Path(args.xlsx).expanduser().resolve()
    repo_cache = Path(args.repo_cache).expanduser().resolve()
    results_root = Path(args.results_dir).expanduser().resolve()

    repo_cache.mkdir(parents=True, exist_ok=True)
    results_root.mkdir(parents=True, exist_ok=True)
    run_dir = create_run_results_dir(results_root)

    rows = read_testdata_rows(xlsx_path)
    selected_rows = rows[: max(0, args.limit_repos)]

    analyzer_instances = build_default_analyzers()
    summary_rows: list[dict[str, object]] = []

    for index, row in enumerate(selected_rows, start=1):
        repo_url = str(row.get("GitHub链接") or "").strip()
        repo_name = str(row.get("完整名称") or row.get("技能名称") or f"repo-{index}").strip()
        if not repo_url:
            continue

        print(f"[batch] ({index}/{len(selected_rows)}) {repo_name}")
        cache_path = get_repo_cache_path(repo_cache, repo_url)

        try:
            if args.refresh and cache_path.exists():
                shutil.rmtree(cache_path, ignore_errors=True)

            if not cache_path.exists():
                if args.skip_clone:
                    print(f"[batch] skip missing cache: {cache_path}")
                    continue
                clone_repo(repo_url, cache_path)

            skill_roots = find_skill_roots(cache_path)
            if not skill_roots:
                summary_rows.append(
                    {
                        "repo_name": repo_name,
                        "repo_url": repo_url,
                        "skill_root": "",
                        "status": "no_skill_root",
                        "total_findings": 0,
                        "high_or_above": 0,
                    }
                )
                continue

            for skill_root in skill_roots[: max(0, args.limit_skills_per_repo)]:
                source = str(skill_root)
                parsed = parse_input(source)
                try:
                    skill = build_skill_model(parsed)
                    analyzer_results = [analyzer.run(skill) for analyzer in analyzer_instances]
                    scan_result = aggregate(skill, analyzer_results)
                finally:
                    cleanup_workspace(parsed)

                sample_id = make_sample_id(repo_name, skill_root)
                json_path = run_dir / f"{sample_id}.json"
                md_path = run_dir / f"{sample_id}.md"
                json_path.write_text(json.dumps(asdict(scan_result), indent=2, ensure_ascii=False), encoding="utf-8")
                md_path.write_text(render_markdown(scan_result), encoding="utf-8")

                high_or_above = sum(
                    1 for finding in scan_result.findings if finding.severity.upper() in {"HIGH", "CRITICAL"}
                )
                summary_rows.append(
                    {
                        "repo_name": repo_name,
                        "repo_url": repo_url,
                        "skill_root": str(skill_root),
                        "status": "scanned",
                        "total_findings": len(scan_result.findings),
                        "high_or_above": high_or_above,
                    }
                )
        except Exception as exc:
            summary_rows.append(
                {
                    "repo_name": repo_name,
                    "repo_url": repo_url,
                    "skill_root": "",
                    "status": f"error: {exc}",
                    "total_findings": 0,
                    "high_or_above": 0,
                }
            )

    write_summary(run_dir, summary_rows)
    update_latest_pointer(results_root, run_dir)
    print(f"[batch] wrote results to {run_dir}")
    return 0


def read_testdata_rows(xlsx_path: Path) -> list[dict[str, str]]:
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(xlsx_path) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("main:si", ns):
                parts = [t.text or "" for t in si.iterfind(".//main:t", ns)]
                shared.append("".join(parts))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        first_sheet = workbook.find("main:sheets/main:sheet", ns)
        if first_sheet is None:
            return []
        rid = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        sheet_path = "xl/" + rel_map[rid]
        sheet_root = ET.fromstring(zf.read(sheet_path))
        rows = sheet_root.findall(".//main:sheetData/main:row", ns)

        values: list[list[str]] = []
        for row in rows:
            current: list[str] = []
            for cell in row.findall("main:c", ns):
                cell_type = cell.attrib.get("t")
                value_elem = cell.find("main:v", ns)
                value = value_elem.text if value_elem is not None else ""
                if cell_type == "s" and value:
                    idx = int(value)
                    value = shared[idx] if 0 <= idx < len(shared) else value
                current.append(value)
            values.append(current)

    if not values:
        return []
    header = values[0]
    data_rows = []
    for row in values[1:]:
        padded = row + [""] * max(0, len(header) - len(row))
        data_rows.append({header[idx]: padded[idx] for idx in range(len(header))})
    return data_rows


def get_repo_cache_path(repo_cache: Path, repo_url: str) -> Path:
    digest = hashlib.sha1(repo_url.encode("utf-8")).hexdigest()[:12]
    slug = repo_url.rstrip("/").split("/")[-1].replace(".git", "") or "repo"
    safe_slug = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in slug)
    return repo_cache / f"{digest}-{safe_slug}"


def clone_repo(repo_url: str, target_dir: Path) -> None:
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--single-branch", repo_url, str(target_dir)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def find_skill_roots(repo_dir: Path) -> list[Path]:
    roots = sorted(path.parent for path in repo_dir.rglob("SKILL.md"))
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def make_sample_id(repo_name: str, skill_root: Path) -> str:
    repo_part = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in repo_name).strip("-")
    skill_part = "__".join(skill_root.parts[-3:]) if len(skill_root.parts) >= 3 else skill_root.name
    skill_part = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in skill_part)
    return f"{repo_part}__{skill_part}"


def write_summary(results_dir: Path, rows: list[dict[str, object]]) -> None:
    json_path = results_dir / "summary.json"
    csv_path = results_dir / "summary.csv"
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    fieldnames = ["repo_name", "repo_url", "skill_root", "status", "total_findings", "high_or_above"]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def create_run_results_dir(results_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = results_root / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def update_latest_pointer(results_root: Path, run_dir: Path) -> None:
    latest_path = results_root / "LATEST.txt"
    latest_path.write_text(str(run_dir), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
