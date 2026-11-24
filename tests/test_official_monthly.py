"""月報頁須完整呈現官方快照，並與站點觀測分開說明。"""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OfficialMonthlyDashboardTests(unittest.TestCase):
    def test_monthly_chart_uses_time_points_and_independent_contiguous_frames(self):
        dashboard = json.loads((ROOT / "grafana/official-monthly.json").read_text())
        chart = next(panel for panel in dashboard["panels"] if panel["id"] == 5)
        self.assertEqual(dashboard["timezone"], "Asia/Taipei")
        self.assertTrue(dashboard["timepicker"]["hidden"])
        self.assertEqual(chart["type"], "xychart")
        self.assertNotIn("$__timeFilter", chart["targets"][0]["rawSql"])
        self.assertEqual(chart["transformations"], [{
            "id": "partitionByValues",
            "options": {"fields": ["連續月份段"], "keepFields": False},
        }])
        self.assertEqual(chart["options"]["mapping"], "auto")
        self.assertEqual(chart["options"]["series"][0]["x"]["matcher"],
                         {"id": "byName", "options": "time"})
        self.assertEqual(chart["options"]["series"][0]["y"]["matcher"],
                         {"id": "byName", "options": "租借車次"})
        custom = chart["fieldConfig"]["defaults"]["custom"]
        self.assertEqual(custom["show"], "points+lines")
        self.assertEqual(custom["pointShape"], "circle")
        self.assertGreater(custom["pointSize"]["fixed"], 0)
        self.assertEqual(chart["options"]["tooltip"]["mode"], "single")

    def test_summary_cards_keep_month_value_count_and_coverage_distinct(self):
        dashboard = json.loads((ROOT / "grafana/official-monthly.json").read_text())
        cards = [panel for panel in dashboard["panels"] if panel["id"] in (3, 7, 8, 9)]
        self.assertEqual({panel["id"] for panel in cards}, {3, 7, 8, 9})
        self.assertEqual({panel["type"] for panel in cards}, {"stat"})
        self.assertEqual(len({panel["gridPos"]["y"] for panel in cards}), 1)
        self.assertEqual(sum(panel["gridPos"]["w"] for panel in cards), 24)


class OfficialMonthlyGuardTests(unittest.TestCase):
    def test_unconfirmed_target_stops_before_database_queries(self):
        from unittest.mock import Mock, patch
        import integration_official_monthly as integration
        connection = Mock()
        with patch.dict(integration.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TICKET03_DISPOSABLE"):
                integration.require_disposable(connection, "youbike_collector")
        connection.execute.assert_not_called()

    def test_marked_empty_or_fixture_database_is_accepted(self):
        from unittest.mock import Mock, patch
        import integration_official_monthly as integration
        for stations in ([], [("T02-A",)]):
            with self.subTest(stations=stations):
                connection = Mock()
                actor, identity = Mock(), Mock()
                actor.fetchone.return_value = ("youbike_collector", "youbike_collector")
                identity.fetchone.return_value = ("youbike", integration.MARKER)
                connection.execute.side_effect = (actor, identity, iter(stations))
                with patch.dict(integration.os.environ, {"TICKET03_DISPOSABLE": "ticket03-check"}):
                    integration.require_disposable(connection, "youbike_collector")
                self.assertEqual(connection.execute.call_count, 3)

    def test_wrong_actor_marker_or_nonfixture_data_refuses_target(self):
        from unittest.mock import Mock, patch
        import integration_official_monthly as integration
        cases = (
            ([("youbike_admin", "youbike_admin")], None, "expected database actor", 1),
            ([("youbike_collector", "youbike_collector"), ("youbike", None)], None,
             "marker missing", 2),
            ([("youbike_collector", "youbike_collector"), ("youbike", integration.MARKER)],
             [("REAL-STATION",)], "non-fixture", 3),
        )
        for identities, stations, message, count in cases:
            with self.subTest(message=message):
                connection = Mock()
                results = []
                for identity in identities:
                    result = Mock()
                    result.fetchone.return_value = identity
                    results.append(result)
                if stations is not None:
                    results.append(iter(stations))
                connection.execute.side_effect = results
                with patch.dict(integration.os.environ, {"TICKET03_DISPOSABLE": "ticket03-check"}):
                    with self.assertRaisesRegex(RuntimeError, message):
                        integration.require_disposable(connection, "youbike_collector")
                self.assertEqual(connection.execute.call_count, count)


if __name__ == "__main__":
    unittest.main()
