"""僅在已標記的隔離資料庫驗證月報、Grafana SQL及寫入邊界。"""

import argparse
from datetime import date, timedelta, timezone
import json
import os
from pathlib import Path

import psycopg

from integration_peak_history import FIXTURE_IDS, preflight_dashboards, require_actor


ROOT = Path(__file__).resolve().parents[1]
MARKER = "ticket03-check disposable verification"


def require_disposable(connection, actor):
    if os.environ.get("TICKET03_DISPOSABLE") != "ticket03-check":
        raise RuntimeError("refusing target: TICKET03_DISPOSABLE must be ticket03-check")
    require_actor(connection, actor)
    identity = connection.execute("""
        SELECT current_database(), shobj_description(oid, 'pg_database')
        FROM pg_database WHERE datname = current_database()
    """).fetchone()
    if identity != ("youbike", MARKER):
        raise RuntimeError("refusing target: disposable database marker missing")
    # reader 沒有原始觀測表權限，以既有 station_history 查相同站號邊界。
    table = "station_history" if actor == "youbike_reader" else "station_observations"
    ids = {row[0] for row in connection.execute(f"SELECT DISTINCT station_id FROM {table}")}
    if ids - FIXTURE_IDS:
        raise RuntimeError("refusing target: non-fixture observations present")


def expect_denied(connection):
    permissions = connection.execute("""
        SELECT has_table_privilege(current_user, 'official_monthly_rentals', 'INSERT, UPDATE, DELETE, TRUNCATE')
    """).fetchone()[0]
    assert permissions is False, "monthly report write privileges unexpectedly granted"
    try:
        connection.execute("UPDATE official_monthly_rentals SET rentals = rentals WHERE month = '2026-09-01'")
    except psycopg.errors.InsufficientPrivilege:
        return
    raise AssertionError("monthly report write unexpectedly allowed")


def run(admin=False):
    dashboard = json.loads((ROOT / "grafana/official-monthly.json").read_text())
    with psycopg.connect(connect_timeout=5, autocommit=True) as collector:
        collector.execute("SET default_transaction_read_only = on")
        require_disposable(collector, "youbike_collector")
        collector.execute("SET default_transaction_read_only = off")
        expect_denied(collector)
    with psycopg.connect(user="youbike_reader", password=os.environ["YOUBIKE_READER_PASSWORD"],
                        connect_timeout=5, autocommit=True) as reader:
        reader.execute("SET default_transaction_read_only = on")
        require_disposable(reader, "youbike_reader")
        preflight_dashboards(reader, (dashboard,))
        panels = {panel["id"]: panel for panel in dashboard["panels"]}
        results = {}
        for panel_id in (3, 4, 5, 6, 7, 8, 9, 11):
            query = panels[panel_id]["targets"][0]["rawSql"]
            results[panel_id] = reader.execute(query).fetchall()
        assert results[3] == [("2025-02–2026-09",)], results[3]
        assert results[7] == [("2026-09",)], results[7]
        assert results[8] == [(2091631,)], results[8]
        assert results[9] == [(18,)], results[9]
        assert results[11] == [("2026-11-24",)], results[11]
        trend = results[5]
        assert len(trend) == 18
        taipei = timezone(timedelta(hours=8))
        published = []
        segments = {}
        for at, rentals, segment in trend:
            local_at = at.astimezone(taipei)
            assert (local_at.day, local_at.hour, local_at.minute, local_at.second) == (1, 0, 0, 0)
            month = local_at.strftime("%Y-%m")
            published.append((month, rentals))
            segments.setdefault(segment, []).append(month)
        assert [(months[0], months[-1], len(months)) for months in segments.values()] == [
            ("2025-02", "2025-09", 8), ("2025-11", "2025-12", 2), ("2026-02", "2026-09", 8),
        ]
        # 每個 frame 只容納相鄰月份；缺月前後必須分屬不同 frame。
        for months in segments.values():
            indices = [int(month[:4]) * 12 + int(month[5:]) for month in months]
            assert all(right - left == 1 for left, right in zip(indices, indices[1:]))
        segment_by_month = {month: segment for segment, months in segments.items() for month in months}
        assert segment_by_month["2025-09"] != segment_by_month["2025-11"]
        assert segment_by_month["2025-12"] != segment_by_month["2026-02"]
        table = results[6]
        assert len(table) == 20
        assert [row[0] for row in table if row[1] is None] == ["2025-10", "2026-01"]
        assert [(row[0], row[1]) for row in table if row[1] is not None] == published
        assert published[-1] == (results[7][0][0], results[8][0][0])
        assert len(published) == results[9][0][0]
        assert [row[2] for row in table if row[1] is None] == ["未發布（本次核對未列）"] * 2
        assert all(row[3].startswith("https://newdatacenter.taichung.gov.tw/")
                   for row in table if row[1] is not None)
        observation_count = reader.execute("SELECT count(*) FROM station_history").fetchone()[0]
        if observation_count == 0:
            assert results[4] == [("尚無站點觀測；從首次成功採集開始累積",)]
        else:
            period = reader.execute("""
                SELECT to_char(min(source_at) AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS')
                  || '–' || to_char(max(source_at) AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS')
                FROM station_history
            """).fetchall()
            assert results[4] == period
        reader.execute("SET default_transaction_read_only = off")
        expect_denied(reader)
    print(f"PASS reader: 18 time/value points in 3 contiguous segments, 2 NULL table gaps, latest/month/count/coverage KPIs match, 2026-09=2091631, station observations={observation_count}; text Stat metadata and reader/collector write denial")
    if admin:
        verify_seed()


