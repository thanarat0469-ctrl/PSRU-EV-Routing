# -*- coding: utf-8 -*-
"""
PSRU SMART RIDE - Digital Twin Dashboard
ระบบจำลองรถรับส่งภายในมหาวิทยาลัย พร้อม AI จัดสรรรถและ Animation
แผนที่อ้างอิงพิกัดสถานที่ในวิทยาเขตทะเลแก้ว และใช้เส้นทางถนนจาก OpenStreetMap/OSRM
"""
from flask import Flask, jsonify, request, render_template_string
from copy import deepcopy
import math
import threading
import time
import json
import urllib.request
import urllib.parse

app = Flask(__name__)
LOCK = threading.Lock()

AVERAGE_SPEED_KMH = 15
MAX_ACCEPTABLE_DETOUR_M = 1000
MAX_EXTRA_DELAY_MIN = 8
QUEUE_WAIT_ESTIMATE_MIN = 5

# พิกัดสถานที่ในวิทยาเขตทะเลแก้ว (WGS84)
# พิกัดตั้งต้นอ้างอิง Plus Code/สถานที่ที่เผยแพร่บนแผนที่ออนไลน์
LOCATIONS = {
    # จุดหลักและอาคารที่มีชื่อ/พิกัดอ้างอิงจาก Plus Code บนแผนที่ออนไลน์
    "ประตู 3": {"x": 120, "y": 450, "lat": 16.8239375, "lon": 100.2155625, "plus_code": "R6F8+H6W"},
    "อาคารทีปวิชญ์": {"x": 350, "y": 340, "lat": 16.8286875, "lon": 100.2050625, "plus_code": "R6H4+F25"},
    "อาคารพิบูลวิชญ์": {"x": 520, "y": 360, "lat": 16.8276875, "lon": 100.2108125, "plus_code": "R6H6+38G"},
    "คณะวิทยาศาสตร์และเทคโนโลยี": {"x": 760, "y": 250, "lat": 16.8280625, "lon": 100.2149375, "plus_code": "R6H7+6XG"},
    "คณะพยาบาลศาสตร์": {"x": 650, "y": 470, "lat": 16.8276875, "lon": 100.2101875, "plus_code": "R6H6+33J"},
    "คณะมนุษยศาสตร์และสังคมศาสตร์": {"x": 250, "y": 180, "lat": 16.8260625, "lon": 100.2066875, "plus_code": "R6G4+CMX"},
    "หอพักทะเลแก้ว อาคาร 3": {"x": 850, "y": 470, "lat": 16.8258125, "lon": 100.2169375, "plus_code": "R6G8+8Q2"},
    "หอสมุด (สำนักวิทยบริการฯ)": {"x": 790, "y": 310, "lat": 16.8288125, "lon": 100.2143125, "plus_code": "R6H7+GPG"},
    "หอประชุมศรีวชิรโชติ": {"x": 430, "y": 150, "lat": 16.8298125, "lon": 100.2073125, "plus_code": "R6H4+WW8"},
    "ศูนย์อาหาร ตึก ร": {"x": 600, "y": 390, "lat": 16.8278125, "lon": 100.2113125, "plus_code": "R6H6+4GC"},
    "สนามกีฬาพระองค์ดำ": {"x": 900, "y": 520, "lat": 16.8316875, "lon": 100.2124375, "plus_code": "R6J6+MX5"},
    "คณะเทคโนโลยีอุตสาหกรรม": {"x": 980, "y": 250, "lat": 16.8348125, "lon": 100.2138125, "plus_code": "R6M7+WGW"},
    "คณะเทคโนโลยีการเกษตรและอาหาร": {"x": 430, "y": 510, "lat": 16.8253125, "lon": 100.2118125, "plus_code": "R6G6+4PP"},
    "อาคารแปรรูปอาหารและพัฒนาผลิตภัณฑ์": {"x": 310, "y": 500, "lat": 16.8259375, "lon": 100.2075625, "plus_code": "R6G5+92X"},
    "โรงผลิตอาหารสัตว์": {"x": 360, "y": 550, "lat": 16.8255625, "lon": 100.2083125, "plus_code": "R6G5+68C"},
    "โรงรีดนมโค": {"x": 260, "y": 550, "lat": 16.8255625, "lon": 100.2078125, "plus_code": "R6G5+649"},
}
# เชื่อมจุดอาคารสำคัญเป็นโครงข่ายสำหรับ Dijkstra; ระยะของแต่ละช่วงคำนวณตามถนนผ่าน OSRM
ROADS = [
    ["ประตู 3", "อาคารทีปวิชญ์", "หอประชุมศรีวชิรโชติ", "คณะมนุษยศาสตร์และสังคมศาสตร์"],
    ["อาคารทีปวิชญ์", "อาคารพิบูลวิชญ์", "ศูนย์อาหาร ตึก ร", "คณะพยาบาลศาสตร์"],
    ["อาคารพิบูลวิชญ์", "คณะวิทยาศาสตร์และเทคโนโลยี", "หอสมุด (สำนักวิทยบริการฯ)"],
    ["คณะพยาบาลศาสตร์", "คณะเทคโนโลยีการเกษตรและอาหาร", "อาคารแปรรูปอาหารและพัฒนาผลิตภัณฑ์", "โรงผลิตอาหารสัตว์", "โรงรีดนมโค"],
    ["คณะวิทยาศาสตร์และเทคโนโลยี", "สนามกีฬาพระองค์ดำ", "คณะเทคโนโลยีอุตสาหกรรม"],
    ["ศูนย์อาหาร ตึก ร", "หอพักทะเลแก้ว อาคาร 3"],
]

