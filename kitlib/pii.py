# -*- coding: utf-8 -*-
"""PII 扫描。扫描文件数必须等于包内可扫描文件数，否则 provenance 里就是假声明。"""
import os
import re
import sys

EXT = {".py", ".md", ".csv", ".txt", ".json", ".yml", ".yaml", ".cfg", ".ini", ".html"}
SKIP_DIRS = {"__pycache__", ".git", "report", ".pytest_cache"}
PAT = [
    # 数字类模式一律加「十六进制边界」防止把 sha256 里的连续数字误报成人证号/卡号：
    # 64 位十六进制的任何 16~19 位数字片段都会命中纯数字正则（#3321 实测命中）。
    # engine.py 的 sha256 中段连续数字）。真实身份证/银行卡两端不会是 hex 字母。
    ("手机号", re.compile(r"(?<![0-9A-Fa-f])1[3-9]\d{9}(?![0-9A-Fa-f])")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("身份证", re.compile(r"(?<![0-9A-Fa-f])\d{17}[\dXx](?![0-9A-Fa-f])")),
    ("银行卡", re.compile(r"(?<![0-9A-Fa-f])\d{16,19}(?![0-9A-Fa-f])")),
]



def files(root, skip_files=("SHA256SUMS.txt",)):
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
        for fn in sorted(fns):
            if fn in skip_files:
                continue
            if os.path.splitext(fn)[1].lower() in EXT:
                yield os.path.join(dp, fn)


def scan(root):
    scanned, hits = 0, []
    for fp in files(root):
        scanned += 1
        txt = open(fp, encoding="utf-8", errors="ignore").read()
        for name, pat in PAT:
            for m in pat.findall(txt):
                hits.append((os.path.relpath(fp, root), name, m[:4] + "***"))
    print("scanned=%d hits=%d" % (scanned, len(hits)))
    for h in hits[:20]:
        print("HIT", h)
    return scanned, hits


def main(root):
    scanned, hits = scan(root)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
