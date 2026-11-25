"""準備與檢查固定的 Grafana 原生快照；此工具不發送 HTTP 請求。"""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from collector import TAIWAN_TIME


DISTRICTS = frozenset("中區 東區 南區 西區 北區 西屯區 南屯區 北屯區 豐原區 東勢區 大甲區 清水區 沙鹿區 梧棲區 后里區 神岡區 潭子區 大雅區 新社區 石岡區 外埔區 大安區 烏日區 大肚區 龍井區 霧峰區 太平區 大里區 和平區".split())
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
FIELDS = [("站號", "string"), ("站點", "string"), ("行政區", "string"),
          ("latitude", "number"), ("longitude", "number"), ("總車位", "number"),
          ("可借車數", "number"), ("可還空位", "number"),
          ("來源時間", "string"), ("來源營運狀態", "string")]


class InvalidSnapshot(ValueError):
    pass


def display_time(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidSnapshot("timezone-aware timestamp required")
    return value.astimezone(TAIWAN_TIME).strftime(DATE_FORMAT)


def parse_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", value):
        raise InvalidSnapshot("invalid timestamp")
    try:
        return datetime.strptime(value, DATE_FORMAT).replace(tzinfo=TAIWAN_TIME)
    except ValueError as error:
        raise InvalidSnapshot("invalid timestamp") from error


def validate_rows(rows, captured_at):
    if not isinstance(rows, list) or not 29 <= len(rows) <= 10000:
        raise InvalidSnapshot("nonempty citywide station data required")
    ids = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != len(FIELDS):
            raise InvalidSnapshot("invalid station fields")
        station_id, name, district, latitude, longitude, capacity, bikes, docks, source, state = row
        if not isinstance(station_id, str) or not re.fullmatch(r"[0-9]{6,12}", station_id) or station_id in ids:
            raise InvalidSnapshot("invalid or duplicate station id")
        ids.add(station_id)
        # 公開文字只接受站名字符；拒絕任意連線字串、標記與可執行查詢。
        if (not isinstance(name, str) or not 1 <= len(name) <= 200
                or not re.fullmatch(r"[A-Za-z0-9\u3400-\u9fff\u3000-\u303f\uff08\uff09\uff0c\uff0d\uff06 _().,\[\]/&+'-]+", name)
                or re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|PASSWORD|TOKEN|SECRET)\b", name, re.I)):
            raise InvalidSnapshot("invalid public station name")
        if not isinstance(district, str) or district not in DISTRICTS:
            raise InvalidSnapshot("invalid district")
        for number, lower, upper in ((latitude, -90, 90), (longitude, -180, 180)):
            if type(number) not in (float, int) or not math.isfinite(number) or not lower <= number <= upper:
                raise InvalidSnapshot("invalid coordinates")
        if any(type(value) is not int for value in (capacity, bikes, docks)):
            raise InvalidSnapshot("integer counts required")
        if not 0 <= capacity <= 2147483647 or not 0 <= bikes <= capacity or not 0 <= docks <= capacity:
            raise InvalidSnapshot("invalid station counts")
        if parse_time(source) > captured_at or state not in ("營運中", "停用"):
            raise InvalidSnapshot("invalid source time or operating state")
    if {row[2] for row in rows} != DISTRICTS:
        raise InvalidSnapshot("all 29 districts required")
    if rows != sorted(rows, key=lambda row: (row[2], row[0])):
        raise InvalidSnapshot("station order must be stable")


def frame(fields, rows):
    # Grafana 13.3.1 PanelModel.snapshotData 使用 DataFrameDTO，不是 SQL 查詢回應封套。
    return [{"refId": "A", "fields": [
        {"name": name, "type": kind, "config": {}, "values": [row[index] for row in rows]}
        for index, (name, kind) in enumerate(fields)
    ]}]


def panel(panel_id, kind, title, position):
    return {"id": panel_id, "type": kind, "title": title,
            "gridPos": dict(zip(("x", "y", "w", "h"), position)),
            "fieldConfig": {"defaults": {}, "overrides": []}}


def _build_v1_payload(rows, captured_at, created_at):
    captured = display_time(captured_at)
    created = display_time(created_at)
    captured_at, created_at = parse_time(captured), parse_time(created)
    if created_at < captured_at:
        raise InvalidSnapshot("snapshot precedes collection")
    validate_rows(rows, captured_at)
    panels = []
    for panel_id, title, kind, value in (
            (1, "全市站點", "number", len(rows)),
            (2, "涵蓋行政區", "number", len(DISTRICTS)),
            (3, "快照建立時間（臺灣）", "string", created),
            (4, "資料擷取時間（臺灣）", "string", captured)):
        item = panel(panel_id, "stat", title, ((panel_id - 1) * 6, 0, 6, 4))
        item["snapshotData"] = frame([(title, kind)], [[value]])
        item["options"] = {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": f"/^{title}$/", "values": kind == "string", "limit": 1},
            "orientation": "horizontal", "textMode": "value", "graphMode": "none",
            "colorMode": "value", "wideLayout": True, "justifyMode": "center",
            "text": {"valueSize": 18 if kind == "string" else 36},
        }
        item["fieldConfig"]["defaults"]["color"] = {"mode": "fixed", "fixedColor": "#45c9cf"}
        panels.append(item)
    item = panel(5, "geomap", "全市站點地圖", (0, 7, 16, 15))
    item["snapshotData"] = frame(FIELDS, rows)
    item["options"] = {
        "view": {"id": "coords", "lat": 24.245, "lon": 120.82, "zoom": 9.9},
        "basemap": {"type": "default", "name": "底圖"},
        "controls": {"showZoom": True, "showAttribution": True, "showScale": True},
        "tooltip": {"mode": "details"},
        "layers": [{"name": "YouBike 站點", "type": "markers",
                    "location": {"mode": "coords", "latitude": "latitude", "longitude": "longitude"},
                    "config": {"showLegend": False, "style": {
                        "color": {"fixed": "#45c9cf"}, "opacity": 0.8,
                        "size": {"fixed": 4}, "symbol": {"fixed": "img/icons/marker/circle.svg"}}}}],
    }
    panels.append(item)
    districts = Counter(row[2] for row in rows)
    item = panel(6, "table", "各區站點數", (16, 7, 8, 15))
    item["snapshotData"] = frame([("行政區", "string"), ("站點數", "number")],
                                 [[district, count] for district, count in sorted(districts.items(), key=lambda pair: (-pair[1], pair[0]))])
    item["options"] = {"showHeader": True, "cellHeight": "sm", "enablePagination": True}
    panels.append(item)
    item = panel(7, "table", "站點明細", (0, 22, 24, 14))
    indices = (0, 1, 2, 5, 6, 7, 8, 9)
    item["snapshotData"] = frame([FIELDS[index] for index in indices], [[row[index] for index in indices] for row in rows])
    item["options"] = {"showHeader": True, "cellHeight": "sm", "enablePagination": True}
    item["fieldConfig"]["overrides"] = [{"matcher": {"id": "byName", "options": "來源時間"},
                                          "properties": [{"id": "custom.width", "value": 205}]}]
    panels.append(item)
    for panel_id, title, position, content in (
            (8, "資料來源與授權", (0, 36, 24, 4),
             "[臺中市政府交通局 YouBike 站點與即時車位資料](https://data.gov.tw/dataset/136781) · "
             "[政府資料開放授權條款第 1 版](https://data.gov.tw/license)。各站來源時間保留於地圖與明細，時間皆為臺灣時間。"),
            (9, "固定展示快照", (0, 4, 24, 3),
             f"**固定資料，非即時站況** · 快照建立：{created}（臺灣時間）。"
             f"資料擷取：{captured}。本機後續採集不會更新這份快照；可縮放地圖、查看站點提示與翻閱明細。")):
        item = panel(panel_id, "text", title, position)
        item["options"] = {"mode": "markdown", "content": content}
        panels.append(item)
    title = "臺中 YouBike 全市展示快照"
    dashboard = {
        "title": title, "description": "固定全市站點展示；完整查詢功能請依專案 README 啟動本機版。",
        "schemaVersion": 41, "version": 1, "timezone": "Asia/Taipei", "editable": False,
        "graphTooltip": 0, "timepicker": {"hidden": True},
        "time": {"from": min(row[8] for row in rows).replace(" ", "T") + "+08:00",
                 "to": captured.replace(" ", "T") + "+08:00"},
        "panels": panels,
    }
    return {"dashboard": dashboard, "name": title, "expires": 0, "external": False}


def build_payload(rows, captured_at, created_at):
    # 保留已公開v1的完整白名單；v2只改原生面板呈現，不改任何公開資料框。
    payload = _build_v1_payload(rows, captured_at, created_at)
    dashboard = payload["dashboard"]
    dashboard["version"] = 2
    panels = dashboard["panels"]
    for item in panels[:4]:
        item["gridPos"]["y"] = 5
        item["options"]["colorMode"] = "background"
        item["options"]["text"]["valueSize"] = 22 if item["id"] in (3, 4) else 48
        item["fieldConfig"]["defaults"]["color"]["fixedColor"] = "#075963"
    panels[4]["gridPos"] = {"x": 0, "y": 9, "w": 17, "h": 12}
    panels[5]["gridPos"] = {"x": 17, "y": 9, "w": 7, "h": 12}
    district_counts = panels[5]["snapshotData"][0]["fields"][1]["values"]
    panels[5]["fieldConfig"]["overrides"] = [{
        "matcher": {"id": "byName", "options": "站點數"},
        "properties": [
            {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "gradient", "valueDisplayMode": "text"}},
            {"id": "color", "value": {"mode": "fixed", "fixedColor": "#29d3c3"}},
            {"id": "min", "value": 0}, {"id": "max", "value": max(district_counts)},
            {"id": "unit", "value": "none"}, {"id": "decimals", "value": 0},
        ],
    }]
    panels[6]["gridPos"]["y"] = 21
    panels[7]["gridPos"]["y"] = 35
    panels[7]["options"]["content"] += (
        "\n\n**固定資料，非即時站況**。本機後續採集不會更新這份快照；"
        "可縮放地圖、查看站點提示與翻閱明細。"
    )
    hero = panels[8]
    hero.update(title="", transparent=True, gridPos={"x": 0, "y": 0, "w": 24, "h": 5})
    # 手機先顯示固定性提示；HTML只含固定文案，交由Grafana預設sanitizer處理。
    hero["options"] = {"mode": "html", "content": (
        '<div style="padding:8px 12px;border-left:3px solid #29d3c3;'
        'background:linear-gradient(110deg,#071e2a,#0c373e);border-radius:6px;color:#e6f7f6">'
        '<p style="margin:0;color:#58e4d6;font-size:11px;line-height:1.3;letter-spacing:1px">'
        'TAICHUNG · CITY DATA</p>'
        '<p style="margin:4px 0;line-height:1.3"><span style="display:inline-block;padding:2px 8px;'
        'border:1px solid #cbe45b;border-radius:12px;color:#e0ee85;font-size:12px">'
        '固定資料，非即時站況</span></p>'
        '<h1 style="margin:4px 0;font-size:clamp(18px,2.4vw,32px);line-height:1.2">'
        '臺中 YouBike 全市展示快照</h1>'
        '<p style="margin:4px 0 0;font-size:clamp(12px,1.2vw,17px);line-height:1.4">'
        '用一張地圖，看見城市的站點分布</p></div>'
    )}
    return payload


