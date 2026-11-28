# Technical Design: Self-Authoring & Self-Debugging Workflow Agent

## 1. Layered Architecture
```
Web Console (#tab-appuse Studio) / CLI (workflow-agent) / MCP & HTTP (/api/workflow-agent/*)
                                    │
                                    ▼
             WorkflowAuthorDebugger (wechat_control/workflow_agent.py)
        ┌─────────────────┬──────────────────┬────────────────────┐
        │ propose_spec()  │ WorkflowSpecLinter│ _diagnose_and_patch│
        │ App Auto-Detect │ Anti-Self-Cert   │ Deterministic + LLM│
        │ SCENARIO_BLUEPR │ Outbound Gates   │ Fingerprint Breaker│
        └────────┬────────┴────────┬─────────┴──────────┬─────────┘
                 └─────────────────┼────────────────────┘
                                   ▼
                 AppUseStudio (wechat_control/app_use_studio.py)
   - run_workflow(..., execution_mode="dry_run"|"shadow"|"live")
   - 8 GUI Primitives + 6 New Cognitive/Logic/Tool/Assert Primitives
   - Shadow Outbound Interceptor + Variable Provenance Ledger + Idempotency Ledger
                                   │
                                   ▼
            AppUseMetaAlgo (wechat_control/app_use_meta_algo.py)
   - SemanticElementGrounder, AppUIStateGraph, ForegroundHIDLease, AntiRiskPacer
                                   │
                                   ▼
   macOS AXUIElement + Apple Vision OCR (wechat-vision-ax) + SalesCRM + SoulMemory + KB
```

## 2. State & Persistence Files
All persisted atomically (`atomic_write_json`) under `resolved_auth.parent` (host app: `/Users/mac/Library/Application Support/WeChatBot/config/`, tests: temp dir):
- `app_use_workflows.json`: Saved workflows with `version`, `revisionHistory`, `verificationStatus` (`dry_run_only` | `shadow_verified` | `verified`), `compiledDeterministic`, `debugSessionId`, `spec`.
- `workflow_idempotency_ledger.json`: Maps `idempotencyKey -> {tool, target, at, resultSummary}` to deduplicate repeated debug/run attempts.
- `workflow_agent_sessions.json`: Stores full authoring & debugging history (`spec`, `debugRounds`, `patchDiffs`, `finalStatus`, `workflowId`, `screenshots`).

## 3. Convergence & Safety Guarantees
1. **No Infinite Loops**: Forward-only `branch_if` + bounded `max_steps` + `max_debug_rounds <= 5` + consecutive identical failure fingerprint circuit breaker (`needs_human_demo`).
2. **No Fake Verification**: `assert_check` checks runtime evidence provenance; `dry_run` never sets `verified`; `shadow` never sends real external IM messages.
3. **No Login-Page Selector Corruption**: `AUTH_GATE` is detected before/during execution and halts immediately (`paused_auth_gate`) without patching selectors.
4. **Cross-App Risk Isolation**: `switch_app` re-runs `classify_app_risk_tier()` at the exact boundary when moving e.g. from `Calculator` (`safe_native`) or `Lark` (`high_risk_social`) into `WeChat` (`high_risk_social`), enforcing `ForegroundHIDLease` + `AntiRiskPacer`.
