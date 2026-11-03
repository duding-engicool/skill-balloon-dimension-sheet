# -*- coding: utf-8 -*-
"""
align_coords.py —— 用 OCR 实测坐标修正 dimensions.json 里的尺寸文本位置。

背景：AI 读图给出的 x/y 是估计值，估计不准时气泡会"贴错位置"。
OCR 的文字内容不可靠（Ø 常被读成 0），但 bbox 坐标是像素级实测。
本脚本把两者合并：内容用 AI 读的，坐标用 OCR 测的。

匹配规则（防错配三重约束）：
  1. 数字序列等价：两边文本都归一化为数字序列再比较（Ø→0、去 ×/-/R/Ra/°、
     去前导零），如 "Ø320"≡"0320"、"3×Ø12"≡"3X012"
  2. 就近贪心：候选对按欧氏距离升序逐一占用，一条 OCR 只能匹配一条尺寸
  3. 距离上限：候选距离 > --max-dist（归一化）直接拒绝，防止左视图的
     "209" 抢走右视图同名数字的坐标

匹配成功后写回：
  x/y            = OCR bbox 中心（归一化）
  tw/th          = 文本半宽/半高（归一化）——build_html.py 用它贴靠文字条边缘
  ocr_text/score = 痕迹字段，供人工核对
未匹配的条目保留原坐标并打印警告（AI 估计值，需人工在网页里核对）。

用法：
  python align_coords.py --dims dimensions.json --ocr ocr_result.json [--out dimensions.json]
退出码：0 正常（含部分未匹配）；2 参数/文件错误
"""
import sys, os, re, json, argparse

sys.stdout.reconfigure(encoding='utf-8')


def numkeys(s):
    """数字序列归一化的双变体：OCR 对 Ø 的处理不稳定（有时读成 0、有时直接丢失），
    因此对 Ø/Φ 同时生成「视作 0」和「删除」两个变体，任一相等即视为匹配。"""
    s = s.upper().replace('Φ', 'Ø')
    out = set()
    for repl in ('0', ''):
        t = s.replace('Ø', repl)
        ds = re.sub(r'[^0-9]', '', t).lstrip('0')
        out.add(ds if ds else '0')
    return out


def main():
    ap = argparse.ArgumentParser(description="OCR 实测坐标回填 dimensions.json")
    ap.add_argument('--dims', required=True)
    ap.add_argument('--ocr', required=True)
    ap.add_argument('--out', default=None, help='默认覆盖 --dims 原文件')
    ap.add_argument('--max-dist', type=float, default=0.25, help='匹配距离上限（归一化）')
    args = ap.parse_args()

    for p in (args.dims, args.ocr):
        if not os.path.isfile(p):
            print("[错误] 文件不存在: %s" % p)
            return 2

    data = json.load(open(args.dims, encoding='utf-8'))
    ocr = json.load(open(args.ocr, encoding='utf-8'))
    items = [it for it in ocr.get('items', []) if it.get('score', 0) >= 0.5]

    # 候选对生成 + 就近贪心
    cands = []
    for d in data.get('dimensions', []):
        ks = numkeys(str(d.get('value', '')))
        for i, it in enumerate(items):
            if not (numkeys(it['text']) & ks):
                continue
            dist = ((d.get('x', 0.5) - it['x']) ** 2 + (d.get('y', 0.5) - it['y']) ** 2) ** 0.5
            if dist <= args.max_dist:
                cands.append((dist, d.get('no'), i))
    cands.sort()
    used_dim, used_ocr, match = set(), set(), {}
    for dist, no, i in cands:
        if no in used_dim or i in used_ocr:
            continue
        used_dim.add(no)
        used_ocr.add(i)
        match[no] = (i, dist)

    # 回填
    updated, unmatched = 0, []
    for d in data.get('dimensions', []):
        no = d.get('no')
        if no in match:
            i, dist = match[no]
            it = items[i]
            d['x'] = it['x']
            d['y'] = it['y']
            d['tw'] = round(it['w'] / 2, 4)   # 文本半宽（归一化）
            d['th'] = round(it['h'] / 2, 4)   # 文本半高
            d['ocr_text'] = it['text']
            d['ocr_score'] = it['score']
            updated += 1
        else:
            unmatched.append(d)

    out = args.out or args.dims
    json.dump(data, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    print("[OK] 匹配 %d / %d 条，已回填 OCR 实测坐标 → %s" % (updated, len(data.get('dimensions', [])), out))
    if unmatched:
        print("[警告] %d 条未匹配（保留 AI 估计坐标，需人工核对）：" % len(unmatched))
        for d in unmatched:
            print("   气泡%s %s  估计坐标 x=%.3f y=%.3f" % (d.get('no'), d.get('value'), d.get('x', -1), d.get('y', -1)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
