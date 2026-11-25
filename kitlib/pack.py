# -*- coding: utf-8 -*-
"""打包 + 校验和。四类跨平台坑在此一次性掐死：
  1) 文本 CRLF —— 上游用 newline="\n" 写；
  2) SHA256SUMS 不列自身（列了 sha256sum -c 恒 1 条 FAIL）；
  3) report/ 是打包时快照，不参与校验（买家跑一遍就 mismatch）；
  4) zip 条目固定 date_time / create_system / STORED，使两侧字节可比。
"""
import hashlib
import os
import sys
import zipfile

SKIP_DIRS = {"__pycache__", ".git", "report", ".pytest_cache"}
SKIP_FILES = {"SHA256SUMS.txt"}
# 不进 SHA256SUMS **但仍在 zip 里**的文件：xlsx 是 zip、条目带本地时间与
# create_system，openpyxl 每次写出的字节都不同（实测重跑 gen 后恰好 1 条不一致）。
# 对它做字节校验只会得到恒假的「失败」，正确做法是改比单元格值（另出 CSV 转储）。
SUMS_SKIP_EXT = {".xlsx"}
FIXED_DT = (2026, 1, 1, 0, 0, 0)


def sha(path):
    h = hashlib.sha256()
    h.update(open(path, "rb").read())
    return h.hexdigest()


def walk(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
        for fn in sorted(fns):
            if fn in SKIP_FILES or fn.endswith(".pyc"):
                continue
            fp = os.path.join(dp, fn)
            yield os.path.join(fp), os.path.relpath(fp, root).replace(os.sep, "/")


def write_sums(root, items):
    lines = ["%s  %s" % (sha(fp), rel) for fp, rel in items]
    path = os.path.join(root, "SHA256SUMS.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
        f.write("# 本文件不列出自身；report/ 为打包时快照，不参与校验。\n")
    return path, len(lines)


def build(root, zip_path):
    items = list(walk(root))
    non_ascii = [rel for _, rel in items if not rel.isascii()]
    if non_ascii:
        print("NON-ASCII FILENAME", non_ascii)
        return 2
    sums, n = write_sums(root, [it for it in items
                                if os.path.splitext(it[0])[1].lower() not in SUMS_SKIP_EXT])
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for fp, rel in items + [(sums, "SHA256SUMS.txt")]:
            zi = zipfile.ZipInfo(rel, date_time=FIXED_DT)
            zi.create_system = 0
            zi.compress_type = zipfile.ZIP_STORED
            zi.external_attr = 0o600 << 16
            z.writestr(zi, open(fp, "rb").read())
    print("FILES %d  SHA256SUMS %d  ZIP %d bytes  sha256 %s"
          % (len(items) + 1, n, os.path.getsize(zip_path), sha(zip_path)))
    return 0


def verify_sums(root):
    """返回 (条数, 不一致列表)。"""
    path = os.path.join(root, "SHA256SUMS.txt")
    n, bad = 0, []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        n += 1
        h, _, rel = ln.partition("  ")
        fp = os.path.join(root, rel)
        if not os.path.exists(fp) or sha(fp) != h:
            bad.append(rel)
    return n, bad


if __name__ == "__main__":
    sys.exit(build(sys.argv[1], sys.argv[2]))