_DISTANCE_CACHE = {}

def haversine_distance(a, b):
    pa, pb = LOCATIONS[a], LOCATIONS[b]
    r = 6371000
    p1, p2 = math.radians(pa["lat"]), math.radians(pb["lat"])
    dp = math.radians(pb["lat"] - pa["lat"])
    dl = math.radians(pb["lon"] - pa["lon"])
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(h))

def road_distance(a, b):
    """ระยะทางตามถนนจาก OSRM; หากบริการไม่พร้อม ใช้ระยะเส้นตรงและระบุ fallback ใน UI"""
    key = tuple(sorted((a, b)))
    if key in _DISTANCE_CACHE:
        return _DISTANCE_CACHE[key]
    pa, pb = LOCATIONS[a], LOCATIONS[b]
    coords = f"{pa['lon']},{pa['lat']};{pb['lon']},{pb['lat']}"
    url = "https://router.project-osrm.org/route/v1/driving/" + coords + "?overview=false&alternatives=false&steps=false"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PSRU-SMART-RIDE/1.0"})
        with urllib.request.urlopen(req, timeout=2.5) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("code") == "Ok" and data.get("routes"):
            distance = float(data["routes"][0]["distance"])
        else:
            distance = haversine_distance(a, b) * 1.25
    except Exception:
        distance = haversine_distance(a, b) * 1.25
    distance = round(distance, 1)
    _DISTANCE_CACHE[key] = distance
    return distance

def shortest_distance(start, end):
    if start == end:
        return 0.0
    graph = {k: [] for k in LOCATIONS}
    for road in ROADS:
        for a, b in zip(road, road[1:]):
            d = road_distance(a, b)
            graph[a].append((b, d))
            graph[b].append((a, d))
    dist = {k: float("inf") for k in LOCATIONS}
    dist[start] = 0
    seen = set()
    while len(seen) < len(LOCATIONS):
        cur = min((n for n in LOCATIONS if n not in seen), key=lambda n: dist[n])
        if dist[cur] == float("inf") or cur == end:
            break
        seen.add(cur)
        for nxt, cost in graph[cur]:
            if dist[cur] + cost < dist[nxt]:
                dist[nxt] = dist[cur] + cost
    return dist[end] if dist[end] != float("inf") else road_distance(start, end)

def estimate_minutes(distance_m):
    return distance_m / (AVERAGE_SPEED_KMH * 1000 / 60)

