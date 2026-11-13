import json
import unittest

from app.sources import (
    CaptureBatch, FileSourceAdapter, SourceItem, SourceKind, SourceSpec,
    SourceRegistry, TextSourceAdapter, BrowserDOMSourceAdapter, default_registry, plan_source,
)


class SourceContractsTests(unittest.TestCase):
    def test_source_requires_stable_id_and_label(self):
        with self.assertRaises(ValueError):
            SourceSpec("", SourceKind.TEXT, "Clipboard")
        with self.assertRaises(ValueError):
            SourceSpec("clip", SourceKind.TEXT, " ")

    def test_rejects_embedded_credentials(self):
        with self.assertRaises(ValueError):
            SourceSpec("web", SourceKind.BROWSER, "Portal", "https://user:pass@example.com")

    def test_capture_batch_deduplicates_without_losing_provenance(self):
        source = SourceSpec("s1", SourceKind.TEXT, "Notes")
        batch = CaptureBatch(source, [
            SourceItem("same text", "s1", "Notes", item_id="1"),
            SourceItem(" same   text ", "s1", "Notes", item_id="2"),
            SourceItem("different", "s1", "Notes", item_id="3"),
            SourceItem("  ", "s1", "Notes", item_id="4"),
        ]).validate()
        self.assertEqual([x.item_id for x in batch.items], ["1", "3"])
        self.assertEqual(batch.summary()["captured"], 2)

    def test_batch_rejects_cross_source_items(self):
        source = SourceSpec("s1", SourceKind.TEXT, "Notes")
        with self.assertRaises(ValueError):
            CaptureBatch(source, [SourceItem("x", "other", "Other")]).validate()

    def test_planner_separates_browser_login_from_capture(self):
        plan = plan_source(SourceSpec("browser", SourceKind.BROWSER, "Portal", "https://example.com"))
        self.assertEqual(plan.strategy, "observe_rendered_page")
        self.assertTrue(any("Sign in manually" in x for x in plan.required_user_actions))
        self.assertTrue(any("virtualized" in x for x in plan.limitations))

    def test_unknown_source_does_not_guess(self):
        plan = plan_source(SourceSpec("mystery", SourceKind.UNKNOWN, "Unknown"))
        self.assertEqual(plan.confidence, 0.0)
        self.assertEqual(plan.adapter, "unresolved")


class GenericAdapterTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_registry_routes_by_kind_not_platform_name(self):
        source = SourceSpec("a", SourceKind.TEXT, "Any text source")
        self.assertEqual(self.registry.for_source(source).name, "text")
        self.assertEqual(self.registry.describe()[0]["name"], "text")

    def test_text_adapter_segments_and_reports_cursor(self):
        source = SourceSpec("clipboard", SourceKind.TEXT, "Clipboard")
        adapter = self.registry.for_source(source)
        batch = adapter.capture(source, limit=1, text="one\n\ntwo\n\nthree")
        self.assertEqual([x.content for x in batch.items], ["one"])
        self.assertFalse(batch.complete)
        self.assertEqual(batch.cursor, "1")
        next_batch = adapter.capture(source, limit=2, cursor=batch.cursor, text="one\n\ntwo\n\nthree")
        self.assertEqual([x.content for x in next_batch.items], ["two", "three"])
        self.assertTrue(next_batch.complete)

    def test_json_file_adapter_preserves_row_identity(self):
        source = SourceSpec("file1", SourceKind.FILE, "records.json", content_type="application/json")
        adapter = self.registry.for_source(source)
        batch = adapter.capture(source, filename="records.json", content=b'[{"name":"A"},{"name":"B"}]')
        self.assertEqual(len(batch.items), 2)
        self.assertEqual(batch.items[1].metadata["row"], 2)
        self.assertEqual(json.loads(batch.items[0].content)["name"], "A")

    def test_csv_adapter_converts_rows_to_json_records(self):
        source = SourceSpec("csv1", SourceKind.FILE, "data.csv")
        batch = self.registry.for_source(source).capture(source, filename="data.csv", content="name,price\nA,10\nB,20")
        self.assertEqual(json.loads(batch.items[0].content), {"name": "A", "price": "10"})

    def test_jsonl_adapter_reports_bad_line(self):
        source = SourceSpec("jsonl", SourceKind.FILE, "data.jsonl")
        with self.assertRaises(json.JSONDecodeError):
            self.registry.for_source(source).capture(source, filename="data.jsonl", content='{"a":1}\nnot-json')

    def test_registry_rejects_duplicate_kind(self):
        registry = SourceRegistry([TextSourceAdapter()])
        with self.assertRaises(ValueError):
            registry.register(TextSourceAdapter())

    def test_unsupported_file_is_inspection_failure(self):
        source = SourceSpec("file", SourceKind.FILE, "archive.pdf")
        result = self.registry.for_source(source).inspect(source, filename="archive.pdf", content=b"%PDF")
        self.assertFalse(result.reachable)
        self.assertTrue(result.warnings)

    def test_browser_adapter_inspects_live_page_without_platform_specific_rules(self):
        class FakePage:
            url = "https://example.test/messages"
            def evaluate(self, script, *args):
                if "document.title" in script:
                    return {"title": "Example", "url": self.url, "ready": "complete", "text": 500}
                return [{"selector": "article.post", "count": 8, "samples": ["item one", "item two"]}]
        source = SourceSpec("web1", SourceKind.BROWSER, "Example page", "https://example.test/messages")
        inspection = BrowserDOMSourceAdapter().inspect(source, page=FakePage())
        self.assertTrue(inspection.reachable)
        self.assertEqual(inspection.item_candidates[0]["selector"], "article.post")
        self.assertIn("pagination_probe", inspection.capabilities)

    def test_browser_adapter_refuses_to_capture_without_validated_item_selector(self):
        class FakePage:
            url = "https://example.test"
            def evaluate(self, script, *args):
                if "document.title" in script:
                    return {"title": "Example", "url": self.url, "ready": "complete", "text": 100}
                return [{"selector": "article", "count": 3, "samples": ["a", "b"]}]
        source = SourceSpec("web1", SourceKind.BROWSER, "Example page", "https://example.test")
        batch = BrowserDOMSourceAdapter().capture(source, page=FakePage())
        self.assertFalse(batch.complete)
        self.assertEqual(batch.items, [])
        self.assertIn("No item selector", batch.warnings[0])


if __name__ == "__main__":
    unittest.main()
