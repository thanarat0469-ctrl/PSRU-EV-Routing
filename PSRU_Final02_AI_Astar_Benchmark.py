# -*- coding: utf-8 -*-
"""
PSRU SMART RIDE
คณะเทคโนโลยีอุตสาหกรรม -> ตึกพิบูล

เวอร์ชันแก้ไข:
- ไม่ใช้ ox.routing.route_to_gdf() จึงไม่เจอ "Graph contains no edges"
- ตรวจสอบว่า graph มีถนนจริงก่อนคำนวณ
- ถ้าขอบเขต polygon ของ OSM ไม่มี edge จะ fallback ไปโหลดถนนรอบมหาวิทยาลัย
- จำกัดเส้นทางให้ใช้เฉพาะถนนภายในกรอบมหาวิทยาลัย
- แสดงเส้นทางตาม geometry ของถนนจริงบน Folium
"""

import sys
import os
import webbrowser
import subprocess
import math
import time
import importlib.util


def ensure_package(package_name, import_name=None):
    import_name = import_name or package_name
    if importlib.util.find_spec(import_name) is None:
        print(f"กำลังติดตั้ง {package_name} ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", package_name
            ]
        )


ensure_package("folium")
ensure_package("networkx")
ensure_package("osmnx")
ensure_package("shapely")

import folium
import networkx as nx
import osmnx as ox
from shapely.geometry import Point, Polygon, LineString, MultiLineString


# ==========================================================
# 1) จุดเรียกรถ / จุดปลายทาง
# ==========================================================
# จุดรับรถ: คณะ/อาคารเทคโนโลยีอุตสาหกรรม (ไม่ใช่คณะเกษตร)
# ให้ OSM ค้นหาพิกัดของสถานที่ตอนรันโปรแกรม เพื่อไม่ล็อกพิกัดผิด
pickup_query = (
    "คณะเทคโนโลยีอุตสาหกรรม มหาวิทยาลัยราชภัฏพิบูลสงคราม, "
    "พิษณุโลก, ประเทศไทย"
)

try:
    pickup_lat, pickup_lon = ox.geocode(pickup_query)
    print(f"พบพิกัดคณะเทคโนโลยีอุตสาหกรรมจาก OSM: {pickup_lat}, {pickup_lon}")
except Exception as e:
    print("ไม่สามารถ geocode คณะเทคโนโลยีอุตสาหกรรมได้:", e)
    print("ใช้พิกัดสำรองบริเวณอาคารเทคโนโลยีอุตสาหกรรม")
    pickup_lat, pickup_lon = 16.835003653482968, 100.21383641931328

pickup = {
    "name": "คณะเทคโนโลยีอุตสาหกรรม",
    "node": "อาคารเทคโนโลยีอุตสาหกรรม",
    "lat": pickup_lat,
    "lon": pickup_lon,
}

destination = {
    "name": "คณะพยาบาลศาสตร์มรพส. ราชภัฏพิบูลสงคราม",
    "node": "Building 4",
    "lat": 16.827724465105913, 
    "lon": 100.21013806048141,
}


# ==========================================================
# 2) ขอบเขต "บริเวณภายในมหาวิทยาลัย"
#
# ใช้กรอบนี้เป็นตัวกรองถนน ไม่ให้เส้นทางวิ่งออกไปถนนรอบนอก
# ปรับค่าได้ภายหลังถ้าต้องการให้แคบ/กว้างขึ้น
# ==========================================================
# ขอบเขตกรองถนนภายในพื้นที่มหาวิทยาลัยแบบไดนามิก
# ครอบคลุมทั้งจุดเทคโนโลยีอุตสาหกรรมและตึกพิบูล
min_lon = min(pickup["lon"], destination["lon"]) - 0.0025
max_lon = max(pickup["lon"], destination["lon"]) + 0.0025
min_lat = min(pickup["lat"], destination["lat"]) - 0.0025
max_lat = max(pickup["lat"], destination["lat"]) + 0.0025

CAMPUS_POLYGON = Polygon([
    (min_lon, min_lat),
    (max_lon, min_lat),
    (max_lon, max_lat),
    (min_lon, max_lat),
])


print("=" * 70)
print("PSRU SMART RIDE")
print("คณะเทคโนโลยีอุตสาหกรรม -> ตึกพิบูล")
print("หาเส้นทางสั้นที่สุดตามถนนภายในมหาวิทยาลัย")
print("=" * 70)


