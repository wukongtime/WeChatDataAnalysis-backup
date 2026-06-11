# Setup And System

Use this when the database is not ready, keys are needed, decrypted data must be imported, or the backend itself needs inspection.

## Setup Tools

- `wechat.setup.get_saved_keys`: read saved DB/media keys for an account or wxid directory.
- `wechat.setup.get_database_key`: desktop workflow to extract the DB key from local WeChat.
- `wechat.setup.get_image_key`: fetch and save image AES/XOR keys.
- `wechat.setup.decrypt_databases`: decrypt databases from `db_storage_path` and a DB key.
- `wechat.setup.get_decrypt_stream_url`: SSE URL for decrypt progress.
- `wechat.setup.preview_import_decrypted`: validate an already-decrypted account directory.
- `wechat.setup.get_import_decrypted_stream_url`: SSE URL for import progress.
- `wechat.setup.cancel_import_decrypted`: cancel an import job by `job_id`.
- `wechat.setup.save_media_keys`: save media XOR/AES keys.
- `wechat.setup.decrypt_all_media`: decrypt all local `.dat` image resources.
- `wechat.setup.get_decrypt_all_media_stream_url`: SSE URL for bulk media decrypt progress.
- `wechat.setup.get_download_all_emojis_stream_url`: SSE URL for bulk emoji download progress.

## System Tools

- `wechat.system.health_check`
- `wechat.system.api_root`
- `wechat.system.get_backend_log_file`
- `wechat.system.open_backend_log_file`
- `wechat.system.get_backend_port`
- `wechat.system.set_backend_port_setting`
- `wechat.system.set_backend_port_and_restart`
- `wechat.system.get_img_helper_status`
- `wechat.system.toggle_img_helper`
- `wechat.system.pick_directory`
- `wechat.system.log_frontend_server_error`

## Rules

- Stream tools return `streamUrl`; the client consumes SSE outside the MCP JSON response.
- `set_backend_port_setting` persists the setting and may require backend restart by the user/client flow.
- `set_backend_port_and_restart` changes the port through the desktop restart flow and will disrupt the current backend connection.
- `open_backend_log_file` and `pick_directory` are desktop-host GUI actions; do not use them for phone-only flows.
- DB key extraction and image helper toggling depend on the local desktop WeChat state.
- Import/decrypt/media bulk operations write local files; summarize expected impact before running them.