INITIAL_VEHICLES = [
    {"id":"รถไฟฟ้าคันที่ 1","capacity":8,"occupancy":6,"distance_to_pickup":180,
     "heading_to":"อาคารพิบูลวิชญ์","status":"กำลังให้บริการ","stops":["อาคารพิบูลวิชญ์"],
     "extra_delay_min":2,"position":"อาคารพิบูลวิชญ์","target":None,"progress":0.0,"color":"#38bdf8"},
    {"id":"รถไฟฟ้าคันที่ 2","capacity":8,"occupancy":2,"distance_to_pickup":250,
     "heading_to":"อาคารทีปวิชญ์","status":"พร้อมรับคำขอ","stops":[],"extra_delay_min":0,
     "position":"อาคารทีปวิชญ์","target":None,"progress":0.0,"color":"#a78bfa"},
    {"id":"รถไฟฟ้าคันที่ 3","capacity":8,"occupancy":7,"distance_to_pickup":160,
     "heading_to":"คณะพยาบาลศาสตร์","status":"กำลังให้บริการ","stops":["คณะพยาบาลศาสตร์"],
     "extra_delay_min":1,"position":"คณะพยาบาลศาสตร์","target":None,"progress":0.0,"color":"#fbbf24"},
    {"id":"รถไฟฟ้าคันที่ 4","capacity":8,"occupancy":1,"distance_to_pickup":520,
     "heading_to":"คณะวิทยาศาสตร์และเทคโนโลยี","status":"พร้อมรับคำขอ","stops":[],"extra_delay_min":0,
     "position":"คณะวิทยาศาสตร์และเทคโนโลยี","target":None,"progress":0.0,"color":"#34d399"},
]
INITIAL_REQUESTS = [
    {"id":"คำขอ 1","request_time":1,"pickup":"หอพักทะเลแก้ว อาคาร 3","destination":"อาคารพิบูลวิชญ์",
     "passengers":1,"detour_m":120,"status":"กำลังพิจารณา","priority":1,"accessibility_required":False},
    {"id":"คำขอ 2","request_time":2,"pickup":"คณะพยาบาลศาสตร์","destination":"คณะวิทยาศาสตร์และเทคโนโลยี",
     "passengers":4,"detour_m":650,"status":"กำลังพิจารณา","priority":1,"accessibility_required":False},
    {"id":"คำขอ 3","request_time":3,"pickup":"คณะวิทยาศาสตร์และเทคโนโลยี","destination":"อาคารทีปวิชญ์",
     "passengers":1,"detour_m":90,"status":"กำลังพิจารณา","priority":1,"accessibility_required":False},
]
vehicles = deepcopy(INITIAL_VEHICLES)
requests = deepcopy(INITIAL_REQUESTS)
next_request = 4
simulation_running = True
last_tick = time.time()

def evaluate_vehicle(vehicle, req):
    free = vehicle["capacity"] - vehicle["occupancy"]
    needed = req["passengers"]
    distance = vehicle["distance_to_pickup"]
    if not vehicle.get("target"):
        distance = shortest_distance(vehicle["position"], req["pickup"])
        vehicle["distance_to_pickup"] = round(distance, 1)
    detour = req["detour_m"]
    delay = vehicle.get("extra_delay_min", 0)
    if vehicle["status"] in {"ขัดข้อง", "ไม่พร้อมให้บริการ"}:
        return None, f"รถไม่พร้อมให้บริการ ({vehicle['status']})"
    if free < needed:
        return None, f"ที่นั่งไม่พอ: ว่าง {free} ที่ ต้องการ {needed} ที่"
    if detour > MAX_ACCEPTABLE_DETOUR_M:
        return None, f"ระยะเบี่ยงเบน {detour} ม. เกินเกณฑ์"
    if delay > MAX_EXTRA_DELAY_MIN:
        return None, f"ผู้โดยสารเดิมล่าช้า {delay} นาที เกินเกณฑ์"
    distance_score = max(0, 30 - distance / 50)
    detour_score = max(0, 25 - detour / 50)
    same_direction = 20 if vehicle["heading_to"] == req["destination"] else 0
    spare_score = min(10, max(0, free - needed) * 2)
    wait = estimate_minutes(distance)
    wait_score = max(0, 15 - wait * 2)
    penalty = delay * 2
    score = distance_score + detour_score + same_direction + spare_score + wait_score - penalty
    return {"score":round(score,2), "wait_min":round(wait,1), "free_seats":free,
            "reasons":[f"ที่นั่งว่าง {free} ต้องการ {needed}", f"ห่างจุดรับ {distance} เมตร",
                       f"ระยะเบี่ยงเบน {detour} เมตร",
                       "ทิศทางตรงกับปลายทาง" if same_direction else "ทิศทางไม่ตรงกับปลายทาง",
                       f"กระทบเวลาผู้โดยสารเดิม {delay} นาที"]}, "ผ่านเงื่อนไข"

