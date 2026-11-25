# -*- coding: utf-8 -*-
"""SOP 类交付件的通用件：话术校验、时限推算、流程图与责任矩阵生成。

为什么单独一个模块（与 tables/xlsx 并列）：
  示例集类（RULE）的可自证点是「数字算得对」；SOP 类的可自证点是
  「步骤齐、岗位与时限齐全、话术变量可渲染、字数不超限」——判据完全不同，
  放进同一套断言里会互相污染（RULE 的金额断言对 SOP 无意义）。
  但两边共用的跨平台坑（CRLF / xlsx 时间戳 / 校验和不列自身）仍在 tables/xlsx/pack 里，不重复写。
"""
import re
from datetime import datetime, timedelta

VAR = re.compile(r"\{([^{}\s]+)\}")


def vars_in(text):
    """按出现顺序返回变量名（去重）。"""
    out = []
    for m in VAR.finditer(text or ""):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def render_vars(text, values):
    """把 {变量} 替换成 values 里的值；未提供的变量保持原样并回报。"""
    missing = [v for v in vars_in(text) if v not in values]
    out = text
    for k, v in values.items():
        out = out.replace("{%s}" % k, str(v))
    return out, missing


def char_count(text, count_vars_as=0):
    """字数：默认把变量占位符整段算 0 字（最保守口径是算满，见 char_count_strict）。

    count_vars_as=0  → {企业名称} 计 0 字（乐观）
    count_vars_as=None → 按变量名长度算（近似）
    """
    if count_vars_as is None:
        return len(text)
    return len(VAR.sub("", text)) + count_vars_as * len(vars_in(text))


def script_problems(sc, declared_vars=None, channel_limit=None):
    """校验一条话术。返回问题列表（空 = 合格）。"""
    bad = []
    text = sc.get("body") or ""
    if not text.strip():
        bad.append("%s 正文为空" % sc.get("id"))
    vs = vars_in(text)
    need = declared_vars if declared_vars is not None else sc.get("vars") or []
    if declared_vars is not None:
        lack = [v for v in need if v not in vs]
        if lack:
            bad.append("%s 缺变量 %s" % (sc.get("id"), lack))
        extra = [v for v in vs if v not in need]
        if extra:
            bad.append("%s 出现未声明变量 %s" % (sc.get("id"), extra))
    lim = channel_limit if channel_limit is not None else sc.get("limit")
    if lim and char_count(text) > lim:
        bad.append("%s 字数 %d 超过上限 %d（变量按 0 字计）"
                   % (sc.get("id"), char_count(text), lim))
    if lim and len(text) > lim:
        bad.append("%s 含变量的原始长度 %d 也超过上限 %d" % (sc.get("id"), len(text), lim))
    return bad


def deadline(start, hours, work=(9, 18), workdays_only=True, holidays=()):
    """从 start 起推 hours 小时后的截止时刻。

    口径：工作时间制 —— 只在工作日 work[0]:00~work[1]:00 内消耗时长，
    跨夜/跨周末/跨假日自动顺延；非工作时间制（workdays_only=False 且 work=None）按自然时间。
    与 zoneinfo 无关，纯 naive datetime，避免系统 tzdata 依赖。
    """
    if work is None:
        return start + timedelta(hours=hours)
    cur, left = start, float(hours)
    guard = 0
    while left > 0:
        guard += 1
        if guard > 4000:
            raise RuntimeError("deadline 推算超出保护上限，检查 work 参数")
        if workdays_only and (cur.weekday() >= 5 or cur.date().isoformat() in holidays):
            nxt = datetime.combine(cur.date() + timedelta(days=1), datetime.min.time())
            cur = nxt.replace(hour=work[0])
            continue
        day_start = cur.replace(hour=work[0], minute=0, second=0, microsecond=0)
        day_end = cur.replace(hour=work[1], minute=0, second=0, microsecond=0)
        if cur < day_start:
            cur = day_start
        if cur >= day_end:
            nxt = datetime.combine(cur.date() + timedelta(days=1), datetime.min.time())
            cur = nxt.replace(hour=work[0])
            continue
        avail = (day_end - cur).total_seconds() / 3600.0
        if left <= avail:
            return cur + timedelta(hours=left)
        left -= avail
        nxt = datetime.combine(cur.date() + timedelta(days=1), datetime.min.time())
        cur = nxt.replace(hour=work[0])
    return cur


def mermaid_flow(nodes, edges, direction="TD"):
    """nodes: [(id, label)]；edges: [(from, to, cond)]。无条件边会被标出来（AC 常要求每边带条件）。"""
    L = ["```mermaid", "flowchart %s" % direction]
    for nid, label in nodes:
        L.append('    %s["%s"]' % (nid, label))
    for a, b, cond in edges:
        if cond:
            L.append("    %s -->|%s| %s" % (a, cond, b))
        else:
            L.append("    %s --> %s" % (a, b))
    L.append("```")
    return L


def flow_problems(nodes, edges, require_cond=True):
    bad = []
    ids = [n for n, _ in nodes]
    if len(set(ids)) != len(ids):
        bad.append("节点 id 重复")
    for a, b, cond in edges:
        if a not in ids or b not in ids:
            bad.append("边 %s->%s 引用了未声明节点" % (a, b))
        if require_cond and not cond:
            bad.append("边 %s->%s 缺条件" % (a, b))
    reach = {ids[0]} if ids else set()
    changed = True
    while changed:
        changed = False
        for a, b, _ in edges:
            if a in reach and b not in reach:
                reach.add(b)
                changed = True
    orphan = [i for i in ids if i not in reach]
    if orphan:
        bad.append("从首节点不可达 %s" % orphan)
    return bad


