#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_coverage.py — 覆盖性自检（漏标检测）

把「读图时识别到的全部尺寸文本」与「已编气泡号的尺寸」做差集，
应标未标 > 0 时以退出码 1 终止，禁止交付。

输入：
    --dims      dimensions.json
    --detected  纯文本文件，每行一条读图识别到的尺寸文本（如 Ø320、3×Ø12、45°）
    --report    可选，输出 coverage_report.json 路径
    --whitelist 可选，额外免标关键词文件，每行一个

免标白名单（默认）：REF 参考尺寸、理论正确尺寸（方括号）、BOM 零件序号、图框尺寸、图幅代号

用法：
    python check_coverage.py --dims dimensions.json --detected detected.txt

退出码：0 通过 / 1 存在应标未标 / 2 参数错误
"""

import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DIA_CHARS = "Øø⌀ⓍΦφ∅𝐷⏀"

# 子串匹配类关键词
DEFAULT_WHITELIST = ["REF", "参考", "理论正确", "BOM", "明细", "图框", "图幅"]
# 整串精确匹配类关键词（图幅代号必须精确，否则 RA3.2 会被 A3 误伤）
EXACT_WHITELIST = {"A0", "A1", "A2", "A3", "A4"}


def norm(s):
    """归一化：去空白、统一直径符号、统一大小写、去全角括号包裹。"""
    s = str(s or "").strip()
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\s+", "", s)
    for ch in DIA_CHARS:
        s = s.replace(ch, "Ø")
    s = s.replace("×", "x").replace("＊", "x")
    s = s.replace("°", "°").replace("度", "°")
    return s.upper()


def numbers(s):
    """提取数字序列，用于宽松匹配。"""
    return re.findall(r"\d+(?:\.\d+)?", str(s or ""))


def main():
    ap = argparse.ArgumentParser(description="覆盖性自检：漏标检测")
    ap.add_argument("--dims", required=True)
    ap.add_argument("--detected", required=True)
    ap.add_argument("--report", default="", help="输出 coverage_report.json 路径")
    ap.add_argument("--whitelist", default="", help="额外免标关键词文件")
    args = ap.parse_args()

    for p in (args.dims, args.detected):
        if not os.path.isfile(p):
            print("[错误] 文件不存在: %s" % p)
            return 2

    with open(args.dims, "r", encoding="utf-8") as f:
        data = json.load(f)
    with open(args.detected, "r", encoding="utf-8") as f:
        detected = [ln.strip() for ln in f if ln.strip()]

    dims = data.get("dimensions", [])
    wl = list(DEFAULT_WHITELIST)
    if args.whitelist and os.path.isfile(args.whitelist):
        with open(args.whitelist, "r", encoding="utf-8") as f:
            wl += [ln.strip() for ln in f if ln.strip()]

    # 已编号集合
    numbered = {}
    for d in dims:
        numbered[norm(d.get("value", ""))] = d.get("no")
        nums = tuple(numbers(d.get("value", "")))
        if nums:
            numbered.setdefault("NUMS:" + ",".join(nums), d.get("no"))

    missing, exempt = [], []
    for raw in detected:
        n = norm(raw)
        if not n:
            continue
        if n in EXACT_WHITELIST:
            exempt.append({"text": raw, "reason": "图幅代号"})
            continue
        if any(w.upper() in n for w in wl):
            exempt.append({"text": raw, "reason": "命中免标白名单"})
            continue
        if n in numbered:
            continue
        nums = tuple(numbers(raw))
        if nums and ("NUMS:" + ",".join(nums)) in numbered:
            continue
        missing.append(raw)

    # 反向：编了号但图上没检测到的（可能是 AI 幻觉条目）
    ghost = []
    det_norm = set(norm(x) for x in detected)
    det_nums = set(",".join(numbers(x)) for x in detected)
    for d in dims:
        v = norm(d.get("value", ""))
        if v not in det_norm and ",".join(numbers(v)) not in det_nums and v != "":
            ghost.append({"no": d.get("no"), "value": d.get("value")})

    report = {
        "detected_total": len(detected),
        "numbered_total": len(dims),
        "missing": missing,
        "missing_count": len(missing),
        "exempt": exempt,
        "exempt_count": len(exempt),
        "ghost": ghost,
        "ghost_count": len(ghost),
        "pass": len(missing) == 0,
    }

    print("=" * 56)
    print("覆盖性自检报告")
    print("=" * 56)
    print("图上识别尺寸 : %d" % len(detected))
    print("已编气泡号   : %d" % len(dims))
    print("按规则免标   : %d" % len(exempt))
    print("应标未标     : %d" % len(missing))
    print("无来源条目   : %d" % len(ghost))
    print("-" * 56)
    if missing:
        print("[应标未标] 以下尺寸必须补号后重新校验：")
        for m in missing:
            print("   - %s" % m)
    if ghost:
        print("[无来源条目] 以下气泡号在图上未找到对应尺寸文本，需人工确认是否为误提：")
        for g in ghost:
            print("   - 气泡%s  %s" % (g["no"], g["value"]))
    if exempt:
        print("[免标] %s" % "、".join(e["text"] for e in exempt[:12]))

    rp = args.report or os.path.join(os.getcwd(), "coverage_report.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("-" * 56)
    print("报告: %s" % rp)

    if missing:
        print("[FAIL] 应标未标 > 0，禁止交付。请补号后重新运行。")
        return 1
    print("[PASS] 覆盖性自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
