from app.server import _agent_tool_selection


def _names(question):
    return {item["function"]["name"] for item in _agent_tool_selection(question)}


def test_explanatory_extraction_question_only_exposes_workflow_inspection():
    names=_names("How can I turn off automatic extraction and use AI only?")
    assert "inspect_workflow" in names
    assert "update_workflow" not in names
    assert "update_collector_settings" not in names
    assert "start_extraction" not in names


def test_explicit_ai_only_change_exposes_workflow_update():
    names=_names("Please change this workflow to AI only and save the extraction mode")
    assert "inspect_workflow" in names
    assert "update_workflow" in names


def test_explicit_automatic_extraction_preference_change_exposes_collector_update():
    names=_names("Please turn off automatic extraction after collection and save that preference")
    assert "update_collector_settings" in names
    assert "start_extraction" not in names


def test_collection_diagnostic_exposes_inspection_not_mutation():
    names=_names("Why did collection stop scrolling? Please diagnose the current history navigation")
    assert "inspect_collection" in names
    assert "start_collection" not in names


def test_connector_learning_question_exposes_saved_connector_inspection():
    names=_names("How do I inspect the Telegram and Rubika connector selectors to build my own website connector?")
    assert "inspect_web_connectors" in names
    assert "update_web_connector" not in names