def matrix(steps, roles):
    """责任矩阵：行=步骤，列=岗位；值 = R(负责)/C(协作)/空。"""
    rows = []
    for s in steps:
        r = [s["id"], s["name"]]
        for role in roles:
            if role == s.get("role"):
                r.append("R")
            elif role in (s.get("support") or []):
                r.append("C")
            else:
                r.append("")
        rows.append(r)
    return ["| 步骤 | 名称 | " + " | ".join(roles) + " |",
            "| --- | --- | " + " | ".join("---" for _ in roles) + " |"] + \
           ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]


def checklist_problems(steps, lo=2, hi=4):
    """检查项条数须在 lo~hi 之间，且每条非空。"""
    bad = []
    for s in steps:
        cl = s.get("checklist") or []
        if not (lo <= len(cl) <= hi):
            bad.append("%s 检查项 %d 条（要求 %d~%d）" % (s["id"], len(cl), lo, hi))
        if any(not str(x).strip() for x in cl):
            bad.append("%s 有空检查项" % s["id"])
    return bad


def fields_problems(steps, need=("id", "name", "role", "sla_hours", "outputs")):
    bad = []
    for s in steps:
        for k in need:
            if s.get(k) in (None, "", [], ()):
                bad.append("%s 缺字段 %s" % (s.get("id", "?"), k))
    return bad


def workdays_after(start, n, work=(9, 18), holidays=()):
    """第 n 个工作日（**含当日为第 1 个工作日**）的同一时刻。

    与 deadline() 的区别：#3319 的「24 小时内」是自然小时，#3318 的「3 个工作日内
    完成首次联系」是**工作日数**，两者不能互相替代。

    口径（显式写清，避免歧义）：
      · 只数工作日（周一~周五且不在节假日表），**当天算第 1 个工作日**；
      · 起点落在非工作时段时，先顺延到下一个工作日的 work[0]；
      · 结果保持起点的同一时分；若该时分已越出 work[1]，收敛到当日 work[1]。

    例（work=(9,18)）：
      周三 10:00 + 3 → 周五 10:00     （周三=1、周四=2、周五=3）
      周五 10:00 + 3 → 下周二 10:00   （周五=1、周一=2、周二=3，周末不计）
      周三 17:00 + 2 → 周四 17:00
    """
    if n <= 0:
        return start
    lo, hi = work
    cur = start
    for _ in range(4000):                       # 规范化到工作时段内
        ok_day = cur.weekday() < 5 and cur.date().isoformat() not in holidays
        if ok_day and lo <= cur.hour < hi:
            break
        if (not ok_day) or cur.hour >= hi:
            d0 = cur.date() + timedelta(days=1)
            cur = datetime(d0.year, d0.month, d0.day, lo, 0)
        elif cur.hour < lo:
            cur = cur.replace(hour=lo, minute=0, second=0, microsecond=0)
    left, d = n - 1, cur
    while left > 0:
        d0 = d.date() + timedelta(days=1)
        d = datetime(d0.year, d0.month, d0.day, cur.hour, cur.minute)
        if d.weekday() < 5 and d.date().isoformat() not in holidays:
            left -= 1
    if d.hour >= hi:
        d = datetime(d.year, d.month, d.day, hi, 0)
    return d


def vars_problems(scripts, forbid_vars=(), forbid_words=(), scenes=None, versions=2):
    """话术集合的批量校验：
      · 每个场景（scene）必须有 versions 个不同 version；
      · 每条必须用变量占位（vars 非空且正文里真的出现）；
      · forbid_vars 里的变量名不得出现在任何话术（用于「不透露联系方式」）；
      · forbid_words 里的词不得出现在正文（同上，兜底正文硬编码）。
    """
    bad = []
    from collections import Counter
    by_scene = {}
    for s in scripts:
        by_scene.setdefault(s.get("scene"), []).append(s)
    if scenes:
        lack = [x for x in scenes if x not in by_scene]
        if lack:
            bad.append("缺场景 %s" % lack)
    for sc, items in by_scene.items():
        if len(items) != versions:
            bad.append("场景 %s 有 %d 版（要求 %d 版）" % (sc, len(items), versions))
        vs = [i.get("version") for i in items]
        if len(set(vs)) != len(vs):
            bad.append("场景 %s 的版本名重复 %s" % (sc, vs))
    for s in scripts:
        body = s.get("body") or ""
        vs = vars_in(body)
        if not vs:
            bad.append("%s 未使用任何变量占位" % s.get("id"))
        miss = [v for v in (s.get("vars") or []) if v not in vs]
        if miss:
            bad.append("%s 声明的变量未出现在正文 %s" % (s.get("id"), miss))
        hitv = [v for v in vs if v in forbid_vars]
        if hitv:
            bad.append("%s 出现禁止的变量 %s" % (s.get("id"), hitv))
        hitw = [w for w in forbid_words if w in body]
        if hitw:
            bad.append("%s 正文出现禁止的词 %s" % (s.get("id"), hitw))
    return bad
