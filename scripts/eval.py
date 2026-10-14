"""Measures ranking: each query names the file it should find; reports top-1, top-5 and MRR.

    rummage add ./testbed && rummage index
    python scripts/eval.py scripts/testbed_eval.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rummage.engine import Engine


def main(cases_file: str) -> int:
    cases = json.loads(Path(cases_file).read_text(encoding="utf-8"))
    top1 = top5 = 0
    reciprocal = 0.0
    with Engine() as engine:
        for query, expected in cases.items():
            names = [Path(r.path).name for r in engine.search(query, limit=10)]
            rank = names.index(expected) + 1 if expected in names else None
            top1 += rank == 1
            top5 += rank is not None and rank <= 5
            reciprocal += 1 / rank if rank else 0
            mark = "ok " if rank == 1 else f"#{rank}" if rank else "-- "
            print(f"{mark:4} {query}  ->  {names[:3]}")
    n = len(cases)
    print(f"\ntop-1 {top1}/{n}   top-5 {top5}/{n}   MRR {reciprocal / n:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "scripts/testbed_eval.json"))
