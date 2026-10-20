"""Pretty-print an agent run (JSON on stdin) for the terminal demo."""

import json
import sys

run = json.load(sys.stdin)
for step in run["steps"]:
    mark = "ok    " if step["ok"] else "DENIED"
    args = {k: v for k, v in step["args"].items() if k != "code"}
    print(f"   {mark} {step['name']:<16} {json.dumps(args)[:90]}")
    if not step["ok"]:
        print(f"          -> {step['result'][:150]}")
print()
print("   answer:", run["answer"])
