import os

from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/slack.env"))

api_token = os.getenv("SLACK_API_TOKEN")
channel_id = os.getenv("SLACK_CHANNEL_ID")
username = os.getenv("SLACK_USERNAME")

json_filename = "slack_report_messages.json"
txt_filename = "slack_report_messages.txt"
date_from = "2024-07-01"
date_to = "2024-07-31"
