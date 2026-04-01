import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import globals as g
from slack_notifier import send_activity_report


# ---------------------------------------------------------------------------
# Workspace configuration
# ---------------------------------------------------------------------------

@dataclass
class WorkspaceConfig:
    name: str
    api_token: str
    channel_id: str
    username: str
    report_type: str
    date_from: str
    date_to: str
    json_filename: str
    txt_filename: str


def load_workspaces(args: argparse.Namespace) -> list[WorkspaceConfig]:
    """
    Build workspace configs from env vars and CLI args.

    Multi-workspace mode — set WORKSPACES=ws1,ws2 and prefix each setting:
      WS1_SLACK_API_TOKEN, WS1_SLACK_CHANNEL_ID, WS1_SLACK_USERNAME,
      WS1_REPORT_TYPE, WS1_DATE_FROM, WS1_DATE_TO

    Single-workspace mode (default) — uses top-level env vars;
    CLI flags --date-from / --date-to / --report-type override them.
    """
    workspaces_env = os.getenv("WORKSPACES", "").strip()
    if workspaces_env:
        names = [n.strip() for n in workspaces_env.split(",") if n.strip()]
        configs = []
        for name in names:
            p = name.upper() + "_"
            ws_username = os.getenv(f"{p}SLACK_USERNAME") or g.username
            configs.append(WorkspaceConfig(
                name=name,
                api_token=os.getenv(f"{p}SLACK_API_TOKEN") or g.api_token,
                channel_id=os.getenv(f"{p}SLACK_CHANNEL_ID") or g.channel_id,
                username=ws_username,
                report_type=os.getenv(f"{p}REPORT_TYPE", g.report_type),
                date_from=os.getenv(f"{p}DATE_FROM", g.date_from),
                date_to=os.getenv(f"{p}DATE_TO", g.date_to),
                json_filename=f"{name}_{ws_username}_report.json",
                txt_filename=f"{name}_{ws_username}_report.txt",
            ))
        return configs

    return [WorkspaceConfig(
        name="default",
        api_token=g.api_token,
        channel_id=g.channel_id,
        username=g.username,
        report_type=args.report_type or g.report_type,
        date_from=args.date_from or g.date_from,
        date_to=args.date_to or g.date_to,
        json_filename=f"{g.username}_report.json",
        txt_filename=f"{g.username}_report.txt",
    )]


# ---------------------------------------------------------------------------
# Slack data fetching
# ---------------------------------------------------------------------------

def fetch_channel_messages(client: WebClient, channel_id: str, user_id: str, oldest: float, latest: float) -> list:
    try:
        messages = []
        has_more = True
        next_cursor = None

        while has_more:
            result = client.conversations_history(
                channel=channel_id, oldest=oldest, latest=latest, limit=200, cursor=next_cursor
            )
            messages.extend(result["messages"])
            has_more = result["has_more"]
            next_cursor = result.get("response_metadata", {}).get("next_cursor")

        user_thread_messages = []

        for message in messages:
            if "thread_ts" in message:
                thread_ts = message["thread_ts"]
                thread_result = client.conversations_replies(channel=channel_id, ts=thread_ts)
                for thread_message in thread_result["messages"]:
                    if "user" in thread_message and thread_message["user"] == user_id:
                        user_thread_messages.append(thread_message)
            if "user" in message and message["user"] == user_id:
                user_thread_messages.append(message)

        return user_thread_messages
    except SlackApiError as e:
        g.logger.error(f"Error fetching messages: {e.response['error']}")
        return []


def get_user_id(client: WebClient, username: str) -> str | None:
    try:
        result = client.users_list()
        for user in result["members"]:
            if user["name"] == username:
                return user["id"]
        return None
    except SlackApiError as e:
        g.logger.error(f"Error fetching user ID: {e.response['error']}")
        return None


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def write_messages_to_json(messages: dict, filename: str) -> None:
    filepath = os.path.join(os.getcwd(), filename)
    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(messages, file, ensure_ascii=False, indent=4)


def write_messages_to_txt(messages: str, filename: str) -> None:
    filepath = os.path.join(os.getcwd(), filename)
    with open(filepath, "w", encoding="utf-8") as file:
        file.write(messages)


