# -*- coding: utf-8 -*-
"""AC 断言器入口：断言内容在 pkg/checks.py，外壳只负责『崩溃也非零退出』。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "pkg"))
from kitlib import checks  # noqa: E402


def main():
    try:
        import checks as C
        fn = C.main
    except Exception as e:
        # 断言还没写就要报出来，不能『没断言所以没失败』
        print("[FAIL] 无法载入 pkg/checks.py：%s: %s" % (type(e).__name__, e))
        return 2
    return checks.run(fn)


if __name__ == "__main__":
    sys.exit(main())
