#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_dwg.py — DWG → DXF → SVG 底图 + 多图框检测（DWG 路线专用）

前置依赖：
    1. ODA File Converter（免费，https://www.opendesign.com/guestfiles/oda_file_converter）
       用于 DWG → DXF；ezdxf 不支持直接写/读 DWG
    2. Python 包：ezdxf、matplotlib

用法：
    python render_dwg.py --dwg 图纸.dwg --outdir out/
    python render_dwg.py --dwg 图纸.dwg --outdir out/ --oda "C:/Program Files/ODA/ODAFileConverter 25.4/ODAFileConverter.exe"

输出：
    out/<名>.dxf              转换后的 DXF
    out/<名>_<布局>.svg        每个布局一张底图
    out/sheet_index.json      图框检测结果，供与用户确认"这是几张图"

退出码：0 成功 / 2 缺依赖（ODA 或 ezdxf/matplotlib）

重要：渲染底图对 SHX 工程字体与中文可能失真。
交付时必须提示用户「以原 DWG 为准」；若用户能提供 PDF 导出，优先用 PDF 做底图。
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 标准图幅（mm），用于图框检测
STD_SIZES = {
    "A0": (841, 1189), "A1": (594, 841), "A2": (420, 594),
    "A3": (297, 420), "A4": (210, 297),
}


def find_oda():
    """探测 ODA File Converter 可执行文件。"""
    env = os.environ.get("ODA_FILE_CONVERTER", "")
    if env and os.path.isfile(env):
        return env
    which = shutil.which("ODAFileConverter")
    if which:
        return which
    pats = [
        r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
        r"C:\Program Files\ODA\Teigha File Converter*\TeighaFileConverter.exe",
        r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe",
        r"C:\Program Files (x86)\ODA\Teigha File Converter*\TeighaFileConverter.exe",
    ]
    for p in pats:
        hit = sorted(glob.glob(p))
        if hit:
            return hit[-1]
    return ""


