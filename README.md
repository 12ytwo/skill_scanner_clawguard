# Static Skill Scanner

A minimal runnable static skill scanner prototype with four layers:

1. `Parser`
2. `Normalizer`
3. `Analyzers`
4. `Aggregator`

## Environment Setup

Create a dedicated conda environment for this project:

```bash
conda env create -f environment.yml
conda activate skill_scanner
pip install -r requirements.txt
pip install -e .
```

## Working Directory

Run commands from the project root:

```bash
cd /d F:\skill_scanner_clawguard
```

## Quick Start

```bash
python -m static_skill_scanner.cli examples/suspicious_skill --format md
```

After `pip install -e .`, you can also run:

```bash
skill-scan examples/suspicious_skill --format md
```

Scan a local zip archive:

```bash
python -m static_skill_scanner.cli path\to\your_skill.zip --format json
```

Scan a local directory:

```bash
python -m static_skill_scanner.cli path\to\your_skill_dir --format md
```

Or scan a zip archive:

```bash
python -m static_skill_scanner.cli examples/suspicious_skill.zip --format json
```

## Batch Scan From `testdata.xlsx`

Recommended command:

```bash
python -m static_skill_scanner.batch_scan --limit-repos 5
```

Or run the installed command from any directory:

```bash
skill-scan-batch --limit-repos 5 --xlsx F:\skill_scanner_clawguard\testdata.xlsx
```

The script wrapper also works from the project root:

```bash
python scripts\run_batch_scan.py --limit-repos 5
```

This batch script will:

- read GitHub repository rows from `testdata.xlsx`
- clone repositories into `data/repo_cache/`
- locate every `SKILL.md`
- scan each detected skill root
- create a new run folder under `results/` for each batch execution
- write per-sample `.json` and `.md` reports into that run folder
- write `summary.json` and `summary.csv` into that run folder
- update `results/LATEST.txt` to point to the newest run directory

Useful options:

```bash
python -m static_skill_scanner.batch_scan --limit-repos 3
python -m static_skill_scanner.batch_scan --limit-repos 5 --refresh
python -m static_skill_scanner.batch_scan --limit-repos 5 --skip-clone
```

## Project Layout

- `static_skill_scanner/parser.py`: input parsing and workspace preparation
- `static_skill_scanner/normalizer.py`: build the unified `SkillModel`
- `static_skill_scanner/analyzers/`: plug-in analyzers
- `static_skill_scanner/aggregator.py`: merge findings and render summary
- `examples/`: sample skills for local testing
- `scripts/run_batch_scan.py`: batch runner for xlsx-based repository datasets
