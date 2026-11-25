# -*- coding: utf-8 -*-
"""xlsx 落盘后再规范化：固定条目时间戳 / create_system / STORED，使两侧字节可比。

openpyxl 写出的 xlsx 是 zip：条目带本地时间、create_system 随平台（Windows=0/POSIX=3）、
压缩输出随 zlib 版本变化——三者任一不同，sha256 就必然不同，校验和 100% 假失败。
"""
import re
import shutil
import zipfile

FIXED_DT = (2026, 1, 1, 0, 0, 0)


def normalize(path):
    tmp = path + ".norm"
    src = zipfile.ZipFile(path)
    names = src.namelist()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for n in names:
            data = src.read(n)
            if n == "docProps/core.xml":
                data = re.sub(rb"(<dcterms:created[^>]*>)[^<]*(<)",
                              rb"\g<1>2026-01-01T00:00:00Z\g<2>", data)
                data = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(<)",
                              rb"\g<1>2026-01-01T00:00:00Z\g<2>", data)
            zi = zipfile.ZipInfo(n, date_time=FIXED_DT)
            zi.create_system = 0
            zi.compress_type = zipfile.ZIP_STORED
            zi.external_attr = 0o600 << 16
            dst.writestr(zi, data)
    src.close()
    shutil.move(tmp, path)
    return path
