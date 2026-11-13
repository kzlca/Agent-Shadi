import unittest
from app.core.collection_policy import validate_collection_policy, evaluate_collection_policy


class CollectionPolicyTests(unittest.TestCase):
    def test_date_before_after_operators_compare_iso_and_jalali_dates(self):
        from app.core.collection_policy import validate_collection_policy, evaluate_collection_policy
        before = validate_collection_policy({"mode":"include","rules":[{"field":"posted_at","operator":"before","value":"2026-11-10"}]})
        after = validate_collection_policy({"mode":"include","rules":[{"field":"posted_at","operator":"after","value":"1405.08.01"}]})
        self.assertTrue(evaluate_collection_policy(before,{"posted_at":"2026-11-09"})[0])
        self.assertTrue(evaluate_collection_policy(after,{"posted_at":"1405.08.02"})[0])

    def test_default_captures_everything(self):
        self.assertTrue(evaluate_collection_policy({"mode":"all"}, {"text":"unrelated text"})[0])

    def test_include_all_logic_requires_every_condition(self):
        policy = validate_collection_policy({"mode":"include","logic":"all","rules":[
            {"field":"text","operator":"contains","value":"urgent"},
            {"field":"source","operator":"equals","value":"Support"},
        ]})
        self.assertTrue(evaluate_collection_policy(policy,{"text":"Urgent ticket","source":"Support"})[0])
        self.assertFalse(evaluate_collection_policy(policy,{"text":"Urgent ticket","source":"Forum"})[0])

    def test_include_any_logic_accepts_any_condition(self):
        policy = validate_collection_policy({"mode":"include","logic":"any","rules":[
            {"field":"text","operator":"contains","value":"error"},
            {"field":"text","operator":"contains","value":"warning"},
        ]})
        self.assertTrue(evaluate_collection_policy(policy,{"text":"A warning appeared"})[0])

    def test_exclude_mode_holds_only_matching_messages(self):
        policy = validate_collection_policy({"mode":"exclude","rules":[{"field":"text","operator":"contains","value":"system notification"}]})
        self.assertFalse(evaluate_collection_policy(policy,{"text":"SYSTEM NOTIFICATION: user joined"})[0])
        self.assertTrue(evaluate_collection_policy(policy,{"text":"User asked for help"})[0])

    def test_numeric_and_boolean_fields(self):
        policy = validate_collection_policy({"mode":"include","rules":[
            {"field":"message_length","operator":"greater_than","value":"10"},
            {"field":"has_link","operator":"equals","value":"true"},
        ]})
        self.assertTrue(evaluate_collection_policy(policy,{"text":"Read this article https://example.com"})[0])

    def test_real_estate_native_decision_is_authoritative(self):
        policy={"mode":"real_estate"}
        self.assertFalse(evaluate_collection_policy(policy,{"text":"whatever"},{"mode":"real_estate","matched":False,"reason":"rejected"})[0])
        self.assertTrue(evaluate_collection_policy(policy,{"text":"whatever"},{"mode":"real_estate","matched":True,"reason":"accepted"})[0])

    def test_empty_custom_filter_rejected(self):
        with self.assertRaises(ValueError):
            validate_collection_policy({"mode":"include","rules":[]})

    def test_unsafe_regex_rejected(self):
        with self.assertRaises(ValueError):
            validate_collection_policy({"mode":"include","rules":[{"field":"text","operator":"regex","value":"(a+)+$"}]})


if __name__ == '__main__': unittest.main()
