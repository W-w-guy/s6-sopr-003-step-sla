# -*- coding: utf-8 -*-
"""断言器骨架：每条 check 打印 [PASS]/[FAIL]+实测值，末尾 SUMMARY n/m，失败即非零退出。

另有 skip()：用于「本机缺某个可选依赖、这条没法真跑」的情形。
  - [SKIP] 既不算通过也不算失败，SUMMARY 里单独报数；
  - 是否允许 SKIP 由调用方决定（verify.py 的 --require-browser），
    需要「必须真跑」的场合把 skip 换成 fail，避免把「没跑」说成「通过」。
"""
import sys

OUT = []
SKIPPED = []


def check(name, cond, detail=""):
    OUT.append((name, bool(cond), detail))
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


def skip(name, detail=""):
    SKIPPED.append((name, detail))
    print("[SKIP] %s %s" % (name, detail))
    return True


def fail_now(name, detail=""):
    return check(name, False, detail)


def summary():
    bad = [x for x in OUT if not x[1]]
    tail = "\nSUMMARY %d/%d PASS" % (len(OUT) - len(bad), len(OUT))
    if SKIPPED:
        tail += "  |  SKIP %d（未真跑，不计入通过）" % len(SKIPPED)
    print(tail)
    return 1 if bad else 0


def run(fn):
    """用法：sys.exit(kitlib.run(main))"""
    try:
        fn()
    except Exception as e:  # 断言器自己崩了也必须非零退出，不能静默通过
        import traceback
        traceback.print_exc()
        print("[FAIL] 断言器异常 %s: %s" % (type(e).__name__, e))
        return 2
    return summary()