# ==========================================================
# 3) โหลด "ถนน + ถนนบริการภายในมหาวิทยาลัย"
# ==========================================================
print("\n[1/5] กำลังดาวน์โหลดถนนภายใน/รอบมหาวิทยาลัยจาก OpenStreetMap...")

center_lat = (pickup["lat"] + destination["lat"]) / 2
center_lon = (pickup["lon"] + destination["lon"]) / 2

north = max(pickup["lat"], destination["lat"]) + 0.0045
south = min(pickup["lat"], destination["lat"]) - 0.0045
east = max(pickup["lon"], destination["lon"]) + 0.0045
west = min(pickup["lon"], destination["lon"]) - 0.0045

# สำคัญ:
# ใช้ "all" เพื่อให้เห็นถนนบริการ (service road) ภายในมหาวิทยาลัย
# ซึ่ง network_type="drive" ของ OSM อาจไม่ดึงถนนภายในบางช่วงมา
try:
    G_all = ox.graph_from_bbox(
        (west, south, east, north),
        network_type="all",
        simplify=True,
        retain_all=True,
    )
except TypeError:
    G_all = ox.graph_from_bbox(
        north=north,
        south=south,
        east=east,
        west=west,
        network_type="all",
        simplify=True,
        retain_all=True,
    )

print(f"Graph ทั้งหมด: {len(G_all.nodes):,} nodes / {len(G_all.edges):,} edges")

if len(G_all.edges) == 0:
    raise RuntimeError("OpenStreetMap ไม่พบโครงข่ายถนน กรุณาตรวจสอบอินเทอร์เน็ต")

# ถนนที่รถ/รถมหาวิทยาลัยสามารถใช้ได้
ALLOWED_HIGHWAYS = {
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
    "road",
    "track",
}

G = G_all.copy()
remove = []

for u, v, k, data in G.edges(keys=True, data=True):
    highway = data.get("highway", "")

    if isinstance(highway, list):
        highway_values = set(highway)
    else:
        highway_values = {highway}

    # ตัด footway/path/pedestrian/cycleway ฯลฯ ออก
    if not (highway_values & ALLOWED_HIGHWAYS):
        remove.append((u, v, k))

G.remove_edges_from(remove)

print(
    f"หลังเลือกถนนที่รถใช้ได้: "
    f"{len(G.nodes):,} nodes / {len(G.edges):,} edges"
)

if len(G.edges) == 0:
    raise RuntimeError("ไม่พบถนนสำหรับรถภายในพื้นที่")


# ==========================================================
# 4) จำกัดการเลือกเส้นทางให้อยู่ภายในมหาวิทยาลัย
#
# ไม่ตัดถนนทิ้งทั้งหมด เพราะจะทำให้กราฟขาดตอนและปลายทางถูกจับ
# ไปยังถนนผิดจุดเหมือนภาพเดิม
#
# เราใช้ "น้ำหนักลงโทษ" ถนนนอกขอบเขตแทน
# -> ถ้ามีถนนภายใน จะเลือกถนนภายในก่อน
# -> ถนนนอกมหาวิทยาลัยจะถูกเลือกก็ต่อเมื่อไม่มีทางเชื่อมจริง ๆ
# ==========================================================
print("\n[2/5] เตรียมถนนและให้น้ำหนักถนนภายในมหาวิทยาลัย...")

G_inside = G.copy()

for u, v, k, data in G_inside.edges(keys=True, data=True):
    ux = G_inside.nodes[u]["x"]
    uy = G_inside.nodes[u]["y"]
    vx = G_inside.nodes[v]["x"]
    vy = G_inside.nodes[v]["y"]

    geometry = data.get("geometry")

    if geometry is not None:
        inside_ratio = geometry.intersection(CAMPUS_POLYGON).length / max(
            geometry.length, 1e-9
        )
        inside = inside_ratio >= 0.80
    else:
        inside = CAMPUS_POLYGON.covers(Point((ux + vx) / 2, (uy + vy) / 2))

    length = float(data.get("length", 1.0))

    # route_cost ใช้สำหรับ Dijkstra
    # ถนนในมหาวิทยาลัย = ราคาปกติ
    # ถนนนอก = แพงมาก เพื่อบังคับให้อยู่ในมหาวิทยาลัย
    data["route_cost"] = length if inside else length * 1000.0
    data["inside_campus"] = inside

