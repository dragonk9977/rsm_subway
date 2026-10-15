"""카카오맵 이름표(겹치지 않게 자동 배치) 표시 모듈 — 회사용 앱에서 사용"""
import json

import streamlit as st
import streamlit.components.v1 as components

ORANGE = "#ff6b00"

MAP_HTML = """
<div id="wrap" style="position:relative;width:100%;height:400px;border-radius:14px;overflow:hidden">
  <div id="m" style="position:absolute;left:0;top:0;right:0;bottom:0"></div>
  <svg id="ln" style="position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:5"></svg>
  <div id="lb" style="position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none;z-index:6"></div>
</div>
<script>
function err(t){
  const at = (document.referrer || location.href || '').split('/').slice(0,3).join('/');
  document.getElementById('m').innerHTML='<div style="padding:22px;font:14px/1.6 sans-serif;color:#c0392b">'+t+
    '<br><br><span style="color:#555">지금 접속 주소: <b>'+at+'</b><br>카카오 콘솔의 JS SDK 도메인에 이 주소가 <b>그대로</b> 등록돼 있어야 합니다.</span></div>';
}
</script>
<script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey=%%KEY%%&autoload=false"
        onerror="err('카카오맵 SDK 로드 실패: 키, 도메인 등록, 카카오맵 사용 설정, 네트워크(차단) 중 하나가 원인입니다.')"></script>
<script>
const DATA = %%PTS%%;
const pts = DATA.pts, paths = DATA.paths;
if (typeof kakao === 'undefined' || !kakao.maps) {
  err('카카오맵 SDK가 응답하지 않습니다: 키, 도메인 등록, 카카오맵 사용 설정을 확인하세요.');
} else kakao.maps.load(function () {
  const wrap = document.getElementById('wrap'), lb = document.getElementById('lb'), ln = document.getElementById('ln');
  const map = new kakao.maps.Map(document.getElementById('m'),
      {center: new kakao.maps.LatLng(pts[0].lat, pts[0].lng), level: 3, draggable: false});
  map.setZoomable(false);   // 화면 고정: 드래그·확대/축소 비활성
  const bounds = new kakao.maps.LatLngBounds();
  pts.forEach(p => {
    p.pos = new kakao.maps.LatLng(p.lat, p.lng);
    bounds.extend(p.pos);
    p.bc = p.best ? '%%ORANGE%%' : p.color;
    new kakao.maps.CustomOverlay({map: map, position: p.pos, zIndex: 3, content:
      '<div style="width:34px;height:34px;border-radius:50%;background:' + p.bc + ';color:#fff;border:3px solid #fff;' +
      'box-shadow:0 2px 8px rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;' +
      'font:700 16px sans-serif">' + p.no + '</div>'});
    const el = document.createElement('div');
    el.style.cssText = 'position:absolute;left:0;top:0;background:#fff;color:#222;border-radius:10px;padding:6px 11px;' +
      'border-left:6px solid ' + p.bc + ';box-shadow:0 2px 8px rgba(0,0,0,.35);font:13px/1.45 sans-serif;white-space:nowrap';
    el.innerHTML = p.html;
    lb.appendChild(el);
    p.el = el;
  });
  paths.forEach(pa => {
    const line = pa.coords.map(c => new kakao.maps.LatLng(c[0], c[1]));
    line.forEach(l => bounds.extend(l));
    new kakao.maps.Polyline({map: map, path: line, strokeWeight: pa.dash ? 4 : 6, strokeColor: pa.color,
                             strokeOpacity: pa.dash ? 0.85 : 0.9, strokeStyle: pa.dash ? 'shortdash' : 'solid'});
  });
  if (pts.length > 1 || paths.length) map.setBounds(bounds, 120, 150, 60, 150);

  // 이름표 배치: 마커·다른 이름표와 안 겹치는 자리를 골라 놓고, 가는 선으로 마커와 연결
  function layout() {
    const W = wrap.clientWidth, H = wrap.clientHeight, pj = map.getProjection();
    const it = pts.map(p => {
      const q = pj.containerPointFromCoords(p.pos);
      return {p: p, x: q.x, y: q.y, w: p.el.offsetWidth, h: p.el.offsetHeight};
    });
    const mk = it.map(i => ({l: i.x - 20, t: i.y - 20, r: i.x + 20, b: i.y + 20}));
    const area = (a, c) => Math.max(0, Math.min(a.r, c.r) - Math.max(a.l, c.l)) *
                           Math.max(0, Math.min(a.b, c.b) - Math.max(a.t, c.t));
    const outside = a => (a.r - a.l) * (a.b - a.t) - area(a, {l: 4, t: 4, r: W - 4, b: H - 4});
    const dirs = [[0, -1], [1, 0], [-1, 0], [0, 1], [1, -1], [-1, -1], [1, 1], [-1, 1]];
    const SIDE = {top: [0, -1], right: [1, 0], left: [-1, 0], bottom: [0, 1]};
    const order = it.slice().sort((a, c) => (c.p.best ? 1 : 0) - (a.p.best ? 1 : 0));
    const placed = [];
    let lines = '';
    order.forEach(i => {
      let best = null;
      const pref = SIDE[i.p.side] || null;   // 정류장이 있는 쪽(방향)을 우선 사용
      [32, 64, 104].forEach(d => dirs.forEach((dir, k) => {
        const cx = i.x + dir[0] * (dir[0] ? i.w / 2 + d : 0);
        const cy = i.y + dir[1] * (dir[1] ? i.h / 2 + d : 0);
        const r = {l: cx - i.w / 2, t: cy - i.h / 2, r: cx + i.w / 2, b: cy + i.h / 2};
        let s = outside(r) * 50 + d * 0.3 + k * 1.5 +
                ((pref && dir[0] === pref[0] && dir[1] === pref[1]) ? 0 : 40);
        mk.forEach(m => { s += area(r, m) * 30; });
        placed.forEach(q => { s += area(r, q) * 30; });
        if (!best || s < best.s) best = {s: s, r: r};
      }));
      placed.push(best.r);
      i.p.el.style.left = best.r.l + 'px';
      i.p.el.style.top = best.r.t + 'px';
      const px = Math.min(Math.max(i.x, best.r.l), best.r.r);
      const py = Math.min(Math.max(i.y, best.r.t), best.r.b);
      const dist = Math.hypot(px - i.x, py - i.y);
      if (dist > 22) {
        const ux = (px - i.x) / dist, uy = (py - i.y) / dist;
        lines += '<line x1="' + (i.x + ux * 19) + '" y1="' + (i.y + uy * 19) + '" x2="' + px + '" y2="' + py +
                 '" stroke="' + i.p.bc + '" stroke-width="2.5" stroke-linecap="round"/>';
      }
    });
    ln.innerHTML = lines;
  }
  kakao.maps.event.addListener(map, 'bounds_changed', layout);
  kakao.maps.event.addListener(map, 'idle', layout);
  layout();
  setTimeout(layout, 300);
});
</script>
"""


def show(points, js_key, paths=None, height=415):
    if not js_key or not points:
        return
    page = (MAP_HTML.replace("%%KEY%%", js_key).replace("%%ORANGE%%", ORANGE)
            .replace("%%PTS%%", json.dumps({"pts": points, "paths": paths or []}, ensure_ascii=False)))
    if hasattr(st, "iframe"):
        st.iframe(page, height=height)
    else:
        components.html(page, height=height)
