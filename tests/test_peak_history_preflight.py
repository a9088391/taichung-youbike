"""前置檢查必須攔住 Grafana 設定與資料庫角色的已知錯誤。"""

from copy import deepcopy
import unittest
from unittest.mock import patch

import integration_peak_history as integration


class PeakHistoryPreflightTests(unittest.TestCase):
    def test_text_stat_panels_select_their_query_text_field(self):
        cases = (
            ("station-overview.json", 3, "採集狀態"),
            ("station-overview.json", 4, "最後成功採集"),
            ("peak-history.json", 1, "資料狀態"),
            ("peak-history.json", 2, "資料狀態"),
            ("peak-history.json", 8, "歷史狀態"),
        )
        for name, panel_id, field in cases:
            with self.subTest(dashboard=name, panel_id=panel_id):
                dashboard = integration.load_dashboard(name)
                panel = next(item for item in dashboard["panels"] if item["id"] == panel_id)
                integration.require_text_stat_selector(panel, {field}, {field})

    def test_missing_or_mismatched_text_stat_selector_fails(self):
        for selector in ("", "/^不存在的欄位$/"):
            with self.subTest(selector=selector):
                dashboard = deepcopy(integration.load_dashboard("peak-history.json"))
                panel = next(item for item in dashboard["panels"] if item["id"] == 1)
                panel["options"]["reduceOptions"]["fields"] = selector
                with self.assertRaisesRegex(AssertionError, "reduceOptions.fields|selects"):
                    integration.require_text_stat_selector(panel, {"資料狀態"}, {"資料狀態"})

    def test_numeric_stat_keeps_its_existing_reducer(self):
        dashboard = integration.load_dashboard("station-overview.json")
        panel = next(item for item in dashboard["panels"] if item["id"] == 1)
        integration.require_text_stat_selector(panel, {"站點數"}, set())

    def test_connected_line_history_variant_fails(self):
        dashboard = deepcopy(integration.load_dashboard("peak-history.json"))
        panel = next(item for item in dashboard["panels"] if item["id"] == 9)
        panel["fieldConfig"]["defaults"]["custom"]["drawStyle"] = "line"
        with self.assertRaisesRegex(AssertionError, "without connecting gaps"):
            integration.require_point_only_history(dashboard)

    def test_collector_role_mismatch_stops_before_fixture_queries(self):
        class Connection:
            def __init__(self):
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, statement, *_):
                self.statements.append(statement)

                class Result:
                    def fetchone(self):
                        return ("youbike_admin", "youbike_admin")

                return Result()

        connection = Connection()
        with patch.dict(integration.os.environ, {"TICKET02_DISPOSABLE": "ticket02-check"}), \
                patch.object(integration.psycopg, "connect", return_value=connection), \
                patch.object(integration.collector, "main") as collector_main:
            with self.assertRaisesRegex(RuntimeError, "expected database actor youbike_collector"):
                integration.run()

        collector_main.assert_not_called()
        self.assertEqual(connection.statements, [
            "SET default_transaction_read_only = on",
            "SELECT current_user, session_user",
        ])


if __name__ == "__main__":
    unittest.main()
