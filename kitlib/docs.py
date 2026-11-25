# -*- coding: utf-8 -*-
"""README / DATA_PROVENANCE / ACCEPTANCE 三者由实跑结果自动生成，禁止手写数字。
ACCEPTANCE 按『原文 / 判定方式 / 复核命令 / 实际输出原文』四元组输出，
实际输出直接从 verify 的 stdout 里按行前缀抓，抓不到就写『（未取到——视为未通过）』。"""
import hashlib
import os

MISS = "（未取到对应行——视为未通过）"


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def acceptance(acs, ver_out):
    lines = ver_out.strip().splitlines()
    L = ["# ACCEPTANCE — 逐条 AC 判定（原文 / 判定方式 / 复核命令 / 实际输出原文）", "",
         "以下输出为 `python tools/verify.py` 在交付包内的真实 stdout，未经修改。", ""]
    for cid, src, how, cmd, prefixes in acs:
        picked = [l for l in lines if l.startswith(tuple(prefixes))]
        L += ["## %s" % cid, "",
              "**原文**：%s" % src, "",
              "**判定方式**：%s" % how, "",
              "**复核命令**：`%s`" % cmd, "",
              "**实际输出原文**：", "", "```"]
        L += picked or [MISS]
        L += ["```", ""]
    L += ["## 汇总", "", "```", lines[-1] if lines else "", "```", ""]
    return "\n".join(L)


def provenance(spec, pkg_dir, pii_scanned, pii_hits):
    rows = [
        ("生成脚本", "`%s`（示例定义与业务规则）+ `tools/gen.py`（写出 docs/）" % spec["engine_rel"]),
        ("生成脚本 sha256", "`%s`" % sha(os.path.join(pkg_dir, "engine.py"))),
        ("渲染脚本 sha256", "`%s`" % sha(os.path.join(pkg_dir, "render.py"))),
        ("随机性", "**无随机**。%s" % spec.get("nondeterministic_note",
                                             "示例为手写固定常量；同一脚本在任何机器重跑，产出字节级一致")),
        ("种子", "不适用（无随机数生成器）"),
        ("重跑命令", "`python tools/gen.py`"),
        ("产出规模", spec["scale"]),
        ("PII 扫描", "`python tools/pii_scan.py` → `scanned=%d hits=%d`（手机号 / 邮箱 / 身份证 / 银行卡 四类正则）"
         % (pii_scanned, pii_hits)),
    ]
    L = ["# DATA_PROVENANCE — 数据来源与可复核性", "",
         "本交付包**不含任何真实个人信息或企业信息**。全部示例数据由脚本生成，可完整重放。", "",
         "| 项 | 值 |", "| --- | --- |"]
    L += ["| %s | %s |" % (k, v) for k, v in rows]
    L += ["", "## 虚构声明", "",
          spec.get("fiction", "企业名、人名、金额与日期均为虚构；示例中不含客户名称。"), ""]
    return "\n".join(L)


def readme(spec, n_verify):
    L = ["# %s" % spec["title"], "",
         spec.get("intro", "全部数据为**虚构**，用作后续开发的测试期望值。"), "",
         "## 一条命令复跑", "", "```",
         "python tools/gen.py             # 重新生成 docs/ 下全部交付物",
         "python tools/verify.py          # 逐条断言 AC（%d 条），任何一条失败即非零退出" % n_verify,
         "python -m pytest tests -q       # 用例逐条比对 CSV 期望值",
         "python tools/mutate.py          # 变异测试：改坏引擎 %d 处，每处都必须让 verify 变红" % len(spec["mutations"]),
         "python tools/build_docs.py      # 由实跑结果重生成 README / DATA_PROVENANCE / ACCEPTANCE",
         "python tools/make_zip.py        # 打包 + SHA256SUMS", "```", ""]
    deps = spec.get("deps")
    if deps:
        L += ["## 环境依赖", ""]
        L += ["- " + x for x in deps]
        L += [""]
    L += ["## 目录", "", "| 路径 | 内容 |", "| --- | --- |",
          "| `%s` | 业务规则引擎 + 示例定义 + 情形编号 |" % spec["engine_rel"],
          "| `%s` | 逐例 Markdown 渲染 |" % spec["render_rel"]]
    for path, desc in spec["deliverables"]:
        L.append("| `%s` | %s |" % (path, desc))
    L += ["| `tools/verify.py` | AC 断言器（%d 条，非零退出可接 CI） |" % n_verify,
          "| `tools/mutate.py` | 变异测试（%d 处） |" % len(spec["mutations"]),
          "| `tools/pii_scan.py` | PII 扫描（手机 / 邮箱 / 身份证 / 银行卡） |",
          "| `report/` | 本次双平台实跑日志（打包时快照，不参与校验和） |", "",
          "## 口径说明", ""]
    L += ["- " + x for x in spec["rules"]]
    L += [""]
    tp = spec.get("third_party")
    if tp:
        L += ["## 第三方资源与许可", "", "| 资源 | 版本/来源 | 许可 |", "| --- | --- | --- |"]
        for row in tp:
            L.append("| %s | %s | %s |" % tuple(row))
        L += ["", "第三方资源仅用于生成交付物，不改变上述任何判定口径；"
              "其许可见包内 `data/fonts/OFL.txt`（字体）等随附文件。", ""]
    gates = spec.get("gates")
    if gates:
        L += ["## 复跑的两种模式", ""]
        L += ["- " + x for x in gates]
        L += [""]
    return "\n".join(L)