def choose_vehicle(req):
    candidates, evaluations = [], []
    for v in vehicles:
        detail, reason = evaluate_vehicle(v, req)
        evaluations.append({"vehicle":v["id"],"eligible":detail is not None,
                            "reason":reason,"score":detail["score"] if detail else None,
                            "details":detail})
        if detail:
            candidates.append((detail["score"], -v["distance_to_pickup"], v, detail))
    req["evaluations"] = evaluations
    if not candidates:
        req.update(status="กำลังรอรถ", assigned_vehicle=None,
                    estimated_wait_min=QUEUE_WAIT_ESTIMATE_MIN,
                    reason="ไม่มีรถผ่านเงื่อนไข จึงจัดคำขอเข้าคิว")
        return
    candidates.sort(key=lambda x:(x[0],x[1]), reverse=True)
    score, _, chosen, detail = candidates[0]
    original_distance = chosen["distance_to_pickup"]
    chosen["occupancy"] += req["passengers"]
    chosen["distance_to_pickup"] = 0
    chosen["stops"] = [req["pickup"], req["destination"]]
    chosen["status"] = "กำลังไปรับผู้โดยสาร"
    chosen["target"] = req["pickup"]
    chosen["progress"] = 0.0
    req.update(status="รับคำขอแล้ว", assigned_vehicle=chosen["id"], score=score,
               estimated_wait_min=estimate_minutes(original_distance),
               reason=f"เลือกจากคะแนนสูงสุด {score:.2f}; ที่นั่งเพียงพอ; ระยะถึงจุดรับ {original_distance} เมตร",
               vehicle_distance_to_pickup_m=original_distance,
               seats_after_assignment=chosen["capacity"]-chosen["occupancy"])
    req["route"] = [req["pickup"], req["destination"]]

def state_snapshot():
    return {"vehicles":vehicles,"requests":requests,"locations":LOCATIONS,
            "running":simulation_running,
            "stats":{"vehicle_count":len(vehicles),
                     "available":sum(v["status"]=="พร้อมรับคำขอ" for v in vehicles),
                     "serving":sum(v["status"] not in {"พร้อมรับคำขอ","ขัดข้อง"} for v in vehicles),
                     "passengers":sum(v["occupancy"] for v in vehicles),
                     "requests":len(requests),
                     "completed":sum(r["status"]=="เสร็จสิ้น" for r in requests),
                     "waiting":sum(r["status"]=="กำลังรอรถ" for r in requests)}}

@app.get("/")
def index():
    return render_template_string(HTML, locations=list(LOCATIONS.keys()))

@app.get("/api/state")
def api_state():
    with LOCK:
        return jsonify(state_snapshot())

@app.post("/api/request")
def add_request():
    global next_request
    data = request.get_json(force=True)
    pickup, destination = data.get("pickup"), data.get("destination")
    passengers = int(data.get("passengers",1))
    if pickup not in LOCATIONS or destination not in LOCATIONS:
        return jsonify(error="กรุณาเลือกจุดรับและจุดหมายจากรายการ"), 400
    if pickup == destination:
        return jsonify(error="จุดรับและจุดหมายต้องไม่เป็นจุดเดียวกัน"), 400
    if passengers < 1 or passengers > 8:
        return jsonify(error="จำนวนผู้โดยสารต้องอยู่ระหว่าง 1-8 คน"), 400
    with LOCK:
        req = {"id":f"คำขอ {next_request}","request_time":next_request,
               "pickup":pickup,"destination":destination,"passengers":passengers,
               "detour_m":round(shortest_distance(pickup,destination)*0.35,1),
               "status":"กำลังพิจารณา","priority":1,"accessibility_required":False}
        next_request += 1
        choose_vehicle(req)
        requests.append(req)
        return jsonify({"request":req,"state":state_snapshot()})

@app.post("/api/toggle")
def toggle():
    global simulation_running
    with LOCK:
        simulation_running = not simulation_running
        return jsonify(running=simulation_running)

