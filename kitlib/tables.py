# -*- coding: utf-8 -*-
"""CSV / Markdown 生成。所有文本一律显式 newline="\n"（Windows 默认 CRLF 会让跨平台 sha256 不同）。"""
import csv
import io
import os


def write_csv(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def write_csv_rows(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    return path


def write_text(path, lines):
    """lines 可为 list；写成 LF 结尾。"""
    body = lines if isinstance(lines, str) else "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return path


def kv_table(pairs):
    out = ["| 输入项 | 值 |", "| --- | --- |"]
    for k, v in pairs:
        out.append("| %s | %s |" % (k, v))
    return out


def grid(header, rows):
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return out


def coverage_lines(cats, ids_by_cat, title="覆盖对照表"):
    out = ["## " + title, ""]
    out += grid(["编号", "情形", "示例"], [[c, n, "、".join(ids_by_cat.get(c, []))] for c, n in cats])
    return out
