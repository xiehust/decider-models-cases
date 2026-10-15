"""Offline checks for scenario aggregation and corrected/missing-answer handling."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent / "v2"))
from report_content import SCENARIOS
from report_data import Data
from report_scenario_models import ScenarioModels, expected_text, result_cell, scenario_comparison


class ScenarioComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = Data()
        cls.comparison = ScenarioModels(cls.data)

    def test_every_request_and_judgment_is_shown_once(self):
        c = self.comparison
        ids = [cid for s in SCENARIOS for cid in c.ids_for(s["skill"])]
        self.assertEqual(len(ids), 76)
        self.assertEqual(len(set(ids)), 76)
        total = sum(c.summary(c.ids_for(s["skill"]))["jev"]["total"] for s in SCENARIOS)
        self.assertEqual(total, 147)
        for s in SCENARIOS:
            html = scenario_comparison(c, self.data, s)
            n = c.summary(c.ids_for(s["skill"]))["jev"]["total"]
            self.assertEqual(html.count('data-question-id="'), n)
            self.assertEqual(html.count('class="model-answer '), n * len(c.models))

    def test_scenario_totals_reconcile_with_existing_report(self):
        c = self.comparison
        expected = {
            "jev": (c.cost.jev_correct()[0], c.cost.jev_cost),
            "decider": (c.cost.decider.correct, c.cost.decider.cost),
            "laya": (c.cost.laya.correct, c.cost.laya.cost),
            **{k: (r.t["terse"]["correct"], r.t["terse"]["cost"]) for k, r in c.cost.runs.items()},
        }
        summaries = [c.summary(c.ids_for(s["skill"])) for s in SCENARIOS]
        for key, (correct, cost) in expected.items():
            self.assertEqual(sum(s[key]["correct"] for s in summaries), correct, key)
            actual_cost = sum((s[key]["cost"] for s in summaries), Decimal(0))
            self.assertLess(abs(actual_cost - cost), Decimal("1e-24"), key)

    def test_filtered_response_keeps_denominator_and_charged_cost(self):
        c = self.comparison
        row = c.summary(c.ids_for("jev-redteam"))["opus"]
        self.assertEqual((row["correct"], row["total"], row["unanswered"]), (8, 10, 2))
        self.assertGreater(c.models["opus"]["calls"]["jev-redteam:R1"]["cost"], 0)
        q = c.items["jev-redteam:R1"]["request"]["questions"]["outcome"]
        cell = result_cell(c.models["opus"], "jev-redteam:R1", "outcome", q)
        self.assertIn("内容过滤", cell)
        self.assertIn("未作答", cell)

    def test_false_is_an_answer_not_a_missing_value(self):
        c = self.comparison
        call = c.models["jev"]["calls"]["jev:recovery"]
        self.assertIs(call["answers"]["repeat_informative"], False)
        self.assertEqual(call["checks"]["repeat_informative"], {"answered": True, "correct": True})

    def test_corrected_ui_inputs_and_rerun_answers_are_used(self):
        c = self.comparison
        self.assertEqual(c.items["ui_settings:turn1"]["request"]["state"]["actions_taken"], [])
        self.assertEqual(len(c.items["ui_settings:turn2"]["request"]["state"]["actions_taken"]), 1)
        self.assertTrue(c.models["gpt6luna"]["calls"]["ui_settings:turn2"]["checks"]["next"]["correct"])
        self.assertTrue(c.models["decider"]["calls"]["ui_settings:turn1"]["checks"]["next"]["correct"])

    def test_control_and_regular_simulation_counts_are_separate(self):
        c = self.comparison
        summary = c.summary(c.ids_for("jev-simulation"))
        for row in summary.values():
            self.assertEqual((row["total"], row["normal_total"]), (56, 26))
        self.assertEqual((summary["jev"]["correct"], summary["jev"]["normal_correct"]), (38, 26))
        self.assertEqual((summary["laya"]["correct"], summary["laya"]["normal_correct"]), (36, 17))
        accepted = c.items["grid:turn1"]["grade"]["accept"]
        self.assertEqual(expected_text(c.items["grid:turn1"], "action"), " / ".join(accepted))

    def test_wrong_selected_and_right_reviewed_are_distinct(self):
        c = self.comparison
        q = c.items["jev:recovery"]["request"]["questions"]["next"]
        laya = result_cell(c.models["laya"], "jev:recovery", "next", q)
        self.assertIn("未达标", laya)
        self.assertIn("直接选定", laya)
        q = c.items["jev:recovery"]["request"]["questions"]["repeat_informative"]
        decider = result_cell(c.models["decider"], "jev:recovery", "repeat_informative", q)
        self.assertIn("符合标准", decider)
        self.assertIn("需复核", decider)
        self.assertIn("P(true)", decider)


if __name__ == "__main__":
    unittest.main()
