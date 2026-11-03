#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_xlsx.py — 由 dimensions.json 生成检验尺寸表 Excel

Sheet1 汇总：图纸信息 + 统计 + 待确认清单 + 基准清单
Sheet2 尺寸明细：13 列

用法：
    python build_xlsx.py --dims dimensions.json --out 法兰盘_检验尺寸表.xlsx
    python build_xlsx.py --dims dimensions.json --coords coordinates.json --out 表.xlsx

退出码：0 成功 / 1 参数或文件错误
"""

import argparse
import json
import os
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

RED = "C8102E"
HEAD_FILL = PatternFill("solid", fgColor="F1EFE8")
TODO_FILL = PatternFill("solid", fgColor="FBE9EB")
KEY_FILL = PatternFill("solid", fgColor="FCEBEB")
THIN = Side(style="thin", color="D3D1C7")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

COLS = [
    ("no", "气泡号", 8), ("page", "图纸页", 8), ("view", "视图", 12),
    ("value", "尺寸值", 12), ("type", "类型", 10), ("desc", "部位描述", 20),
    ("char_class", "特性分类", 10), ("explicit_tol", "显式公差", 12),
    ("final_tol", "最终公差", 14), ("tol_source", "公差来源", 16),
    ("gauge", "量具", 14), ("insp_type", "检验类别", 12), ("freq", "检验频次", 12),
]

TYPE_CN = {
    "linear": "长度", "diameter": "直径", "radius": "半径", "hole": "孔径",
    "angle": "角度", "thread": "螺纹", "gdnt": "形位", "chamfer": "倒角",
    "roughness": "粗糙度", "other": "其他",
}


def is_todo(d):
    if d.get("need_confirm"):
        return True
    for k in ("final_tol", "tol_source", "freq", "gauge"):
        if "待确认" in str(d.get(k, "")):
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description="生成检验尺寸表 Excel")
    ap.add_argument("--dims", required=True, help="dimensions.json 路径")
    ap.add_argument("--coords", default="", help="可选：网页导出的 coordinates/dimensions.json，用于合并拖拽后的坐标")
    ap.add_argument("--out", required=True, help="输出 xlsx 路径")
    args = ap.parse_args()

    if not os.path.isfile(args.dims):
        print("[错误] dimensions.json 不存在: %s" % args.dims)
        return 1
    with open(args.dims, "r", encoding="utf-8") as f:
        data = json.load(f)

    dims = data.get("dimensions", [])
    if not dims:
        print("[错误] dimensions.json 中没有尺寸条目")
        return 1

    if args.coords and os.path.isfile(args.coords):
        with open(args.coords, "r", encoding="utf-8") as f:
            cd = json.load(f)
        m = {str(d.get("no")): d for d in cd.get("dimensions", [])}
        hit = 0
        for d in dims:
            s = m.get(str(d.get("no")))
            if s and s.get("x") is not None:
                d["x"], d["y"] = s["x"], s["y"]
                hit += 1
        print("[信息] 已合并 %d 条拖拽坐标" % hit)

    wb = Workbook()

    # ---------- Sheet1 汇总 ----------
    ws = wb.active
    ws.title = "汇总"
    src = data.get("source", {})
    gt = data.get("general_tolerance", {})
    row = 1

    def kv(k, v):
        nonlocal row
        ws.cell(row=row, column=1, value=k).font = Font(bold=True, size=11)
        ws.cell(row=row, column=2, value=v)
        ws.cell(row=row, column=1).border = BORDER
        ws.cell(row=row, column=2).border = BORDER
        row += 1

    def sec(t):
        nonlocal row
        row += 1
        c = ws.cell(row=row, column=1, value=t)
        c.font = Font(bold=True, size=12, color=RED)
        row += 1

    ws.cell(row=row, column=1, value="图纸气泡图检验尺寸表").font = Font(bold=True, size=14, color=RED)
    row += 2

    sec("一、图纸信息")
    kv("源文件", src.get("file", ""))
    kv("图号", src.get("drawing_no", "") or "未标注")
    kv("名称", src.get("name", "") or "未标注")
    kv("版本", src.get("version", "") or "未标注")
    kv("单位", data.get("unit", "mm"))
    kv("一般公差声明", gt.get("text", "") or ("未声明" if not gt.get("declared") else ""))
    kv("线性公差", gt.get("linear", "") or "—")
    kv("形位公差", gt.get("geometric", "") or "—")

    sec("二、统计")
    tc = Counter(TYPE_CN.get(d.get("type", "other"), "其他") for d in dims)
    cc = Counter(d.get("char_class", "一般") or "一般" for d in dims)
    todo = [d for d in dims if is_todo(d)]
    lowconf = [d for d in dims if (d.get("confidence") or 1) < 0.8]
    kv("尺寸总数", len(dims))
    kv("页数", len(set(str(d.get("page", 1)) for d in dims)))
    kv("类型分布", "、".join("%s %d" % (k, v) for k, v in tc.most_common()))
    kv("特性分类", "、".join("%s %d" % (k, v) for k, v in cc.most_common()))
    kv("待确认项", len(todo))
    kv("低置信度项", len(lowconf))

    sec("三、待确认清单（须工程师确认后定稿）")
    hdr = ["气泡号", "尺寸值", "部位描述", "待确认内容", "说明"]
    for i, h in enumerate(hdr, start=1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = Font(bold=True)
        c.fill = HEAD_FILL
        c.border = BORDER
    row += 1
    if todo:
        for d in todo:
            items = []
            if "待确认" in str(d.get("final_tol", "")):
                items.append("最终公差")
            if "待确认" in str(d.get("tol_source", "")):
                items.append("公差来源")
            if "待确认" in str(d.get("gauge", "")):
                items.append("量具")
            if "待确认" in str(d.get("freq", "")):
                items.append("检验频次")
            if d.get("need_confirm"):
                items.append("识别置信度低")
            ws.cell(row=row, column=1, value=d.get("no"))
            ws.cell(row=row, column=2, value=d.get("value", ""))
            ws.cell(row=row, column=3, value=d.get("desc", ""))
            ws.cell(row=row, column=4, value="、".join(items) or "待确认")
            ws.cell(row=row, column=5, value=d.get("final_tol", ""))
            for i in range(1, 6):
                ws.cell(row=row, column=i).border = BORDER
                ws.cell(row=row, column=i).fill = TODO_FILL
            row += 1
    else:
        ws.cell(row=row, column=1, value="无")
        row += 1

    sec("四、基准清单（基准符号不编气泡号）")
    ws.cell(row=row, column=1, value="基准")
    ws.cell(row=row, column=2, value="所在要素")
    ws.cell(row=row, column=3, value="备注")
    for i in range(1, 4):
        ws.cell(row=row, column=i).font = Font(bold=True)
        ws.cell(row=row, column=i).fill = HEAD_FILL
        ws.cell(row=row, column=i).border = BORDER
    row += 1
    ws.cell(row=row, column=1, value="（由工程师填写）")
    row += 1

    sec("五、量具与频次说明")
    ws.cell(row=row, column=1,
            value="量具与检验频次为按规则推导的建议值，须工程师确认；"
                  "抽样方案（GB/T 2828.1 检验水平与 AQL）未默认套用，按公司标准填写。")
    row += 2
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 24
    for L in "CDE":
        ws.column_dimensions[L].width = 22

    # ---------- Sheet2 尺寸明细 ----------
    wd = wb.create_sheet("尺寸明细")
    for i, (_, cn, w) in enumerate(COLS, start=1):
        c = wd.cell(row=1, column=i, value=cn)
        c.font = Font(bold=True)
        c.fill = HEAD_FILL
        c.border = BORDER
        c.alignment = Alignment(horizontal="center", vertical="center")
        wd.column_dimensions[get_column_letter(i)].width = w
    wd.freeze_panes = "A2"

    dims_sorted = sorted(dims, key=lambda d: (str(d.get("page", 1)), int(d.get("no", 0) or 0)))
    for r, d in enumerate(dims_sorted, start=2):
        for i, (k, _, _) in enumerate(COLS, start=1):
            v = d.get(k, "")
            if k == "type":
                v = TYPE_CN.get(v, v)
            if v in (None, ""):
                v = "—"
            c = wd.cell(row=r, column=i, value=v)
            c.border = BORDER
            c.alignment = Alignment(vertical="center")
            if "待确认" in str(v):
                c.fill = TODO_FILL
            if k == "char_class" and v == "关键":
                c.fill = KEY_FILL
                c.font = Font(bold=True, color=RED)
    wd.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(COLS)), len(dims_sorted) + 1)

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    wb.save(out)
    print("[OK] 检验尺寸表: %s" % out)
    print("     尺寸 %d 条 · 待确认 %d 条 · 低置信 %d 条" % (len(dims), len(todo), len(lowconf)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
