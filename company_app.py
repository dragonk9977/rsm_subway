"""퇴근길 버스 (회사 공유용) — 가산디지털단지역 / 독산역 방면, 버스만 타고 지하철로 가는 간단 버전
실행: streamlit run company_app.py   (Secrets: BUS_API_KEY, KAKAO_JS_KEY)"""
import html as H
import time
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

import bus
import kmap

KST = ZoneInfo("Asia/Seoul")
st.set_page_config(page_title="퇴근길 버스", page_icon="🚌", layout="wide")

# ── 설정 (정류장/노선은 여기만 고치면 됩니다) ───────────────────
WALK_MIN = 3            # 1층 → 정류장 도보(분)
FALLBACK_RIDE_MIN = 15  # 실시간 주행시간을 못 구했을 때 쓰는 대략값(분)
REFRESH = 30            # 서버 조회 주기(초). 접속자가 여러 명이어도 조회는 공유됩니다
WINDOW = (17, 19)       # 평일 이 시간대(시)에만 자동 조회
DAILY_LIMIT = 950       # 하루 API 호출 안전선(한도 1,000회)
SIDES = [
    dict(name="가산디지털단지역 방면", subway="가산디지털단지역", color="#2f6fed", stops=[
        dict(ars="18500", route="금천05", off="18594", mark="가", side="right")]),
    dict(name="독산역 방면", subway="독산역", color="#1fa971", stops=[
        dict(ars="18810", route="27", off="18643", mark="독", side="right"),
        dict(ars="18517", route="금천05", off="18643", mark="독", side="left")]),
]
STOPS = [stp["ars"] for sd in SIDES for stp in sd["stops"]]

st.markdown("""
<style>
.block-container{padding-top:1.6rem;max-width:1100px}
.side{border:1px solid rgba(128,128,128,.28);border-top-width:6px;border-radius:18px;padding:16px 18px 12px;margin:0 0 14px;background:rgba(128,128,128,.05)}
.side .sn{font-weight:800;font-size:1.15rem}
.side .big{font-size:2.5rem;font-weight:800;line-height:1.15;margin:6px 0 2px}
.side .big .sm{font-size:1rem;font-weight:600;opacity:.7}
.side .meta{opacity:.75;font-size:.9rem}
.side .eta{margin-top:8px;font-weight:700}
.row{display:flex;gap:8px;align-items:baseline;padding:6px 0;border-top:1px dashed rgba(128,128,128,.28);font-size:.92rem;flex-wrap:wrap}
.row .rn{font-weight:700;min-width:5.2em}
.row.best{background:rgba(255,107,0,.08);border-radius:8px;padding-left:6px}
.badge{display:inline-block;border-radius:6px;padding:0 7px;color:#fff;font-weight:700;font-size:.85rem}
.chip{display:inline-block;margin-top:6px;font-size:.82rem;opacity:.85}
</style>
""", unsafe_allow_html=True)

try:
    KEY = st.secrets["BUS_API_KEY"]
except Exception:
    st.error("Secrets에 BUS_API_KEY 가 없습니다.")
    st.stop()
try:
    JS_KEY = st.secrets["KAKAO_JS_KEY"]
except Exception:
    JS_KEY = ""


# ── 조회 (같은 서버의 모든 접속자가 결과를 공유) ──────────────────
@st.cache_resource
def api_counter():
    return {"day": "", "n": 0}


def count_call():
    c, today = api_counter(), datetime.now(KST).strftime("%Y-%m-%d")
    if c["day"] != today:
        c["day"], c["n"] = today, 0
    c["n"] += 1


@st.cache_data(ttl=25, show_spinner=False)
def load(ars):
    count_call()
    arr, stop = bus.fetch_station(ars, KEY)
    return arr, stop, time.time()


@st.cache_data(ttl=120, show_spinner=False)
def load_route(route_id):
    count_call()
    return bus.fetch_route_all(route_id, KEY), time.time()


