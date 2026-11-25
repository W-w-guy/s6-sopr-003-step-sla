# -*- coding: utf-8 -*-
"""HTML 原型的通用构建件：转义、栅格、表格、图例、折线图、状态帧外壳。

为什么单独成模块：S1-PROTO 这类单的交付物是**可点击原型**，判据是
「该出现的元素是否都在、交互是否真能发生、状态帧是否齐」——与示例集（数字算对）
和 SOP（步骤齐）都不同。但跨平台坑（LF/校验和/打包）仍复用 tables/pack，不重写。
"""
import html as _h


def esc(x):
    return _h.escape(str(x), quote=True)


def page(title, css, body, data_json="{}", script=""):
    """单文件页面：无任何外链资源，离线打开即可用。"""
    return (
        "<!doctype html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        "<title>%s</title>\n<style>\n%s\n</style></head>\n<body>\n%s\n"
        "<script>window.__DATA__ = %s;</script>\n<script>\n%s\n</script>\n</body></html>\n"
        % (esc(title), css, body, data_json, script)
    )


def card(label, rows, cls="card", extra=""):
    """卡片：label 标题 + [(字段名, 值)] 明细。"""
    L = ['<div class="%s" %s>' % (cls, extra),
         '<div class="card-h">%s</div>' % esc(label), '<dl>']
    for k, v in rows:
        L.append('<dt>%s</dt><dd>%s</dd>' % (esc(k), esc(v)))
    L += ['</dl>', '</div>']
    return "\n".join(L)


def table(headers, rows, cls="tbl", row_attr=None):
    """表格。row_attr(i, row) 可给每行加 data-* 与 onclick 钩子。"""
    L = ['<table class="%s">' % cls, '<thead><tr>']
    L += ['<th>%s</th>' % esc(h) for h in headers]
    L += ['</tr></thead>', '<tbody>']
    for i, r in enumerate(rows):
        attrs = row_attr(i, r) if row_attr else ""
        L.append('<tr %s>' % attrs)
        L += ['<td>%s</td>' % esc(c) for c in r]
        L.append('</tr>')
    L += ['</tbody>', '</table>']
    return "\n".join(L)


def legend(items, cls="legend"):
    """图例：[(色块类名, 文案)]。"""
    L = ['<ul class="%s">' % cls]
    for k, t in items:
        L.append('<li><i class="sw %s"></i>%s</li>' % (k, esc(t)))
    L += ['</ul>']
    return "\n".join(L)


def line_svg(series, w=720, h=180, ymax=None, marks=()):
    """折线图（内联 SVG，无外链）。series: [(标签, [值...])]；marks: [(i, 文案)] 标红点。"""
    n = max(len(v) for _, v in series)
    top = ymax or (max(max(v) for _, v in series) * 1.15 or 1)
    pad, gap = 28, 8
    step = (w - pad * 2) / max(n - 1, 1)
    L = ['<svg class="chart" viewBox="0 0 %d %d" width="%d" height="%d">' % (w, h, w, h)]
    L.append('<line x1="%d" y1="%d" x2="%d" y2="%d" class="axis"/>' % (pad, h - 24, w - pad, h - 24))
    for label, vals in series:
        pts = " ".join("%.1f,%.1f" % (pad + i * step, h - 24 - (v / top) * (h - 48))
                       for i, v in enumerate(vals))
        L.append('<polyline class="line" points="%s"/>' % pts)
        for i, v in enumerate(vals):
            x, y = pad + i * step, h - 24 - (v / top) * (h - 48)
            L.append('<circle class="dot" cx="%.1f" cy="%.1f" r="3"/>' % (x, y))
    for i, txt in marks:
        x = pad + i * step
        y = h - 24 - (max(v for _, v in series for v in [0]) if False else 0)
        L.append('<circle class="dot-hot" cx="%.1f" cy="%.1f" r="6"/>' % (x, y))
        L.append('<text class="mk" x="%.1f" y="18">%s</text>' % (x, esc(txt)))
    L.append('</svg>')
    return "\n".join(L)


BASE_CSS = """
*{box-sizing:border-box} body{margin:0;background:#0f172a;color:#e2e8f0;
font:14px/1.6 -apple-system,"Segoe UI","Noto Sans CJK SC",sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:20px 24px 48px}
h1{font-size:20px;margin:0 0 4px} .sub{color:#94a3b8;font-size:12px;margin-bottom:16px}
.grid6{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
.card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px}
.card-h{font-weight:600;font-size:13px;border-bottom:1px solid #334155;padding-bottom:6px;margin-bottom:8px}
.card.on{border-color:#2563eb;box-shadow:0 0 0 2px #2563eb55}
dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:2px 8px;font-size:12px}
dt{color:#94a3b8} dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}
.bad{color:#f87171;font-weight:600} .ok{color:#34d399}
.tbl{width:100%;border-collapse:collapse;font-size:12px}
.tbl th,.tbl td{border-bottom:1px solid #334155;padding:6px 8px;text-align:left}
.tbl th{color:#94a3b8;font-weight:500;background:#16213b}
.tbl tr.hot td{background:#7f1d1d55} .tbl tbody tr{cursor:pointer}
.legend{list-style:none;display:flex;gap:14px;padding:0;margin:6px 0;font-size:12px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.s1{background:#dc2626}.s2{background:#f59e0b}.s3{background:#22d3ee}.s4{background:#34d399}
.chart .axis{stroke:#334155} .chart .line{fill:none;stroke:#60a5fa;stroke-width:2}
.chart .dot{fill:#60a5fa} .chart .dot-hot{fill:#ef4444} .chart .mk{fill:#f87171;font-size:11px}
.sec{margin-top:22px} .sec h2{font-size:15px;margin:0 0 8px;padding-left:8px;border-left:3px solid #2563eb}
.empty{padding:48px;text-align:center;color:#94a3b8;border:1px dashed #475569;border-radius:10px}
.load{height:6px;background:#1e293b;border-radius:3px;overflow:hidden;margin:60px auto;width:280px}
.load i{display:block;height:100%;width:40%;background:#2563eb;animation:m 1s infinite}
@keyframes m{0%{margin-left:-40%}100%{margin-left:100%}}
.err{padding:28px;border:1px solid #7f1d1d;background:#450a0a;border-radius:10px}
.btn{background:#2563eb;color:#fff;border:0;border-radius:8px;padding:7px 14px;cursor:pointer;font-size:12px}
.modal{position:fixed;inset:0;background:#0009;display:flex;align-items:center;justify-content:center}
.modal .box{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:20px;width:420px}
input,select,textarea{width:100%;background:#0f172a;border:1px solid #334155;color:#e2e8f0;
border-radius:6px;padding:7px;font-size:12px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0}
.tag{background:#334155;border-radius:999px;padding:3px 10px;font-size:11px}
"""
