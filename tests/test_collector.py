import io
import json
import threading
import types
import unittest
from contextlib import contextmanager, redirect_stderr
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import collector


def station(**changes):
    row = {
        "sno": "500101001", "sna": "YouBike2.0_市政府", "sarea": "西屯區",
        "lat": "24.161", "lng": "120.647", "tot": "40", "sbi": "0",
        "bemp": "39", "act": "1", "mday": "20261124104702",
    }
    row.update(changes)
    return row


@contextmanager
def http_response(body, status=200, content_type="application/octet-stream", declared_length=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if declared_length is not None:
                self.send_header("Content-Length", str(declared_length))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/stations"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class FetchTests(unittest.TestCase):
    def test_rejects_invalid_batches_and_fields(self):
        invalid = [[], {}, [None], [station(), station()],
                   [station(sno=" ")], [station(sna=None)], [station(sarea="")],
                   [station(lat="NaN")], [station(lng="181")], [station(lat="91")],
                   [station(tot="-1")], [station(sbi="41")], [station(bemp="41")],
                   [station(tot="2147483648")], [station(sbi="1.5")],
                   [station(act="2")], [station(mday="20260230000000")],
                   [station(mday="2026112410472")], [station(sna="bad\x00name")],
                   [station(sna="\ud800")]]
        for value in invalid:
            with self.subTest(value=value):
                with http_response(json.dumps(value).encode()) as url:
                    with self.assertRaises(collector.InvalidData):
                        collector.fetch_snapshot(url)

    def test_rejects_malformed_and_oversized_json(self):
        for body in (b"not json", b"\xff", b" " * (collector.MAX_PAYLOAD_BYTES + 1)):
            with self.subTest(size=len(body)):
                with http_response(body) as url:
                    with self.assertRaises(collector.InvalidData):
                        collector.fetch_snapshot(url)

    def test_http_failure_is_fetch_error(self):
        with http_response(b"private server diagnostics", status=503) as url:
            with self.assertRaises(collector.FetchError):
                collector.fetch_snapshot(url)

    def test_truncated_http_body_is_fetch_error_even_when_partial_json_is_valid(self):
        body = json.dumps([station()]).encode()
        with http_response(body, declared_length=len(body) + 10) as url:
            with self.assertRaises(collector.FetchError):
                collector.fetch_snapshot(url)

    def test_inactive_and_zero_coordinates_are_valid(self):
        with http_response(json.dumps([station(act="0", lat="0", lng="0")]).encode()) as url:
            rows = collector.fetch_snapshot(url)
        self.assertFalse(rows[0].is_active)
        self.assertEqual((rows[0].latitude, rows[0].longitude), (0.0, 0.0))

    def test_octet_stream_snapshot_preserves_zero_and_source_time(self):
        with http_response(json.dumps([station()]).encode()) as url:
            rows = collector.fetch_snapshot(url)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.station_id, "500101001")
        self.assertEqual(row.station_name, "YouBike2.0_市政府")
        self.assertEqual(row.district, "西屯區")
        self.assertEqual(row.available_bikes, 0)
        self.assertEqual(row.available_docks, 39)
        self.assertEqual(row.latitude, 24.161)
        self.assertEqual(row.longitude, 120.647)
        self.assertTrue(row.is_active)
        self.assertEqual(row.source_at, datetime(2026, 11, 24, 10, 47, 2,
                                               tzinfo=timezone(timedelta(hours=8))))


class DatabaseError(Exception):
    pass