print(
    f"พร้อมใช้งาน: {len(G_inside.nodes):,} nodes / "
    f"{len(G_inside.edges):,} edges"
)

if len(G_inside.edges) == 0:
    raise RuntimeError("ไม่พบ edge ของถนน")


# ==========================================================
# 5) จับคู่จุดอาคารกับ node ถนน
# ==========================================================
print("\n[3/5] หาถนนที่ใกล้คณะเทคโนโลยีอุตสาหกรรมและตึกพิบูล...")

start_node = ox.distance.nearest_nodes(
    G_inside,
    X=pickup["lon"],
    Y=pickup["lat"],
)

end_node = ox.distance.nearest_nodes(
    G_inside,
    X=destination["lon"],
    Y=destination["lat"],
)

print("start node:", start_node)
print("end node  :", end_node)

start_node_distance = ox.distance.great_circle(
    pickup["lat"], pickup["lon"],
    G_inside.nodes[start_node]["y"], G_inside.nodes[start_node]["x"]
)
end_node_distance = ox.distance.great_circle(
    destination["lat"], destination["lon"],
    G_inside.nodes[end_node]["y"], G_inside.nodes[end_node]["x"]
)

print(f"ระยะจากจุดรับถึงถนน: {start_node_distance:.1f} เมตร")
print(f"ระยะจากจุดส่งถึงถนน: {end_node_distance:.1f} เมตร")

if end_node_distance > 250:
    print(
        "⚠️ จุดตึกพิบูลอยู่ห่างถนน OSM มากกว่า 250 ม. "
        "ระบบจะใช้ถนนที่ใกล้ที่สุดที่มีข้อมูลแทน"
    )

if start_node == end_node:
    # ถ้าสองตึกถูกจับเป็น node เดียว ให้ค้นหา node ที่ใกล้ที่สุดหลายตัว
    # เพื่อป้องกันระยะทาง 0 เมตรจากข้อมูล OSM ที่ละเอียดไม่พอ
    start_candidates = ox.distance.nearest_nodes(
        G_inside,
        X=[pickup["lon"]],
        Y=[pickup["lat"]],
    )
    end_candidates = ox.distance.nearest_nodes(
        G_inside,
        X=[destination["lon"]],
        Y=[destination["lat"]],
    )

    raise RuntimeError(
        "จุดถนนที่ใกล้ตึกเทคโนและตึกพิบูลถูกจับเป็น node เดียวกัน "
        "แสดงว่า OSM บริเวณนี้ละเอียดไม่พอสำหรับการหาเส้นทาง "
        "แนะนำให้ใช้พิกัดจุดรับ/จุดส่งที่อยู่บนถนนภายในมหาวิทยาลัยโดยตรง"
    )


# ==========================================================
# 6) เปรียบเทียบ Dijkstra และ A* ด้วยการทดลองซ้ำ 30 รอบ
#    วัดเวลาและจำนวนโหนดที่ถูกนำออกจากคิวเพื่อสำรวจจริง
# ==========================================================
print("\\n[4/5] เปรียบเทียบ Dijkstra และ A* จำนวน 30 รอบ...")

import heapq
import csv
import statistics


def astar_heuristic(u, v):
    """ระยะทางเส้นตรง (เมตร) เป็นค่าประมาณที่เหลือสำหรับ A*."""
    lat1 = math.radians(G_inside.nodes[u]["y"])
    lon1 = math.radians(G_inside.nodes[u]["x"])
    lat2 = math.radians(G_inside.nodes[v]["y"])
    lon2 = math.radians(G_inside.nodes[v]["x"])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6371000 * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def route_cost_total(graph, path, weight="route_cost"):
    """รวมต้นทุนเส้นทาง โดยรองรับ MultiGraph/MultiDiGraph."""
    total = 0.0
    for u, v in zip(path[:-1], path[1:]):
        edge_data = graph.get_edge_data(u, v) or {}
        if graph.is_multigraph():
            costs = [
                float(data.get(weight, 1.0))
                for data in edge_data.values()
            ]
            if not costs:
                raise RuntimeError(f"ไม่พบข้อมูล edge ระหว่าง {u} และ {v}")
            total += min(costs)
        else:
            total += float(edge_data.get(weight, 1.0))
    return total


