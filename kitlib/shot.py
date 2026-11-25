# -*- coding: utf-8 -*-
"""用真实浏览器无头截图（不是画图，是渲染）。

跨平台现实（2026-11-22 实测）：
  Windows  Edge  --headless --screenshot=  可用（无需装 playwright）
  Ubuntu   firefox 为 snap 包，--headless --screenshot 超时/无输出；chromium 未安装
因此本模块：优先用本机可用浏览器真截图；无浏览器时**明确报 unavailable**，
绝不用 PIL 画一张假图冒充截图（那等于伪造证据）。
无浏览器侧的复核方式见 checks.py：HTML 结构断言 + 字节一致性。
"""
import glob
import os
import shutil
import subprocess
import sys

CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    "/snap/bin/chromium",
]


def browser():
    """返回 (路径, 类型) 或 (None, None)。"""
    for p in CANDIDATES:
        if os.path.exists(p):
            kind = "chromium" if ("chrome" in p.lower() or "chromium" in p.lower()) else "edge"
            return p, kind
    for name in ("msedge", "chrome", "chromium", "chromium-browser", "google-chrome"):
        w = shutil.which(name)
        if w:
            return w, "chromium"
    return None, None


def shoot(html_path, png_path, w=1440, h=1100, timeout=90):
    """渲染 html_path 到 png_path。返回 (ok, 说明)。"""
    exe, kind = browser()
    if not exe:
        return False, "UNAVAILABLE: 本机无 Chromium/Edge，无法真截图（不允许用绘图冒充）"
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    args = [exe, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=%d,%d" % (w, h),
            "--screenshot=" + os.path.abspath(png_path), url]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: %s 超过 %ds 未完成" % (kind, timeout)
    if not os.path.exists(png_path) or os.path.getsize(png_path) < 1000:
        return False, "NOFILE: %s rc=%d 未产出有效 PNG" % (kind, r.returncode)
    return True, "%s %d bytes" % (kind, os.path.getsize(png_path))


def shoot_many(jobs, outdir):
    """jobs: [(html_path, png_name, w, h)]。返回 [(name, ok, note)]。"""
    os.makedirs(outdir, exist_ok=True)
    out = []
    for hp, name, w, h in jobs:
        ok, note = shoot(hp, os.path.join(outdir, name), w, h)
        out.append((name, ok, note))
        print("[%s] shot %-28s %s" % (" OK " if ok else "FAIL", name, note))
    return out
