#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_html.py — 生成网页版气泡标注图（单文件、双击即开、气泡可拖拽）

输入：dimensions.json + 底图（PNG/JPG/SVG）
输出：单文件 HTML，底图内联为 base64，无需 Web 服务、无需联网

用法：
    python build_html.py --dims dimensions.json --images 1:法兰盘.png --out 法兰盘_气泡标注图.html
    python build_html.py --dims dimensions.json --images 1:p1.png;2:p2.png --out 多页_气泡标注图.html

退出码：0 成功 / 1 参数或文件错误
"""

import argparse
import base64
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RED = "#C8102E"
RED_SOFT = "#FBE9EB"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
:root{--red:__RED__;--red-soft:__REDSOFT__;--bd:#E3E3E0;--tx:#2C2C2A;--tx2:#6B6B66;--bg:#F7F7F5}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:var(--tx);background:var(--bg);font-size:14px}
header{background:#fff;border-bottom:1px solid var(--bd);padding:12px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
header h1{font-size:16px;font-weight:600;margin:0;color:var(--red)}
.meta{font-size:12px;color:var(--tx2)}
.tabs{display:flex;gap:6px}
.tab{padding:5px 14px;border:1px solid var(--bd);background:#fff;border-radius:6px;cursor:pointer;font-size:13px}
.tab.on{background:var(--red);color:#fff;border-color:var(--red)}
.actions{margin-left:auto;display:flex;gap:8px}
.btn{padding:6px 14px;border:1px solid var(--bd);background:#fff;border-radius:6px;cursor:pointer;font-size:13px}
.btn:hover{border-color:var(--red);color:var(--red)}
.btn.primary{background:var(--red);color:#fff;border-color:var(--red)}
main{display:flex;gap:16px;padding:16px 20px;align-items:flex-start}
@media(max-width:1100px){main{flex-direction:column}}
.panel{background:#fff;border:1px solid var(--bd);border-radius:10px;overflow:hidden}
.canvas{flex:1 1 auto;min-width:0;position:relative}
.stage{position:relative;width:100%;line-height:0}
.stage img{width:100%;height:auto;display:block}
.stage svg{position:absolute;inset:0;width:100%;height:100%}
#leads{position:absolute;inset:0;width:100%;height:100%}
#leads .bl{cursor:grab}
#leads .bl:active{cursor:grabbing}
#leads .bl circle{fill:#fff;stroke:var(--red);stroke-width:1.5}
#leads .bl.on circle{fill:var(--red)}
#leads .bl text{fill:var(--red);font-weight:600;text-anchor:middle;dominant-baseline:central;pointer-events:none;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
#leads .bl.on text{fill:#fff}
#leads .bl.conf circle{stroke-dasharray:3.5 2.5}
.side{flex:0 0 46%;max-height:80vh;overflow:auto}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{border:1px solid var(--bd);padding:5px 7px;text-align:left;white-space:nowrap}
th{background:#F1EFE8;font-weight:600;position:sticky;top:0;z-index:2}
tr{cursor:pointer}
tr.on td{background:var(--red-soft)}
td.todo{color:#9A3412}
.tip{padding:8px 20px;font-size:12px;color:var(--tx2)}
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <span class="meta">__META__</span>
  <div class="tabs">__TABS__</div>
  <div class="actions">
    <button class="btn" onclick="resetAll()">还原位置</button>
    <button class="btn" onclick="exportCSV()">导出表格 CSV</button>
    <button class="btn primary" onclick="exportJSON()">导出 dimensions.json</button>
  </div>
</header>
<div class="tip">气泡已紧贴对应尺寸文本（竖标在其上方、横标/特殊尺寸在其右侧），一眼对应；气泡与底图同一坐标系、随浏览器缩放等比例，缩放窗口不会漂移。拖拽可微调避让；点击气泡或表格行双向高亮；调完点「导出 dimensions.json」，再跑 build_xlsx.py 出表。虚线圈 = 低置信度待确认项。</div>
<main>
  <div class="panel canvas"><div class="stage" id="stage">
    <img id="base" src="" alt="底图">
    <svg id="leads" viewBox="__VIEWBOX__"></svg>
  </div></div>
  <div class="panel side"><table id="tbl"><thead>__THEAD__</thead><tbody></tbody></table></div>
</main>
<script>
const DATA = __DATA__;
const PAGES = __PAGES__;
const SIZES = __SIZES__;
let cur = PAGES[0];
const pos = {};
// 气泡几何：半径/字号随图片宽等比例；偏移按尺寸文本实际长度留恒定 GAP_PX 间隙（图片像素）
function balloonGeom(){
  const W = SIZES[cur][0], H = SIZES[cur][1];
  return {W:W, H:H, R:0.012*W, FS:0.010*W};
}
const GAP_PX = 3;  // 气泡与尺寸文本的恒定间隙（图片像素），随图等比例缩放
function calcBalloon(d){
  const g = balloonGeom();
  const x = (d.x==null?0.5:d.x), y = (d.y==null?0.5:d.y);
  const o = (d.orient||'h');
  // 文本半宽/半高：优先用 align_coords.py 回填的 OCR 实测值（tw/th），
  // 否则按字符数估算（估算对长文本误差大，是"气泡离尺寸远"的主因）
  const hasTw = (d.tw!=null && d.th!=null);
  const tw = hasTw ? d.tw : Math.max(g.FS*0.6, String(d.value||'').length*g.FS*0.58)/g.W;
  const th = hasTw ? d.th : Math.max(g.FS*0.6, String(d.value||'').length*g.FS*0.58)/g.H;
  if(o==='v'){
    // 竖排（旋转90°长条文字）：气泡推到文字条顶端上方
    // 注意单位：tw/th 是归一化值，R/GAP_PX 是图片像素，须先换算再相加
    const dy = th + (g.R + GAP_PX) / g.H;
    return {x:x, y:y - dy};
  }
  // 横排：气泡放文字右侧
  const dx = tw + (g.R + GAP_PX) / g.W;
  return {x:x + dx, y:y};
}
const manualNos = new Set();
function initPos(){
  DATA.dimensions.forEach(d=>{
    if(d.bx!=null && d.by!=null){ pos[d.no] = {x:d.bx, y:d.by}; manualNos.add(d.no); }  // 已拖拽/手动：直接用，不再自动避让
    else { pos[d.no] = calcBalloon(d); }                            // 否则按尺寸中心 + 方向自动算
  });
}
// 防重叠自动避让：保持方向语义（竖标仅沿 y 向上、横标仅沿 x 向右）。
// 1) 同方向组内按序单向堆叠；2) 跨方向对按各自轴补充推开。迭代至收敛。
// 仅作用于自动布局项（手动项不动）。结果与 verify_layout.py 的 apply_nudge 一致。
function antiOverlap(){
  const W = SIZES[cur][0], H = SIZES[cur][1], R = 0.012*W;
  const minD = 2*R*1.15;   // 留 15% 半径间隙，气泡间不贴死
  const oOf = no => { const d = DATA.dimensions.find(x=>String(x.no)===String(no)); return (d&&d.orient)||'h'; };
  for(let pass=0; pass<60; pass++){
    // 1) 组内排序单向推（竖标 y 升序：下方者推到上方者之上；横标 x 升序：右侧者推到左侧者之右）
    for(const o of ['v','h']){
      const grp = dimsOf(cur).filter(d=>!manualNos.has(d.no) && oOf(d.no)===o)
        .map(d=>({no:d.no, p:pos[d.no]}))
        .sort((a,b)=> o==='v' ? a.p.y-b.p.y : a.p.x-b.p.x);
      for(let i=1;i<grp.length;i++){
        const a=grp[i-1], b=grp[i];
        if(o==='v'){ if(b.p.y > a.p.y - minD/H) b.p.y = Math.max(0.01, a.p.y - minD/H); }
        else        { if(b.p.x > a.p.x - minD/W) b.p.x = Math.min(0.99, a.p.x + minD/W); }
        pos[b.no]=b.p;
      }
    }
    // 2) 跨方向对按各自轴补充推（竖标向上、横标向右），解除跨组重叠
    const list = dimsOf(cur).filter(d=>!manualNos.has(d.no)).map(d=>({no:d.no, o:oOf(d.no), p:pos[d.no]}));
    let moved=false;
    for(let i=0;i<list.length;i++) for(let j=i+1;j<list.length;j++){
      const a=list[i], b=list[j];
      if(a.o===b.o) continue;
      const dxp=(b.p.x-a.p.x)*W, dyp=(b.p.y-a.p.y)*H;
      const dist=Math.hypot(dxp,dyp);
      if(dist<minD && dist>1e-6){
        const gap=(minD-dist)/2;
        if(a.o==='v') a.p.y=Math.max(0.01,a.p.y-gap/H); else a.p.x=Math.min(0.99,a.p.x+gap/W);
        if(b.o==='v') b.p.y=Math.max(0.01,b.p.y-gap/H); else b.p.x=Math.min(0.99,b.p.x+gap/W);
        pos[a.no]=a.p; pos[b.no]=b.p; moved=true;
      }
    }
    if(!moved) break;
  }
}
function dimsOf(p){return DATA.dimensions.filter(d=>String(d.page||1)===String(p));}
const NS = 'http://www.w3.org/2000/svg';
function render(){
  const p = cur;
  const g = balloonGeom();
  const W = g.W, H = g.H, R = g.R, FS = g.FS;   // 气泡半径/字号随图等比例
  document.getElementById('base').src = IMAGES[p];
  const svg = document.getElementById('leads');
  svg.setAttribute('viewBox','0 0 '+W+' '+H);
  while(svg.firstChild) svg.removeChild(svg.firstChild);
  dimsOf(p).forEach(d=>{
    const c = pos[d.no];
    const grp = document.createElementNS(NS,'g');
    grp.setAttribute('class','bl' + (d.need_confirm ? ' conf' : ''));
    grp.dataset.no = d.no;
    const cx = c.x*W, cy = c.y*H;
    const cir = document.createElementNS(NS,'circle');
    cir.setAttribute('cx',cx); cir.setAttribute('cy',cy); cir.setAttribute('r',R);
    const tx = document.createElementNS(NS,'text');
    tx.setAttribute('x',cx); tx.setAttribute('y',cy); tx.setAttribute('font-size',FS);
    tx.textContent = d.no;
    grp.appendChild(cir); grp.appendChild(tx);
    grp.addEventListener('pointerdown', startDrag);
    svg.appendChild(grp);
  });
  renderTable();
}
function clientToNorm(e){
  const svg = document.getElementById('leads');
  const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
  const p = pt.matrixTransform(svg.getScreenCTM().inverse());
  return {x: p.x/SIZES[cur][0], y: p.y/SIZES[cur][1]};
}
function startDrag(ev){
  ev.preventDefault();
  const grp = ev.currentTarget, no = grp.dataset.no;
  const W = SIZES[cur][0], H = SIZES[cur][1];
  function mv(e){
    let n = clientToNorm(e);
    n.x = Math.min(0.995, Math.max(0.005, n.x));
    n.y = Math.min(0.995, Math.max(0.005, n.y));
    pos[no] = n;
    const cx = n.x*W, cy = n.y*H;
    grp.querySelector('circle').setAttribute('cx',cx);
    grp.querySelector('circle').setAttribute('cy',cy);
    grp.querySelector('text').setAttribute('x',cx);
    grp.querySelector('text').setAttribute('y',cy);
  }
  function up(){ window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); }
  window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
  hl(no);
}
// drawLead 已移除：气泡紧贴尺寸文本旁，不再绘制引线（用户方案 v1.0.2）
function hl(no){
  document.querySelectorAll('#leads .bl').forEach(e=>e.classList.toggle('on', e.dataset.no==String(no)));
  document.querySelectorAll('#tbl tbody tr').forEach(tr=>tr.classList.toggle('on', tr.dataset.no==String(no)));
  const t = document.querySelector('#tbl tbody tr[data-no="'+no+'"]');
  if(t) t.scrollIntoView({block:'nearest'});
}
const COLS = __COLS__;
function renderTable(){
  const tb = document.querySelector('#tbl tbody');
  tb.innerHTML = '';
  dimsOf(cur).forEach(d=>{
    const tr = document.createElement('tr');
    tr.dataset.no = d.no;
    COLS.forEach(k=>{
      const td = document.createElement('td');
      let v = d[k[0]];
      if(v==null || v==='') v = '—';
      td.textContent = v;
      if(String(v).indexOf('待确认')>=0) td.className = 'todo';
      tr.appendChild(td);
    });
    tr.addEventListener('click', ()=>hl(d.no));
    tb.appendChild(tr);
  });
}
function go(p){
  cur = p;
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on', t.dataset.p==String(p)));
  render();
}
function syncSize(){
  const b = document.getElementById('base'), p = cur;
  if(!b || !b.naturalWidth) return;
  if(Math.abs(SIZES[p][0] - b.naturalWidth) > 1 || Math.abs(SIZES[p][1] - b.naturalHeight) > 1){
    SIZES[p] = [b.naturalWidth, b.naturalHeight];
    render();   // 图片实际尺寸与传入不符时按真实尺寸重算气泡半径/字号
  }
}
document.getElementById('base').onload = syncSize;
function resetAll(){ initPos(); render(); }
function download(name, text, mime){
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], {type:mime}));
  a.download = name; a.click();
}
function exportJSON(){
  const out = JSON.parse(JSON.stringify(DATA));
  out.dimensions.forEach(d=>{ const c = pos[d.no]; if(c){ d.bx = +c.x.toFixed(4); d.by = +c.y.toFixed(4); } });
  // 注意：d.x / d.y 仍为尺寸文本中心（数据契约语义），气泡位置写入 bx / by
  download('dimensions.json', JSON.stringify(out, null, 2), 'application/json');
}
function exportCSV(){
  const rows = [COLS.map(c=>c[1]).join(',')];
  dimsOf(cur).forEach(d=>rows.push(COLS.map(c=>{
    let v = d[c[0]]==null?'':String(d[c[0]]);
    return /[",\\n]/.test(v) ? '"'+v.replace(/"/g,'""')+'"' : v;
  }).join(',')));
  download('气泡尺寸表_p'+cur+'.csv', '\\ufeff'+rows.join('\\n'), 'text/csv');
}
const IMAGES = __IMAGES__;
// 调试/自检接口：暴露给无头浏览器做布局核查。
// 注意：不要在此行写 __DATA__/__IMAGES__/__SIZES__ 字面量——它们是模板占位符，会被整串替换成 JSON。
window.DATA = DATA; window.IMG_MAP = IMAGES; window.SIZE_MAP = SIZES;
const RED = '__RED__';
initPos(); render();
window.POS = pos;       // 自检接口：无头浏览器可读取实际渲染位置
</script>
</body>
</html>
"""

