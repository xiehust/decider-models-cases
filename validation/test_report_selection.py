"""Offline ranking checks: identical question sets, preserved ties and control scope."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent / "v2"))
from report_content import SCENARIOS
from report_data import Data
from report_scenario_models import DECISION_KEYS, ScenarioModels, question_ids, scenario_comparison
from report_selection import eligible_decision_models, selection_rows, selection_section


class DecisionRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparison = ScenarioModels(Data())
        cls.rows = {row["key"]: row for row in selection_rows(cls.comparison, SCENARIOS)}

    def test_selection_rows_partition_the_complete_test_set(self):
        c = self.comparison
        ids = [cid for row in self.rows.values() for cid in row["ids"]]
        self.assertEqual(len(self.rows), 12)
        self.assertEqual(len(ids), 76)
        self.assertEqual(set(ids), set(c.items))
        self.assertEqual(sum(len(question_ids(c.items[cid])) for cid in ids), 147)
        self.assertEqual(sum(len(question_ids(item)) for cid, item in c.items.items() if ":turn" not in cid), 86)
        self.assertEqual(sum(len(question_ids(item)) for cid, item in c.items.items() if ":turn" in cid), 61)
        for row in self.rows.values():
            self.assertEqual({r["key"] for r in row["ranking"]}, set(DECISION_KEYS))
            self.assertEqual(len({r["total"] for r in row["ranking"]}), 1)

    def test_ties_are_not_broken_by_price_or_latency(self):
        for key in ("documents", "find-code", "grid_planned"):
            ranks = {r["key"]: r for r in self.rows[key]["ranking"]}
            self.assertEqual(ranks["jev"]["rank"], 1)
            self.assertEqual(ranks["decider"]["rank"], 1)
            self.assertEqual(ranks["laya"]["rank"], 3)
            self.assertNotEqual(ranks["jev"]["cost"], ranks["decider"]["cost"])

    def test_simulation_links_land_on_their_own_visible_group(self):
        expected = {"npc": "compare-npc", "grid_planned": "compare-grid_planned", "grid": "compare-grid"}
        home = selection_section(self.comparison, SCENARIOS)
        scenario = next(s for s in SCENARIOS if s["slug"] == "simulation")
        target = scenario_comparison(self.comparison, Data(), scenario)
        for key, anchor in expected.items():
            self.assertEqual(self.rows[key]["anchor"], anchor)
            self.assertIn(f'href="scenarios/simulation.html#{anchor}"', home)
            self.assertIn(f'<section class="model-case-group" id="{anchor}" data-group-key="{key}">', target)
            self.assertNotIn(f'<details class="model-case-details" id="{anchor}"', target)
        for key, row in self.rows.items():
            if key not in expected:
                self.assertEqual(row["anchor"], "model-comparison")

    def test_use_threshold_is_strict_and_ignores_llm_scores(self):
        results = {
            "jev": {"correct": 9, "total": 10},
            "decider": {"correct": 91, "total": 100},
            "laya": {"correct": 0, "total": 0},
            "opus": {"correct": 10, "total": 10},
        }
        self.assertEqual(eligible_decision_models(results), ["decider"])
        self.assertEqual(eligible_decision_models(results, control=True), [])
        # This would round to 90.0% in the table, but the exact value exceeds 90%.
        results["jev"] = {"correct": 9001, "total": 10000}
        self.assertEqual(eligible_decision_models(results), ["jev", "decider"])

    def test_real_scenario_recommendations_name_only_qualified_deciders(self):
        self.assertEqual(self.rows["code-review"]["eligible_models"], [])
        for key in ("opus", "haiku", "gpt6luna"):
            self.assertEqual(self.rows["code-review"]["results"][key]["correct"], 7)
        self.assertEqual(self.rows["grid"]["eligible_models"], [])
        for key in ("documents", "find-code", "grid_planned"):
            self.assertEqual(self.rows[key]["eligible_models"], ["jev", "decider"])
        self.assertEqual(self.rows["triage"]["eligible_models"], ["jev"])
        self.assertEqual(sum(bool(row["eligible_models"]) for row in self.rows.values()), 10)

    def test_selection_includes_all_llms_and_counts_filtered_answers(self):
        for row in self.rows.values():
            self.assertEqual(set(row["results"]), set(self.comparison.models))
        filtered = self.rows["redteam"]["results"]["opus"]
        self.assertEqual((filtered["correct"], filtered["total"], filtered["unanswered"]), (8, 10, 2))
        html = selection_section(self.comparison, SCENARIOS)
        for key in self.comparison.models:
            self.assertEqual(html.count(f'data-selection-model="{key}"'), 12)

    def test_misuse_control_has_its_own_ranking(self):
        row = self.rows["grid"]
        self.assertTrue(row["control"])
        self.assertEqual([(r["key"], r["correct"], r["rank"]) for r in row["ranking"]],
                         [("laya", 19, 1), ("jev", 12, 2), ("decider", 6, 3)])
        self.assertTrue(all(r["total"] == 30 for r in row["ranking"]))

    def test_overall_ranking_excludes_exactly_the_control(self):
        c = self.comparison
        ids = [cid for cid in c.items if not cid.startswith("grid:")]
        self.assertEqual([(r["key"], r["correct"], r["total"], r["rank"]) for r in c.ranking(ids)],
                         [("jev", 114, 117, 1), ("decider", 93, 117, 2), ("laya", 52, 117, 3)])

    def test_generalized_cascade_matches_existing_jev_estimates(self):
        c = self.comparison
        for key in c.cost.runs:
            old = c.cost.cascade("terse", key)
            new = c.cascade("jev", key)
            self.assertEqual((old["escalated"], old["correct"], old["total"]),
                             (new["escalated"], new["correct"], new["total"]))
            self.assertLess(abs(old["cost"] - new["cost"]), Decimal("1e-24"))
        # All three native models use the same estimate rule; no model gets a fabricated run.
        for key in DECISION_KEYS:
            self.assertEqual(c.cascade(key, "haiku")["total"], 147)


if __name__ == "__main__":
    unittest.main()
