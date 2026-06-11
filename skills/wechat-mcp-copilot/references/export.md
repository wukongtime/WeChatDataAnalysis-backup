# Export

Use export only when the user asks for an artifact.

## Chat Export

1. Resolve target session if `scope=selected`.
2. Confirm time range, format, media options, and output directory when needed.
3. Preview targets with `wechat.export.preview_chat_targets`.
4. Create job with `wechat.export.create_chat_export`.
5. Poll `wechat.export.get_chat_export`.
6. Return `wechat.export.get_chat_export_download` when ready.
7. Use `wechat.export.get_chat_export_events_url` when the client can consume SSE progress.

## Moments Export

Use `wechat.export.create_moments_export`, `wechat.export.get_moments_export`, `wechat.export.get_moments_export_download`, and `wechat.export.get_moments_export_events_url`.

## Account Archive

Use `wechat.export.create_account_archive`, `wechat.export.get_account_archive`, `wechat.export.get_account_archive_download`, and `wechat.export.cancel_account_archive`.

## Contacts Export

Use `wechat.contacts.export_contacts` only when the user asks for a contacts file. It writes JSON or CSV to a local output directory.

Do not silently export all history and all media unless the user explicitly asked for that scope.

For phone clients, prefer `wechat.mobile.export_job` unless exact low-level export options are required.
