"""Conservative source strategy planner.

Planning is deliberately separate from execution: the agent can recommend a
method, disclose limitations, and request sign-in/confirmation before it acts.
"""
from __future__ import annotations

from .contracts import CapturePlan, SourceKind, SourceSpec


def plan_source(source: SourceSpec) -> CapturePlan:
    if source.kind == SourceKind.BROWSER:
        return CapturePlan(source.id, "browser", "observe_rendered_page", 0.82,
                           required_user_actions=["Sign in manually if the site requires authentication.",
                                                  "Confirm the intended page or conversation before capture."],
                           validation_checks=["Detect repeated content items from live DOM evidence.",
                                              "Validate candidate fields against multiple items.",
                                              "Verify active source identity and observed page progress."],
                           limitations=["The agent can capture only content exposed to the authenticated browser session.",
                                        "CAPTCHA, access denial, virtualized history gaps, or inaccessible content may require user action."])
    if source.kind == SourceKind.FILE:
        return CapturePlan(source.id, "file", "parse_declared_file_format", 0.97,
                           validation_checks=["Detect file type and encoding.", "Preview rows/items before import.",
                                              "Preserve row numbers and original file provenance."])
    if source.kind == SourceKind.TEXT:
        return CapturePlan(source.id, "text", "segment_supplied_text", 0.99,
                           validation_checks=["Preview segmentation before ingestion.", "Preserve original text and source label."])
    if source.kind == SourceKind.API:
        return CapturePlan(source.id, "api", "use_explicit_documented_endpoint", 0.75,
                           required_user_actions=["Provide or authorize the endpoint and authentication method."],
                           validation_checks=["Validate response schema and pagination.", "Apply rate limits and checkpoint cursors."],
                           limitations=["No undocumented/private endpoint discovery or credential extraction."])
    if source.kind == SourceKind.DATABASE:
        return CapturePlan(source.id, "database", "read_only_export_or_connector", 0.72,
                           required_user_actions=["Authorize a read-only connection or provide an export."],
                           validation_checks=["Inspect schema before reading.", "Use bounded queries and stable cursors."],
                           limitations=["Writes and destructive queries are not part of acquisition."])
    if source.kind == SourceKind.HTTP:
        return CapturePlan(source.id, "http", "inspect_public_document", 0.65,
                           validation_checks=["Check content type and response status.", "Extract only supported public content."],
                           limitations=["Authenticated interactive applications require the browser adapter instead."])
    return CapturePlan(source.id, "unresolved", "request_source_details", 0.0,
                       required_user_actions=["Identify the source type or provide a sample."])
