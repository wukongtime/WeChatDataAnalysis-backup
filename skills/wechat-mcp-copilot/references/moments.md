# Moments

Use this for 朋友圈, posts, likes, comments, shared links, and Moments media.

## Flow

1. If the clue is a person, resolve with `wechat.contacts.resolve_contact`.
2. Use `wechat.moments.list_users` when you need poster candidates.
3. Use `wechat.moments.list_timeline` or `wechat.moments.search_moments`.
4. Use `wechat.moments.get_media_url` only when the user needs a media resource.

## Rules

- Person names must be resolved to username before filtering timeline by `usernames`.
- Keyword search is for post content/topic, not poster identity.
- Do not request raw XML by default.
- Use `wechat.moments.sync_latest` only when the user explicitly wants fresh local sync or status indicates data is stale.

