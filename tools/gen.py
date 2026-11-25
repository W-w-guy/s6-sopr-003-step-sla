# -*- coding: utf-8 -*-
"""由 pkg/engine.py 的示例定义生成 docs/ 下全部交付物（CSV 期望值、覆盖表、逐例 Markdown）。"""
import importlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "pkg"))
from kitlib import tables as T  # noqa: E402

SPEC = json.load(open(os.path.join(ROOT, "spec.json"), encoding="utf-8"))
try:
    E = importlib.import_module("engine")
    R = importlib.import_module("render")
except Exception as e:
    sys.exit("[FAIL] 无法载入 pkg/engine.py 或 pkg/render.py：%s: %s" % (type(e).__name__, e))
DOCS = os.path.join(ROOT, "docs")


def main():
    rows = [E.row_of(c) for c in E.CASES]
    p1 = T.write_csv(os.path.join(DOCS, SPEC["csv"]), SPEC["cols"], rows)
    idmap = {code: [E.case_id(c) for c in E.CASES if code in E.cats_of(c)]
             for code, _ in E.CATS}
    p2 = T.write_csv_rows(os.path.join(DOCS, SPEC["coverage_csv"]),
                          ["category_id", "category", "example_ids"],
                          [[c, n, " ".join(idmap[c])] for c, n in E.CATS])
    L = R.md_head()
    for c in E.CASES:
        L += R.md_section(c)
    L += T.coverage_lines(E.CATS, idmap, SPEC.get("coverage_title", "覆盖对照表"))
    p3 = T.write_text(os.path.join(DOCS, SPEC["md"]), L)
    if SPEC.get("extras"):
        xm = importlib.import_module(SPEC["extras"])
        p4 = xm.write_extras(DOCS)
        for q in (p4 or []):
            print("WROTE %s %d bytes" % (os.path.relpath(q, ROOT).replace(os.sep, "/"),
                                         os.path.getsize(q)))
    for p in (p1, p2, p3):
        print("WROTE %s %d bytes" % (os.path.relpath(p, ROOT).replace(os.sep, "/"),
                                     os.path.getsize(p)))
    print("examples=%d categories=%d" % (len(rows), len(E.CATS)))


if __name__ == "__main__":
    main()
