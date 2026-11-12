"""Bundle the exact shared scheduler sources; no Node build pipeline is required."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "ScheduleController" / "schedule_controller"
TARGET = ROOT / "api" / "schedule_controller"


def main():
    TARGET.mkdir(exist_ok=True)
    checksums = {}
    for name in ("__init__.py", "rules.py", "update_rollouts.py", "hand_settlement.py", "mtt_plans.py"):
        source = SOURCE / name
        shutil.copyfile(source, TARGET / name)
        checksums[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    (ROOT / "api" / "scheduler-core.json").write_text(json.dumps(checksums, indent=2) + "\n")
    print("Bundled the shared scheduler core. Frontend is ready as static files.")


if __name__ == "__main__":
    main()
