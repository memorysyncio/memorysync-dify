# MemorySync

Long-term user memory for Dify apps — recall relevant context before LLM
calls, remember new facts, search memories, and manage them across
conversations, apps, and every other MemorySync surface.

[MemorySync](https://memorysync.io) is a hosted memory service: facts a user
shares in one conversation are recallable in every later conversation — and
from any other MemorySync-connected surface (LangChain, Flowise, n8n, Zapier,
Claude Code, and more).

- **Source repository:** https://github.com/memorysyncio/memorysync-dify
- **Documentation:** https://docs.memorysync.io/guides/dify
- **Privacy policy:** [PRIVACY.md](PRIVACY.md)

## Requirements

- A MemorySync account and API key — sign up at
  [app.memorysync.io](https://app.memorysync.io) (free plan available).
- Outbound HTTPS access from your Dify instance to `api.memorysync.io`
  (or your configured base URL). No inbound connections, webhooks, or other
  services are required.

## Setup

1. Install the plugin from the Dify Marketplace (or import the `.difypkg`).
2. In [app.memorysync.io](https://app.memorysync.io) go to
   **Settings → API Keys** and create a key inside a project.
3. In Dify, open **Plugins → MemorySync → Authorize** and paste the key
   (`ms_...`). Leave **Base URL** empty for the MemorySync cloud — it exists
   only for staging environments. Credentials are validated against the live
   API on save.

## Tools

| Tool | What it does |
| --- | --- |
| **Recall Context** | Returns a prompt-ready block of the user's relevant memories for a query — wire it into any LLM node's context. |
| **Remember** | Stores a fact or conversation turn. Deterministic idempotency: node re-runs and retries converge on one stored row. |
| **Search Memories** | Scored JSON list of matching memories (capped at 25), each with a usable numeric id. |
| **Forget Memory** | Deletes exactly ONE memory by numeric id, loudly. There is deliberately no delete-everything tool. |

## Usage

A typical chatflow wires two tools:

1. **Recall Context** runs before your LLM node — pass the user's message as
   `query` and inject the returned `context` into the LLM's system prompt.
2. **Remember** runs after the reply — store the user's message (and
   optionally the assistant's) so future conversations recall it.

User identity resolves automatically from Dify's runtime user, so each of
your end users gets their own private memory space; an optional `user_id`
parameter overrides it per call. Sessions are recorded as
`dify::<conversation_id>`.

Behavior under failure: every call runs under a 10-second budget and returns
structured, branchable JSON (`status: ok / error`) instead of raising —
a slow or unreachable memory service never hangs a workflow node. Monthly
plan limits degrade silently server-side (writes accepted without storing,
recalls return empty) so production flows keep answering.

## Support

- Docs: https://docs.memorysync.io/guides/dify
- Email: support@memorysync.io