def measured_search(graph, start, goal, use_astar=False):
    """
    ค้นหาเส้นทางและนับจำนวนโหนดที่ถูกนำออกจาก priority queue
    และผ่านการตรวจสอบว่าเป็นรายการต้นทุนล่าสุดแล้ว (รวม goal)
    """
    counter = 0
    start_h = astar_heuristic(start, goal) if use_astar else 0.0
    queue = [(start_h, counter, 0.0, start)]
    best_cost = {start: 0.0}
    came_from = {}
    explored = 0

    while queue:
        priority, _, popped_cost, current = heapq.heappop(queue)

        # ข้ามรายการเก่าที่ถูกแทนที่ด้วยเส้นทางที่ดีกว่า
        if popped_cost > best_cost.get(current, float("inf")) + 1e-12:
            continue

        explored += 1
        if current == goal:
            path = [goal]
            while path[-1] != start:
                path.append(came_from[path[-1]])
            path.reverse()
            return path, explored, best_cost[goal]

        for neighbor in graph.successors(current):
            edge_data = graph.get_edge_data(current, neighbor) or {}
            if graph.is_multigraph():
                edge_cost = min(
                    float(data.get("route_cost", 1.0))
                    for data in edge_data.values()
                )
            else:
                edge_cost = float(edge_data.get("route_cost", 1.0))

            if edge_cost < 0:
                raise ValueError("Dijkstra และ A* ต้องใช้ต้นทุนขอบที่ไม่ติดลบ")

            new_cost = best_cost[current] + edge_cost
            if new_cost + 1e-12 < best_cost.get(neighbor, float("inf")):
                best_cost[neighbor] = new_cost
                came_from[neighbor] = current
                h = astar_heuristic(neighbor, goal) if use_astar else 0.0
                counter += 1
                heapq.heappush(
                    queue, (new_cost + h, counter, new_cost, neighbor)
                )

    raise nx.NetworkXNoPath(f"ไม่พบเส้นทางจาก {start} ไป {goal}")


NUM_RUNS = 30
benchmark_rows = []
benchmark_results = {}

# Warm-up หนึ่งครั้งต่ออัลกอริทึม ไม่รวมในสถิติ เพื่อลดผลจากการเริ่มต้นครั้งแรก
for use_astar in (False, True):
    measured_search(G_inside, start_node, end_node, use_astar=use_astar)

for algorithm_name, use_astar in (("Dijkstra", False), ("A*", True)):
    run_times = []
    explored_counts = []
    costs = []
    final_path = None

    for run_number in range(1, NUM_RUNS + 1):
        t0 = time.perf_counter()
        path_result, explored, cost = measured_search(
            G_inside, start_node, end_node, use_astar=use_astar
        )
        elapsed = time.perf_counter() - t0

        run_times.append(elapsed)
        explored_counts.append(explored)
        costs.append(cost)
        final_path = path_result

        benchmark_rows.append({
            "algorithm": algorithm_name,
            "run": run_number,
            "time_seconds": f"{elapsed:.9f}",
            "explored_nodes": explored,
            "route_nodes": len(path_result),
            "route_cost": f"{cost:.6f}",
        })

    benchmark_results[algorithm_name] = {
        "path": final_path,
        "cost": costs[-1],
        "avg_time": statistics.mean(run_times),
        "min_time": min(run_times),
        "max_time": max(run_times),
        "avg_explored": statistics.mean(explored_counts),
        "min_explored": min(explored_counts),
        "max_explored": max(explored_counts),
        "route_nodes": len(final_path),
    }

# บันทึกผลรายรอบเป็น CSV เปิดด้วย Excel ได้
csv_file = os.path.abspath("PSRU_route_benchmark_30_runs.csv")
with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "algorithm", "run", "time_seconds",
            "explored_nodes", "route_nodes", "route_cost"
        ],
    )
    writer.writeheader()
    writer.writerows(benchmark_rows)

