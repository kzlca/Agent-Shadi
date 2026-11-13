import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.automation import collector_runner
from app.core.jalali import is_jalali_leap, jalali_to_gregorian, gregorian_to_jalali, validate_jalali
from app.cleanup.engine import _date_sort_value


class JalaliAccuracyTests(unittest.TestCase):
    def test_leap_esfand_and_round_trip(self):
        self.assertTrue(is_jalali_leap(1403))
        self.assertFalse(is_jalali_leap(1404))
        self.assertEqual(jalali_to_gregorian(1403, 12, 30), (2025, 3, 20))
        self.assertEqual(gregorian_to_jalali(2025, 3, 20), (1403, 12, 30))
        with self.assertRaises(ValueError):
            validate_jalali("1404.12.30")

    def test_1405_date_rollover(self):
        self.assertEqual(jalali_to_gregorian(1405, 12, 29), (2027, 3, 20))
        self.assertEqual(jalali_to_gregorian(1406, 1, 1), (2027, 3, 21))

    def test_duplicate_cleaner_uses_same_correct_jalali_conversion(self):
        last_day = _date_sort_value("1405.12.29")
        next_year = _date_sort_value("1406.01.01")
        self.assertEqual(next_year[0] - last_day[0], 1)


class DailyCombinerTests(unittest.TestCase):
    def test_multi_day_range_preserves_each_posting_date(self):
        import json
        with tempfile.TemporaryDirectory(prefix="structura-range-") as tmp:
            base = Path(tmp)
            output = base / "Collected_InputData_Extractions_Outputs"
            output.mkdir()
            config = {
                "telegram_channels": [{
                    "username": "telegram_demo", "search_name": "Rental feed", "deal_type": "rental"
                }],
                "rubika_channels": [],
            }
            rows = [
                {"text": "آگهی مربوط به روز اول", "date": 14050630, "date_str": "1405.06.30"},
                {"text": "آگهی مربوط به روز دوم", "date": 14050631, "date_str": "1405.06.31"},
            ]
            records = output / "telegram_telegram_demo_accepted_records.jsonl"
            records.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
            (output / "telegram_telegram_demo_raw.txt").write_text(
                "آگهی مربوط به روز اول\n\nآگهی مربوط به روز دوم", encoding="utf-8"
            )
            with patch.object(collector_runner, "BASE", base), patch.object(collector_runner, "OUTPUT_DIR", output):
                manifest = collector_runner.combine_for_range(
                    config, "1405.06.30", "1405.06.31", expected_platforms=("telegram",)
                )
                self.assertEqual(len(manifest["days"]), 2)
                self.assertEqual(manifest["days"][0]["outputs"]["rental"]["count"], 1)
                self.assertEqual(manifest["days"][1]["outputs"]["rental"]["count"], 1)
                first_path = base / manifest["days"][0]["outputs"]["rental"]["file"]
                second_path = base / manifest["days"][1]["outputs"]["rental"]["file"]
                self.assertIn("روز اول", first_path.read_text(encoding="utf-8"))
                self.assertNotIn("روز دوم", first_path.read_text(encoding="utf-8"))
                self.assertIn("روز دوم", second_path.read_text(encoding="utf-8"))
                self.assertNotIn("روز اول", second_path.read_text(encoding="utf-8"))
                self.assertTrue((output / "source_ranges" / "1405.06.30_to_1405.06.31").exists())

                # A second platform run over the same range must reuse each
                # day's archived Telegram records and deduplicate exact repeats.
                config_both = {
                    "telegram_channels": config["telegram_channels"],
                    "rubika_channels": [{
                        "username": "rubika_demo", "search_name": "Rental mirror", "deal_type": "rental"
                    }],
                }
                rubika_rows = [
                    {"text": "آگهی مربوط به روز اول", "date": 14050630, "date_str": "1405.06.30"},
                    {"text": "آگهی مستقل روبیکا روز دوم", "date": 14050631, "date_str": "1405.06.31"},
                ]
                rubika_records = output / "rubika_rubika_demo_accepted_records.jsonl"
                rubika_records.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rubika_rows), encoding="utf-8")
                rubika_raw = output / "rubika_rubika_demo_raw.txt"
                rubika_raw.write_text("آگهی مربوط به روز اول\n\nآگهی مستقل روبیکا روز دوم", encoding="utf-8")
                merged = collector_runner.combine_for_range(
                    config_both, "1405.06.30", "1405.06.31", expected_platforms=("rubika",)
                )
                first_merged = base / merged["days"][0]["outputs"]["rental"]["file"]
                second_merged = base / merged["days"][1]["outputs"]["rental"]["file"]
                self.assertEqual(merged["days"][0]["outputs"]["rental"]["count"], 1)
                self.assertEqual(merged["days"][1]["outputs"]["rental"]["count"], 2)
                self.assertEqual(first_merged.read_text(encoding="utf-8").count("روز اول"), 1)
                self.assertIn("روز دوم", second_merged.read_text(encoding="utf-8"))
                self.assertIn("مستقل روبیکا", second_merged.read_text(encoding="utf-8"))

    def test_telegram_then_rubika_same_day_archives_and_deduplicates(self):
        with tempfile.TemporaryDirectory(prefix="structura-combiner-") as tmp:
            base = Path(tmp)
            output = base / "Collected_InputData_Extractions_Outputs"
            output.mkdir()
            telegram = {
                "telegram_channels": [{
                    "username": "telegram_demo", "search_name": "Rental feed", "deal_type": "rental"
                }],
                "rubika_channels": [],
            }
            rubika = {
                "telegram_channels": telegram["telegram_channels"],
                "rubika_channels": [{
                    "username": "rubika_demo", "search_name": "Rental feed mirror", "deal_type": "rental"
                }],
            }
            with patch.object(collector_runner, "BASE", base), patch.object(collector_runner, "OUTPUT_DIR", output):
                (output / "telegram_telegram_demo_raw.txt").write_text(
                    "آگهی مشترک شماره ۱۲۳\n\nآگهی تلگرام اختصاصی", encoding="utf-8"
                )
                first = collector_runner.combine_for_day(telegram, "1405.06.31", expected_platforms=("telegram",))
                day = output / "1405.06.31"
                self.assertTrue((day / "telegram_telegram_demo_raw.txt").exists())
                self.assertEqual(first["outputs"]["rental"]["count"], 2)

                (output / "rubika_rubika_demo_raw.txt").write_text(
                    "آگهی مشترک شماره 123\n\nآگهی جدید روبیکا", encoding="utf-8"
                )
                second = collector_runner.combine_for_day(rubika, "1405.06.31", expected_platforms=("rubika",))
                combined_path = base / second["outputs"]["rental"]["file"]
                combined = combined_path.read_text(encoding="utf-8")
                self.assertEqual(second["outputs"]["rental"]["count"], 3)
                self.assertIn("آگهی تلگرام اختصاصی", combined)
                self.assertIn("آگهی جدید روبیکا", combined)
                self.assertEqual(combined.count("آگهی مشترک"), 1)
                self.assertIn("\n\n", combined)
                self.assertNotIn("\\n\\n", combined)
                self.assertTrue((day / "rubika_rubika_demo_raw.txt").exists())
                self.assertTrue((day / "manifest.json").exists())


    def test_structured_import_preserves_blank_lines_inside_one_post(self):
        import json
        from app.core.normalization import segment_messages
        with tempfile.TemporaryDirectory(prefix="structura-boundaries-") as tmp:
            base = Path(tmp)
            output = base / "Collected_InputData_Extractions_Outputs"
            output.mkdir()
            message_with_paragraph_break = (
                "#آپارتمان فروشی\nبلوار نمونه، ۱۲۰ متر، دو خواب\n\n"
                "قیمت ۴ میلیارد تومان\nتماس: ۰۹۱۲۱۲۳۴۵۶۷"
            )
            second_message = "#زمین فروشی\nزمین ۲۰۰ متر\nقیمت متری ۳۰ میلیون"
            config = {
                "telegram_channels": [{
                    "username": "demo_channel", "search_name": "فروش ملک", "deal_type": "sale"
                }],
                "rubika_channels": [],
            }
            records = output / "telegram_demo_channel_accepted_records.jsonl"
            rows = [
                {"text": message_with_paragraph_break, "date": 14050631, "date_str": "1405.06.31"},
                {"text": second_message, "date": 14050631, "date_str": "1405.06.31"},
            ]
            records.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
            (output / "telegram_demo_channel_raw.txt").write_text(
                message_with_paragraph_break + "\n\n" + second_message, encoding="utf-8"
            )
            with patch.object(collector_runner, "BASE", base), patch.object(collector_runner, "OUTPUT_DIR", output):
                manifest = collector_runner.combine_for_day(
                    config, "1405.06.31", expected_platforms=("telegram",)
                )
                detail = manifest["outputs"]["sale"]
                self.assertEqual(detail["count"], 2)
                self.assertIn("records_file", detail)
                loaded = list(collector_runner.read_combined_messages(base, detail, "1405.06.31"))
                self.assertEqual(len(loaded), 2)
                self.assertEqual(loaded[0][0], message_with_paragraph_break)
                self.assertEqual(loaded[1][0], second_message)
                # Demonstrate why importing the combined TXT with the generic
                # blank-line splitter was wrong: it fractures the first post.
                txt_path = base / detail["file"]
                old_split = segment_messages(txt_path.read_text(encoding="utf-8"))
                self.assertGreater(len(old_split), 2)

    def test_native_collector_writers_preserve_rejected_messages_in_complete_sidecars(self):
        import json
        import os
        import sys
        import types
        # The writer itself does not need calendar/emoji helpers; keep this
        # focused unit test independent from optional collector runtime extras.
        fake_emoji=types.ModuleType("emoji")
        fake_jdatetime=types.ModuleType("jdatetime")
        with patch.dict(sys.modules,{"emoji":fake_emoji,"jdatetime":fake_jdatetime}):
            from app.collectors import telegram_collector, rubika_collector
        with tempfile.TemporaryDirectory(prefix="structura-native-sidecars-") as tmp:
            good = "آگهی فروش آپارتمان ۹۰ متر دو خواب خیابان نمونه قیمت ۳ میلیارد تومان"
            rejected = "سلام دوستان، جلسه امشب ساعت ۸ برگزار می‌شود"
            tg_records = [
                {"text":good,"date":14050631,"date_str":"1405.06.31","fingerprint":telegram_collector.fingerprint(good),"channel":"TG feed"},
                {"text":rejected,"date":14050631,"date_str":"1405.06.31","fingerprint":telegram_collector.fingerprint(rejected),"channel":"TG feed"},
            ]
            rb_records = [
                {"text":good,"date":14050631,"date_str":"1405.06.31","channel":"RB feed"},
                {"text":rejected,"date":14050631,"date_str":"1405.06.31","channel":"RB feed"},
            ]
            env_patch = patch.dict(os.environ, {"STRUCTURA_COLLECT_FILTER_MODE":"real_estate"})
            with patch.object(telegram_collector, "OUTPUT_DIR", tmp), patch.object(rubika_collector, "OUTPUT_DIR", tmp), env_patch:
                telegram_collector.write_outputs({"username":"tg_feed","search_name":"TG feed"}, [good], tg_records, [{"text":rejected,"reason":"No property details"}])
                rubika_collector.write_outputs({"username":"rb_feed","search_name":"RB feed"}, [good], rb_records, [{"text":rejected,"reason":"No property details"}])
            for platform, username in (("telegram","tg_feed"),("rubika","rb_feed")):
                rows=[json.loads(line) for line in (Path(tmp)/f"{platform}_{username}_all_records.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(rows),2)
                rejected_row=next(x for x in rows if x["text"]==rejected)
                self.assertFalse(rejected_row["collector_filter"]["matched"])
                self.assertEqual(rejected_row["channel"],"TG feed" if platform=="telegram" else "RB feed")

    def test_generic_workflow_archives_all_captured_messages_before_policy_routing(self):
        import json
        with tempfile.TemporaryDirectory(prefix="structura-generic-capture-") as tmp:
            base = Path(tmp)
            output = base / "Collected_InputData_Extractions_Outputs"
            output.mkdir()
            config = {
                "workflow_profile": "custom",
                "telegram_channels": [{"username":"support_feed", "search_name":"Support feed", "deal_type":"not-applicable"}],
                "rubika_channels": [],
            }
            rows = [
                {"text":"A general conversation message", "date":14050631, "date_str":"1405.06.31", "channel":"support_feed", "collector_filter":{"mode":"real_estate","matched":False,"reason":"Not a property listing"}},
                {"text":"Customer support ticket #481", "date":14050631, "date_str":"1405.06.31", "channel":"support_feed", "collector_filter":{"mode":"real_estate","matched":True,"reason":"Legacy accepted"}},
            ]
            (output / "telegram_support_feed_all_records.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
            )
            with patch.object(collector_runner, "BASE", base), patch.object(collector_runner, "OUTPUT_DIR", output):
                manifest = collector_runner.combine_for_day(config, "1405.06.31", expected_platforms=("telegram",))
                self.assertEqual(set(manifest["outputs"]), {"all"})
                detail = manifest["outputs"]["all"]
                self.assertEqual(detail["count"], 2)
                self.assertEqual(detail["captured_count"], 2)
                self.assertIn("A general conversation message", (base / detail["file"]).read_text(encoding="utf-8"))
                self.assertTrue((base / manifest["captured_records_file"]).exists())
                imported = list(collector_runner.read_combined_messages(base, detail, "1405.06.31"))
                self.assertEqual(len(imported), 2)
                self.assertFalse(imported[0][4]["matched"])
                self.assertEqual(imported[0][4]["mode"], "real_estate")
                range_manifest=collector_runner.combine_for_range(config,"1405.06.31","1405.06.31",expected_platforms=("telegram",))
                self.assertEqual(range_manifest["captured_count"],2)
                self.assertEqual(range_manifest["total_unique_messages"],2)

    def test_structured_combiner_sidecar_deduplicates_cross_platform_exact_posts(self):
        import json
        with tempfile.TemporaryDirectory(prefix="structura-sidecar-dedupe-") as tmp:
            base = Path(tmp)
            output = base / "Collected_InputData_Extractions_Outputs"
            output.mkdir()
            telegram_cfg = {
                "telegram_channels": [{"username":"tg_demo", "search_name":"sale", "deal_type":"sale"}],
                "rubika_channels": [],
            }
            with patch.object(collector_runner, "BASE", base), patch.object(collector_runner, "OUTPUT_DIR", output):
                row = {"text":"آگهی کامل\nخط دوم\n\nپاراگراف سوم", "date":14050631, "date_str":"1405.06.31"}
                (output / "telegram_tg_demo_accepted_records.jsonl").write_text(
                    json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                first = collector_runner.combine_for_day(telegram_cfg, "1405.06.31", ("telegram",))
                rubika_cfg = {
                    "telegram_channels": telegram_cfg["telegram_channels"],
                    "rubika_channels": [{"username":"rb_demo", "search_name":"sale", "deal_type":"sale"}],
                }
                (output / "rubika_rb_demo_accepted_records.jsonl").write_text(
                    json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                second = collector_runner.combine_for_day(rubika_cfg, "1405.06.31", ("rubika",))
                detail = second["outputs"]["sale"]
                self.assertEqual(detail["count"], 1)
                imported = list(collector_runner.read_combined_messages(base, detail, "1405.06.31"))
                self.assertEqual(len(imported), 1)
                self.assertEqual(imported[0][0], row["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
