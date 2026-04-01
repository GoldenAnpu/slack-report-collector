# slack-report-collector

## Purpose

Fetches Slack channel messages for a specific user within a date range and outputs them as JSON, TXT, or a formatted Slack DM.

---

## Copilot instructions

- Prefer targeted edits over full rewrites to reduce premium request usage.
- Read only the files relevant to the task; avoid loading the whole codebase at once.
- Batch independent edits with `multi_replace_string_in_file` instead of sequential calls.
- Do not add docstrings, comments, or type annotations to code you did not change.

---

## File Structure

```
globals.py          — env config (loads from ~/slack.env)
main.py             — entry point: fetch → extract → output
slack_notifier.py   — Slack DM sender
requirements.txt    — dependencies (slack_sdk, python-dotenv)
slack_report_messages.json  — output: JSON mode
slack_report_messages.txt   — output: TXT mode
.github/copilot-instructions.md  — this file: project context auto-loaded by Copilot
```

---

## Env Variables (~/slack.env)

### Single-workspace mode (default)

| Variable           | Required | Description                                               |
| ------------------ | -------- | --------------------------------------------------------- |
| `SLACK_API_TOKEN`  | yes      | Slack token (xoxs- user token or xoxb- bot token)         |
| `SLACK_CHANNEL_ID` | yes      | Channel to fetch messages from                            |
| `SLACK_USERNAME`   | yes      | Username (without @) to filter and DM                     |
| `REPORT_TYPE`      | no       | `json` (default) \| `txt` \| `slack`                      |
| `DATE_FROM`        | no       | Period start `YYYY-MM-DD` (default: 1st of current month) |
| `DATE_TO`          | no       | Period end `YYYY-MM-DD` (default: last of current month)  |

### Multi-workspace mode

Set `WORKSPACES=ws1,ws2` and prefix each workspace's settings:

```
WORKSPACES=alice,bob

ALICE_SLACK_API_TOKEN=xoxb-...
ALICE_SLACK_CHANNEL_ID=C111
ALICE_SLACK_USERNAME=alice
ALICE_REPORT_TYPE=slack
ALICE_DATE_FROM=2026-03-01
ALICE_DATE_TO=2026-03-31

BOB_SLACK_API_TOKEN=xoxb-...
BOB_SLACK_CHANNEL_ID=C222
BOB_SLACK_USERNAME=bob
BOB_REPORT_TYPE=json
```

All workspaces run in parallel (ThreadPoolExecutor). Outputs are named `{workspace}_slack_report_messages.json/txt`.

---

## globals.py — current state

```python
api_token   = os.getenv("SLACK_API_TOKEN")
channel_id  = os.getenv("SLACK_CHANNEL_ID")
username    = os.getenv("SLACK_USERNAME")
report_type = os.getenv("REPORT_TYPE", "json")  # json | txt | slack
date_from   = os.getenv("DATE_FROM", <first day of current month>)
date_to     = os.getenv("DATE_TO",   <last day of current month>)
```

---

## main.py — key flow

1. `argparse` — `--date-from`, `--date-to`, `--report-type` (override env vars in single-workspace mode)
2. `load_workspaces(args)` — builds list of `WorkspaceConfig` from env (multi if `WORKSPACES` is set, else single default)
3. If one workspace: `run_workspace(cfg)` directly
4. If multiple: `ThreadPoolExecutor` runs all `run_workspace(cfg)` in parallel, each isolated
5. Per workspace `run_workspace(cfg)`:
   - creates its own `WebClient(token=cfg.api_token)`
   - `get_user_id(client, cfg.username)` — resolves username → user ID
   - `fetch_channel_messages(client, cfg.channel_id, user_id, oldest, latest)` — paginates history + thread replies
   - `extract_text(data)` — extracts `{date, message}` from raw payloads
   - branches on `cfg.report_type`: json / txt / slack

### CLI usage

```
python main.py                                      # uses env vars
python main.py --date-from 2026-03-01 --date-to 2026-03-31
python main.py --report-type slack
```

### Known issues / optimization candidates

- `fetch_channel_messages`: non-threaded message added twice if it also appears in thread (deduplication missing).
- `get_user_id`: no pagination — only checks first page of `users.list`.
- `extract_text` ignores rich block text (only captures top-level `text` field).

---

## slack_notifier.py — current state

### Public API

```python
send_activity_report(
    messages: list[dict],
    date_from: str,
    date_to: str,
    *,
    api_token: str,   # per-workspace token
    username: str,    # per-workspace recipient
) -> bool
```

- `messages`: list of `{date: str, message: str}` dicts from `extract_text()`
- Opens DM to the specified `username`, posts using Block Kit
- Splits into multiple messages if > 50 blocks (Slack limit)
- Does **not** import from `globals` — all config is passed explicitly

### Internal helpers

- `_find_user_id(client, user_ref)` — paginated `users.list` scan; matches name, display_name, real_name
- `_open_dm(client, user_id)` — `conversations.open`
- `_build_header_blocks(date_from, date_to)` — header + context blocks (posted as main message)
- `_build_message_blocks(messages)` — section + divider per message (posted as thread replies)
- `_split_blocks(blocks)` — chunks at 50-block limit

### Slack DM structure

**Main message** (header only):
```json
{
  "blocks": [
    { "type": "header", "text": { "type": "plain_text", "text": "💻 Activity Report" } },
    { "type": "context", "elements": [{ "type": "mrkdwn", "text": "🗓 *2026-03-01 — 2026-03-31*" }] }
  ]
}
```

**Thread replies** (one chunk per ≤50 blocks, each with `thread_ts`):
```json
{
  "blocks": [
    {
      "type": "section",
      "text": { "type": "mrkdwn", "text": "*Date: 2026-03-24*\n\n<text>" }
    },
    { "type": "divider" },
    {
      "type": "section",
      "text": { "type": "mrkdwn", "text": "*Date: 2026-03-25*\n\n<text>" }
    },
    { "type": "divider" }
  ]
}
```

---

## Required Slack token scopes

| Scope              | Used for                |
| ------------------ | ----------------------- |
| `channels:history` | `conversations.history` |
| `channels:read`    | channel info            |
| `groups:history`   | private channels        |
| `im:history`       | DM channels             |
| `im:write`         | `conversations.open`    |
| `users:read`       | `users.list`            |
| `chat:write`       | `chat.postMessage`      |

---

## Optimization roadmap (future iterations)

1. Fix duplicate messages in `fetch_channel_messages` (track seen `ts` values).
2. Add pagination to `get_user_id` (currently only first page).
3. Support `users.lookupByEmail` as fast-path in `_find_user_id` if `@` is in username.
4. Extract rich block text in `extract_text` (traverse `blocks → elements → text`).
5. Add `--dry-run` flag to print Slack blocks to stdout without sending.
6. Replace hardcoded filenames in `globals.py` with env vars.