def dwg_to_dxf(oda, dwg, outdir, ver="ACAD2018"):
    """ODAFileConverter 输入目录 输出目录 版本 类型 递归 审计 过滤"""
    cmd = [oda, os.path.dirname(os.path.abspath(dwg)), outdir, ver, "DXF", "0", "1",
           os.path.basename(dwg)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        print("[错误] 调用 ODA 失败: %s" % e)
        return ""
    # ODA 会按输入目录结构复制子目录，递归找一下
    stem = os.path.splitext(os.path.basename(dwg))[0]
    cand = []
    for root, _, files in os.walk(outdir):
        for f in files:
            if f.lower().endswith(".dxf") and os.path.splitext(f)[0].lower() == stem.lower():
                cand.append(os.path.join(root, f))
    if cand:
        return cand[0]
    print("[错误] ODA 未产出 DXF。返回码 %s" % r.returncode)
    if r.stdout:
        print("  stdout: %s" % r.stdout[:800])
    if r.stderr:
        print("  stderr: %s" % r.stderr[:800])
    return ""


def rect_of(e):
    """从 LWPOLYLINE/POLYLINE 提取轴对齐矩形包围盒，非矩形返回 None。"""
    try:
        pts = [(p[0], p[1]) for p in e.get_points("xy")] if e.dxftype() == "LWPOLYLINE" else None
    except Exception:
        pts = None
    if not pts or len(pts) < 4:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def detect_frames(entities, tol=8.0):
    """在实体中找近似标准图幅的矩形，返回 [(bbox, 图幅名, 宽, 高)]"""
    out = []
    for e in entities:
        if e.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
            continue
        r = rect_of(e)
        if not r:
            continue
        w, h = r[2] - r[0], r[3] - r[1]
        if w <= 0 or h <= 0:
            continue
        for name, (sw, sh) in STD_SIZES.items():
            for a, b in ((sw, sh), (sh, sw)):
                if abs(w - a) <= tol and abs(h - b) <= tol:
                    out.append({"bbox": [round(v, 2) for v in r],
                                "size": [round(w, 1), round(h, 1)],
                                "std": name})
                    break
            else:
                continue
            break
    return out


def main():
    ap = argparse.ArgumentParser(description="DWG/DXF 转底图 + 多图框检测")
    ap.add_argument("--dwg", default="", help="DWG 路径（需 ODA 转 DXF）")
    ap.add_argument("--dxf", default="", help="DXF 路径（已有 DXF 时直接渲染，不需要 ODA）")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--oda", default="", help="ODAFileConverter.exe 路径")
    ap.add_argument("--fmt", default="svg", choices=["svg", "png"])
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()

    if not args.dwg and not args.dxf:
        print("[错误] 必须提供 --dwg 或 --dxf 之一")
        return 2

    try:
        import ezdxf
    except ImportError:
        print("[错误] 缺少 ezdxf。安装：")
        print("  pip install -i https://pypi.org/simple ezdxf matplotlib")
        return 2

    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)

    if args.dxf:
        if not os.path.isfile(args.dxf):
            print("[错误] DXF 不存在: %s" % args.dxf)
            return 2
        dxf = args.dxf
        stem = os.path.splitext(os.path.basename(args.dxf))[0]
        print("[信息] 直接使用 DXF，跳过 ODA 转换")
    else:
        if not os.path.isfile(args.dwg):
            print("[错误] DWG 不存在: %s" % args.dwg)
            return 2
        oda = args.oda or find_oda()
        if not oda:
            print("[错误] 未找到 ODA File Converter。")
            print("  1) 下载安装：https://www.opendesign.com/guestfiles/oda_file_converter")
            print("  2) 或用 --oda 指定 ODAFileConverter.exe 路径，或设环境变量 ODA_FILE_CONVERTER")
            print("  3) 也可以让用户直接提供该图的 PDF 导出作为底图（推荐，渲染质量更好）")
            return 2
        print("[信息] ODA: %s" % oda)
        stem = os.path.splitext(os.path.basename(args.dwg))[0]
        dxf = dwg_to_dxf(oda, args.dwg, outdir)
        if not dxf:
            return 2
        print("[OK] DXF: %s" % dxf)

    doc = ezdxf.readfile(dxf)

    index = {"file": os.path.basename(args.dwg), "dxf": dxf, "layouts": [], "images": {}}
    layouts = [n for n in doc.layouts.names() if not n.startswith("*")]
    if "Model" in doc.layouts.names():
        layouts = ["Model"] + [n for n in layouts if n != "Model"]

    for lname in layouts:
        try:
            lay = doc.layouts.get(lname)
        except Exception:
            continue
        ents = list(lay)
        if not ents and lname != "Model":
            continue  # 空布局不渲染，避免产出空白图干扰用户判断
        texts = []
        for e in ents:
            if e.dxftype() in ("TEXT",):
                texts.append(e.dxf.text)
            elif e.dxftype() == "MTEXT":
                try:
                    texts.append(e.text)
                except Exception:
                    pass
        frames = detect_frames(ents)
        img = ""
        out_img = os.path.join(outdir, "%s_%s.%s" % (stem, re.sub(r"[^\w\u4e00-\u9fa5-]", "_", lname), args.fmt))
        try:
            from ezdxf.addons.drawing.matplotlib import qsave
            # 必须传 layout 对象，传实体 list 会报 AttributeError: 'list' object has no attribute 'doc'
            qsave(lay, out_img, dpi=args.dpi, bg="#FFFFFF")
        except ImportError:
            print("[警告] 布局 %s 未渲染：缺少 matplotlib。安装：" % lname)
            print("       pip install -i https://pypi.org/simple matplotlib")
        except Exception as e:
            import traceback
            print("[错误] 布局 %s 渲染失败：%s" % (lname, e))
            traceback.print_exc()
        if os.path.isfile(out_img) and os.path.getsize(out_img) > 0:
            img = out_img
            print("[OK] 底图: %s" % out_img)
        else:
            print("[错误] 布局 %s 未产出底图，DWG 自动渲染不可用。" % lname)
            print("       请让用户提供该图的 PDF 导出作为底图（推荐）。")

        index["layouts"].append({
            "name": lname,
            "entity_count": len(ents),
            "frames": frames,
            "title_hint": [t for t in texts if t.strip()][:40],
            "image": img,
        })
        if img:
            index["images"][lname] = img

    with open(os.path.join(outdir, "sheet_index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print("=" * 56)
    print("图框检测结果（请与用户确认「这是几张图」）")
    print("=" * 56)
    for L in index["layouts"]:
        print("布局 %s：实体 %d，检测到图框 %d 个 %s"
              % (L["name"], L["entity_count"], len(L["frames"]),
                 [f["std"] for f in L["frames"]]))
    print("索引: %s" % os.path.join(outdir, "sheet_index.json"))
    print("[提示] 自动检测的图框可能误判（剖面线块、明细栏）。必须让用户看缩略图确认后再编号。")
    print("[提示] 渲染底图的 SHX 工程字体与中文可能失真，交付时须注明「以原 DWG 为准」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
