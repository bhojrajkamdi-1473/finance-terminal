"""News engine tests: headline dedup, entity aliases, relevance ranking."""

import unittest

from providers.orchestrator import (
    _entity_aliases,
    _headline_tokens,
    _jaccard,
    _relevance,
    _same_story,
)


class NewsEngineTest(unittest.TestCase):
    def test_headline_similarity(self):
        a = _headline_tokens("TCS announces $2B share buyback program")
        b = _headline_tokens("TCS announces $2B share buyback programme today")
        c = _headline_tokens("Nifty hits record high on banking rally")
        self.assertTrue(_same_story(a, b))
        self.assertFalse(_same_story(a, c))
        self.assertLess(_jaccard(a, c), 0.4)

    def test_aliases_cover_ticker_forms(self):
        aliases = _entity_aliases("TCS.NS")
        for form in ("TCS.NS", "TCS", "NSE:TCS"):
            self.assertIn(form, aliases)
        self.assertEqual(_entity_aliases(None), [])
        self.assertIn("META", _entity_aliases("META"))

    def test_relevance_ranks_company_first(self):
        aliases = _entity_aliases("TCS.NS")
        company = _relevance("TCS Q3 results beat estimates", "", aliases)
        market = _relevance("Nifty ends higher on global cues", "", aliases)
        self.assertGreater(company, market)

    def test_relevance_rejects_false_positives(self):
        aliases = _entity_aliases("ITC.NS")
        # "IT" substring alone must not match; full alias forms required.
        self.assertEqual(_relevance("IT sector outlook improves", "", aliases), 0)


if __name__ == "__main__":
    unittest.main()