def verify_seed():
    seed = (ROOT / "postgres/official-monthly.sql").read_text()
    with psycopg.connect(user="youbike_admin", password=os.environ["YOUBIKE_ADMIN_PASSWORD"],
                        connect_timeout=5, autocommit=True) as connection:
        connection.execute("SET default_transaction_read_only = on")
        require_disposable(connection, "youbike_admin")
        monthly = connection.execute("SELECT * FROM official_monthly_rentals ORDER BY month").fetchall()
        stations = connection.execute("SELECT * FROM station_observations ORDER BY station_id, source_at").fetchall()
        status = connection.execute("SELECT * FROM collection_status").fetchall()
        connection.execute("SET default_transaction_read_only = off")
        for _ in range(2):
            connection.execute(seed)
            assert connection.execute("SELECT * FROM official_monthly_rentals ORDER BY month").fetchall() == monthly
        # 使用實際腳本的失敗副本；先前成功的更新亦必須隨整筆交易回滾。
        failing_seed = seed.replace("BEGIN;", "BEGIN;\nUPDATE official_monthly_rentals SET rentals = rentals + 1;", 1)
        if ", 2091631," not in failing_seed:
            raise AssertionError("failure fixture requires the verified 2026-09 row")
        failing_seed = failing_seed.replace(", 2091631,", ", -1,", 1)
        try:
            connection.execute(failing_seed)
        except psycopg.errors.CheckViolation:
            connection.execute("ROLLBACK")
        else:
            raise AssertionError("invalid seed unexpectedly accepted")
        assert connection.execute("SELECT * FROM official_monthly_rentals ORDER BY month").fetchall() == monthly
        for month, rentals in ((date(2026, 9, 30), 1), (date(2026, 9, 1), -1)):
            try:
                connection.execute("UPDATE official_monthly_rentals SET month = %s, rentals = %s WHERE month = '2026-09-01'", (month, rentals))
            except psycopg.errors.CheckViolation:
                pass
            else:
                raise AssertionError("invalid month/rental unexpectedly accepted")
        assert connection.execute("SELECT * FROM station_observations ORDER BY station_id, source_at").fetchall() == stations
        assert connection.execute("SELECT * FROM collection_status").fetchall() == status
        assert connection.execute("SELECT * FROM official_monthly_rentals ORDER BY month").fetchall() == monthly
    print("PASS admin: actual seed twice unchanged; failing seed rolled back earlier update; month-start/negative checks; station/status preserved")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin", action="store_true", help="also run guarded seed replay/rollback checks with the admin secret from environment")
    run(admin=parser.parse_args().admin)
