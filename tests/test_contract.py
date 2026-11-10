"""Synthetic tests; no protected credit-union snapshot content."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "submission"))
from contract import Page, Snapshot
from solution import build

class KnowledgeEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = build()
        u = "https://example-cu.test/rates/certificates"
        a = Page(u, "Certificate Rates", "# Certificates\n\n6-month certificate APY: 2.15%\n\n12-month certificate APY: 2.80%", "2026-01-01")
        b = Page(u, "Certificate Rates", "# Certificates\n\n6-month certificate APY: 3.15%\n\n12-month certificate APY: 2.80%", "2026-04-01")
        fee = Page("https://example-cu.test/fees", "Fees", "# Fees\n\nLost debit card replacement fee: $4.25", "2026-01-01")
        self.engine.ingest(Snapshot("jan", "2026-01-01", [a, fee]))
        self.engine.ingest(Snapshot("apr", "2026-04-01", [b]))

    def test_current_source_and_stable_result(self):
        q = "What is the 6-month certificate APY?"
        a = self.engine.answer(q)
        self.assertIn("3.15%", a.text)
        self.assertEqual(a.text, self.engine.answer(q).text)
        self.assertEqual(a.sources[0].url, "https://example-cu.test/rates/certificates")
        self.assertEqual(a.sources[0].snapshot_id, "apr")

    def test_historical_as_of(self):
        a = self.engine.answer("What was the 6-month certificate rate?", as_of="2026-01-20")
        self.assertIn("2.15%", a.text)
        self.assertNotIn("3.15%", a.text)
        self.assertEqual(a.sources[0].snapshot_id, "jan")

    def test_unknown_term_refused(self):
        self.assertFalse(self.engine.answer("What is the 60-month jumbo certificate APY?").confident)

    def test_conflict_has_resolution(self):
        c = next(c for c in self.engine.conflicts() if "6 month" in c.topic.lower())
        self.assertEqual(set(c.values), {"2.15%", "3.15%"})
        self.assertEqual(c.resolution, "3.15%")
        self.assertEqual(len(c.sources), 2)

    def test_stable_fee_fallback_if_missing_recrawl(self):
        a = self.engine.answer("What is the lost debit card replacement fee?")
        self.assertIn("$4.25", a.text)
        self.assertEqual(a.sources[0].snapshot_id, "jan")

    def test_predates_first_snapshot_refuses(self):
        self.assertFalse(self.engine.answer("What is the 6-month certificate rate?", as_of="2025-12-31").confident)

if __name__ == "__main__":
    unittest.main()
