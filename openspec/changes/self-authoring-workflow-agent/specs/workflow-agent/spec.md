# Delta Specification: `workflow-agent` (WeChat Bot v3.1)

## ADDED Capabilities

### 1. Six Bounded Workflow Primitives (Layered on Existing 8 GUI Actions)
All new steps MUST conform to these 6 non-Turing-complete actions:
- `switch_app`: Cross-app boundary handoff. Resolves `bundleID` / `appName` / `appPath`, re-evaluates `classify_app_risk_tier()` dynamically mid-workflow, runs read-only `AUTH_GATE` probe in `shadow`/`live`, activates target window in `live` (or `safe_native` in `shadow`).
- `llm_extract`: Extracts structured data from `sourceVar` or latest `inspect_ui` AX+OCR snapshot via deterministic fast-paths (`wechat_accounts`, `regex`, `json_fields`) or Magpie LLM. Marks extracted outputs with provenance `captured_var_from_read` when sourced from observed reads. Emits `EXTRACTION_EMPTY` if `required=true` and empty.
- `llm_draft`: Composes customer-facing or summary copy using `TenantProfile` (`businessName`, `ownerName`), optional KB search (`kbQuery`), template rendering, or LLM generation; stores result into `captureAs`.
- `branch_if`: Forward-only conditional control (`not_empty`, `is_empty`, `equals`, `not_equals`, `contains`, `regex_match`) with `onFalse` in `("skip_next", "jump_to_step", "stop_ok")`. Backward jumps (`jumpToStep <= currentStep`) MUST be rejected statically & at runtime with `CYCLE_DETECTED`.
- `builtin_tool`: Whitelisted local capability bridge restricted strictly to `("crm_enroll", "memory_add", "kb_search", "extract_wechat_accounts", "omni_read", "wechat_add_friend")`. Non-whitelisted tools fail with `UNWHITELISTED_TOOL`. Mutating tools record `idempotencyKey` in `workflow_idempotency_ledger.json`.
- `assert_check`: Machine-verifiable post-condition check declaring `evidenceSource` in `("post_ui_readback", "tool_result", "crm_db", "memory_store", "captured_var_from_read")`. Emits `ASSERTION_FAILED` on mismatch or `SELF_CERTIFIED_ASSERTION` if provenance is input-only.

### 2. Static Safety & Quality Linter (`WorkflowSpecLinter`)
- Rejects `SELF_CERTIFIED_ASSERTION`, `MISSING_ASSERTIONS`, `CYCLE_DETECTED`, `UNWHITELISTED_TOOL`, and `MISSING_OUTBOUND_GATE` (outbound actions on `high_risk_social` apps without preceding `pause_for_human`).
- `auto_harden()` deterministically injects `pause_for_human` gates before high-risk external sends and fills `idempotencyKey` defaults on mutating tools.

### 3. OpenSpec-Driven Closed-Loop Self-Authoring & Self-Debugging (`WorkflowAuthorDebugger`)
- `propose_spec()`: Auto-detects target macOS apps from natural language, performs non-intrusive inspection, generates structured `WorkflowSpec` (`proposal`, `inputs`, `outputs`, `safetyBoundaries`, `acceptanceCriteria`, `blueprintSteps`, `lintReport`, optional `ominiCriticReview`).
- `author_and_debug()`: Executes bounded closed-loop synthesis & debugging (`1 <= max_debug_rounds <= 5`):
  - **Execution Tiers**:
    - `dry_run`: UI grounding & schema check -> max status `dry_run_only` (`evidenceLevel: "locate_ok"`).
    - `shadow`: Real inspections, extractions, drafting, branching, and read-only tools; outbound IM writes (`focus_and_type(submitAfter=true)` on `high_risk_social` & `wechat_add_friend`) are intercepted into `shadowPreviews` -> `shadow_verified` (`evidenceLevel: "shadow_ok"`).
    - `live`: Explicit `confirm_run=true` + `HumanActivityGuard` + `ForegroundHIDLease` -> real execution -> `verified` (`evidenceLevel: "effect_ok"`).
  - **Stop Conditions**:
    - All assertions pass -> finalize verified version with `compiledDeterministic=true`.
    - `AUTH_GATE` -> immediate halt (`paused_auth_gate`), zero selector patches.
    - Identical failure fingerprint `(failedStep, failureCategory, errorKey)` repeating back-to-back -> immediate halt (`needs_human_demo`) with last 2 patch diffs & screenshot.
    - Budget exhausted -> halt (`max_rounds_reached`) preserving full version history & rollback.

### 4. Interfaces (Engine, MCP, HTTP, CLI, Zero-Jargon Web Console)
- CLI: `wechat-bot workflow-agent --action <templates|spec|author-debug|debug|sessions>`
- MCP Tools: `workflow_agent_propose_spec`, `workflow_agent_author_and_debug`, `workflow_agent_debug_existing`, `workflow_agent_list_sessions`
- HTTP Routes: `/api/workflow-agent/{templates,sessions,spec,author-debug,debug,lint}`
- Web Console: Top section in `#tab-appuse` ("AI 场景自建与自动调试工坊") with plain Chinese prompts, quick chips, Shadow/Dry-Run/Live mode switch, Spec preview, round-by-round debug timeline, and 1-click repair/export/rollback (zero `window.confirm`).

## MODIFIED Capabilities
- `AppUseStudio._invoke_cli_agent`: Fix `cli:omini` command from `--role advisor` to `--role proposer --id <uuid>` and unwrap JSON `responseText`.
- `AppUseStudio.run_workflow`: Support `execution_mode` (`""` | `"dry_run"` | `"shadow"` | `"live"`), dynamic per-step `switch_app` target & risk tier updates, variable provenance tracking, shadow interception receipts, and structured `assertionResults` / `evidenceLevel`.
- `app_use_meta_algo`: Recognize all 6 new primitives in `step_action_signature`, preserve them in `optimize_and_enrich_steps`, score assertions in `score_workflow_readiness`, and classify new cognitive/assertion/tool failures in `classify_step_failure`.
