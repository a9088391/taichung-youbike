"""受控 HTTP → 真實採集入口 → 隔離 PostgreSQL → 儀表板 SQL 驗證。"""

import json
import os
from pathlib import Path
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collector


TZ = timezone(timedelta(hours=8))
FIXTURE_IDS = {"T02-A", "T02-B", "T02-C", "T02-INACTIVE", "T02-STALE",
               "T02-FUTURE", "T02-30", "T02-OVER30", "T02-UNDER30", "T02-CLOCK"}
MARKER = "ticket02-check disposable verification"
DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "grafana/dashboards"


def require_actor(connection, expected):
    actor = connection.execute("SELECT current_user, session_user").fetchone()
    if actor != (expected, expected):
        raise RuntimeError(f"refusing target: expected database actor {expected}")


def require_disposable(connection):
    if os.environ.get("TICKET02_DISPOSABLE") != "ticket02-check":
        raise RuntimeError("refusing target: TICKET02_DISPOSABLE must be ticket02-check")
    require_actor(connection, "youbike_collector")
    identity = connection.execute("""
        SELECT current_database(), shobj_description(oid, 'pg_database')
        FROM pg_database WHERE datname = current_database()
    """).fetchone()
    if identity != ("youbike", MARKER):
        raise RuntimeError("refusing target: disposable database marker missing")
    ids = {row[0] for row in connection.execute("SELECT DISTINCT station_id FROM station_observations")}
    if ids - FIXTURE_IDS:
        raise RuntimeError("refusing target: non-fixture observations present")


def preflight_collector(connection):
    connection.execute("SET default_transaction_read_only = on")
    require_disposable(connection)
    connection.execute("SELECT last_attempt_at FROM collection_status LIMIT 0")
    connection.execute("SELECT station_id, source_at FROM station_observations LIMIT 0")
    last_attempt = connection.execute("SELECT last_attempt_at FROM collection_status").fetchone()[0]
    original_count = connection.execute("SELECT count(*) FROM station_observations").fetchone()[0]
    return last_attempt, original_count


def load_dashboard(name):
    return json.loads((DASHBOARD_DIR / name).read_text())


def dashboard_sql(connection, raw_sql, districts=("西屯區",), stations=("T02-A",),
                  start="2026-11-16T00:00:00+08:00", end="2026-11-18T00:00:00+08:00"):
    for name, values in (("district", districts), ("station", stations)):
        rendered = sql.SQL(",").join(sql.Literal(value) for value in values).as_string(connection)
        raw_sql = raw_sql.replace("${" + name + ":sqlstring}", rendered)
    time_filter = sql.SQL("source_at BETWEEN {}::timestamptz AND {}::timestamptz").format(
        sql.Literal(start), sql.Literal(end)
    ).as_string(connection)
    raw_sql = raw_sql.replace("$__timeFilter(source_at)", time_filter)
    if "${" in raw_sql or "$__" in raw_sql:
        raise RuntimeError("refusing preflight: unsupported Grafana query macro")
    return raw_sql


def preflight_query(raw_sql):
    return f"SELECT * FROM ({raw_sql.rstrip().rstrip(';')}) AS dashboard_preflight LIMIT 0"


def require_point_only_history(dashboard):
    panel = next((item for item in dashboard["panels"] if item.get("id") == 9), None)
    custom = panel.get("fieldConfig", {}).get("defaults", {}).get("custom", {}) if panel else {}
    if custom.get("drawStyle") != "points" or custom.get("showPoints") != "always":
        raise AssertionError("peak-history panel 9 must render valid observations as points without connecting gaps")


def require_text_stat_selector(panel, column_names, text_columns):
    if not text_columns:
        return
    reducer = panel.get("options", {}).get("reduceOptions", {})
    selector = reducer.get("fields", "")
    if reducer.get("values") is not True:
        raise AssertionError(
            f"Stat panel {panel['id']} returns text columns without reduceOptions.values enabled"
        )
    if not selector:
        raise AssertionError(
            f"Stat panel {panel['id']} ({panel['title']}) returns text columns without reduceOptions.fields"
        )
    try:
        matcher = re.compile(selector[1:-1]) if selector.startswith("/") and selector.endswith("/") else None
    except re.error as error:
        raise AssertionError(f"Stat panel {panel['id']} has an invalid reduceOptions.fields selector") from error
    selected = (
        {name for name in column_names if matcher.search(name)}
        if matcher else {name for name in column_names if name == selector}
    )
    if selected != text_columns:
        raise AssertionError(
            f"Stat panel {panel['id']} selector {selector!r} selects {sorted(selected)}, "
            f"but its query returns text columns {sorted(text_columns)}"
        )