print("\\n" + "=" * 76)
print(f"ผลเปรียบเทียบอัลกอริทึม ({NUM_RUNS} รอบต่อวิธี)")
print("-" * 76)
for name in ("Dijkstra", "A*"):
    result = benchmark_results[name]
    print(f"{name}:")
    print(f"  เวลาเฉลี่ย       : {result['avg_time']:.6f} วินาที")
    print(f"  เวลาต่ำสุด/สูงสุด: {result['min_time']:.6f} / {result['max_time']:.6f} วินาที")
    print(f"  โหนดสำรวจเฉลี่ย : {result['avg_explored']:.1f} โหนด")
    print(f"  โหนดสำรวจต่ำสุด/สูงสุด: {result['min_explored']} / {result['max_explored']}")
    print(f"  จำนวนโหนดในเส้นทาง: {result['route_nodes']}")
    print(f"  ต้นทุนเส้นทาง    : {result['cost']:.2f}")

dijkstra_cost = benchmark_results["Dijkstra"]["cost"]
astar_cost = benchmark_results["A*"]["cost"]
print("-" * 76)
print("ต้นทุนเส้นทางเท่ากัน:", math.isclose(
    dijkstra_cost, astar_cost, rel_tol=1e-9, abs_tol=1e-6
))
print("ไฟล์ผลทดลองรายรอบ:", csv_file)
print("หมายเหตุ: explored_nodes คือจำนวนโหนดที่นำออกจากคิวและตรวจสอบแล้ว รวมโหนดปลายทาง")
print("=" * 76)

# ใช้เส้นทาง A* แสดงบนแผนที่
route = benchmark_results["A*"]["path"]

# ==========================================================
# 7) คำนวณระยะทางจาก edge ของ route โดยตรง
#    ไม่ใช้ route_to_gdf()
# ==========================================================
route_length_m = 0.0
route_coords = []

for i in range(len(route) - 1):
    u = route[i]
    v = route[i + 1]

    edge_data = G_inside.get_edge_data(u, v)

    if not edge_data:
        continue

    # MultiDiGraph: เลือก edge ที่มี length น้อยที่สุด
    best_key = min(
        edge_data,
        key=lambda key: edge_data[key].get("length", float("inf")),
    )

    data = edge_data[best_key]
    route_length_m += float(data.get("length", 0.0))

    geometry = data.get("geometry")

    if geometry is not None:
        if isinstance(geometry, LineString):
            points = list(geometry.coords)

        elif isinstance(geometry, MultiLineString):
            points = []
            for line in geometry.geoms:
                points.extend(list(line.coords))

        else:
            points = [
                (G_inside.nodes[u]["x"], G_inside.nodes[u]["y"]),
                (G_inside.nodes[v]["x"], G_inside.nodes[v]["y"]),
            ]
    else:
        points = [
            (G_inside.nodes[u]["x"], G_inside.nodes[u]["y"]),
            (G_inside.nodes[v]["x"], G_inside.nodes[v]["y"]),
        ]

    # ไม่ใส่จุดซ้ำตรงรอยต่อ
    if route_coords and points:
        if route_coords[-1] == points[0]:
            points = points[1:]

    route_coords.extend(points)


if route_length_m <= 0:
    raise RuntimeError(
        "เส้นทางมีระยะทาง 0 เมตร ซึ่งหมายถึงข้อมูลถนนไม่สมบูรณ์ "
        "ไม่สร้างแผนที่ผิดพลาดให้"
    )

estimated_minutes = (route_length_m / 1000) / 20 * 60

print("\n" + "=" * 70)
print("ผลการคำนวณ")
print("=" * 70)
print(f"จุดเรียกรถ : {pickup['name']}")
print(f"จุดปลายทาง : {destination['name']}")
print(f"จำนวนจุดบนเส้นทาง : {len(route):,}")
print(f"ระยะทางตามถนนจริง : {route_length_m:.1f} เมตร")
print(f"ระยะทาง : {route_length_m / 1000:.2f} กม.")
print(f"เวลาโดยประมาณ : {estimated_minutes:.1f} นาที")
print("=" * 70)


# ==========================================================
# 8) สร้างแผนที่
# ==========================================================
print("\n[5/5] สร้างแผนที่...")

m = folium.Map(
    location=[16.821, 100.265],
    zoom_start=16,
    tiles=None
)

folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    attr="Tiles © Esri",
    name="แผนที่ถนน",
    overlay=False,
    control=True
).add_to(m)

