"""
Slack notification module for the activity report collector.

Sends a formatted DM to the user specified by SLACK_USERNAME with the
collected activity messages for the requested period.

Configuration is shared with the main app via globals.py:
  SLACK_API_TOKEN  - Slack token (xoxs- user token or xoxb- bot token).
                     Required scopes: chat:write, im:write, users:read
  SLACK_USERNAME   - Slack username (without @) of the report recipient.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from globals import logger

_MAX_BLOCKS_PER_MESSAGE = 50


# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------

def _build_header_blocks(date_from: str, date_to: str) -> list[dict]:
    period = f"{date_from} — {date_to}"
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "💻 Activity Report"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🗓 *{period}*"}]},
    ]


def _build_message_blocks(messages: list[dict]) -> list[dict]:
    blocks: list[dict] = []
    for msg in messages:
        raw_date = msg.get("date", "")
        try:
            date = datetime.strptime(raw_date, "%Y-%m-%d %H:%M:%S.%f").strftime("%Y-%m-%d")
        except ValueError:
            date = raw_date[:10]
        text = msg.get("message", "")
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Date: {date}*\n\n{text}",
            },
        })
        blocks.append({"type": "divider"})
    return blocks


def _split_blocks(blocks: list[dict]) -> list[list[dict]]:
    """Split blocks into chunks that fit within Slack's 50-block limit."""
    if len(blocks) <= _MAX_BLOCKS_PER_MESSAGE:
        return [blocks]

    chunks: list[list[dict]] = []
    for i in range(0, len(blocks), _MAX_BLOCKS_PER_MESSAGE):
        chunks.append(blocks[i : i + _MAX_BLOCKS_PER_MESSAGE])
    return chunks


# ---------------------------------------------------------------------------
# User / DM helpers
# ---------------------------------------------------------------------------

def _find_user_id(client: WebClient, user_ref: str) -> Optional[str]:
    """Resolve a Slack username to a user ID via users.list scan."""
    user_ref = user_ref.lstrip("@").strip()
    if not user_ref:
        return None

    cursor = None
    while True:
        resp = client.users_list(limit=200, cursor=cursor)
        for member in resp.get("members", []):
            if member.get("deleted") or member.get("is_bot"):
                continue
            profile = member.get("profile", {})
            handles = [
                member.get("name", ""),
                profile.get("display_name", ""),
                profile.get("display_name_normalized", ""),
                profile.get("real_name", ""),
                profile.get("real_name_normalized", ""),
            ]
            if user_ref.lower() in [h.lower() for h in handles if h]:
                return member["id"]
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    logger.warning("Could not find Slack user: %s", user_ref)
    return None


def _open_dm(client: WebClient, user_id: str) -> Optional[str]:
    """Open (or reuse) a DM channel and return its ID."""
    try:
        resp = client.conversations_open(users=[user_id])
        return resp["channel"]["id"]
    except SlackApiError as e:
        logger.error("Could not open DM with user %s: %s", user_id, e.response["error"])
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_activity_report(
    messages: list[dict],
    date_from: str,
    date_to: str,
    *,
    api_token: str,
    username: str,
    workspace: str = "default",
) -> bool:
    """
    Send the activity report as a DM to the specified user.

    Parameters
    ----------
    messages:  list of {date, message} dicts produced by extract_text() in main.py
    date_from: report period start string (e.g. "2026-03-01")
    date_to:   report period end string   (e.g. "2026-03-31")
    api_token: Slack API token for this workspace
    username:  Slack username (without @) of the report recipient

    Returns True on success, False if skipped or failed.
    """
    if not api_token:
        logger.warning("[%s] SLACK_API_TOKEN is not configured — Slack notification skipped.", workspace)
        return False

    if not username:
        logger.warning("[%s] SLACK_USERNAME is not configured — Slack notification skipped.", workspace)
        return False

    if not messages:
        logger.info("[%s] No messages to report — Slack notification skipped.", workspace)
        return False

    client = WebClient(token=api_token)

    logger.info("[%s] Looking up Slack user '%s'...", workspace, username)
    user_id = _find_user_id(client, username)
    if not user_id:
        logger.error("[%s] Slack user '%s' not found — notification skipped.", workspace, username)
        return False

    logger.info("[%s] Opening DM with '%s' (id=%s)...", workspace, username, user_id)
    dm_channel = _open_dm(client, user_id)
    if not dm_channel:
        return False

    header_blocks = _build_header_blocks(date_from, date_to)
    message_blocks = _build_message_blocks(messages)
    message_chunks = _split_blocks(message_blocks)
    fallback_text = f"Activity Report {date_from} — {date_to} ({len(messages)} message(s))"

    # Post the header as the main message and capture thread_ts
    try:
        resp = client.chat_postMessage(channel=dm_channel, text=fallback_text, blocks=header_blocks)
        thread_ts = resp["ts"]
    except SlackApiError as e:
        logger.error("[%s] Failed to post header message: %s", workspace, e.response["error"])
        return False

    # Post message blocks as threaded replies
    for i, chunk in enumerate(message_chunks, start=1):
        chunk_text = fallback_text if len(message_chunks) == 1 else f"{fallback_text} ({i}/{len(message_chunks)})"
        try:
            client.chat_postMessage(channel=dm_channel, text=chunk_text, blocks=chunk, thread_ts=thread_ts)
        except SlackApiError as e:
            logger.error("[%s] Failed to send Slack report (chunk %d/%d): %s", workspace, i, len(message_chunks), e.response["error"])
            return False

    logger.info("[%s] Activity report sent to '@%s' (%d message(s), %d chunk(s)).", workspace, username, len(messages), len(message_chunks))
    return True