@app.post("/api/reset")
def reset():
    global vehicles, requests, next_request, simulation_running
    with LOCK:
        vehicles = deepcopy(INITIAL_VEHICLES)
        requests = deepcopy(INITIAL_REQUESTS)
        next_request = 4
        simulation_running = True
        for r in requests:
            choose_vehicle(r)
        return jsonify(state_snapshot())

def simulation_loop():
    global last_tick
    while True:
        time.sleep(0.12)
        with LOCK:
            now = time.time()
            dt = min(now-last_tick, 0.5)
            last_tick = now
            if not simulation_running:
                continue
            for v in vehicles:
                if not v.get("target"):
                    continue
                target = v["target"]
                # ใช้ระยะจำลอง 350 เมตรต่อวินาทีใน Animation เพื่อให้เห็นการเคลื่อนที่
                distance = max(80, road_distance(v["position"], target))
                v["progress"] += dt / max(1.5, distance/350)
                if v["progress"] >= 1:
                    v["position"] = target
                    v["progress"] = 0
                    if v["status"] == "กำลังไปรับผู้โดยสาร":
                        v["status"] = "กำลังส่งผู้โดยสาร"
                        # ปลายทางของคำขอที่ผูกกับรถคันนี้
                        linked = next((r for r in requests if r.get("assigned_vehicle")==v["id"]
                                       and r["status"]=="รับคำขอแล้ว"), None)
                        if linked:
                            v["target"] = linked["destination"]
                    else:
                        linked = next((r for r in requests if r.get("assigned_vehicle")==v["id"]
                                       and r["status"]=="รับคำขอแล้ว"), None)
                        if linked:
                            linked["status"] = "เสร็จสิ้น"
                        v["target"] = None
                        v["status"] = "พร้อมรับคำขอ"
                        v["occupancy"] = max(0, v["occupancy"] - (linked["passengers"] if linked else 0))
                        v["stops"] = []
                        v["distance_to_pickup"] = 200
                        v["heading_to"] = v["position"]

threading.Thread(target=simulation_loop, daemon=True).start()