# ขอบเขตมหาวิทยาลัย
folium.GeoJson(
    CAMPUS_POLYGON.__geo_interface__,
    name="ขอบเขตมหาวิทยาลัย",
    style_function=lambda feature: {
        "color": "green",
        "weight": 3,
        "fillColor": "green",
        "fillOpacity": 0.04,
    },
    tooltip="ขอบเขตพื้นที่ที่ใช้หาเส้นทาง",
).add_to(m)


# ถนนทั้งหมดที่อยู่ในกรอบ แสดงจาง ๆ เพื่อให้เห็นบริบท
road_layer = folium.FeatureGroup(
    name="ถนนภายในพื้นที่",
    show=True,
).add_to(m)

for u, v, k, data in G_inside.edges(keys=True, data=True):
    geometry = data.get("geometry")

    if geometry is None:
        coords = [
            [G_inside.nodes[u]["y"], G_inside.nodes[u]["x"]],
            [G_inside.nodes[v]["y"], G_inside.nodes[v]["x"]],
        ]
    elif isinstance(geometry, LineString):
        coords = [[lat, lon] for lon, lat in geometry.coords]
    elif isinstance(geometry, MultiLineString):
        for line in geometry.geoms:
            coords = [[lat, lon] for lon, lat in line.coords]
            folium.PolyLine(
                coords,
                color="gray",
                weight=2,
                opacity=0.35,
            ).add_to(road_layer)
        continue
    else:
        continue

    folium.PolyLine(
        coords,
        color="gray",
        weight=2,
        opacity=0.35,
    ).add_to(road_layer)


# เส้นทางที่สั้นที่สุดตามถนน
route_layer = folium.FeatureGroup(
    name="🟣 เส้นทาง A*",
    show=True,
).add_to(m)

folium.PolyLine(
    [[lat, lon] for lon, lat in route_coords],
    color="purple",
    weight=8,
    opacity=0.95,
    tooltip="🛣️ เส้นทางที่คำนวณด้วย A* (หลีกเลี่ยงถนนภายนอกตาม route_cost)",
).add_to(route_layer)


# จุดเรียกรถ
folium.Marker(
    [pickup["lat"], pickup["lon"]],
    tooltip="🟢 จุดเรียกรถ - คณะเทคโนโลยีอุตสาหกรรม",
    popup=folium.Popup(
        f"""
        <b>🟢 จุดเรียกรถ</b><br>
        {pickup['name']}<br>
        {pickup['node']}
        """,
        max_width=300,
    ),
    icon=folium.Icon(
        color="green",
        icon="user",
        prefix="fa",
    ),
).add_to(m)


# จุดปลายทาง
folium.Marker(
    [destination["lat"], destination["lon"]],
    tooltip="🔴 จุดปลายทาง - ตึกพิบูล",
    popup=folium.Popup(
        f"""
        <b>🔴 จุดปลายทาง</b><br>
        {destination['name']}<br>
        {destination['node']}<br><br>
        ระยะทางตามถนน: {route_length_m:.1f} เมตร<br>
        เวลาโดยประมาณ: {estimated_minutes:.1f} นาที
        """,
        max_width=320,
    ),
    icon=folium.Icon(
        color="red",
        icon="flag",
        prefix="fa",
    ),
).add_to(m)


# จุดถนนที่ระบบเริ่ม route / จบ route
folium.CircleMarker(
    [G_inside.nodes[start_node]["y"], G_inside.nodes[start_node]["x"]],
    radius=5,
    color="green",
    fill=True,
    tooltip="จุดถนนเริ่มต้น",
).add_to(m)

folium.CircleMarker(
    [G_inside.nodes[end_node]["y"], G_inside.nodes[end_node]["x"]],
    radius=5,
    color="red",
    fill=True,
    tooltip="จุดถนนปลายทาง",
).add_to(m)


# กล่องข้อมูล
info = f"""
<div style="
position: fixed;
top: 15px;
left: 15px;
z-index: 9999;
background: white;
padding: 14px;
border: 2px solid #555;
border-radius: 10px;
width: 280px;
font-size: 14px;
box-shadow: 0 2px 8px rgba(0,0,0,.25);
">
<h3 style="margin-top:0">🚕 PSRU SMART RIDE</h3>
<b>🟢 รับ:</b> {pickup['name']}<br>
<b>🔴 ส่ง:</b> {destination['name']}<br><br>
<b>🛣️ ระยะทางตามถนน:</b><br>
{route_length_m:.1f} เมตร ({route_length_m/1000:.2f} กม.)<br>
<b>⏱️ เวลา:</b> {estimated_minutes:.1f} นาที<br><br>
<span style="color:purple"><b>เส้นสีม่วง</b></span> =
เส้นทางที่คำนวณด้วย A* ตามน้ำหนักถนน route_cost
</div>
"""