def extract_text(data, indent_level=0, seen=None) -> dict:
    if seen is None:
        seen = set()
    result = {}
    if isinstance(data, list):
        result["messages"] = [extract_text(item, indent_level, seen) for item in data]
    elif isinstance(data, dict):
        if "ts" in data:
            timestamp = datetime.fromtimestamp(float(data["ts"]))
            result["date"] = str(timestamp)
        if "text" in data and data["text"] not in seen:
            seen.add(data["text"])
            result["message"] = data["text"]
        if "blocks" in data:
            extract_text(data["blocks"], indent_level + 1, seen)
        if "elements" in data:
            extract_text(data["elements"], indent_level + 1, seen)
    return result


def reformat(messages: dict) -> str:
    formatted_messages = ""
    for message in messages["messages"]:
        if "date" in message:
            date_object = datetime.strptime(message["date"], "%Y-%m-%d %H:%M:%S.%f")
            date = date_object.strftime("%Y-%m-%d %H:%M")
            formatted_messages += f"\nDate: {date}\n"
        if "message" in message:
            formatted_messages += f'Message:\n{message["message"]}\n'
    return formatted_messages


# ---------------------------------------------------------------------------
# Per-workspace runner
# ---------------------------------------------------------------------------

def run_workspace(cfg: WorkspaceConfig) -> None:
    prefix = f"[{cfg.name}]"
    client = WebClient(token=cfg.api_token)

    oldest = time.mktime(time.strptime(cfg.date_from, "%Y-%m-%d"))
    latest = time.mktime(time.strptime(cfg.date_to, "%Y-%m-%d"))

    user_id = get_user_id(client, cfg.username)
    if not user_id:
        g.logger.warning(f"{prefix} User '{cfg.username}' not found")
        return

    raw_messages = fetch_channel_messages(client, cfg.channel_id, user_id, oldest, latest)
    if not raw_messages:
        g.logger.info(f"{prefix} No messages found for user '{cfg.username}' in channel '{cfg.channel_id}' between {cfg.date_from} and {cfg.date_to}.")
        return
    messages = extract_text(raw_messages)
    messages["messages"].reverse()

    if cfg.report_type == "json":
        write_messages_to_json(messages, cfg.json_filename)
        g.logger.info(f"{prefix} Messages written to {cfg.json_filename}")
    elif cfg.report_type == "txt":
        write_messages_to_txt(reformat(messages), cfg.txt_filename)
        g.logger.info(f"{prefix} Messages written to {cfg.txt_filename}")
    elif cfg.report_type == "slack":
        ok = send_activity_report(
            messages["messages"], cfg.date_from, cfg.date_to,
            api_token=cfg.api_token, username=cfg.username, workspace=cfg.name,
        )
        if ok:
            g.logger.info(f"{prefix} Slack report sent to '{cfg.username}'.")
        else:
            g.logger.error(f"{prefix} Failed to send Slack report. Check logs for details.")
    else:
        g.logger.error(f"{prefix} Unknown REPORT_TYPE '{cfg.report_type}'. Use: json, txt, slack.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Slack activity report collector")
    parser.add_argument("--date-from", dest="date_from", metavar="YYYY-MM-DD",
                        help="Report period start (overrides DATE_FROM env)")
    parser.add_argument("--date-to", dest="date_to", metavar="YYYY-MM-DD",
                        help="Report period end (overrides DATE_TO env)")
    parser.add_argument("--report-type", dest="report_type", choices=["json", "txt", "slack"],
                        help="Output format (overrides REPORT_TYPE env)")
    args = parser.parse_args()

    workspaces = load_workspaces(args)

    if len(workspaces) == 1:
        run_workspace(workspaces[0])
    else:
        g.logger.info(f"Running {len(workspaces)} workspace(s) in parallel: {[w.name for w in workspaces]}")
        with ThreadPoolExecutor(max_workers=len(workspaces)) as executor:
            futures = {executor.submit(run_workspace, cfg): cfg.name for cfg in workspaces}
            for future in as_completed(futures):
                name = futures[future]
                exc = future.exception()
                if exc:
                    g.logger.error(f"[{name}] ERROR: {exc}")
