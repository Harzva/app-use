# Proposal: Self-Authoring & Self-Debugging Workflow Agent Studio (v3.1)

## 1. Why & Business Problem
Currently, onboarding a new client acquisition or cross-app office scenario (e.g. **Feishu/Lark DM lead capture -> self-intro WeChat friend add -> `飞书引流-xxx` remark -> SalesCRM enrollment**, or **Feishu digest -> TextEdit brief**) requires engineers to write dedicated Python bridge modules (`douyin_wechat_bridge.py`, custom CLI flags, etc.). This does not scale when users continuously request new apps (Feishu, DingTalk, ERP, Safari/Chrome CRM, Notes, etc.).

Users need an **AI Workflow Agent** that lets anyone describe a cross-app workflow in plain Chinese, watches the agent inspect the live desktop apps, author a structured Spec + Workflow v1, test & self-debug it across rounds (catching UI drift, timing lag, empty extractions, or assertion failures), and lock in verified deterministic workflows + reusable Skills.

## 2. Competitive Benchmark & Synthesis
| Product / Framework | Core Strength Adopted | Limitation Avoided in WeChat Bot v3.1 |
|---|---|---|
| **识流 (Thiflow)** | Vision-driven non-intrusive desktop RPA + RAG/SOP reasoning + Feishu/WeChat synergy | Avoids ad-hoc prompt scripts without structural assertions or versioned rollback |
| **影刀 RPA (魔法指令 + AI Power + 智能修复)** | Natural-language intent-to-steps, single-step visual debugging, 1-click Smart Healing | Avoids opaque selector edits that mask fake passes or omit risk gates |
| **实在智能 (实在Agent / ISSUT)** | Conversational workflow synthesis + screen semantic understanding + API+GUI dual-mode | Avoids unconstrained code generation without whitelisting or idempotency |
| **UiPath Autopilot / Maestro & Stagehand** | Spec-driven synthesis + JIT compile from exploration to deterministic replay + self-healing fallback | Adapted to native macOS AXUIElement + Apple Vision OCR + `ForegroundHIDLease` |

## 3. Omini Independent Review Incorporation (`31c620da` Proposer & `359201c8` Critic)
- **Proposer (`31c620da`)**: Reject Turing-complete DSL bloat. Extend the existing 8 GUI primitives with **6 bounded declarative primitives** (`switch_app`, `llm_extract`, `llm_draft`, `branch_if` forward-only, `builtin_tool`, `assert_check`).
- **Critic (`359201c8`) Critical Blockers Mitigated**:
  1. **Anti-Self-Certification (`SELF_CERTIFIED_ASSERTION`)**: `assert_check` MUST cite independent post-action evidence (`post_ui_readback`, `tool_result`, `crm_db`, `memory_store`, `captured_var_from_read`), never raw input variables.
  2. **Three-Tier Verification Separation**: `dry_run` yields `locate_ok` only; `shadow` yields `shadow_verified` (intercepting outbound social sends into `shadowPreviews`); ONLY real `live` execution with `effect_ok` grants `verified`.
  3. **Auth-Gate & Anti-Infinite-Loop Breakers**: Immediate stop on `AUTH_GATE` (zero selector patching on login/QR screens); immediate halt (`needs_human_demo`) with patch diffs when the exact failure fingerprint repeats consecutively; hard cap `max_debug_rounds <= 5`.
  4. **Idempotent Ledger**: Mutating tools (`crm_enroll`, `memory_add`, `wechat_add_friend`) use `idempotencyKey` so debug retries never create duplicate CRM contacts or friend requests.

## 4. Scope & Success Criteria
- Zero breaking changes to existing `AppUseStudio` v2.7–v2.9 APIs or Web Console selectors.
- Fix existing `cli:omini` invocation bug (`--role advisor` -> `--role proposer --id <UUID>` JSON parsing) in `app_use_studio.py`.
- Deliver end-to-end Feishu -> WeChat -> CRM shadow synthesis + Safe Native (`Calculator`) real live multi-round self-debugging proof + Omini Verifier audit.