m.get_root().html.add_child(folium.Element(info))

# ซูมให้เห็นจุดเริ่ม-ปลาย
m.fit_bounds(
    [
        [pickup["lat"], pickup["lon"]],
        [destination["lat"], destination["lon"]],
    ],
    padding=(40, 40),
)

folium.LayerControl(collapsed=False).add_to(m)


# ==========================================================
# 9) บันทึกและเปิด
# ==========================================================
output_file = "PSRU_Technology_to_Phibun_INSIDE_CAMPUS_FIXED2.html"
m.save(output_file)

full_path = os.path.abspath(output_file)

print("\nสร้างแผนที่สำเร็จ!")
print(full_path)
print("🟢 คณะเทคโนโลยีอุตสาหกรรม = จุดเรียกรถ")
print("🔴 ตึกพิบูล = จุดปลายทาง")
print("🟣 เส้นม่วง = เส้นทาง A* ตามน้ำหนัก route_cost")
print("🟩 กรอบเขียว = พื้นที่ที่ใช้จำกัดเส้นทาง")

webbrowser.open("file://" + full_path)


# ==========================================================
# 10) AI SMART RIDE DECISION ENGINE
# ==========================================================
# ระบบช่วยตัดสินใจเลือกคันรถโดยพิจารณา:
# 1. จำนวนผู้โดยสาร
# 2. จำนวนที่นั่งว่าง
# 3. ระยะห่างจากจุดรับ
# 4. รถกำลังมุ่งหน้าไปทางเดียวกับผู้โดยสารหรือไม่
#
# ตัวอย่าง:
# ผู้โดยสาร 3 คน
# รถ A ใกล้ที่สุด แต่เหลือ 2 ที่นั่ง -> AI ไม่เลือก
# ระบบจะค้นหารถคันอื่นที่รับผู้โดยสารครบได้

print("\n" + "=" * 70)
print("🤖 PSRU SMART RIDE - AI DECISION ENGINE")
print("=" * 70)

# ----------------------------------------------------------
# ข้อมูลคำขอเรียกรถ (แก้ตรงนี้ได้)
# ----------------------------------------------------------
ride_request = {
    "pickup": "ตึกพิบูล",
    "destination": "หอสมุด",
    "passengers": 3
}

# ----------------------------------------------------------
# รถจำลองในระบบ
# สามารถเพิ่ม/ลดจำนวนรถและแก้ข้อมูลได้
#
# seats = จำนวนที่นั่งว่าง
# distance_to_pickup = ระยะจากรถถึงจุดรับ (เมตร)
# heading_to = จุดหมายที่รถกำลังมุ่งหน้าไป
# ----------------------------------------------------------
vehicles = [
    {
        "id": "รถ A",
        "seats": 2,
        "distance_to_pickup": 120,
        "heading_to": "ตึกเทคโน"
    },
    {
        "id": "รถ B",
        "seats": 4,
        "distance_to_pickup": 280,
        "heading_to": "หอสมุด"
    },
    {
        "id": "รถ C",
        "seats": 5,
        "distance_to_pickup": 420,
        "heading_to": "ตึกพิบูล"
    },
    {
        "id": "รถ D",
        "seats": 3,
        "distance_to_pickup": 650,
        "heading_to": "โรงอาหาร"
    }
]

required_seats = ride_request["passengers"]

print(f"👥 ผู้โดยสาร : {required_seats} คน")
print(f"🟢 จุดรับ     : {ride_request['pickup']}")
print(f"🔴 จุดส่ง     : {ride_request['destination']}")
print("-" * 70)

# ----------------------------------------------------------
# AI ประเมินรถแต่ละคัน
# ----------------------------------------------------------
eligible_vehicles = []