def is_active():
    now = datetime.now(KST)
    forced = st.query_params.get("force") == "1"
    return forced or (WINDOW[0] <= now.hour < WINDOW[1] and now.weekday() < 5)


def fetch_snapshot():
    st.session_state["last_try"] = time.time()
    if api_counter()["n"] >= DAILY_LIMIT:
        st.session_state["snap_err"] = "오늘 조회 한도에 가까워 자동 조회를 멈췄어요. 내일 다시 이용해 주세요."
        return
    try:
        loaded = {a: load(a) for a in STOPS}
    except Exception as e:
        st.session_state["snap_err"] = str(e)
        return
    st.session_state["snap_err"] = ""
    coords = st.session_state.setdefault("coords", {})
    rids = st.session_state.setdefault("rids", {})
    for sd in SIDES:
        for stp in sd["stops"]:
            arr, stop, _ = loaded[stp["ars"]]
            if stop:
                coords[stp["ars"]] = stop
            m = bus.pick(arr, stp["route"])
            if m and m[0].route_id:
                rids[stp["ars"]] = m[0].route_id
    routes = {}
    for rid in set(rids.values()):
        try:
            routes[rid] = load_route(rid)
        except Exception:
            pass
    st.session_state["snap"] = {"t": time.time(), "loaded": loaded, "routes": routes}


def get_snapshot():
    first_visit = "last_try" not in st.session_state       # 페이지를 처음 연 순간: 시간대와 상관없이 한 번 조회
    stale = time.time() - st.session_state.get("last_try", 0) >= REFRESH
    if first_visit or (is_active() and stale):              # 이후 자동 갱신은 퇴근 시간대에만
        fetch_snapshot()
    return st.session_state.get("snap")


# ── 계산/표시 ─────────────────────────────────────
def mmss(sec):
    sec = int(sec)
    return f"{sec // 60}분 {sec % 60:02d}초"


def short(sec):
    return "곧 도착" if sec < 30 else f"{round(sec / 60)}분 후"


def mark(eta_sec):
    s = bus.status(eta_sec, WALK_MIN * 60)
    return {"ok": "🟢", "tight": "🟠", "miss": "⚪"}[s]


STATUS_TXT = {"ok": "🟢 걸어가서 여유 있게 탈 수 있어요",
              "tight": "🟠 도보 시간보다 빨라요 · 뛰면 탈 수 있어요",
              "miss": "⚪ 도보 시간보다 많이 빨라 타기 어려워요"}


def compute():
    snap = get_snapshot()
    if not snap:
        return None
    now = time.time()
    sides = []
    for sd in SIDES:
        rows, best = [], None
        for stp in sd["stops"]:
            arr, stop, ts = snap["loaded"][stp["ars"]]
            buses = [replace(a, eta_sec=int(a.eta_sec - (now - ts)))
                     for a in bus.pick(arr, stp["route"]) if a.eta_sec - (now - ts) >= 0]
            rows.append(dict(stp=stp, buses=buses, stop=snap_coord(stp["ars"], stop)))
            ok = [a for a in buses if a.eta_sec >= WALK_MIN * 60]
            if ok and (best is None or ok[0].eta_sec < best["bus"].eta_sec):
                best = dict(stp=stp, bus=ok[0])
        ride = None
        if best:
            rid = st.session_state.get("rids", {}).get(best["stp"]["ars"])
            ride = (FALLBACK_RIDE_MIN, "예상")
            if rid and rid in snap["routes"]:
                items, rts = snap["routes"][rid]
                got = bus.choose_ride(bus.segment_rides(items, best["stp"]["ars"], best["stp"]["off"]),
                                      best["bus"].eta_sec + (now - rts))
                if got:
                    ride = (got[0] / 60, "실시간" if got[1] == "bus" else "실시간(구간)")
        sides.append(dict(sd=sd, rows=rows, best=best, ride=ride))
    return dict(now=datetime.now(KST), t=snap["t"], sides=sides)


def snap_coord(ars, stop):
    return stop or st.session_state.get("coords", {}).get(ars)


