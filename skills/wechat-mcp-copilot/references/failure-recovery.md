# Failure Recovery

Use this when MCP status, DB readiness, or results are suspicious.

## Checks

1. Phone clients: `wechat.mobile.get_overview`
2. `wechat.core.get_status`
3. `wechat.core.list_accounts`
4. `wechat.core.get_account_info`
5. Search index status with `wechat.chat.get_search_index_status` when message search fails.
6. Moments availability by checking account info and `wechat.moments.list_users`.
7. Setup readiness: load `setup-system.md` for keys, decrypt, import, health, or media-key problems.

## Empty Results

- Do not conclude "no data" after one failed query.
- Try contact/session resolution with a simpler keyword.
- Try session search before global message search when a target is known.
- For Moments, resolve poster identity before timeline filtering.
- If setup is not ready, stop content tools and explain the missing readiness condition.
