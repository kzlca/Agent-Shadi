from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
JS = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")


class UIRefinementTests(unittest.TestCase):
    def test_background_monitor_has_pause_resume_stop_and_persistent_dock(self):
        self.assertIn('id="globalRunMonitor"', HTML)
        self.assertIn("async function controlBackgroundRun(action)", JS)
        self.assertIn("data-run-action=\"pause\"", JS)
        self.assertIn("data-run-action=\"resume\"", JS)
        self.assertIn("data-run-action=\"cancel\"", JS)
        self.assertIn("Background extraction monitor", JS)

    def test_assets_are_versioned_and_build_is_visible(self):
        self.assertIn("styles.css?v=__APP_VERSION__", HTML)
        self.assertIn("app.js?v=__APP_VERSION__", HTML)
        self.assertIn("<span>__APP_VERSION__</span>", HTML)

    def test_universal_web_inspector_is_modifier_free_and_session_is_configurable(self):
        self.assertIn('id="wcPersistSession"', JS)
        self.assertIn('id="wcWaitMode"', JS)
        self.assertIn('id="wcScrollStep"', JS)
        self.assertIn('id="wcMaxWait"', JS)
        self.assertIn('Click select: OFF', (ROOT / "app/collectors/web_inspector.py").read_text(encoding="utf-8"))
        self.assertIn("Select nearest repeated item", (ROOT / "app/collectors/web_inspector.py").read_text(encoding="utf-8"))
        self.assertIn("Navigation diagnostics", JS)

    def test_guided_picker_is_in_setup_and_launches_before_arming(self):
        self.assertIn('Pick elements directly in the source browser', JS)
        self.assertIn('<details class=\"web-evidence-advanced\">', JS)
        self.assertIn('data-wc-pick="root"', JS)
        self.assertIn('data-wc-pick="text"', JS)
        self.assertIn('data-wc-pick="timestamp"', JS)
        self.assertIn('no HTML copy/paste', JS)
        self.assertIn('message text—not an emoji, link or timestamp', JS)
        self.assertIn("if(!state.activeWebConnectorId || state.webInspector?.status!=='ready'){", JS)
        self.assertIn('await startWebInspector();', JS)
        self.assertIn('wait for Browser: ready, then press this Pick button again.', JS)
        self.assertIn('checks the configured target URL, username and platform ID', JS)
        self.assertNotIn('will search for the saved channel name when collection starts', JS)

    def test_universal_connector_exposes_platform_agnostic_identity_fields(self):
        for field_id in ("wcTargetUrl", "wcTargetUrlTemplate", "wcChannelUsername", "wcChannelId", "wcIdentitySelector", "wcIdentityAttribute"):
            self.assertIn(f'id="{field_id}"', JS)
        self.assertIn("already_open", (ROOT / "app/collectors/web_inspector.py").read_text(encoding="utf-8"))
        self.assertIn("channel_url:savedChannel.target_url", JS)
        self.assertIn("platform-specific ID", JS)

    def test_eitaa_uses_shared_date_controls_and_global_browser_launcher(self):
        self.assertIn('value="web">Saved web connector (Eitaa / custom)', JS)
        self.assertIn('id="collectWebConnector"', JS)
        self.assertIn('id="collectStart"', JS)
        self.assertIn('id="collectEnd"', JS)
        self.assertIn('id="collectWebMaxMessages"', JS)
        self.assertIn('id="openCollectWebBrowser"', JS)
        self.assertIn('async function openSelectedWebCollectionBrowser()', JS)
        self.assertIn('Collect selected date range', JS)

    def test_rubika_manual_selection_and_single_run_guidance_is_visible(self):
        self.assertIn("One channel per run", JS)
        self.assertIn("manually navigate to the intended channel", JS)
        self.assertIn("never searches for, clicks, opens, or switches channels", JS)
        self.assertIn("separate run", JS)
        self.assertIn('option value="telegram"', JS)
        self.assertIn('option value="rubika"', JS)
        self.assertNotIn('option value="both"', JS)

    def test_review_command_terminal_is_standalone_not_embedded_in_webapp(self):
        self.assertIn("function renderStandaloneReviewLaunchCard()", JS)
        self.assertIn("Agent Shadi Review Desk", JS)
        self.assertIn("Process all queued messages", JS)
        self.assertIn("explicit_batch:true", JS)
        self.assertIn("renderBatchProcessAction(", JS)
        self.assertIn("/review/live/queue", JS)
        self.assertIn("/review/live/${messageId}/extract", JS)
        self.assertIn("data-review-path=\"live\"", JS)
        self.assertNotIn('id="reviewCommandForm"', JS)
        self.assertNotIn("runReviewCommandFromInput", JS)

    def test_process_all_is_a_prominent_counted_one_click_action(self):
        self.assertIn("${renderBatchProcessAction(s,'dashboard')}",JS)
        self.assertIn("buttonId=dashboard?'dashboardProcessAll':'reviewProcessAll'",JS)
        self.assertIn('id=\"${buttonId}\"',JS)
        self.assertIn("failed ·",JS)
        self.assertIn("interrupted",JS)
        self.assertIn("held/filtered messages require requeueing first",JS.lower())
        self.assertIn("explicit_batch:true",JS)
        self.assertIn("failed",(ROOT/"app/server.py").read_text(encoding="utf-8"))
        self.assertIn("status='filtered'", (ROOT/"app/server.py").read_text(encoding="utf-8"))

    def test_dashboard_run_controls_route_to_live_review_when_live_path_is_selected(self):
        server = (ROOT / "app/server.py").read_text(encoding="utf-8")
        self.assertIn("const liveReviewPath=(cfg.review_settings||{}).processing_path==='live'", JS)
        self.assertIn("liveReviewPath?()=>setView('review'):startProcessing", JS)
        self.assertIn("if((state.config?.review_settings||{}).processing_path==='live')", JS)
        self.assertIn("Live AI · one by one. Use the explicit Process all queued messages action", server)
        self.assertIn("Auto-processing was held because this workflow uses Live AI one-by-one review", server)

    def test_settings_shortcut_uses_delegated_navigation(self):
        self.assertIn('data-view="settings" data-nav="settings"', HTML)
        self.assertIn("closest('[data-nav], [data-view]')", JS)
        self.assertIn("},true);", JS)
        self.assertNotIn("function wireNavButtons()", JS)

    def test_agent_shadi_workspace_has_workflow_canvas_and_ai_chat(self):
        self.assertIn("Agent Shadi — AI Data Agent Studio", HTML)
        self.assertIn('id="view-agent"', HTML)
        self.assertIn('data-view="agent"', HTML)
        self.assertIn("function renderPipelineNode(", JS)
        self.assertIn("data-pipeline-node", JS)
        self.assertIn("async function renderAgent()", JS)
        self.assertIn("/agent/chat", JS)
        self.assertIn("COMMAND PALETTE", JS)
        self.assertIn("Ctrl + K", HTML)

    def test_sidebar_local_workspace_and_settings_are_inside_scrollable_navigation(self):
        nav_start=HTML.index('<nav class="nav shadi-nav"')
        nav_end=HTML.index('</nav>',nav_start)
        nav=HTML[nav_start:nav_end]
        self.assertIn('class="local-card shadi-local sidebar-info-item"',nav)
        self.assertIn('data-view="settings" data-nav="settings"',nav)
        self.assertNotIn('class="local-card shadi-local"',HTML[nav_end:])
        self.assertIn('flex:1 1 auto;min-height:0;overflow-y:auto',CSS)
        self.assertIn('height:100dvh;min-height:0;overflow:hidden',CSS)

    def test_live_extraction_progress_polls_without_initial_idle_race_and_recovers_after_refresh(self):
        self.assertIn("function startLiveProgressPolling(messageId)", JS)
        self.assertIn("r.liveProgressTimer=setInterval(poll,900)", JS)
        self.assertIn("if(current&&current.status==='processing')startLiveProgressPolling(current.id)", JS)
        self.assertNotIn("await poll();", JS)
        self.assertIn("Previous attempt interrupted", JS)
        self.assertIn("progress.status==='idle'?null:progress", JS)

    def test_agent_ui_is_an_app_operator_not_read_only(self):
        self.assertIn("APP-AWARE AGENT", JS)
        self.assertNotIn("READ-ONLY ASSISTANT", JS)
        self.assertIn("Shadi can work inside the application.", JS)
        self.assertIn("inspect and update supported settings", JS)

    def test_collector_status_shows_structured_live_phase(self):
        self.assertIn("d.phase_message", JS)
        self.assertIn("d.platform", JS)
        self.assertIn("d.channel", JS)
        self.assertIn("waiting for the next verified browser phase", JS.lower())

    def test_live_model_status_rechecks_and_never_trusts_bootstrap_green_flag(self):
        self.assertIn('/api/settings/model/status',JS)
        self.assertIn('function checkModelStatus(',JS)
        self.assertIn('setInterval(()=>{if(!document.hidden)checkModelStatus({force:true})},30000)',JS)
        self.assertIn("window.addEventListener('focus'",JS)
        self.assertIn("document.addEventListener('visibilitychange'",JS)
        self.assertIn("h.status==='online'?'ok'",JS)
        self.assertIn("status:'offline'",JS)
        self.assertIn('id="refreshModelStatus"',JS)

    def test_new_interface_has_no_remote_google_font_dependency(self):
        self.assertNotIn("fonts.googleapis.com", CSS)
        self.assertIn("--purple-glow", CSS)
        self.assertIn("shadi-light", CSS)

    def test_upload_is_block_level_with_hidden_input_not_overlay(self):
        self.assertIn('class="dropzone" id="dropzone"', JS)
        self.assertIn('id="chooseFile"', JS)
        self.assertIn('id="fileUpload"', JS)
        self.assertIn("dropzone.addEventListener('drop'", JS)
        self.assertIn("dropzone.classList.add('dragover')", JS)
        self.assertIn("font-size: 18px;", CSS)

    def test_collection_date_system_selector_and_custom_format_exist(self):
        self.assertIn('id="collectDateSystem"', JS)
        self.assertIn('value="gregorian"', JS)
        self.assertIn('value="auto"', JS)
        self.assertIn('value="custom"', JS)
        self.assertIn('id="collectDateFormat"', JS)
        self.assertIn("date_system:", JS)

    def test_in_app_continue_is_the_collection_pause_control(self):
        self.assertIn("Start collection", JS)
        self.assertIn("1 · Open source browser", JS)
        self.assertIn("2 · Collect selected date range", JS)
        self.assertIn("Continue collection", JS)
        self.assertIn('id="continueCollection"', JS)
        self.assertIn("/collect/status", JS)
        self.assertIn("/collect/resume", JS)
        self.assertNotIn("Step over", JS)
        self.assertNotIn("original Playwright control panel", JS)

    def test_common_text_sizes_are_increased(self):
        self.assertIn("body { font-size: 16px; }", CSS)
        self.assertIn(".field label { font-size: 15px; }", CSS)
        self.assertIn(".nav-item { font-size: 16px; }", CSS)
        self.assertIn(".btn { font-size: 15px; }", CSS)

    def test_collection_log_follows_latest_output_and_preserves_page_position(self):
        self.assertIn("log.scrollTop=log.scrollHeight", JS)
        self.assertIn("window.scrollTo(0,pageY)", JS)
        self.assertIn("slice(-80)", JS)
        self.assertIn("overflow-anchor: none", CSS)

    def test_collection_shows_indeterminate_progress_and_in_app_continue(self):
        self.assertIn("const active=['queued','running','resume_requested'].includes(d.status)", JS)
        self.assertIn('id="continueCollection"', JS)
        self.assertIn("/collect/resume", JS)
        self.assertIn("collection-progress", JS)
        self.assertIn("@keyframes collectionIndeterminate", CSS)

    def test_rubika_and_telegram_extract_top_level_message_containers(self):
        rubika = (ROOT / "app/collectors/rubika_collector.py").read_text(encoding="utf-8")
        telegram = (ROOT / "app/collectors/telegram_collector.py").read_text(encoding="utf-8")
        self.assertIn("document.querySelectorAll('.message-item')", rubika)
        self.assertIn("const candidateSet = new Set(messageCandidates)", rubika)
        self.assertIn("if (candidateSet.has(parent)) return false", rubika)
        self.assertIn("parent.matches(messageSelector)", telegram)

    def test_model_settings_explain_and_enable_explicit_rules_only_mode(self):
        self.assertIn('id="allowRulesOnly"', JS)
        self.assertIn("Model needs configuration", JS)
        self.assertIn("Model offline", JS)
        self.assertIn("Model not loaded", JS)
        self.assertIn("LLM not configured", JS)
        self.assertIn("allow_rules_only:$('#allowRulesOnly').checked", JS)
        self.assertIn('connection_verified', JS)
        self.assertIn("Extraction was not started.", JS)

    def test_inbox_has_safe_clear_controls_and_scope_confirmation(self):
        self.assertIn('id="clearInbox"', JS)
        self.assertIn('id="clearInboxScope"', JS)
        self.assertIn('value="pending"', JS)
        self.assertIn('value="all"', JS)
        self.assertIn('confirmClearAll', JS)
        self.assertIn('/messages/clear', JS)

    def test_dataset_explorer_has_advanced_field_filters_grouping_and_compact_view(self):
        self.assertIn('id="explorerFieldName"', JS)
        self.assertIn('id="explorerFieldOp"', JS)
        self.assertIn('id="explorerFieldValue"', JS)
        self.assertIn('id="explorerGroupBy"', JS)
        self.assertIn('class="column-picker-panel"', JS)
        self.assertIn('data-field-column=', JS)
        self.assertIn('id="recordCompactMode"', JS)
        self.assertIn('data-preset="no_schema_match"', JS)
        self.assertIn('function compareSelectedRecords()', JS)

    def test_source_messages_have_bulk_trash_and_multiple_views(self):
        self.assertIn('data-select-message=', JS)
        self.assertIn('id="trashSelectedMessages"', JS)
        self.assertIn('messageGroupBy', JS)
        self.assertIn('/messages/bulk-action', JS)

    def test_dataset_explorer_has_real_tab_dispatcher_and_overview(self):
        self.assertIn("function renderExplorerTab()", JS)
        self.assertIn("case 'overview': html=renderExplorerOverview()", JS)
        self.assertIn("function renderExplorerOverview()", JS)
        self.assertIn("Records by source", JS)
        self.assertIn("Fields that need attention", JS)
        self.assertIn("function wireExplorerTab()", JS)

    def test_large_dataset_explorer_has_load_more_and_stable_offsets(self):
        self.assertIn("function loadMoreExplorerRecords()", JS)
        self.assertIn("function loadMoreExplorerMessages()", JS)
        self.assertIn("id=\"loadMoreRecords\"", JS)
        self.assertIn("id=\"loadMoreMessages\"", JS)
        server = (ROOT / "app/server.py").read_text(encoding="utf-8")
        self.assertIn("limit:int=250,offset:int=0", server)
        self.assertIn("limit:int=500,offset:int=0", server)
        self.assertIn("ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", server)
        self.assertIn("ORDER BY r.created_at DESC, r.id DESC LIMIT ? OFFSET ?", server)

    def test_record_field_edits_are_reversible_in_quality_history(self):
        self.assertIn('action["action"]=="edit"', (ROOT / "app/server.py").read_text(encoding="utf-8"))
        self.assertIn('"undo_token":batch', (ROOT / "app/server.py").read_text(encoding="utf-8"))


    def test_review_studio_uses_standalone_keyboard_first_review_desk(self):
        self.assertIn("async function renderReview()", JS)
        self.assertIn("/review/queue", JS)
        self.assertIn("Agent Shadi Review Desk", JS)
        self.assertIn("Process all queued messages", JS)
        self.assertIn("explicit_batch:true", JS)
        self.assertIn("renderBatchProcessAction(", JS)
        self.assertIn("renderStandaloneReviewLaunchCard()", JS)
        self.assertIn("data-review-mode=\"guided\"", JS)
        self.assertIn("data-review-mode=\"batch\"", JS)
        self.assertIn("review-switch", JS)
        self.assertIn(".review-studio-grid", CSS)
        self.assertNotIn("reviewCommandForm", JS)
        self.assertNotIn('id="reviewCommandInput"', JS)
        tui=(ROOT / "review_tui.py").read_text(encoding="utf-8")
        self.assertIn('self._put(0, 1, "AGENT SHADI  /  REVIEW DESK"', tui)
        self.assertIn('if op in {"a", "approve", "r", "reject", "select", "deselect"}:', tui)
        self.assertIn('if op == "undo": self.undo(); return', tui)

    def test_review_studio_uses_real_edit_and_approval_routes(self):
        self.assertIn("/api/records/${ids[0]}/${action}", JS)
        self.assertIn("/api/workflows/${workflowId()}/records/bulk-action", JS)
        self.assertIn("/api/workflows/${workflowId()}/quality/undo", JS)

    def test_review_studio_guided_approval_and_native_desk_navigation(self):
        tui=(ROOT / "review_tui.py").read_text(encoding="utf-8")
        self.assertIn('> Review Studio <em id="reviewBadge"',HTML)
        self.assertIn('id="reviewStudioAutoAdvance"',JS)
        self.assertIn('id="reviewPageSize"',JS)
        self.assertIn('id="reviewConfirmBulk"',JS)
        self.assertIn('saveReviewSettings({enabled:rstate.enabled,mode:rstate.mode,page_size:Number(',JS)
        self.assertIn('saveReviewSettings({enabled:rstate.enabled,mode:rstate.mode,auto_advance:',JS)
        self.assertIn('if(rstate.awaitingAdvance){',JS)
        self.assertIn('rstate.position=Math.max(0,Math.min(Number(rstate.position)||0',JS)
        self.assertIn('if(target>=r.items.length&&r.hasMore)',JS)
        self.assertIn('if(target<0&&r.offset>0)',JS)
        self.assertIn('if op == "undo": self.undo(); return',tui)
        self.assertIn('if op == "page":',tui)
        self.assertIn('parse_rows(arg',tui)



