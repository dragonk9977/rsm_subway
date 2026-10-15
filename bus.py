"""서울시 버스 도착정보(정류소정보조회 getStationByUid) 조회 + 퇴근길 환승 판정 로직 (Streamlit 비의존)"""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
import requests

BASE_URL = "http://ws.bus.go.kr/api/rest/stationinfo/getStationByUid"
ROUTE_URL = "http://ws.bus.go.kr/api/rest/arrive/getArrInfoByRouteAll"


@dataclass
class Arrival:
    route: str
    eta_sec: int           # 지금부터 도착까지 남은 초
    msg: str
    congestion: str = ""   # 3 여유 / 4 보통 / 5 혼잡
    full: bool = False
    last: bool = False
    term_min: int = 0      # 배차간격(분)
    estimated: bool = False
    route_id: str = ""


def parse_eta(msg: str, tra_time: str, is_arrive: str):
    """도착 메시지 → 초. 파악 불가(운행종료/출발대기 등)면 None"""
    if is_arrive == "1" or "곧 도착" in msg:
        return 0
    m = re.search(r"(?:(\d+)분)?(?:(\d+)초)?후", msg)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    if tra_time and tra_time.isdigit() and int(tra_time) > 0 and "종료" not in msg and "대기" not in msg:
        return int(tra_time)
    return None


def parse_response(xml_text: str):
    """XML → ([Arrival], stop_info|None). 오류면 RuntimeError"""
    root = ET.fromstring(xml_text)
    code = (root.findtext(".//headerCd") or "").strip()
    if code not in ("0", ""):
        raise RuntimeError(f"API 오류 {code}: {root.findtext('.//headerMsg')}")
    out, stop = [], None
    for it in root.iter("itemList"):
        g = lambda k: (it.findtext(k) or "").strip()
        if stop is None and g("gpsX") and g("gpsY"):
            try:
                stop = {"name": g("stNm"), "lng": float(g("gpsX")), "lat": float(g("gpsY"))}
            except ValueError:
                pass
        route = g("rtNm") or g("busRouteAbrv")
        term = int(g("term")) if g("term").isdigit() else 0
        for n in ("1", "2"):
            msg = g(f"arrmsg{n}")
            eta = parse_eta(msg, g(f"traTime{n}"), g(f"isArrive{n}"))
            if eta is None:
                continue
            out.append(Arrival(route, eta, msg, g(f"congestion{n}"),
                               g(f"isFullFlag{n}") == "1", g(f"isLast{n}") == "1", term,
                               route_id=g("busRouteId")))
    return out, stop


def fetch_station(ars_id: str, key: str):
    """(arrivals, stop_info) 반환. stop_info = {name, lat, lng} (도착 버스가 하나도 없으면 None)"""
    r = requests.get(BASE_URL, params={"ServiceKey": key, "arsId": ars_id}, timeout=8)
    r.raise_for_status()
    return parse_response(r.text)


def route_match(actual: str, name: str) -> bool:
    """'27' 은 '27' 과 '27광명'(뒤에 한글 지역명이 붙은 표기)에는 맞고 '270'에는 안 맞는다."""
    return actual == name or re.fullmatch(re.escape(name) + r"[가-힣]+", actual) is not None


def parse_route_all(xml_text: str):
    """노선 전체 정류장 도착정보 → {정류장번호(arsId): [(차량ID, 남은초), ...]}"""
    root = ET.fromstring(xml_text)
    code = (root.findtext(".//headerCd") or "").strip()
    if code not in ("0", ""):
        raise RuntimeError(f"API 오류 {code}: {root.findtext('.//headerMsg')}")
    out = {}
    for it in root.iter("itemList"):
        g = lambda k: (it.findtext(k) or "").strip()
        ars = g("arsId")
        for n in ("1", "2"):
            veh = g(f"vehId{n}")
            eta = parse_eta(g(f"arrmsg{n}"), g(f"traTime{n}"), g(f"isArrive{n}"))
            if veh in ("", "0") or eta is None:
                continue
            out.setdefault(ars, []).append((veh, eta))
    return out


def fetch_route_all(route_id: str, key: str):
    r = requests.get(ROUTE_URL, params={"ServiceKey": key, "busRouteId": route_id}, timeout=10)
    r.raise_for_status()
    return parse_route_all(r.text)


def segment_rides(route_all: dict, board_ars: str, off_ars: str):
    """같은 차량이 승차·하차 정류장 둘 다에 '도착 예정'으로 잡힌 경우 → 실제 주행 시간(초)"""
    rides = []
    for veh, eb in route_all.get(board_ars, []):
        diffs = [eo - eb for v, eo in route_all.get(off_ars, []) if v == veh and 60 <= eo - eb <= 5400]
        if diffs:
            rides.append({"veh": veh, "board_eta": eb, "ride_sec": min(diffs)})
    return rides