def preflight_dashboards(reader, dashboards):
    require_actor(reader, "youbike_reader")
    reader.execute("SET default_transaction_read_only = on")
    # 以 Grafana 唯讀角色檢查兩張儀表板實際使用的檢視及授權。
    reader.execute("SELECT * FROM current_stations LIMIT 0")
    reader.execute("SELECT * FROM station_history LIMIT 0")

    stat_results = []
    for dashboard in dashboards:
        for panel in dashboard.get("panels", []):
            for target in panel.get("targets", []):
                raw_sql = target.get("rawSql")
                if not raw_sql:
                    continue
                query = dashboard_sql(reader, raw_sql)
                description = reader.execute(preflight_query(query)).description
                if panel.get("type") == "stat":
                    stat_results.append((panel, description))
        for variable in dashboard.get("templating", {}).get("list", []):
            raw_sql = variable.get("query")
            if raw_sql:
                reader.execute(preflight_query(dashboard_sql(reader, raw_sql)))

    type_codes = {column.type_code for _, description in stat_results for column in description}
    categories = dict(reader.execute(
        "SELECT oid, typcategory FROM pg_type WHERE oid = ANY(%s)", (list(type_codes),)
    ).fetchall())
    for panel, description in stat_results:
        column_names = {column.name for column in description}
        text_columns = {
            column.name for column in description if categories.get(column.type_code) == "S"
        }
        require_text_stat_selector(panel, column_names, text_columns)


def station(station_id, at, bikes=10, docks=20, district="西屯區", active="1"):
    return {"sno": station_id, "sna": "同名站 O'Reilly", "sarea": district,
            "lat": "24.161", "lng": "120.647", "tot": "40",
            "sbi": str(bikes), "bemp": str(docks), "act": active,
            "mday": at.strftime("%Y%m%d%H%M%S")}


