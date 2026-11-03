#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_layout.py — 网页版气泡图生成后的几何自检

目的：在 build_html.py 生成 HTML 之后，用同一套几何规则（与网页一致的像素感知布局）
检查每个气泡相对对应尺寸的位置是否合适，避免「压字 / 太远 / 重叠 / 越界 / 方向错」。

输入：dimensions.json + 对应的底图（用于取图片像素尺寸）
输出：人类可读报告 + 退出码
  0 = 全部通过
  1 = 仅存在「间隙偏宽 / 轻微重叠」等警告，可交付但建议人工瞄一眼
  2 = 存在「压字 / 越界 / 方向错 / 明显重叠」等严重问题，禁止直接交付

几何规则（与 build_html.py 的 balloonGeom / calcBalloon 保持一致）：
  R   = 0.012 * W      （气泡半径，图片像素）
  FS  = 0.010 * W      （字号，图片像素）
  GAP = 3              （气泡与尺寸文本恒定间隙，图片像素）
  竖标(v)：气泡中心在尺寸中心正上方，间距 = (R + 文本半高 + GAP) / H
  横标(h)：气泡中心在尺寸中心右侧，间距 = (文本半宽 + R + GAP) / W
  文本半宽 hw = max(FS*0.6, len(value)*FS*0.58)；文本半高 vh = FS*0.6

用法：
  python verify_layout.py --dims dimensions.json --images 1:法兰盘.png
  python verify_layout.py --dims dimensions.json --images 1:法兰盘.png --json report.json
"""

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def image_size(path):
    """读取底图像素尺寸（与 build_html.py 同源逻辑）。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".svg":
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(4096)
            import re
            m = re.search(r'viewBox=["\']\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)', head)
            if m:
                return (float(m.group(1)), float(m.group(2)))
        except Exception:
            pass
        return (1000.0, 700.0)
    try:
        from PIL import Image
        with Image.open(path) as im:
            return (float(im.size[0]), float(im.size[1]))
    except Exception:
        pass
    try:
        with open(path, "rb") as f:
            raw = f.read(4096)
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            return (float(int.from_bytes(raw[16:20], "big")),
                    float(int.from_bytes(raw[20:24], "big")))
    except Exception:
        pass
    return (1000.0, 700.0)


def text_half(value, FS):
    """尺寸文本的半宽/半高（图片像素），用于「压字」判定。"""
    vh = FS * 0.6
    hw = max(FS * 0.6, len(str(value or "")) * FS * 0.58)
    return hw, vh


def ideal_pos(d, W, H, R, FS):
    """复算网页 calcBalloon 的自动布局位置（归一化）。
    与 build_html.py 一致：优先用 align_coords.py 回填的 OCR 实测 tw/th（归一化），
    否则按字符数估算。"""
    x = d.get("x", 0.5)
    y = d.get("y", 0.5)
    if d.get("tw") is not None and d.get("th") is not None:
        tw, th = d["tw"], d["th"]
    else:
        hw, vh = text_half(d.get("value", ""), FS)
        tw, th = hw / W, vh / H
    if d.get("orient", "h") == "v":
        return {"x": x, "y": y - th - (R + 3) / H}
    return {"x": x + tw + (R + 3) / W, "y": y}


def apply_nudge(items, W, H, manual_nos):
    """不做自动避让：直接返回原始位置。重叠/压字由人工拖拽解决。
    （自动避让在密集区容易堆到图顶越界、间距失控，不如保留原始紧贴位置 + 自检报告）"""
    return {it["no"]: (it["cx"] / W, it["cy"] / H) for it in items}


