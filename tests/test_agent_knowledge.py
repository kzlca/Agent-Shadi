import unittest

from app.agent_knowledge import retrieve_agent_knowledge
from app.collectors.universal_web import normalize_connector_payload
from app.collectors.web_inspector import _OPEN_CHANNEL_SCRIPT


class AgentKnowledgeTests(unittest.TestCase):
    def test_retrieval_returns_only_relevant_connector_knowledge(self):
        pages = retrieve_agent_knowledge("custom connector channel name search and open conversation", limit=3)
        self.assertTrue(pages)
        self.assertTrue(any("web-connectors.md" == x["source"] for x in pages))
        self.assertLessEqual(sum(len(x["text"]) for x in pages), 5200)

    def test_golden_data_query_retrieves_data_quality_guidance(self):
        pages = retrieve_agent_knowledge("deduplicate normalize filtered records and approve golden data", limit=3)
        self.assertTrue(any(x["source"] == "golden-data.md" for x in pages))


class CustomConnectorChannelTests(unittest.TestCase):
    def test_connector_persists_channel_name_and_search_selectors(self):
        item = normalize_connector_payload({
            "name": "Messenger", "url": "https://example.com/app",
            "config": {"channel": {"name": "Support room", "target_url": "https://example.com/room/42", "username": "@support42", "platform_id": "42", "search_input_selector": "input.search", "search_result_selector": ".result"},
                       "root": {"selector": ".message"}, "fields": {"text": {"selector": ".body"}}}
        })
        self.assertEqual(item["config"]["channel"]["name"], "Support room")
        self.assertEqual(item["config"]["channel"]["target_url"], "https://example.com/room/42")
        self.assertEqual(item["config"]["channel"]["username"], "support42")
        self.assertEqual(item["config"]["channel"]["platform_id"], "42")
        self.assertEqual(item["config"]["channel"]["search_input_selector"], "input.search")
        self.assertEqual(item["config"]["channel"]["search_result_selector"], ".result")

    def test_channel_opener_requires_unique_match_and_verifies_active_title(self):
        self.assertIn("searchInputSelector", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("ambiguous_search_results", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("active_channel_identity_not_verified", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("channel_identity_result_not_found", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("already_open", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("navigation_required", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("platformId", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("wantedUser", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("!el.closest('.chatlist')", _OPEN_CHANNEL_SCRIPT)


class ChannelIdentityFalsePositiveRegressionTests(unittest.TestCase):
    def test_username_matching_uses_exact_handle_or_url_segment_not_substring(self):
        self.assertIn('urlContainsUsername', _OPEN_CHANNEL_SCRIPT)
        self.assertIn('usernames.some(v=>v===wantedUser)', _OPEN_CHANNEL_SCRIPT)
        self.assertNotIn('x.hints.some(v=>v.includes(wantedUser))', _OPEN_CHANNEL_SCRIPT)

    def test_search_fallback_is_scoped_to_result_containers(self):
        self.assertIn("'.chatlist, [role=\"listbox\"], [role=\"list\"], .search-results", _OPEN_CHANNEL_SCRIPT)
        self.assertNotIn("document.querySelectorAll('a,button,[role=\"option\"],[role=\"button\"],li')", _OPEN_CHANNEL_SCRIPT)
        self.assertIn('const isBroad=parts.length>0', _OPEN_CHANNEL_SCRIPT)
        self.assertIn('if(isBroad) results=results.filter', _OPEN_CHANNEL_SCRIPT)

    def test_generic_search_title_cannot_verify_active_conversation(self):
        self.assertIn('target_route_loaded_but_active_conversation_not_detected', _OPEN_CHANNEL_SCRIPT)
        self.assertIn('activeConversation=nonGenericActiveTitle&&(messageCount>0||headerIdentityVerified)', _OPEN_CHANNEL_SCRIPT)
        self.assertIn('headerIdentityVerified=(exactIdInHeader|| (targetUrlMatch&&visibleExactPeerId))&&titleVerified&&nonGenericActiveTitle', _OPEN_CHANNEL_SCRIPT)
        self.assertIn('const genericTitles = new Set', _OPEN_CHANNEL_SCRIPT)

    def test_conversation_identity_is_scoped_to_header_not_main_page(self):
        self.assertIn("'.chat-header, .chat-info, .topbar, .conversation-header", _OPEN_CHANNEL_SCRIPT)
        self.assertNotIn("'header, main, [role=\"main\"]", _OPEN_CHANNEL_SCRIPT)
