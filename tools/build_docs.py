# -*- coding: utf-8 -*-
"""README / DATA_PROVENANCE / ACCEPTANCE 由实跑结果生成；数字一律取自 stdout 与真实文件。"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from kitlib import docs as D  # noqa: E402
from kitlib import pii as P  # noqa: E402

SPEC = json.load(open(os.path.join(ROOT, "spec.json"), encoding="utf-8"))
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")


def py(*args):
    r = subprocess.run([sys.executable, *args], cwd=ROOT, env=ENV,
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout or "")


def main():
    rc_v, ver_out = py("tools/verify.py")
    n = len([l for l in ver_out.splitlines() if l.startswith(("[PASS]", "[FAIL]"))])
    W = lambda p, s: open(os.path.join(ROOT, p), "w", encoding="utf-8", newline="\n").write(s)
    W("README.md", D.readme(SPEC, n))
    W("ACCEPTANCE.md", D.acceptance(SPEC["acs"], ver_out))
    # 两遍：先写占位，再数真实文件数回填；回填不改变文件数，回填后复扫须一致
    W("DATA_PROVENANCE.md", D.provenance(SPEC, os.path.join(ROOT, "pkg"), -1, 0))
    scanned, hits = P.scan(ROOT)
    W("DATA_PROVENANCE.md", D.provenance(SPEC, os.path.join(ROOT, "pkg"), scanned, len(hits)))
    scanned2, hits2 = P.scan(ROOT)
    if (scanned2, len(hits2)) != (scanned, len(hits)):
        print("FAIL 回填后扫描数变化 %s -> %s" % (scanned, scanned2))
        return 1
    print("verify_rc=%d verify_lines=%d pii scanned=%d hits=%d (recheck %d/%d)"
          % (rc_v, n, scanned, len(hits), scanned2, len(hits2)))
    return 0 if rc_v == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