def check_payload(payload):
    try:
        version = payload["dashboard"]["version"]
        if type(version) is not int or version not in (1, 2):
            raise InvalidSnapshot("unknown public template version")
        panels = payload["dashboard"]["panels"]
        map_fields = panels[4]["snapshotData"][0]["fields"]
        if [(field["name"], field["type"]) for field in map_fields] != FIELDS:
            raise InvalidSnapshot("invalid map fields")
        lengths = [len(field["values"]) for field in map_fields]
        if len(set(lengths)) != 1:
            raise InvalidSnapshot("unequal frame columns")
        rows = [list(row) for row in zip(*(field["values"] for field in map_fields))]
        created = parse_time(panels[2]["snapshotData"][0]["fields"][0]["values"][0])
        captured = parse_time(panels[3]["snapshotData"][0]["fields"][0]["values"][0])
        builder = _build_v1_payload if version == 1 else build_payload
        expected = builder(rows, captured, created)
        # 以固定白名單重建並逐值比對，未知設定／隱藏 metadata 也必須拒絕。
        if json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False) != json.dumps(expected, sort_keys=True, ensure_ascii=False, allow_nan=False):
            raise InvalidSnapshot("payload differs from public template")
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as error:
        raise InvalidSnapshot("invalid public snapshot payload") from error
    return {"stations": len(rows), "districts": len(DISTRICTS), "created_at": display_time(created), "captured_at": display_time(captured)}