class FakeDatabase:
    def __init__(self, last_attempt=None, fail_insert=False):
        self.last_attempt = last_attempt
        self.fail_insert = fail_insert
        self.statements = []
        self.rows = []
        self.rolled_back = False
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, error_type, error, traceback):
        self.rolled_back = error_type is not None
        self.committed = error_type is None

    def cursor(self):
        return self

    def execute(self, query, params=None):
        self.statements.append((query, params))

    def fetchone(self):
        return (self.last_attempt,)

    def executemany(self, query, rows):
        self.statements.append((query, None))
        self.rows.extend(rows)
        if self.fail_insert:
            raise DatabaseError("secret database diagnostics")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.attempt = datetime(2026, 11, 24, 3, tzinfo=timezone.utc)
        self.capture = self.attempt + timedelta(seconds=2)
        self.row = collector.Observation("001", self.attempt, "市政府", "西屯區",
                                         24.161, 120.647, 40, 0, 39, True)

    def test_success_uses_one_atomic_capture_and_preserves_first_observation(self):
        database = FakeDatabase()
        driver = types.SimpleNamespace(connect=lambda **kwargs: database, Error=DatabaseError)
        with patch.dict("sys.modules", psycopg=driver):
            accepted = collector.persist_success([self.row], self.attempt, self.capture)
        self.assertTrue(accepted)
        self.assertTrue(database.committed)
        self.assertIn("FOR UPDATE", database.statements[0][0])
        self.assertEqual(database.rows[0], ("001", self.attempt, "市政府", "西屯區",
                                           24.161, 120.647, 40, 0, 39, True,
                                           self.capture, self.capture))
        insert = database.statements[1][0]
        self.assertIn("ON CONFLICT (station_id, source_at)", insert)
        conflict_update = insert.split("DO UPDATE SET")[1].strip()
        self.assertEqual(conflict_update, "last_captured_at = EXCLUDED.last_captured_at")
        self.assertEqual(database.statements[-1][1], (self.attempt, self.capture))

    def test_late_older_success_or_failure_cannot_overwrite_newer_outcome(self):
        for success in (True, False):
            with self.subTest(success=success):
                database = FakeDatabase(last_attempt=self.capture)
                driver = types.SimpleNamespace(connect=lambda **kwargs: database, Error=DatabaseError)
                with patch.dict("sys.modules", psycopg=driver):
                    if success:
                        accepted = collector.persist_success([self.row], self.attempt, self.capture)
                    else:
                        accepted = collector.persist_failure(self.attempt, "fetch")
                self.assertFalse(accepted)
                self.assertEqual(len(database.statements), 1)
                self.assertEqual(database.rows, [])

    def test_failed_insert_rolls_back_without_success_status(self):
        database = FakeDatabase(fail_insert=True)
        driver = types.SimpleNamespace(connect=lambda **kwargs: database, Error=DatabaseError)
        with patch.dict("sys.modules", psycopg=driver):
            with self.assertRaises(DatabaseError):
                collector.persist_success([self.row], self.attempt, self.capture)
        self.assertTrue(database.rolled_back)
        self.assertFalse(any("UPDATE collection_status" in query
                             for query, _ in database.statements))

    def test_failure_changes_only_attempt_and_sanitized_error(self):
        database = FakeDatabase()
        driver = types.SimpleNamespace(connect=lambda **kwargs: database, Error=DatabaseError)
        with patch.dict("sys.modules", psycopg=driver):
            self.assertTrue(collector.persist_failure(self.attempt, "fetch"))
        update, params = database.statements[-1]
        self.assertNotIn("last_success_at", update)
        self.assertEqual(params, (self.attempt, "fetch"))
        self.assertEqual(database.rows, [])


class CollectionTests(unittest.TestCase):
    def test_periodic_run_survives_unavailable_database_then_collects_next_attempt(self):
        recovered = FakeDatabase()
        driver = types.SimpleNamespace(
            connect=Mock(side_effect=[DatabaseError("secret connect"),
                                      DatabaseError("secret status"), recovered]),
            Error=DatabaseError,
        )
        with patch.dict("sys.modules", psycopg=driver):
            with http_response(json.dumps([station()]).encode()) as url:
                with patch.object(collector, "SOURCE_URL", url):
                    with patch("collector.time.sleep", side_effect=[None, KeyboardInterrupt]) as sleep:
                        with self.assertLogs("collector", level="WARNING") as logs:
                            self.assertEqual(collector.main([]), 0)
        self.assertEqual(len(recovered.rows), 1)
        self.assertEqual(sleep.call_args_list[0].args, (600,))
        self.assertEqual(sleep.call_count, 2)
        self.assertNotIn("secret", "".join(logs.output))

    def test_once_success_returns_zero(self):
        database = FakeDatabase()
        driver = types.SimpleNamespace(connect=lambda **kwargs: database, Error=DatabaseError)
        with patch.dict("sys.modules", psycopg=driver):
            with http_response(json.dumps([station()]).encode()) as url:
                self.assertEqual(collector.main(["--once", "--source-url", url]), 0)
        self.assertEqual(len(database.rows), 1)

    def test_failed_http_or_invalid_data_records_status_without_observations(self):
        for body, status, error_kind in ((b"secret body", 503, "fetch"),
                                         (b"[]", 200, "invalid-data"),
                                         (json.dumps([station(), station()]).encode(), 200, "invalid-data")):
            with self.subTest(error_kind=error_kind):
                database = FakeDatabase()
                driver = types.SimpleNamespace(connect=lambda **kwargs: database, Error=DatabaseError)
                with patch.dict("sys.modules", psycopg=driver):
                    with http_response(body, status=status) as url:
                        with self.assertLogs("collector", level="WARNING") as logs:
                            result = collector.main(["--once", "--source-url", url])
                self.assertEqual(result, 1)
                self.assertEqual(database.rows, [])
                self.assertEqual(database.statements[-1][1][1], error_kind)
                self.assertNotIn("secret body", "".join(logs.output))

    def test_storage_failure_rolls_back_then_records_sanitized_status(self):
        broken = FakeDatabase(fail_insert=True)
        status_database = FakeDatabase()
        connections = iter((broken, status_database))
        driver = types.SimpleNamespace(connect=lambda **kwargs: next(connections), Error=DatabaseError)
        with patch.dict("sys.modules", psycopg=driver):
            with http_response(json.dumps([station()]).encode()) as url:
                with self.assertLogs("collector", level="WARNING") as logs:
                    self.assertEqual(collector.main(["--once", "--source-url", url]), 1)
        self.assertTrue(broken.rolled_back)
        self.assertEqual(status_database.statements[-1][1][1], "storage")
        self.assertNotIn("secret database diagnostics", "".join(logs.output))

    def test_source_override_requires_once(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                collector.main(["--source-url", "http://127.0.0.1:1"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