def times_html(buses):
    if not buses:
        return "도착 정보 없음"
    return " · ".join(f"{mark(a.eta_sec)} {short(a.eta_sec)}" for a in buses[:2])


@st.fragment(run_every=1)
def cards_frag():
    err = st.session_state.get("snap_err")
    if err:
        st.warning(err)
    v = compute()
    if not v:
        return
    now = v["now"]
    st.caption(f"마지막 조회 {datetime.fromtimestamp(v['t'], KST):%H:%M:%S} · 숫자는 1초마다 줄어들고 "
               f"{REFRESH}초마다 새로 받아옵니다")
    for col, s in zip(st.columns(len(v["sides"])), v["sides"]):   # 방면별 카드를 좌우로 나란히 (좁은 화면은 자동으로 위아래)
        sd, best, ride = s["sd"], s["best"], s["ride"]
        if best:
            b = best["bus"]
            arrive = (now + timedelta(seconds=b.eta_sec + ride[0] * 60)).strftime("%H:%M")
            head = (f'<div class="big">{mmss(b.eta_sec)}<span class="sm"> 후 도착</span></div>'
                    f'<div class="meta"><span class="badge" style="background:{sd["color"]}">{H.escape(best["stp"]["route"])}</span> '
                    f'{best["stp"]["ars"]} 정류장 · 도보 {WALK_MIN}분</div>'
                    f'<div class="chip">{STATUS_TXT[bus.status(b.eta_sec, WALK_MIN * 60)]}</div>'
                    f'<div class="eta">🚇 {H.escape(sd["subway"])} 도착 예상 {arrive} '
                    f'<span style="font-weight:400;opacity:.65">(버스 {ride[0]:.0f}분 · {ride[1]})</span></div>')
        else:
            head = '<div class="big" style="font-size:1.6rem">지금 탈 수 있는 버스가 없어요</div>'
        rows = ""
        for r in s["rows"]:
            is_best = best and r["stp"] is best["stp"]
            rows += (f'<div class="row{" best" if is_best else ""}"><span class="rn">{H.escape(r["stp"]["route"])}번</span>'
                     f'<span style="opacity:.6">{r["stp"]["ars"]}</span><span>{times_html(r["buses"])}</span></div>')
        with col:
            st.markdown(f'<div class="side" style="border-top-color:{sd["color"]}"><div class="sn">{H.escape(sd["name"])}</div>'
                        f'{head}<div style="margin-top:8px">{rows}</div></div>', unsafe_allow_html=True)


@st.fragment(run_every=REFRESH)
def map_frag():
    v = compute()
    if not v or not JS_KEY:
        return
    pts = []
    for s in v["sides"]:
        sd = s["sd"]
        for r in s["rows"]:
            c = r["stop"]
            if not c:
                continue
            is_best = bool(s["best"] and r["stp"] is s["best"]["stp"])
            pts.append({"lat": c["lat"], "lng": c["lng"], "best": is_best, "color": sd["color"],
                        "no": r["stp"]["mark"], "side": r["stp"]["side"],
                        "html": f'<b>{H.escape(sd["name"])}</b><br>{H.escape(r["stp"]["route"])}번 {times_html(r["buses"])}'
                                f'<div style="font-size:11px;color:#777">{H.escape(c["name"])}</div>'})
    kmap.show(pts, JS_KEY)


if not is_active():
    st.info(f"페이지를 열 때 한 번 조회했어요. 자동 갱신은 퇴근 시간대({WINDOW[0]}~{WINDOW[1]}시, 평일)에만 돼요. "
            "최신 정보가 필요하면 아래 버튼을 누르거나 새로고침하세요.")
    if st.button("지금 다시 조회"):
        fetch_snapshot()

st.title("🚌 퇴근길 버스")
cards_frag()
map_frag()
st.caption("데이터: 서울특별시 버스도착정보(공공데이터포털) · 화면을 열어둔 동안만 갱신돼요 · "
           "🟢 여유 / 🟠 뛰면 가능 / ⚪ 도보 시간보다 빨라 어려움")
