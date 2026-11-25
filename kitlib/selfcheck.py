# -*- coding: utf-8 -*-
"""一条命令跑完整条管线：gen → verify → pytest → mutate → pii → build_docs → pack →
解压到全新目录 → 校验和 → 再跑一遍（买家视角）。任何一步非零即失败。"""
import os
import subprocess
import sys
import tempfile
import zipfile

from . import pack as PK


def _py(root, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, *args], cwd=root, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def run(root, zip_path, steps=("tools/gen.py", "tools/verify.py",
                               "-m pytest tests -q", "tools/mutate.py",
                               "tools/build_docs.py", "tools/make_zip.py"),
        fresh_regen=True):
    bad = []
    for s in steps:
        rc, out, err = _py(root, *s.split())
        tail = (out.strip().splitlines() or [""])[-1]
        print("[%s] %-24s %s" % (" OK " if rc == 0 else "FAIL", s, tail))
        if rc != 0:
            bad.append(s)
            print(err[-600:])
    if bad:
        print("SELFCHECK FAIL（%d 步失败）" % len(bad))
        return 1
    tmp = tempfile.mkdtemp(prefix="fresh_")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    n, badsum = PK.verify_sums(tmp)
    print("[%s] 解压后校验和 %d 条，不一致 %d 条" % (" OK " if not badsum else "FAIL", n, len(badsum)))
    rc = 0 if not badsum else 1
    if fresh_regen:
        rc2, out2, _ = _py(tmp, "tools/gen.py")
        n2, bad2 = PK.verify_sums(tmp)
        print("[%s] 全新目录重跑 gen 后校验和 %d 条，不一致 %d 条（%s）"
              % (" OK " if rc2 == 0 and not bad2 else "FAIL", n2, len(bad2), ",".join(bad2) or "无"))
        rc = rc or rc2 or (1 if bad2 else 0)
    return rc