if __name__ == "__main__":
    unittest.main()


def test_ai_only_mode_manual_extraction_default_and_platform_blueprints_are_visible():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    js=(root/"app/static/app.js").read_text(encoding="utf-8")
    assert 'id="extractionMode"' in js
    assert 'value="ai_only"' in js
    assert 'value="ai_plus_rules"' in js
    assert 'value="rules_only"' in js
    assert 'collector.auto_process===true?' in js
    assert "After capture, automatically send queued messages to AI" in js
    assert "Telegram Web" in js and "Rubika Web" in js
    assert "span.translatable-message" in js
    assert ".message-text, .text-content" in js

    def test_agent_mixed_rtl_ltr_messages_use_explicit_direction_and_bidi_isolation(self):
        self.assertIn("function agentDir(text)", JS)
        self.assertIn('dir="${agentDir(m.content)}"', JS)
        self.assertIn('class="bidi-ltr" dir="ltr"', JS)
        self.assertIn('.agent-bubble p[dir="rtl"]', CSS)

    def test_global_diagnostics_drawer_collects_errors_and_copies_support_bundle(self):
        self.assertIn('id="openDiagnostics"', HTML)
        self.assertIn("window.addEventListener('unhandledrejection'", JS)
        self.assertIn("function openDiagnostics()", JS)
        self.assertIn("diagnosticsCopy", JS)
        self.assertIn('@app.get("/api/diagnostics")', (ROOT / "app/server.py").read_text(encoding="utf-8"))

    def test_dashboard_only_readability_zoom(self):
        self.assertIn('body.dashboard-view-active #view-overview{zoom:1.3}', CSS)
        self.assertIn("document.body.classList.toggle('dashboard-view-active',view==='overview')", JS)

    def test_guided_picker_uses_selection_revision_and_acknowledged_binding(self):
        inspector=(ROOT / "app/collectors/web_inspector.py").read_text(encoding="utf-8")
        self.assertIn('selection_revision', inspector)
        self.assertIn('Promise.resolve(window.__structuraSelect(payload))', inspector)
        self.assertIn('Number(d.selection_revision||0)>Number(state.webPickRevision||0)', JS)

    def test_guided_picker_updates_form_and_json_preview_after_selection(self):
        self.assertIn("selectorInput.dispatchEvent(new Event('input'", JS)
        self.assertIn("$('#wcJsonEditor').value=pretty({...draft,id:state.activeWebConnectorId||'draft'})", JS)
        self.assertIn("Saved element applied to Message root", JS)
        self.assertIn("webInspectorPollBusy", JS)

    def test_guided_picker_requires_server_acknowledgement_before_showing_saved(self):
        inspector=(ROOT / "app/collectors/web_inspector.py").read_text(encoding="utf-8")
        self.assertIn('result.ok !== true', inspector)
        self.assertIn('"selection_revision": revision', inspector)

    def test_telegram_always_authenticates_in_web_app_before_searching(self):
        source=(ROOT / "app/collectors/telegram_collector.py").read_text(encoding="utf-8")
        self.assertIn('base_url = "https://web.telegram.org/k/" if platform == "Telegram"', source)
        self.assertIn('ensure_authenticated(page, platform, base_url, selectors)', source)
        self.assertIn('Do not navigate to t.me as a fallback', source)

    def test_telegram_search_falls_back_to_live_operator_selection_instead_of_closing(self):
        source=(ROOT / "app/collectors/telegram_collector.py").read_text(encoding="utf-8")
        self.assertIn("def _click_telegram_search_result", source)
        self.assertIn("def wait_for_manual_telegram_channel_selection", source)
        self.assertIn("STRUCTURA_TELEGRAM_MANUAL_SELECT_TIMEOUT", source)
        self.assertIn("selected_result_text=selected_result_text", source)
        self.assertIn("allow_operator_selection=allow_operator_selection", source)

    def test_collection_status_discloses_per_source_counts_and_platform_specific_selection(self):
        self.assertIn('function collectorSourceBreakdown(manifest)', JS)
        self.assertIn('messages captured across all sources', JS)
        self.assertIn('Choose the intended ${operatorPlatform} channel', JS)
        self.assertIn('If a result is already visible, click it once.', JS)

    def test_existing_connector_reopens_inspector_polling_before_a_new_pick(self):
        self.assertIn('if(item)ensureWebInspectorPolling()', JS)
        self.assertIn('function ensureWebInspectorPolling(refresh=true)', JS)
        self.assertIn('const current=await api(`/api/web-connectors/${state.activeWebConnectorId}/inspect/status`)', JS)

    def test_review_numeric_shortcut_opens_field_editor_and_refresh_preserves_record(self):
        source=(ROOT / "review_tui.py").read_text(encoding="utf-8")
        self.assertIn('target = int(key) - 1', source)
        self.assertIn('replacement = self._prompt_edit_value(label, current_text)', source)
        self.assertIn('self.refresh(preserve=True)', source)
        self.assertIn('Saved and refreshed live record', source)
