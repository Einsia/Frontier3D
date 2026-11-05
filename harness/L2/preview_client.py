"""Draft-only request client. The parent harness executes Blender outside Codex's sandbox."""
import json
from pathlib import Path
import time
import uuid


def main():
    root = Path(__file__).resolve().parent
    request = root / ".preview" / uuid.uuid4().hex
    request.mkdir(parents=True)
    (request / "request.json").write_text('{"operation":"render_solution"}\n')
    print("Preview requested; waiting for the outer harness. Keep this command running.", flush=True)
    policy = json.loads((root / '.preview_policy.json').read_text())
    deadline = time.monotonic() + max(0, policy['deadline_epoch']-time.time()) + 5
    while time.monotonic() < deadline:
        result = request / "result.json"
        if result.exists():
            try:
                data = json.loads(result.read_text())
            except json.JSONDecodeError:
                time.sleep(.1)
                continue
            for name in ("stdout.log", "stderr.log"):
                log = request / name
                if log.exists():
                    print(log.read_text(errors="replace")[-12000:])
            print(json.dumps(data), flush=True)
            return 0 if data.get("status") == "success" else 1
        time.sleep(.5)
    print("Preview broker did not finish within its configured limit", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