def verify(dims, sizes):
    errors, warns = [], []
    pages = sorted(set(str(d.get("page", "1")) for d in dims))
    for pg in pages:
        pdims = [d for d in dims if str(d.get("page", "1")) == pg]
        W, H = sizes.get(pg, (1000.0, 700.0))
        R = 0.012 * W
        FS = 0.010 * W
        items = []
        for d in pdims:
            if d.get("bx") is not None and d.get("by") is not None:
                bx, by = d["bx"], d["by"]
            else:
                ideal = ideal_pos(d, W, H, R, FS)
                bx, by = ideal["x"], ideal["y"]
            cx, cy = bx * W, by * H
            dx, dy = d.get("x", 0.5) * W, d.get("y", 0.5) * H
            orient = d.get("orient", "h")
            # 压字判定的文本半宽/半高：优先 OCR 实测（tw/th 归一化 → 像素）
            if d.get("tw") is not None and d.get("th") is not None:
                hw, vh = d["tw"] * W, d["th"] * H
            else:
                hw, vh = text_half(d.get("value", ""), FS)
            items.append({"no": d.get("no"), "value": d.get("value"), "orient": orient,
                          "cx": cx, "cy": cy, "dx": dx, "dy": dy, "R": R, "FS": FS, "hw": hw, "vh": vh})
        # 与网页一致的防重叠避让（仅自动项），后续判定都用避让后的最终位置
        manual_nos = {d.get("no") for d in pdims if d.get("bx") is not None and d.get("by") is not None}
        nudged = apply_nudge(items, W, H, manual_nos)
        for it in items:
            nx, ny = nudged[it["no"]]
            it["cx"], it["cy"] = nx * W, ny * H

        # 1) 间隙 + 方向一致性（逐条）
        for it in items:
            orient = it["orient"]
            if orient == "v":
                gap = (it["dy"] - it["cy"]) - it["R"] - it["vh"]
                direction_ok = it["cy"] < it["dy"] - 1
            else:
                gap = (it["cx"] - it["dx"]) - it["R"] - it["hw"]
                direction_ok = it["cx"] > it["dx"] + 1
            if not direction_ok:
                errors.append("气泡%d(%s) 方向异常：%s 标应位于%s，但实际相反"
                              % (it["no"], it["value"], "竖标" if orient == "v" else "横标",
                                 "尺寸上方" if orient == "v" else "尺寸右侧"))
            elif gap < 0:
                errors.append("气泡%d(%s) 压住尺寸文本（重叠约 %.1fpx）" % (it["no"], it["value"], -gap))
            elif gap > max(it["R"] * 2.5, 45):
                warns.append("气泡%d(%s) 与尺寸间距偏大(%.1fpx)，可能看不出对应" % (it["no"], it["value"], gap))

        # 2) 越界（气泡整体应落在图内）
        for it in items:
            if it["cx"] < it["R"] or it["cx"] > W - it["R"] or it["cy"] < it["R"] or it["cy"] > H - it["R"]:
                errors.append("气泡%d(%s) 超出底图边界" % (it["no"], it["value"]))

        # 3) 气泡两两重叠（阈值与 apply_nudge 的 minD 对齐，避免把已避让结果误报）
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if a["no"] == b["no"]:
                    continue
                dist = ((a["cx"] - b["cx"]) ** 2 + (a["cy"] - b["cy"]) ** 2) ** 0.5
                sumR = a["R"] + b["R"]
                if dist < sumR * 0.95:
                    # 两圆相交（真正压到一起），必须处理
                    errors.append("气泡%d 与 气泡%d 重叠(间距%.1f < 2R*0.95≈%.1f)"
                                  % (a["no"], b["no"], dist, sumR * 0.95))
                elif dist < sumR * 1.15:
                    # 相切/极近：密集阵列常见，提示人工拖开，不算错误
                    warns.append("气泡%d 与 气泡%d 相切(间距%.1fpx)，密集区建议拖开"
                                 % (a["no"], b["no"], dist))
    return errors, warns


def main():
    ap = argparse.ArgumentParser(description="网页版气泡图几何自检")
    ap.add_argument("--dims", required=True)
    ap.add_argument("--images", required=True, help="底图映射，如 1:法兰盘.png")
    ap.add_argument("--json", default="", help="可选：报告写到该 JSON 文件")
    args = ap.parse_args()

    if not os.path.isfile(args.dims):
        print("[错误] dimensions.json 不存在: %s" % args.dims)
        return 1
    with open(args.dims, "r", encoding="utf-8") as f:
        data = json.load(f)
    dims = data.get("dimensions", [])

    imgs = {}
    for part in args.images.split(";"):
        if ":" in part and not part.startswith("http"):
            k, v = part.split(":", 1)
        else:
            k, v = "1", part
        imgs[str(k).strip()] = v.strip().strip('"')

    sizes = {}
    for p, path in imgs.items():
        if not os.path.isfile(path):
            print("[警告] 底图不存在: %s（按默认 1000x700 估算）" % path)
            sizes[p] = (1000.0, 700.0)
        else:
            sizes[p] = image_size(path)

    errors, warns = verify(dims, sizes)

    print("=" * 56)
    print("网页版气泡图 · 几何自检报告")
    print("=" * 56)
    print("尺寸总数: %d" % len(dims))
    if not errors and not warns:
        print("✅ 全部通过：气泡与尺寸间距合适、无重叠、无越界、方向正确。")
    else:
        if errors:
            print("\n❌ 严重问题（%d 项，禁止直接交付，需调整）：" % len(errors))
            for e in errors:
                print("   - " + e)
        if warns:
            print("\n⚠️  警告（%d 项，可交付但建议人工瞄一眼）：" % len(warns))
            for w in warns:
                print("   - " + w)
    print("=" * 56)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"errors": errors, "warns": warns,
                       "exit_code": 2 if errors else (1 if warns else 0)}, f, ensure_ascii=False, indent=2)

    return 2 if errors else (1 if warns else 0)


if __name__ == "__main__":
    sys.exit(main())
