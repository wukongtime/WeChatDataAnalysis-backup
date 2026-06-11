# Chats

Use this for chat sessions, message search, and message context.

## Flow

1. Resolve fuzzy target with `wechat.chat.resolve_session`.
2. For recent messages, call `wechat.chat.get_messages` with a small `limit`.
3. For keywords, call `wechat.chat.search_messages`.
4. Use `wechat.chat.list_search_senders` when the user needs sender facets for a broad search.
5. For a hit that needs context, call `wechat.chat.get_message_around`.
6. For merged-forward chat history or AppMsg cards that only expose `server_id`, call `wechat.chat.resolve_chat_history` or `wechat.chat.resolve_app_message`.
7. Use `wechat.chat.get_message_raw` only for debugging or missing structured fields.

## Useful Tools

- `wechat.chat.list_sessions`
- `wechat.chat.resolve_session`
- `wechat.chat.get_messages`
- `wechat.chat.search_messages`
- `wechat.chat.list_search_senders`
- `wechat.chat.get_message_around`
- `wechat.chat.get_message_anchor`
- `wechat.chat.get_daily_message_counts`
- `wechat.chat.resolve_chat_history`
- `wechat.chat.resolve_app_message`

Do not scan full histories by pagination when an aggregate or search tool can answer.
