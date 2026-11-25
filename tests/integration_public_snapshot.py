"""第04張專用：真實 reader、官方一次採集及本地原生快照不變檢查。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import urlopen

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import collector
import public_snapshot as snapshot


def guard():
    if os.environ.get("TICKET04_DISPOSABLE") != "ticket04-check" or os.environ.get("PGHOST") != "db":
        raise RuntimeError("ticket04 target guard rejected")
    with psycopg.connect(connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT current_database(), current_user, session_user,
                shobj_description((SELECT oid FROM pg_database WHERE datname=current_database()), 'pg_database')""")
            if cursor.fetchone() != ("youbike", "youbike_collector", "youbike_collector", "ticket04-check disposable verification"):
                raise RuntimeError("ticket04 database guard rejected")


def reader_environment():
    return {**os.environ, "PGUSER": "youbike_reader", "PGPASSWORD": os.environ["YOUBIKE_READER_PASSWORD"]}


def run_cli(*args):
    result = subprocess.run([sys.executable, "-B", "public_snapshot.py", *args],
                            env=reader_environment(), capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError("snapshot CLI failed")
    return json.loads(result.stdout)


def api_snapshot(key):
    with urlopen(f"http://grafana:3000/api/snapshots/{key}", timeout=30) as response:
        content = response.read(snapshot.MAX_BYTES + 1)
    if len(content) > snapshot.MAX_BYTES:
        raise RuntimeError("snapshot response too large")
    return content


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-key", help="existing local snapshot public key; requires --recollect")
    parser.add_argument("--recollect", action="store_true", help="one official collection in the guarded ticket04 DB")
    parser.add_argument("--guard-only", action="store_true", help="check target identity without preparing or collecting")
    args = parser.parse_args()
    if bool(args.snapshot_key) != args.recollect or (args.snapshot_key and not re.fullmatch(r"[A-Za-z0-9]{1,80}", args.snapshot_key)):
        parser.error("--snapshot-key and --recollect must be used together")
    guard()
    if args.guard_only:
        print("ticket04 guard accepted; no collection performed")
        return
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "snapshot.json"
        summary = run_cli("prepare", str(path))
        assert run_cli("check", str(path)) == summary
        payload = json.loads(path.read_bytes())
        fields = payload["dashboard"]["panels"][4]["snapshotData"][0]["fields"]
        actual_rows = list(zip(*(field["values"] for field in fields)))
        # 獨立 SQL 與每個公開欄位逐站核對，不以站數相等代替完整性。
        with psycopg.connect(user="youbike_reader", password=os.environ["YOUBIKE_READER_PASSWORD"], connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute('''SELECT station_id, station_name, district, latitude, longitude,
                    capacity, available_bikes, available_docks,
                    to_char(source_at AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
                    CASE WHEN is_active THEN '營運中' ELSE '停用' END
                    FROM current_stations ORDER BY district COLLATE "C", station_id COLLATE "C"''')
                assert actual_rows == cursor.fetchall()
                cursor.execute("SELECT last_success_at FROM collection_status WHERE singleton = true")
                old_capture = cursor.fetchone()[0]
        if args.recollect:
            before = api_snapshot(args.snapshot_key)
            original_dashboard = json.loads(before)["dashboard"]
            saved_date = original_dashboard["panels"][2]["snapshotData"][0]["fields"][0]["values"][0]
            assert collector.main(["--once"]) == 0
            after = api_snapshot(args.snapshot_key)
            assert after == before
            assert json.loads(after)["dashboard"]["panels"][2]["snapshotData"][0]["fields"][0]["values"][0] == saved_date
            with psycopg.connect(user="youbike_reader", password=os.environ["YOUBIKE_READER_PASSWORD"], connect_timeout=5) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT last_success_at FROM collection_status WHERE singleton = true")
                    assert cursor.fetchone()[0] > old_capture
            summary.update(local_snapshot_unchanged=True,
                           snapshot_response_sha256=hashlib.sha256(before).hexdigest(),
                           saved_snapshot_date=saved_date)
    print(json.dumps({"result": "PASS", "reader_columns_match": True, **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