def run():
    with psycopg.connect(connect_timeout=5, autocommit=True) as database:
        last_attempt, original_count = preflight_collector(database)

    overview_dashboard = load_dashboard("station-overview.json")
    dashboard = load_dashboard("peak-history.json")
    require_point_only_history(dashboard)
    with psycopg.connect(user="youbike_reader", password=os.environ["YOUBIKE_READER_PASSWORD"],
                        connect_timeout=5, autocommit=True) as reader:
        preflight_dashboards(reader, (overview_dashboard, dashboard))

    class Handler(BaseHTTPRequestHandler):
        body = b"[]"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.body)))
            self.end_headers()
            self.wfile.write(self.body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/stations"
    attempt = last_attempt

    def collect(rows, capture_at, expected=0):
        nonlocal attempt
        # 只替換測試時鐘；第二次執行可重抓同組資料，不清空或改寫既有觀測。
        attempt = max(capture_at, attempt + timedelta(seconds=1)) if attempt else capture_at
        clock = iter((attempt, attempt)) if expected == 0 else iter((attempt,))

        class FixtureClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return next(clock).astimezone(tz)

        if expected == 1:
            with psycopg.connect(connect_timeout=5, autocommit=True) as database:
                before_failure_count = database.execute("SELECT count(*) FROM station_observations").fetchone()[0]
        Handler.body = json.dumps(rows, ensure_ascii=False).encode()
        with patch.object(collector, "datetime", FixtureClock):
            assert collector.main(["--once", "--source-url", url]) == expected
        if expected == 1:
            with psycopg.connect(connect_timeout=5, autocommit=True) as database:
                assert database.execute("SELECT error_kind FROM collection_status").fetchone() == ("invalid-data",)
                assert database.execute("SELECT count(*) FROM station_observations").fetchone()[0] == before_failure_count

    try:
        for day in (16, 17):
            for hour, peak in ((7, "morning"), (17, "evening")):
                for minute in range(0, 120, 10):
                    index = (day - 16) * 12 + minute // 10
                    at = datetime(2026, 11, day, hour, tzinfo=TZ) + timedelta(minutes=minute)
                    bikes = 0 if index < (6 if peak == "morning" else 12) else 10
                    docks = 0 if index < (3 if peak == "morning" else 6) else 20
                    rows = [station("T02-A", at, bikes, docks),
                            station("T02-C", at, district="北區"),
                            station("T02-INACTIVE", at, active="0"),
                            station("T02-STALE", at - timedelta(minutes=30)),
                            station("T02-FUTURE", at + timedelta(minutes=2)),
                            station("T02-30", at - timedelta(minutes=29), district="測'試區"),
                            station("T02-OVER30", at - timedelta(minutes=29, seconds=1)),
                            station("T02-UNDER30", at - timedelta(minutes=28, seconds=59))]
                    if index < 23:
                        rows.append(station("T02-B", at))
                    collect(rows, at + timedelta(minutes=1))
        for at in [datetime(2026, 11, 18, hour, minute, second, tzinfo=TZ)
                   for hour, minute, second in [(6, 59, 59), (7, 0, 0), (8, 59, 59),
                                               (9, 0, 0), (16, 59, 59), (17, 0, 0),
                                               (18, 59, 59), (19, 0, 0)]]:
            collect([station("T02-CLOCK", at)], at + timedelta(minutes=1))
        saturday = datetime(2026, 11, 21, 7, tzinfo=TZ)
        collect([station("T02-CLOCK", saturday)], saturday + timedelta(minutes=1))
        # 同一來源時間重抓兩次，並讓第二次抓取已超過30分鐘。
        collect([station("T02-CLOCK", saturday)], saturday + timedelta(hours=1))
        invalid = station("T02-CLOCK", saturday + timedelta(minutes=10))
        del invalid["sbi"]
        collect([invalid], saturday + timedelta(hours=1, minutes=1), expected=1)
        collect([station("T02-CLOCK", saturday)], saturday + timedelta(hours=1, minutes=2))
        # 有效、停用、有效交替：歷史圖排除中間觀測，不能以連線暗示該時段有資料。
        for minute, active in ((0, "1"), (10, "0"), (20, "1")):
            at = datetime(2026, 11, 22, 10, minute, tzinfo=TZ)
            collect([station("T02-CLOCK", at, active=active)], at + timedelta(minutes=1))
    finally:
        server.shutdown()
        server.server_close()
        worker.join()

    with psycopg.connect(connect_timeout=5, autocommit=True) as database:
        require_disposable(database)
        assert database.execute("SELECT count(*) FROM station_observations").fetchone()[0] == 442
        assert database.execute("SELECT error_kind FROM collection_status").fetchone() == (None,)
        assert database.execute("SELECT count(*) FROM station_observations WHERE station_id='T02-B'").fetchone()[0] == 46
        assert database.execute("SELECT count(*) FROM station_observations WHERE station_id='T02-CLOCK'").fetchone()[0] == 12

    with psycopg.connect(user="youbike_reader", password=os.environ["YOUBIKE_READER_PASSWORD"],
                        connect_timeout=5, autocommit=True) as reader:
        assert reader.execute("SELECT station_id FROM current_stations").fetchall() == [("T02-CLOCK",)]
        validity = dict(reader.execute("SELECT station_id, bool_and(valid_sample) FROM station_history GROUP BY station_id"))
        for station_id in ("T02-A", "T02-B", "T02-C", "T02-30", "T02-UNDER30"):
            assert validity[station_id], (station_id, validity)
        for station_id in ("T02-INACTIVE", "T02-STALE", "T02-FUTURE", "T02-OVER30"):
            assert not validity[station_id], (station_id, validity)
        assert reader.execute("""
            SELECT count(*) FILTER (WHERE valid_sample), count(*) FILTER (WHERE NOT valid_sample)
            FROM station_history WHERE station_id='T02-CLOCK'
        """).fetchone() == (11, 1)
        boundaries = reader.execute("""
            SELECT to_char(source_at AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'), peak
            FROM station_history WHERE station_id='T02-CLOCK' ORDER BY source_at
        """).fetchall()
        assert boundaries == [
            ("2026-11-18 06:59:59", None), ("2026-11-18 07:00:00", "早尖峰"),
            ("2026-11-18 08:59:59", "早尖峰"), ("2026-11-18 09:00:00", None),
            ("2026-11-18 16:59:59", None), ("2026-11-18 17:00:00", "晚尖峰"),
            ("2026-11-18 18:59:59", "晚尖峰"), ("2026-11-18 19:00:00", None),
            ("2026-11-21 07:00:00", None),
            ("2026-11-22 10:00:00", None), ("2026-11-22 10:10:00", None),
            ("2026-11-22 10:20:00", None),
        ], boundaries
        assert not reader.execute("SELECT has_table_privilege('youbike_reader', 'station_observations', 'SELECT')").fetchone()[0]
        assert not reader.execute("SELECT has_table_privilege('youbike_reader', 'station_history', 'INSERT')").fetchone()[0]
        panels = {panel["id"]: panel for panel in dashboard["panels"]}

        def query(panel_id, districts=("西屯區",), stations=("T02-A", "T02-B"),
                  start="2026-11-16T00:00:00+08:00", end="2026-11-18T00:00:00+08:00"):
            raw = dashboard_sql(reader, panels[panel_id]["targets"][0]["rawSql"],
                                districts, stations, start, end)
            return reader.execute(raw).fetchall()

        # 直接執行受版本控制的儀表板查詢，避免測試另一份近似 SQL。
        assert query(3) == [("T02-A", "同名站 O'Reilly", "西屯區", 24, 25.0, 12.5)]
        assert query(4) == query(3)
        assert query(5) == [("T02-A", "同名站 O'Reilly", "西屯區", 24, 50.0, 25.0)]
        assert query(6) == query(5)
        details = query(7)
        assert [(row[0], row[3], row[4]) for row in details] == [("T02-A", "早尖峰", 24), ("T02-A", "晚尖峰", 24),
                                                                              ("T02-B", "早尖峰", 23), ("T02-B", "晚尖峰", 23)]
        assert query(3, stations=("T02-B",)) == []
        assert len(query(7, stations=("T02-B",))) == 2
        assert query(3, districts=("北區",), stations=("T02-C",))[0][0] == "T02-C"
        assert query(3, districts=("北區",)) == []
        assert query(3, stations=("T02-A",), end="2026-11-17T00:00:00+08:00") == []
        assert query(1, stations=("T02-INACTIVE",)) == [("無資料",)]
        assert query(1, start="2020-01-01T00:00:00Z", end="2020-01-02T00:00:00Z") == [("無資料",)]
        assert query(9, stations=("T02-A",))[0][1:] == (0, 0)
        assert len(query(9, stations=("T02-A",))) == 48
        assert query(9) == []  # All 或多站時提示先選單站。
        assert len(query(10, stations=("T02-INACTIVE",))) == 48
        assert query(8, stations=("T02-INACTIVE",)) == [("無資料（觀測皆不合格，見歷史明細）",)]
        assert query(8, stations=("T02-A",), start="2020-01-01T00:00:00Z", end="2020-01-02T00:00:00Z") == [("無資料",)]
        assert query(8) == [("請選擇單一站點查看歷史",)]
        assert query(1, districts=(), stations=()) == [("無資料",)]
        assert query(3, districts=(), stations=()) == []
        assert query(9, districts=(), stations=()) == []
        clock_points = query(9, stations=("T02-CLOCK",), end="2026-11-23T00:00:00+08:00")
        assert len(clock_points) == 11
        assert [row[0] for row in clock_points[-2:]] == [
            datetime(2026, 11, 22, 10, tzinfo=TZ), datetime(2026, 11, 22, 10, 20, tzinfo=TZ),
        ]
        weekday_points = query(9, stations=("T02-A",))
        assert len(weekday_points) == 48
        weekday_times = [row[0] for row in weekday_points]
        long_gap = (datetime(2026, 11, 16, 8, 50, tzinfo=TZ),
                    datetime(2026, 11, 16, 17, tzinfo=TZ))
        assert long_gap in set(zip(weekday_times, weekday_times[1:]))
        clock_details = query(10, stations=("T02-CLOCK",), end="2026-11-23T00:00:00+08:00")
        assert len(clock_details) == 12
        assert [(row[0], row[6]) for row in clock_details if row[6] != "有效"] == [
            ("2026-11-22 10:10:00", "停用（不計入比例）"),
        ]
        # 包含引號的行政區與站名，仍以穩定站號查詢，不影響 SQL。
        assert len(query(10, districts=("測'試區",), stations=("T02-30",))) == 48
        for variable in dashboard["templating"]["list"]:
            raw = variable["query"]
            if variable["name"] == "station":
                raw = raw.replace("${district:sqlstring}", "'西屯區'")
            options = reader.execute(raw).fetchall()
            if variable["name"] == "station":
                assert {row[1] for row in options} == FIXTURE_IDS - {"T02-C", "T02-30"}
                assert len({row[0] for row in options}) == len(options)
        print(f"PASS: 442 observations; previous={original_count}; HTTP collector, age/peak boundaries, duplicate/invalid/missing data, 23/24, ratios, filters, history, reader grants")


if __name__ == "__main__":
    run()