def choose_ride(rides, target_eta=None, tol=120):
    """(주행초, 'bus'|'seg') — bus: 내가 탈 그 버스, seg: 이 구간을 지금 달리는 버스들의 중간값. 없으면 None"""
    if not rides:
        return None
    if target_eta is not None:
        near = min(rides, key=lambda x: abs(x["board_eta"] - target_eta))
        if abs(near["board_eta"] - target_eta) <= tol:
            return near["ride_sec"], "bus"
    secs = sorted(x["ride_sec"] for x in rides)
    return secs[len(secs) // 2], "seg"


def pick(arrivals, route: str):
    return sorted((a for a in arrivals if route_match(a.route, route)), key=lambda a: a.eta_sec)


def status(eta_sec: int, walk_sec: int) -> str:
    """ok: 여유 있게 탈 수 있음 / tight: 뛰면 가능 / miss: 도보 시간보다 훨씬 빨라 어려움"""
    if eta_sec >= walk_sec:
        return "ok"
    return "tight" if eta_sec >= walk_sec * 0.6 else "miss"


def next_transfer(arrivals, reach_sec: int):
    """내가 환승 정류장에 도착하는 시점(reach_sec) 이후 첫 버스.
    API는 앞선 2대만 알려주므로, 없으면 배차간격으로 추정(estimated=True)."""
    ok = [a for a in arrivals if a.eta_sec >= reach_sec]
    if ok:
        return ok[0]
    if not arrivals:
        return None
    last = max(arrivals, key=lambda a: a.eta_sec)
    if last.term_min <= 0 or last.last:
        return None
    eta = last.eta_sec
    while eta < reach_sec:
        eta += last.term_min * 60
    return Arrival(last.route, eta, f"배차간격 {last.term_min}분 기준 추정", last.congestion,
                   False, False, last.term_min, True, last.route_id)


@dataclass
class Option:
    label: str
    route: str
    boarded: Arrival | None = None   # 탈 수 있는 첫 버스
    ride_end_sec: int | None = None  # 하차 예상 시점
    notes: list = field(default_factory=list)
    transfer: Arrival | None = None
    transfer_wait_sec: int | None = None
    home_stop_sec: int | None = None  # 최종 하차 정류장 도착 예상 시점(지금 기준 초)
    ride_used: float | None = None    # 1구간 주행 분
    ride_src: str = ""                # 실시간 / 설정값
    ride2_used: float | None = None
    ride2_src: str = ""


def _val(x, arg=None):
    r = x(arg) if callable(x) else x
    return r if isinstance(r, tuple) else (r, "설정값")


def plan_option(label, route, stop_arrivals, walk_to_stop_min, ride_min,
                walk_transfer_min, transfer_arrivals, ride2_min):
    """ride_min / ride2_min 은 숫자(분) 또는 (버스)→(분, 출처) 함수"""
    o = Option(label, route)
    catchable = [a for a in pick(stop_arrivals, route) if a.eta_sec >= walk_to_stop_min * 60]
    if not catchable:
        o.notes.append("탈 수 있는 도착 정보 없음")
        return o
    o.boarded = catchable[0]
    o.ride_used, o.ride_src = _val(ride_min, o.boarded)
    o.ride_end_sec = o.boarded.eta_sec + o.ride_used * 60
    reach = o.ride_end_sec + walk_transfer_min * 60       # 환승 정류장 도착 시점
    o.transfer = next_transfer(transfer_arrivals, reach)
    if o.transfer is None:
        o.notes.append("환승 버스 도착 정보 없음")
        return o
    o.transfer_wait_sec = o.transfer.eta_sec - reach
    o.ride2_used, o.ride2_src = _val(ride2_min, o.transfer)
    o.home_stop_sec = o.transfer.eta_sec + o.ride2_used * 60
    return o


def recommend(options, tol_sec: int = 120):
    """최종 도착이 가장 빠른 경로. 단, 도착 시각 차이가 tol_sec 이내면 '먼저 타는 버스' 쪽을 추천
    (같은 환승 버스를 타게 돼 도착이 사실상 같다면, 일찍 타는 쪽이 지연에 안전하고 정류장에서 덜 기다림)"""
    ok = [o for o in options if o.home_stop_sec is not None]
    if not ok:
        return None
    fastest = min(o.home_stop_sec for o in ok)
    near = [o for o in ok if o.home_stop_sec <= fastest + tol_sec]
    return min(near, key=lambda o: (o.boarded.eta_sec, o.home_stop_sec))