HTML = r"""
<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PSRU SMART RIDE | ระบบจำลองเสมือน</title>
<style>
:root{--bg:#07111f;--panel:#101f32;--panel2:#142840;--line:#263b53;--text:#e8f1fb;--muted:#91a7bf;--cyan:#38bdf8;--green:#34d399;--amber:#fbbf24;--red:#fb7185}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0%,#132b45,var(--bg) 48%);color:var(--text);font-family:Tahoma,Arial,sans-serif}
header{padding:20px 26px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
h1{font-size:22px;margin:0}header p{margin:6px 0 0;color:var(--muted);font-size:13px}.pill{border:1px solid #28516a;border-radius:30px;padding:8px 12px;color:#8de0ff;font-size:12px}
main{max-width:1500px;margin:auto;padding:20px;display:grid;gap:16px}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.panel,.stat{background:linear-gradient(145deg,var(--panel),#0c1929);border:1px solid var(--line);border-radius:15px;padding:15px;box-shadow:0 10px 28px #0002}
.stat small{color:var(--muted)}.stat strong{display:block;font-size:27px;margin-top:7px}.layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(300px,.85fr);gap:16px}
.panel h2{font-size:16px;margin:0 0 13px}.map-wrap{background:#0a1726;border:1px solid #203a52;border-radius:12px;overflow:hidden}.map-wrap{height:620px}.map-wrap #campus{width:100%;height:100%;min-height:380px}
.road{fill:none;stroke:#334d65;stroke-width:19;stroke-linecap:round;stroke-linejoin:round}.roadline{fill:none;stroke:#6c8197;stroke-width:2;stroke-dasharray:7 8}
.building{fill:#1c344b;stroke:#47637c;stroke-width:2}.place{fill:#d7e8f6;font-size:14px;text-anchor:middle}.sub{fill:#7993ac;font-size:10px;text-anchor:middle}
.marker{fill:#0e263b;stroke:#83a8c7;stroke-width:2}.bus circle{stroke:#07111f;stroke-width:3}.bus text{font-size:12px;font-weight:bold;fill:#07111f;text-anchor:middle;dominant-baseline:middle}
.route{fill:none;stroke:#a78bfa;stroke-width:6;stroke-linecap:round;stroke-dasharray:10 8;filter:drop-shadow(0 0 5px #a78bfa)}
.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:10px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}button{border:0;border-radius:9px;padding:10px 14px;background:#0e7490;color:white;font-weight:bold;cursor:pointer}button.secondary{background:#263b53;color:#d8e7f6}button:hover{filter:brightness(1.15)}
form{display:grid;gap:10px}label{font-size:12px;color:var(--muted)}select,input{width:100%;margin-top:5px;background:#091727;color:var(--text);border:1px solid #30465d;border-radius:8px;padding:10px}
.vehicle-list,.request-list{display:grid;gap:9px}.vehicle,.request{background:#0b1a2b;border:1px solid #223a51;border-radius:10px;padding:11px}.row{display:flex;justify-content:space-between;gap:10px;align-items:center}.muted{color:var(--muted);font-size:12px}.status{font-size:11px;padding:4px 7px;border-radius:20px;background:#183c50;color:#8de0ff}.bar{height:6px;background:#26394c;border-radius:9px;overflow:hidden;margin-top:8px}.bar span{display:block;height:100%;background:var(--cyan)}
.ai{border-left:3px solid var(--green);padding:8px 10px;background:#102b2b;border-radius:5px;margin-top:8px;font-size:12px;color:#b9f4dc}.reject{color:#fda4af}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.section-note{font-size:11px;color:var(--muted);line-height:1.5;margin-top:12px}
@media(max-width:900px){.layout{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}}@media(max-width:520px){main{padding:12px}.stats{grid-template-columns:1fr 1fr}.stat strong{font-size:22px}header{padding:16px}}
.leaflet-container{background:#e8e3d5;font-family:Tahoma,Arial,sans-serif}.leaflet-popup-content{font-family:Tahoma,Arial,sans-serif;font-size:13px}
</style><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script></head><body>
<header><div><h1>◈ PSRU SMART RIDE</h1><p>ระบบจำลองการเดินรถรับส่งภายในมหาวิทยาลัยและการตัดสินใจด้วยปัญญาประดิษฐ์</p></div><div class="pill">● โหมดจำลอง <span id="runState">กำลังทำงาน</span></div></header>
<main>
<section class="stats">
<div class="stat"><small>รถทั้งหมด</small><strong id="sVehicles">4</strong></div>
<div class="stat"><small>พร้อมให้บริการ</small><strong id="sAvailable">2</strong></div>
<div class="stat"><small>กำลังให้บริการ</small><strong id="sServing">2</strong></div>
<div class="stat"><small>ผู้โดยสารบนรถ</small><strong id="sPassengers">16</strong></div>
<div class="stat"><small>คำขอทั้งหมด</small><strong id="sRequests">3</strong></div>
</section>
<div class="layout">
<section class="panel"><div class="row"><h2>แผนที่จำลองมหาวิทยาลัย · การเคลื่อนที่ของรถ</h2><span class="status">อาคารจริง · OpenStreetMap</span></div>
<div class="map-wrap"><div id="campus" aria-label="แผนที่วิทยาเขตทะเลแก้ว"></div></div>
<div class="legend"><span><i class="dot" style="background:#38bdf8"></i>รถคันที่ 1</span><span><i class="dot" style="background:#a78bfa"></i>รถคันที่ 2</span><span><i class="dot" style="background:#fbbf24"></i>รถคันที่ 3</span><span><i class="dot" style="background:#34d399"></i>รถคันที่ 4</span><span>เส้นประสีรถ = เส้นทางที่เรียกจาก OSRM</span></div>
<div class="controls"><button id="pauseBtn" onclick="toggleSim()">หยุดการเคลื่อนที่</button><button class="secondary" onclick="resetSim()">รีเซ็ตการจำลอง</button></div>
<p class="section-note">หมายเหตุ: พิกัดสถานที่อ้างอิงแผนที่ออนไลน์; จุดรับ–ส่งเลือกจากอาคาร/สถานที่ที่มีพิกัดอ้างอิง; เส้นทางและระยะทางเรียกจาก OSRM/ถนน OpenStreetMap เมื่อเชื่อมต่ออินเทอร์เน็ต หากบริการเส้นทางไม่ตอบสนอง ระบบใช้ค่าประมาณจากพิกัดแทน และตำแหน่งรถยังเป็นการจำลอง ไม่ใช่ GPS รถจริง</p>
</section>
<aside class="panel"><h2>＋ ทดลองเพิ่มคำขอผู้โดยสาร</h2>
<form id="requestForm"><div><label>จุดรับผู้โดยสาร (เลือกอาคาร/สถานที่จริง)</label><select id="pickup">{% for x in locations %}<option>{{x}}</option>{% endfor %}</select></div>
<div><label>จุดส่งผู้โดยสาร (เลือกอาคาร/สถานที่จริง)</label><select id="destination">{% for x in locations %}<option>{{x}}</option>{% endfor %}</select></div>
<div><label>จำนวนผู้โดยสาร</label><input id="passengers" type="number" min="1" max="8" value="1"></div>
<button type="submit">วิเคราะห์และเลือกรถด้วย AI</button></form><div id="decisionResult"></div>
<hr style="border:0;border-top:1px solid var(--line);margin:18px 0"><h2>สถานะรถไฟฟ้า</h2><div class="vehicle-list" id="vehicleList"></div></aside>
</div>
<section class="panel"><div class="row"><h2>ประวัติคำขอและผลการตัดสินใจของระบบ AI</h2><span class="status">AI ที่อธิบายเหตุผลได้</span></div><div class="request-list" id="requestList"></div></section>
</main>
<script>
let state=null, lastState=null, map=null, markers={}, busMarkers={}, routeLayers=[], roadCache={};
const $=id=>document.getElementById(id);
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function initMap(){
 if(map)return;
 map=L.map('campus').setView([16.8280,100.2115],16);
 L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:20,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(map);
}
function iconFor(color,label){return L.divIcon({className:'',html:`<div style="width:30px;height:30px;border-radius:50%;background:${color};border:3px solid #07111f;color:#07111f;font-weight:bold;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px #0008">${label}</div>`,iconSize:[30,30],iconAnchor:[15,15]});}
function pointAlong(coords,t){
 if(!coords||coords.length<2)return coords?.[0]||null;
 const lengths=[];let total=0;
 for(let i=1;i<coords.length;i++){const a=coords[i-1],b=coords[i];const d=Math.hypot((b[0]-a[0])*111000,(b[1]-a[1])*105000);lengths.push(d);total+=d;}
 let remain=Math.max(0,Math.min(1,t))*total;
 for(let i=0;i<lengths.length;i++){
  if(remain<=lengths[i]||i===lengths.length-1){const f=lengths[i]?remain/lengths[i]:0;return [coords[i][0]+(coords[i+1][0]-coords[i][0])*f,coords[i][1]+(coords[i+1][1]-coords[i][1])*f];}
  remain-=lengths[i];
 }
 return coords[coords.length-1];
}
async function getRoadGeometry(a,b){
 const key=[a,b].sort().join("|");if(roadCache[key])return roadCache[key];
 const p=state.locations[a],q=state.locations[b];
 const url=`https://router.project-osrm.org/route/v1/driving/${p.lon},${p.lat};${q.lon},${q.lat}?overview=full&geometries=geojson&steps=false`;
 try{const r=await fetch(url);const d=await r.json();if(d.code==='Ok'&&d.routes?.length){roadCache[key]={coords:d.routes[0].geometry.coordinates.map(c=>[c[1],c[0]]),distance:d.routes[0].distance};return roadCache[key];}}catch(e){}
 roadCache[key]={coords:[[p.lat,p.lon],[q.lat,q.lon]],distance:null};return roadCache[key];
}
async function drawMap(){
 initMap();
 Object.values(markers).forEach(m=>map.removeLayer(m));markers={};
 Object.values(busMarkers).forEach(m=>map.removeLayer(m));busMarkers={};
 routeLayers.forEach(l=>map.removeLayer(l));routeLayers=[];
 Object.entries(state.locations).forEach(([name,p])=>{
  const m=L.marker([p.lat,p.lon]).addTo(map).bindPopup(`<b>${esc(name)}</b><br><small>พิกัด ${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}<br>Plus Code: ${esc(p.plus_code||'-')}</small>`);
  markers[name]=m;
 });
 const bounds=Object.values(state.locations).map(p=>[p.lat,p.lon]);
 if(bounds.length)map.fitBounds(bounds,{padding:[35,35]});
 for(let i=0;i<state.vehicles.length;i++){
  const v=state.vehicles[i],p=state.locations[v.position];if(!p)continue;
  let lat=p.lat,lon=p.lon;
  if(v.target&&state.locations[v.target]){
   const route=await getRoadGeometry(v.position,v.target);
   const line=L.polyline(route.coords,{color:v.color,weight:5,opacity:.85,dashArray:'8 8'}).addTo(map);routeLayers.push(line);
   const pos=pointAlong(route.coords,v.progress||0);if(pos){lat=pos[0];lon=pos[1];}
  }
  busMarkers[v.id]=L.marker([lat,lon],{icon:iconFor(v.color,String(i+1)),zIndexOffset:1000}).addTo(map).bindPopup(`<b>${esc(v.id)}</b><br>${esc(v.status)}<br>ตำแหน่ง: ${esc(v.position)}`);
 }
}
function render(){
 if(!state)return;
 const s=state.stats;
 $('sVehicles').textContent=s.vehicle_count;$('sAvailable').textContent=s.available;
 $('sServing').textContent=s.serving;$('sPassengers').textContent=s.passengers;
 $('sRequests').textContent=s.requests;$('runState').textContent=state.running?'กำลังทำงาน':'หยุดชั่วคราว';
 $('pauseBtn').textContent=state.running?'หยุดการเคลื่อนที่':'เริ่มการเคลื่อนที่';
 $('vehicleList').innerHTML=state.vehicles.map(v=>{
  const pct=Math.min(100,v.occupancy/v.capacity*100);
  return `<div class="vehicle"><div class="row"><b>${esc(v.id)}</b><span class="status">${esc(v.status)}</span></div>
  <div class="muted">ผู้โดยสาร ${v.occupancy}/${v.capacity} คน · ตำแหน่ง ${esc(v.position)}${v.target?' → '+esc(v.target):''}</div>
  <div class="bar"><span style="width:${pct}%;background:${v.color}"></span></div></div>`;
 }).join('');
 $('requestList').innerHTML=[...state.requests].reverse().map(r=>{
  const ev=(r.evaluations||[]).map(e=>`<div class="muted ${e.eligible?'':'reject'}">• ${esc(e.vehicle)}: ${e.eligible?'ผ่าน · คะแนน '+e.score:'ไม่ผ่าน · '+esc(e.reason)}</div>`).join('');
  return `<div class="request"><div class="row"><b>${esc(r.id)} · ${esc(r.pickup)} → ${esc(r.destination)}</b><span class="status">${esc(r.status)}</span></div>
  <div class="muted">ผู้โดยสาร ${r.passengers} คน · รถที่ได้รับมอบหมาย: ${esc(r.assigned_vehicle||'ยังไม่มีรถ')} · เวลารอประมาณ ${r.estimated_wait_min??'-'} นาที</div>
  <div class="ai">ผลการตัดสินใจของ AI: ${esc(r.reason||'รอการประมวลผล')}</div><details style="margin-top:8px"><summary class="muted">ดูผลการประเมินรถทุกคัน</summary>${ev||'<p class="muted">ไม่มีข้อมูลการประเมิน</p>'}</details></div>`;
 }).join('');
 drawMap();
}
async function refresh(){try{const r=await fetch('/api/state');state=await r.json();render()}catch(e){}}
async function toggleSim(){await fetch('/api/toggle',{method:'POST'});refresh()}
async function resetSim(){await fetch('/api/reset',{method:'POST'});$('decisionResult').innerHTML='';refresh()}
$('requestForm').addEventListener('submit',async e=>{
 e.preventDefault();const payload={pickup:$('pickup').value,destination:$('destination').value,passengers:Number($('passengers').value)};
 const box=$('decisionResult');box.innerHTML='<p class="muted">ระบบ AI กำลังประเมินรถทุกคัน...</p>';
 try{const r=await fetch('/api/request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 const data=await r.json();if(!r.ok)throw new Error(data.error);
 state=data.state;render();const q=data.request;
 box.innerHTML=`<div class="ai"><b>ผลการตัดสินใจ: ${esc(q.status)}</b><br>${esc(q.assigned_vehicle||'ยังไม่มีรถ — เข้าคิว')}<br>${esc(q.reason)}</div>`;
 }catch(err){box.innerHTML=`<p class="reject">${esc(err.message)}</p>`}
});
refresh();setInterval(refresh,350);
</script></body></html>
"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
