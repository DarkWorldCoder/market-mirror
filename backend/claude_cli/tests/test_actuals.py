import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import actuals


class ActualsTests(unittest.TestCase):
    def test_mapped_csv_retains_provenance_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ads.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["Day", "Region", "Views", "Taps", "Ad"])
                writer.writeheader()
                writer.writerow({"Day": "2026-10-01", "Region": "PH", "Views": "100", "Taps": "5", "Ad": "A"})
                writer.writerow({"Day": "2026-10-02", "Region": "PH", "Views": "10", "Taps": "50", "Ad": "B"})
            result = actuals.normalize(path, "ads", {"date": "Day", "market": "Region",
                                                     "impressions": "Views", "clicks": "Taps", "variant": "Ad"})
            self.assertEqual(result["summary"]["rows_valid"], 1)
            self.assertEqual(result["summary"]["rows_invalid"], 1)
            self.assertEqual(result["observations"][0]["quality"], "user_export_unverified")
            self.assertEqual(result["observations"][0]["market"], "PH")
            self.assertEqual(result["validation_errors"][0]["field"], "metrics")

    def test_missing_market_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "survey.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("date,responses\n2026-10-01,10\n")
            result = actuals.normalize(path, "survey")
            self.assertEqual(result["summary"]["rows_valid"], 0)
            self.assertEqual(result["validation_errors"][0]["field"], "market")

    def test_backtest_aggregates_normalized_ads_and_keeps_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ads.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("date,market,variant,impressions,clicks,conversions\n"
                        "2026-10-01,PH,A,100,5,1\n2026-10-02,PH,A,100,15,2\n")
            result = actuals.normalize(path, "ads")
            ad = actuals.ad_backtest_table(result)["tables"]["ad"][0]
            self.assertEqual(ad["ctr"], 10.0)
            self.assertEqual(ad["conversions"], 3)
            self.assertEqual(ad["dates"], ["2026-10-01", "2026-10-02"])
            self.assertEqual(ad["markets"], ["PH"])

    def test_conflicting_market_hint_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ads.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("date,market,impressions,clicks\n2026-10-01,PH,100,5\n")
            result = actuals.normalize(path, "ads", market="IN")
            self.assertEqual(result["summary"]["rows_invalid"], 1)
            self.assertEqual(result["validation_errors"][0]["field"], "market")


if __name__ == "__main__":
    unittest.main()
