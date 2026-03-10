#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import sys

TASK_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 99994
TITLE = sys.argv[2] if len(sys.argv) > 2 else "ops report apply tool smoke"
NOTES = sys.argv[3] if len(sys.argv) > 3 else "no-op live apply smoke"

target = Path("/home/rollan/.openclaw/workspace/tasks/local_executor.py")
spec = importlib.util.spec_from_file_location("local_executor_live", str(target))
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)

out = module.write_ops_report_artifact(TASK_ID, TITLE, NOTES)
print(out)
