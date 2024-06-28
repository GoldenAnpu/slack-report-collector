import json
import os
import time
from datetime import datetime

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from globals import (
    api_token,
    channel_id,
    date_from,
    date_to,
    json_filename,
    txt_filename,
    username,
)

client = WebClient(token=api_token)


def fetch_channel_messages(channel_id, user_id, oldest, latest):
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
                thread_messages = thread_result["messages"]
                for thread_message in thread_messages:
                    if "user" in thread_message and thread_message["user"] == user_id:
                        user_thread_messages.append(thread_message)
            if "user" in message and message["user"] == user_id:
                user_thread_messages.append(message)
        return user_thread_messages
    except SlackApiError as e:
        print(f"Error fetching messages: {e.response['error']}")
        return []


def get_user_id(username):
    try:
        result = client.users_list()
        for user in result["members"]:
            if user["name"] == username:
                return user["id"]
        return None
    except SlackApiError as e:
        print(f"Error fetching user ID: {e.response['error']}")
        return None


def write_messages_to_json(messages, filename):
    filename = os.path.join(os.getcwd(), filename)
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(messages, file, ensure_ascii=False, indent=4)


def write_messages_to_txt(messages, filename):
    filename = os.path.join(os.getcwd(), filename)
    with open(filename, "w", encoding="utf-8") as file:
        file.write(f"{messages}")


def extract_text(data, indent_level=0, seen=None):
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


def reformat(messages):
    formatted_messages = ""
    for message in messages["messages"]:
        if "date" in message:
            date_string = message["date"]
            date_object = datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S.%f")
            date = date_object.strftime("%Y-%m-%d %H:%M")
            formatted_messages += f"\nDate: {date}\n"
        if "message" in message:
            formatted_messages += f'Message:\n{message["message"]}\n'
    return formatted_messages


if __name__ == "__main__":
    oldest = time.mktime(time.strptime(date_from, "%Y-%m-%d"))
    latest = time.mktime(time.strptime(date_to, "%Y-%m-%d"))

    user_id = get_user_id(username)
    if user_id:
        raw_messages = fetch_channel_messages(channel_id, user_id, oldest, latest)
        messages = extract_text(raw_messages)
        messages["messages"].reverse()
        write_messages_to_json(messages, json_filename)
        formatted_messages = reformat(messages)
        write_messages_to_txt(formatted_messages, txt_filename)
        print(f"Messages written to:\n    - {json_filename}\n    - {txt_filename}")
    else:
        print(f"User {username} not found")
