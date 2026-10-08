"""Run: python3 -m unittest test_fetch"""
import unittest
from datetime import timedelta

import fetch


class TitleTest(unittest.TestCase):
    def test_fits(self):
        for t in ["Senior Product Designer", "Product Designer", "UI/UX Designer", "Lead UX Designer",
                  "AI Product Designer", "Staff Product Designer, Payments", "Product Design Lead",
                  "Senior UX/UI Designer (Arabic)", "Conversational AI Designer", "Lead Experience Designer", "Service Designer"]:
            self.assertTrue(fetch.title_fits(t), t)

    def test_rejects(self):
        for t in ["Junior Product Designer", "Graphic Designer", "Product Design Manager", "Head of Design",
                  "UX Researcher", "Design Engineer", "Interior Designer", "Motion Designer", "Product Manager",
                  "Brand Designer", "Product Design Intern", "Freelance UI Designer",
                  "Product Designer (Saudi Nationals Only)", "Tamheer (Product Designer)", "UX Designer - Emirati"]:
            self.assertFalse(fetch.title_fits(t), t)


class PlaceTest(unittest.TestCase):
    def test_gulf(self):
        self.assertEqual(fetch.classify_place("Dubai, United Arab Emirates")[0], "AE")
        self.assertEqual(fetch.classify_place("Riyadh")[0], "SA")
        self.assertEqual(fetch.classify_place("", "sa")[0], "SA")
        self.assertIsNone(fetch.classify_place("Doha, Qatar")[0])  # Gulf means UAE and KSA only
        self.assertEqual(fetch.classify_place("Doha, Qatar; Dubai, UAE")[0], "AE")
        self.assertEqual(fetch.classify_place("Remote - Saudi Arabia", None, True)[0], "SA")

    def test_remote(self):
        self.assertEqual(fetch.classify_place("Worldwide", None, True)[0], "REMOTE")
        self.assertEqual(fetch.classify_place("Remote - EMEA")[0], "REMOTE")
        self.assertEqual(fetch.classify_place("Remote", None, True)[0], "REMOTE")
        self.assertEqual(fetch.classify_place("USA, EMEA", None, True)[0], "REMOTE")

    def test_rejects_other_places(self):
        for text in ["London, UK", "Remote - US", "USA", "Europe", "Berlin", "Cairo, Egypt", "LATAM"]:
            self.assertIsNone(fetch.classify_place(text, None, True)[0], text)
        self.assertIsNone(fetch.classify_place("Singapore", "SG")[0])


class FreshnessTest(unittest.TestCase):
    def job(self, days_old, region="AE", title="Senior Product Designer", source="greenhouse"):
        posted = (fetch.NOW - timedelta(days=days_old)).isoformat()
        return {"region": region, "title": title, "url": "https://x.test/j", "posted": posted, "first_seen": posted, "source": source}

    def test_window(self):
        self.assertTrue(fetch.keep(self.job(6)))
        self.assertFalse(fetch.keep(self.job(8)))  # older than a week drops for every source
        self.assertFalse(fetch.keep(self.job(8, source="linkedin")))
        self.assertFalse(fetch.keep(self.job(1, region=None)))

    def test_failed_feed_keeps_last_jobs_and_closed_roles_drop(self):
        prev = [dict(self.job(1), id="a:1", board="greenhouse:x", source="greenhouse", company="X", tags=[], fit=1, network=False),
                dict(self.job(1), id="b:2", board="lever:y", source="lever", company="Y", tags=[], fit=1, network=False)]
        results = [("greenhouse:x", [], "URLError: timeout"), ("lever:y", [], None)]
        out = fetch.build(results, prev, {})
        self.assertEqual([j["id"] for j in out], ["a:1"])  # x failed: kept; y answered without the job: closed

    def test_dates(self):
        self.assertIsNotNone(fetch.to_dt(1751528852234))
        self.assertIsNotNone(fetch.to_dt("2026-09-29"))
        self.assertIsNotNone(fetch.to_dt("Sun, 04 Oct 2026 07:31:28 +0000"))
        self.assertIsNone(fetch.to_dt("not a date"))


class SlotTest(unittest.TestCase):
    def at(self, hh, mm):
        from datetime import datetime
        fetch.NOW = datetime(2026, 10, 9, hh, mm, tzinfo=fetch.CAIRO).astimezone(fetch.timezone.utc)

    def test_latest_slot(self):
        self.at(11, 55)
        self.assertEqual((fetch.latest_slot().hour, fetch.latest_slot().minute, fetch.latest_slot().day), (11, 40, 9))
        self.at(6, 0)  # before the first slot: yesterday's last slot
        self.assertEqual((fetch.latest_slot().hour, fetch.latest_slot().day), (19, 8))

    def tearDown(self):
        from datetime import datetime
        fetch.NOW = datetime.now(fetch.timezone.utc)


if __name__ == "__main__":
    unittest.main()
