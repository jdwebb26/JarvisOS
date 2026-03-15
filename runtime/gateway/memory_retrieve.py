#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.acknowledgements import memory_retrieval_ack
from runtime.memory.governance import retrieve_memory, retrieve_memory_for_context


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for bounded memory retrieval.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="memory", help="Lane name")
    parser.add_argument("--task-id", default="", help="Filter by task id")
    parser.add_argument("--memory-type", default="", help="Filter by memory type")
    parser.add_argument("--source-artifact-id", default="", help="Filter by source artifact id")
    parser.add_argument("--source-trace-id", default="", help="Filter by source trace id")
    parser.add_argument("--source-eval-result-id", default="", help="Filter by source eval result id")
    parser.add_argument("--include-candidate", action="store_true", help="Include non-promoted memories")
    parser.add_argument("--include-contradicted", action="store_true", help="Include contradicted/superseded memories")
    parser.add_argument("--query-text", default="", help="Context query text for bounded context retrieval")
    parser.add_argument("--retrieval-budget-tokens", type=int, default=1200, help="Bounded retrieval token budget")
    parser.add_argument("--episodic-limit", type=int, default=4, help="Max episodic memories to return")
    parser.add_argument("--semantic-limit", type=int, default=4, help="Max semantic memories to return")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.query_text.strip():
        result = retrieve_memory_for_context(
            actor=args.actor,
            lane=args.lane,
            root=root,
            task_id=args.task_id or None,
            query_text=args.query_text,
            retrieval_budget_tokens=args.retrieval_budget_tokens,
            episodic_limit=args.episodic_limit,
            semantic_limit=args.semantic_limit,
            promoted_only=not args.include_candidate,
            include_contradicted=args.include_contradicted,
        )
    else:
        result = retrieve_memory(
            actor=args.actor,
            lane=args.lane,
            root=root,
            promoted_only=not args.include_candidate,
            task_id=args.task_id or None,
            memory_type=args.memory_type or None,
            source_artifact_id=args.source_artifact_id or None,
            source_trace_id=args.source_trace_id or None,
            source_eval_result_id=args.source_eval_result_id or None,
            include_contradicted=args.include_contradicted,
        )
    print(json.dumps({"result": result, "ack": memory_retrieval_ack(result)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
