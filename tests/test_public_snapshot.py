import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import public_snapshot as snapshot


CAPTURE = datetime(2026, 11, 24, 3, 0, tzinfo=timezone.utc)
CREATED = datetime(2026, 11, 24, 3, 5, tzinfo=timezone.utc)
V1_FIXTURE = Path(__file__).with_name("fixtures") / "public-snapshot-v1.json"


def stations():
    return [
        [str(500100000 + index), f"YouBike2.0_站點{index}", district,
         24.16, 120.64, 40, 0, 39, "2026-11-24 10:59:00", "營運中"]
        for index, district in enumerate(sorted(snapshot.DISTRICTS))
    ]


class PublicSnapshotTests(unittest.TestCase):
    def test_original_v1_golden_still_passes_check_and_cli(self):
        # 改版前以合成29區資料凍結完整v1，避免以新版builder自行證明相容。
        payload = json.loads(V1_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(payload["dashboard"]["version"], 1)
        self.assertEqual(snapshot.check_payload(payload), {
            "stations": 29, "districts": 29,
            "created_at": "2026-11-24 11:05:00", "captured_at": "2026-11-24 11:00:00"})
        with redirect_stdout(io.StringIO()):
            self.assertEqual(snapshot.main(["check", str(V1_FIXTURE)]), 0)

    def test_v2_native_presentation_preserves_all_v1_data_and_fixed_contracts(self):
        payload = snapshot.build_payload(stations(), CAPTURE, CREATED)
        dashboard = payload["dashboard"]
        self.assertEqual(dashboard["version"], 2)
        panels = dashboard["panels"]
        old = json.loads(V1_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual([panel["id"] for panel in panels], list(range(1, 10)))
        for current, original in zip(panels, old["dashboard"]["panels"]):
            self.assertEqual(current.get("snapshotData"), original.get("snapshotData"))
        self.assertEqual(dashboard["time"], old["dashboard"]["time"])
        for item in panels[:4]:
            self.assertEqual(item["options"]["colorMode"], "background")
            self.assertEqual(item["gridPos"]["y"], 5)
            self.assertEqual(item["fieldConfig"]["defaults"]["color"]["fixedColor"], "#075963")
        self.assertGreater(panels[0]["options"]["text"]["valueSize"],
                           panels[2]["options"]["text"]["valueSize"])
        self.assertEqual(panels[4]["gridPos"], {"x": 0, "y": 9, "w": 17, "h": 12})
        self.assertEqual(panels[5]["gridPos"], {"x": 17, "y": 9, "w": 7, "h": 12})
        self.assertEqual(panels[6]["gridPos"]["y"], 21)
        self.assertEqual(panels[7]["gridPos"]["y"], 35)
        for item in panels[5:7]:
            self.assertTrue(item["options"]["enablePagination"])
        self.assertEqual(panels[4]["options"], old["dashboard"]["panels"][4]["options"])
        hero = panels[8]
        self.assertEqual(hero["type"], "text")
        self.assertEqual(hero["gridPos"], {"x": 0, "y": 0, "w": 24, "h": 5})
        self.assertEqual(hero["options"]["mode"], "html")
        for text in ("TAICHUNG · CITY DATA", "臺中 YouBike 全市展示快照",
                     "用一張地圖，看見城市的站點分布", "固定資料，非即時站況"):
            self.assertIn(text, hero["options"]["content"])
        self.assertIn("font-size:clamp(", hero["options"]["content"])
        self.assertLess(hero["options"]["content"].index("固定資料，非即時站況"),
                        hero["options"]["content"].index("<h1"))
        self.assertNotIn("2026-11-24", hero["options"]["content"])
        source = panels[7]["options"]["content"]
        self.assertTrue(source.startswith(old["dashboard"]["panels"][7]["options"]["content"]))
        for text in ("本機後續採集不會更新", "縮放地圖", "站點提示", "翻閱明細"):
            self.assertIn(text, source)
        for forbidden in ("<script", "<style", "<iframe", "http", "<img", "YouBike2.0_站點"):
            self.assertNotIn(forbidden, hero["options"]["content"])
        self.assertEqual(snapshot.check_payload(payload)["stations"], 29)

    def test_district_gauge_displays_station_counts_with_zero_baseline(self):
        rows = stations()
        extra = copy.deepcopy(rows[0])
        extra[0] = "500199999"
        rows.append(extra)
        rows.sort(key=lambda row: (row[2], row[0]))
        district_panel = snapshot.build_payload(rows, CAPTURE, CREATED)["dashboard"]["panels"][5]
        fields = district_panel["snapshotData"][0]["fields"]
        self.assertEqual(fields[1]["values"], [2] + [1] * 28)
        override = next(item for item in district_panel["fieldConfig"]["overrides"]
                        if item["matcher"] == {"id": "byName", "options": "站點數"})
        properties = {item["id"]: item["value"] for item in override["properties"]}
        self.assertEqual(properties["custom.cellOptions"],
                         {"type": "gauge", "mode": "gradient", "valueDisplayMode": "text"})
        self.assertEqual((properties["min"], properties["max"]), (0, 2))
        self.assertEqual((properties["unit"], properties["decimals"]), ("none", 0))

    def test_check_rejects_unknown_or_wrongly_typed_template_versions(self):
        for version in (0, 3, "2", True, 2.0, None):
            changed = snapshot.build_payload(stations(), CAPTURE, CREATED)
            changed["dashboard"]["version"] = version
            with self.subTest(version=version):
                with self.assertRaises(snapshot.InvalidSnapshot):
                    snapshot.check_payload(changed)

    def test_source_timestamp_rejects_unicode_digits_at_build_and_check(self):
        baseline = snapshot.build_payload(stations(), CAPTURE, CREATED)
        fullwidth = str.maketrans("0123456789", "０１２３４５６７８９")
        arabic_indic = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
        for label, translate in (
                ("fullwidth_year", lambda value: value[:4].translate(fullwidth) + value[4:]),
                ("arabic_indic_year", lambda value: value[:4].translate(arabic_indic) + value[4:]),
                ("fullwidth_timestamp", lambda value: value.translate(fullwidth))):
            rows = stations()
            for row in rows:
                row[8] = translate(row[8])
            changed = copy.deepcopy(baseline)
            for panel_index in (4, 6):
                fields = changed["dashboard"]["panels"][panel_index]["snapshotData"][0]["fields"]
                source = next(field for field in fields if field["name"] == "來源時間")
                source["values"] = [translate(value) for value in source["values"]]
            changed["dashboard"]["time"]["from"] = rows[0][8].replace(" ", "T") + "+08:00"
            with self.subTest(case=label, entry="build"):
                with self.assertRaises(snapshot.InvalidSnapshot):
                    snapshot.build_payload(rows, CAPTURE, CREATED)
            with self.subTest(case=label, entry="check"):
                with self.assertRaises(snapshot.InvalidSnapshot):
                    snapshot.check_payload(changed)

    def test_ascii_timestamp_preserves_calendar_validation(self):
        self.assertEqual(snapshot.parse_time("2026-11-24 11:00:00"), CAPTURE)
        with self.assertRaises(snapshot.InvalidSnapshot):
            snapshot.parse_time("2026-02-30 11:00:00")

    def test_native_frames_preserve_every_public_station_and_fixed_dates(self):
        rows = stations()
        payload = snapshot.build_payload(rows, CAPTURE, CREATED)
        summary = snapshot.check_payload(payload)
        self.assertEqual(summary["stations"], 29)
        self.assertEqual(summary["districts"], 29)
        dashboard = payload["dashboard"]
        panels = {panel["id"]: panel for panel in dashboard["panels"]}
        self.assertEqual(panels[1]["snapshotData"][0]["fields"][0]["values"], [29])
        self.assertEqual(panels[3]["snapshotData"][0]["fields"][0]["values"],
                         ["2026-11-24 11:05:00"])
        self.assertEqual(panels[4]["snapshotData"][0]["fields"][0]["values"],
                         ["2026-11-24 11:00:00"])
        map_fields = panels[5]["snapshotData"][0]["fields"]
        self.assertEqual(list(map(list, zip(*(field["values"] for field in map_fields)))), rows)
        self.assertEqual(len(panels[7]["snapshotData"][0]["fields"][0]["values"]), 29)
        encoded = json.dumps(payload)
        for forbidden in ("rawSql", "datasource", "refresh", "postgres", "/d/"):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(payload["expires"], 0)
        self.assertFalse(payload["external"])

    def test_rejects_empty_partial_duplicate_and_invalid_station_data(self):
        cases = [[], stations()[:-1], stations() + [stations()[0]]]
        for index, value in ((0, "postgres://secret@db"), (1, "SELECT password FROM secrets"),
                             (1, "<script>alert(1)</script>"), (2, "未知區"),
                             (3, float("nan")), (3, 91), (4, -181),
                             (5, -1), (6, 41), (6, True), (7, "1"),
                             (8, "2026-11-24 12:00:00"), (8, "invalid"),
                             (9, "unknown")):
            rows = stations()
            rows[0][index] = value
            cases.append(rows)
        for rows in cases:
            with self.subTest(rows=repr(rows)[:90]):
                with self.assertRaises(snapshot.InvalidSnapshot):
                    snapshot.build_payload(rows, CAPTURE, CREATED)
        for capture, created in ((CREATED, CAPTURE), (CAPTURE.replace(tzinfo=None), CREATED)):
            with self.assertRaises(snapshot.InvalidSnapshot):
                snapshot.build_payload(stations(), capture, created)

    def test_check_fails_closed_for_config_metadata_queries_and_inconsistent_frames(self):
        payloads = [json.loads(V1_FIXTURE.read_text(encoding="utf-8")),
                    snapshot.build_payload(stations(), CAPTURE, CREATED)]
        mutations = [
            lambda p: p.update(external=True),
            lambda p: p.update(deleteKey="secret"),
            lambda p: p["dashboard"].update(refresh="1m"),
            lambda p: p["dashboard"].update(links=[{"url": "/d/local"}]),
            lambda p: p["dashboard"]["panels"][0].update(targets=[{"rawSql": "SELECT secret"}]),
            lambda p: p["dashboard"]["panels"][0].update(datasource={"uid": "internal"}),
            lambda p: p["dashboard"]["panels"][4]["snapshotData"][0].update(meta={"secret": "x"}),
            lambda p: p["dashboard"]["panels"][4]["snapshotData"][0]["fields"][0].update(labels={"secret": "x"}),
            lambda p: p["dashboard"]["panels"][4]["snapshotData"][0]["fields"][0]["values"].pop(),
            lambda p: p["dashboard"]["panels"][0]["snapshotData"][0]["fields"][0]["values"].append(3),
            lambda p: p["dashboard"]["panels"][6]["snapshotData"][0]["fields"][0]["values"].reverse(),
            lambda p: p["dashboard"]["panels"][7]["options"].update(content="https://internal.example"),
            lambda p: p["dashboard"]["panels"][8]["options"].update(content="<script>alert(1)</script>"),
            lambda p: p["dashboard"]["panels"][8]["options"].update(content="<img src=x onerror=alert(1)>"),
            lambda p: p["dashboard"]["panels"][8]["options"].update(content="<div>unapproved template</div>"),
            lambda p: p["dashboard"].update(version=3),
        ]
        for payload in payloads:
            for mutate in mutations:
                changed = copy.deepcopy(payload)
                mutate(changed)
                with self.subTest(version=payload["dashboard"]["version"], mutate=mutate):
                    with self.assertRaises(snapshot.InvalidSnapshot):
                        snapshot.check_payload(changed)

    def test_reader_uses_one_readonly_repeatable_read_snapshot_and_reader_actor(self):
        class Cursor:
            def __init__(self):
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def execute(self, sql):
                self.statements.append(sql)

            def fetchone(self):
                return ("youbike_reader", "youbike_reader", CAPTURE, None)

            def fetchall(self):
                return stations()

        cursor = Cursor()
        connection = unittest.mock.MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor
        with patch.dict("sys.modules", {"psycopg": unittest.mock.Mock(connect=unittest.mock.Mock(return_value=connection))}):
            payload = snapshot.prepare_payload(CREATED)
        self.assertEqual(snapshot.check_payload(payload)["stations"], 29)
        self.assertIn("REPEATABLE READ READ ONLY", cursor.statements[0])
        self.assertIn("last_success_at", cursor.statements[1])
        self.assertIn("current_stations", cursor.statements[2])

    def test_cli_prepare_check_preserves_existing_files_and_redacts_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            with patch.object(snapshot, "prepare_payload", return_value=snapshot.build_payload(stations(), CAPTURE, CREATED)):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(snapshot.main(["prepare", str(path)]), 0)
                    original = path.read_bytes()
                    self.assertEqual(snapshot.main(["check", str(path)]), 0)
                error = io.StringIO()
                with redirect_stderr(error):
                    self.assertEqual(snapshot.main(["prepare", str(path)]), 1)
                self.assertEqual(path.read_bytes(), original)
                self.assertNotIn(str(path), error.getvalue())
            path.write_text('{"secret":"x","secret":"y"}')
            with redirect_stderr(io.StringIO()):
                self.assertEqual(snapshot.main(["check", str(path)]), 1)

    def test_reader_rejects_wrong_actor_missing_success_and_failed_collection(self):
        for status in (None, ("youbike_collector", "youbike_collector", CAPTURE, None),
                       ("youbike_reader", "youbike_admin", CAPTURE, None),
                       ("youbike_reader", "youbike_reader", None, None),
                       ("youbike_reader", "youbike_reader", CAPTURE, "fetch")):
            cursor = unittest.mock.MagicMock()
            cursor.__enter__.return_value = cursor
            cursor.fetchone.return_value = status
            connection = unittest.mock.MagicMock()
            connection.__enter__.return_value = connection
            connection.cursor.return_value = cursor
            fake_driver = unittest.mock.Mock(connect=unittest.mock.Mock(return_value=connection), Error=RuntimeError)
            with self.subTest(status=status):
                with patch.dict("sys.modules", {"psycopg": fake_driver}):
                    with self.assertRaises(snapshot.InvalidSnapshot):
                        snapshot.prepare_payload(CREATED)
                self.assertEqual(cursor.execute.call_count, 2)
                cursor.fetchall.assert_not_called()


if __name__ == "__main__":
    unittest.main()