COLS = [
    ("no", "气泡号"), ("page", "图纸页"), ("view", "视图"), ("value", "尺寸值"),
    ("type", "类型"), ("desc", "部位描述"), ("char_class", "特性分类"),
    ("explicit_tol", "显式公差"), ("final_tol", "最终公差"), ("tol_source", "公差来源"),
    ("gauge", "量具"), ("insp_type", "检验类别"), ("freq", "检验频次"),
]


def image_size(path):
    """读取底图像素尺寸；SVG 尝试解析 viewBox / width / height。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".svg":
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(4096)
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
    # 兜底：PNG / JPEG 头解析
    try:
        with open(path, "rb") as f:
            raw = f.read(4096)
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(raw[16:20], "big")
            h = int.from_bytes(raw[20:24], "big")
            return (float(w), float(h))
        i = 2
        while i < len(raw) - 9:
            if raw[i] != 0xFF:
                i += 1
                continue
            mk = raw[i + 1]
            if mk in (0xC0, 0xC1, 0xC2, 0xC3):
                h = int.from_bytes(raw[i + 5:i + 7], "big")
                w = int.from_bytes(raw[i + 7:i + 9], "big")
                return (float(w), float(h))
            if mk in (0xD8, 0xD9) or 0xD0 <= mk <= 0xD7:
                i += 2
                continue
            ln = int.from_bytes(raw[i + 2:i + 4], "big")
            i += 2 + ln
    except Exception:
        pass
    return (1000.0, 700.0)


def embed(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".svg":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read()
        return "data:image/svg+xml;base64," + base64.b64encode(txt.encode("utf-8")).decode("ascii")
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp"}.get(ext, "image/png")
    with open(path, "rb") as f:
        raw = f.read()
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


def parse_images(spec):
    """'1:a.png;2:b.png' -> {1: 'a.png', 2: 'b.png'}"""
    out = {}
    if not spec:
        return out
    for part in re.split(r"[;|]", spec):
        part = part.strip()
        if not part:
            continue
        if ":" in part and not re.match(r"^[A-Za-z]:[\\/]", part):
            k, v = part.split(":", 1)
        elif ":" in part and part.count(":") > 1:
            k, v = part.split(":", 1)
        else:
            k, v = "1", part
        out[str(k).strip()] = v.strip().strip('"')
    return out


def main():
    ap = argparse.ArgumentParser(description="生成网页版气泡标注图")
    ap.add_argument("--dims", required=True, help="dimensions.json 路径")
    ap.add_argument("--images", required=True, help="底图映射，如 1:a.png;2:b.png")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    ap.add_argument("--title", default="", help="页面标题")
    args = ap.parse_args()

    if not os.path.isfile(args.dims):
        print("[错误] dimensions.json 不存在: %s" % args.dims)
        return 1
    with open(args.dims, "r", encoding="utf-8") as f:
        data = json.load(f)

    imgs = parse_images(args.images)
    if not imgs:
        print("[错误] --images 解析为空，格式应为 1:a.png;2:b.png")
        return 1
    for p, path in imgs.items():
        if not os.path.isfile(path):
            print("[错误] 底图不存在: %s" % path)
            return 1

    pages = sorted(imgs.keys(), key=lambda x: (len(x), x))
    dims = data.get("dimensions", [])
    # 未标注 page 的归入第 1 页
    for d in dims:
        if d.get("page") in (None, ""):
            d["page"] = pages[0]
    used = set(str(d.get("page")) for d in dims)
    for p in used:
        if p not in imgs:
            print("[错误] dimensions 中页 %s 没有对应底图，请补 --images" % p)
            return 1

    sizes = {p: [round(image_size(v)[0], 1), round(image_size(v)[1], 1)] for p, v in imgs.items()}
    embedded = {p: embed(v) for p, v in imgs.items()}

    title = args.title or (data.get("source", {}).get("file", "图纸") + " 气泡标注图")
    n = len(dims)
    todo = sum(1 for d in dims if d.get("need_confirm") or str(d.get("final_tol", "")).find("待确认") >= 0)
    meta = "共 %d 个尺寸 · %d 页 · 待确认 %d 项 · 单位 %s" % (
        n, len(pages), todo, data.get("unit", "mm"))
    tabs = "".join('<div class="tab%s" data-p="%s" onclick="go(\'%s\')">第 %s 页</div>'
                   % (" on" if p == pages[0] else "", p, p, p) for p in pages)
    if len(pages) == 1:
        tabs = ""
    thead = "<tr>" + "".join("<th>%s</th>" % c[1] for c in COLS) + "</tr>"

    html = (HTML_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__META__", meta)
            .replace("__TABS__", tabs)
            .replace("__IMG__", embedded[pages[0]])
            .replace("__VIEWBOX__", "0 0 %g %g" % (sizes[pages[0]][0], sizes[pages[0]][1]))
            .replace("__THEAD__", thead)
            .replace("__DATA__", json.dumps(data, ensure_ascii=False))
            .replace("__PAGES__", json.dumps(pages, ensure_ascii=False))
            .replace("__SIZES__", json.dumps(sizes, ensure_ascii=False))
            .replace("__IMAGES__", json.dumps(embedded, ensure_ascii=False))
            .replace("__COLS__", json.dumps(COLS, ensure_ascii=False))
            .replace("__RED__", RED)
            .replace("__REDSOFT__", RED_SOFT))

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("[OK] 网页版气泡标注图: %s" % out)
    print("     页数 %d · 尺寸 %d · 待确认 %d" % (len(pages), n, todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
