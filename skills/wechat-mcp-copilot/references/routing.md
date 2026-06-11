# Routing

Use this first for every WeChatDataAnalysis MCP task.

## First Calls

- Phone, ScreenMemo, mobile app, or compact external client: load `mobile.md` and start with `wechat.mobile.get_overview`.
- Status, readiness, "why can't I find anything": `wechat.core.get_status`, or `wechat.mobile.get_overview` for phone clients.
- Available tools or packages: `wechat.core.list_tools`.
- Account selection: `wechat.core.list_accounts`, then `wechat.core.get_account_info`.
- Key/decrypt/import/backend health problems: load `setup-system.md`.
- Fuzzy person/group/official account: load `target-resolution.md`.
- Chat content, recent messages, keyword search: load `chats.md`.
- Moments / 朋友圈 / likes / comments / post media: load `moments.md`.
- Images, videos, emoji, files, voice resources: load `media.md`.
- Export requests: load `export.md`.
- Rankings, yearly summary, activity stats: load `analytics.md`.
- Empty results or setup errors: load `failure-recovery.md`.

## Mixed Intent

Resolve the target first, then load only the main domain reference. Do not load chats, moments, media, export, and analytics together unless the user explicitly asks for a broad audit.

For phone clients, keep using `mobile.md` until the user needs a low-level fallback such as editing, raw fields, special media URL construction, or exact export options.