for vehicle in vehicles:

    seats = vehicle["seats"]
    distance = vehicle["distance_to_pickup"]
    heading_to = vehicle["heading_to"]

    # ที่นั่งไม่พอ -> ไม่ผ่าน
    if seats < required_seats:
        vehicle["status"] = "ไม่ผ่าน - ที่นั่งไม่พอ"
        vehicle["score"] = -1
        continue

    # คะแนนพื้นฐานจากระยะทาง
    # ยิ่งใกล้ยิ่งได้คะแนนสูง
    distance_score = max(0, 100 - (distance / 10))

    # คะแนนจำนวนที่นั่ง
    # มีที่นั่งพอดีหรือมากกว่าเล็กน้อยถือว่าเหมาะสม
    seat_score = min(30, seats * 5)

    # ถ้าปลายทางของรถตรงกับปลายทางผู้โดยสาร
    destination_score = 30 if heading_to == ride_request["destination"] else 0

    # คะแนนรวม
    total_score = distance_score + seat_score + destination_score

    vehicle["status"] = "ผ่าน"
    vehicle["score"] = total_score

    eligible_vehicles.append(vehicle)

# ----------------------------------------------------------
# แสดงผลการวิเคราะห์
# ----------------------------------------------------------
for vehicle in vehicles:

    print(
        f"{vehicle['id']}: "
        f"ว่าง {vehicle['seats']} ที่ | "
        f"ห่าง {vehicle['distance_to_pickup']} ม. | "
        f"กำลังไป {vehicle['heading_to']} | "
        f"{vehicle['status']}"
    )

# ----------------------------------------------------------
# เลือกรถที่เหมาะสมที่สุด
# ----------------------------------------------------------
if not eligible_vehicles:

    print("\n❌ AI ไม่พบรถที่สามารถรับผู้โดยสารครบจำนวน")
    print(
        f"ต้องการ {required_seats} ที่นั่ง "
        f"แต่ไม่มีรถที่มีที่นั่งเพียงพอ"
    )

else:

    selected_vehicle = max(
        eligible_vehicles,
        key=lambda vehicle: vehicle["score"]
    )

    print("\n" + "=" * 70)
    print("🤖 ผลการตัดสินใจของ AI")
    print("=" * 70)

    print(f"✅ AI เลือก : {selected_vehicle['id']}")
    print(f"💺 ที่นั่งว่าง : {selected_vehicle['seats']} ที่")
    print(
        f"📍 ระยะจากรถถึงจุดรับ : "
        f"{selected_vehicle['distance_to_pickup']} เมตร"
    )
    print(f"🎯 รถกำลังไป : {selected_vehicle['heading_to']}")
    print(f"⭐ คะแนน AI : {selected_vehicle['score']:.1f}")

    # ------------------------------------------------------
    # อธิบายเหตุผลแบบอ่านง่าย
    # ------------------------------------------------------
    reasons = []

    if selected_vehicle["seats"] >= required_seats:
        reasons.append(
            f"มีที่นั่งเพียงพอสำหรับผู้โดยสาร {required_seats} คน"
        )

    if selected_vehicle["distance_to_pickup"] <= 300:
        reasons.append("อยู่ไม่ไกลจากจุดรับ")

    if selected_vehicle["heading_to"] == ride_request["destination"]:
        reasons.append("กำลังมุ่งหน้าไปยังปลายทางเดียวกัน")

    print("\n🧠 เหตุผลที่ AI เลือก:")
    for i, reason in enumerate(reasons, 1):
        print(f"   {i}. {reason}")

    # ------------------------------------------------------
    # แสดงเหตุผลว่าทำไมรถที่ใกล้ที่สุดถึงไม่ถูกเลือก
    # ------------------------------------------------------
    nearest_vehicle = min(
        vehicles,
        key=lambda vehicle: vehicle["distance_to_pickup"]
    )

    if nearest_vehicle["id"] != selected_vehicle["id"]:

        print("\n⚠️ รถที่ใกล้ที่สุดคือ "
              f"{nearest_vehicle['id']}")

        if nearest_vehicle["seats"] < required_seats:
            print(
                f"❌ แต่ไม่สามารถรับได้ เพราะมีที่นั่งว่าง "
                f"{nearest_vehicle['seats']} ที่ "
                f"ขณะที่ต้องการ {required_seats} ที่"
            )
        else:
            print("ℹ️ AI เลือกรถคันอื่นเนื่องจากคะแนนรวมสูงกว่า")

print("=" * 70)
print("🤖 AI Decision Engine ทำงานเสร็จสิ้น")
print("=" * 70)
