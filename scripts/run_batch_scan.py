from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from static_skill_scanner.batch_scan import main


if __name__ == "__main__":
    raise SystemExit(main())