def prepare_payload(created_at=None):
    import psycopg

    # 狀態與全市站點同一唯讀交易，避免採集交易切換時混用兩份資料。
    try:
        with psycopg.connect(connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute("SELECT current_user, session_user, last_success_at, error_kind FROM collection_status WHERE singleton = true")
                status = cursor.fetchone()
                if status is None or status[:2] != ("youbike_reader", "youbike_reader") or status[2] is None or status[3] is not None:
                    raise InvalidSnapshot("successful reader snapshot required")
                captured_at = status[2]
                cursor.execute('''SELECT station_id, station_name, district, latitude, longitude,
                    capacity, available_bikes, available_docks,
                    to_char(source_at AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
                    CASE WHEN is_active THEN '營運中' ELSE '停用' END
                    FROM current_stations ORDER BY district COLLATE "C", station_id COLLATE "C"'''
                )
                rows = [list(row) for row in cursor.fetchall()]
    except psycopg.Error as error:
        raise InvalidSnapshot("reader snapshot unavailable") from error
    return build_payload(rows, captured_at, created_at or datetime.now(TAIWAN_TIME))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidSnapshot("duplicate JSON key")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare/check a fixed public Grafana snapshot (no upload)")
    parser.add_argument("action", choices=("prepare", "check"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            payload = prepare_payload()
            summary = check_payload(payload)
            content = (json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()
            if len(content) > MAX_BYTES:
                raise InvalidSnapshot("snapshot too large")
            with args.path.open("xb") as output:
                output.write(content)
        else:
            with args.path.open("rb") as source:
                content = source.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                raise InvalidSnapshot("snapshot too large")
            payload = json.loads(content, object_pairs_hook=unique_object)
            summary = check_payload(payload)
    except (OSError, ValueError, UnicodeError, RecursionError):
        print("snapshot rejected; no upload performed", file=sys.stderr)
        return 1
    print(json.dumps({**summary, "sha256": hashlib.sha256(content).hexdigest()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
