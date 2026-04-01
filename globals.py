import logging
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("slack_report")

load_dotenv(os.path.expanduser("~/slack.env"))  # sensitive: tokens only
load_dotenv(os.path.join(os.path.dirname(__file__), "local.env"), override=False)  # project config


def _current_month_range() -> tuple[str, str]:
    today = datetime.now()
    first = today.replace(day=1)
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    last = next_month - timedelta(days=1)
    return first.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d")


_default_date_from, _default_date_to = _current_month_range()

api_token   = os.getenv("SLACK_API_TOKEN")
channel_id  = os.getenv("SLACK_CHANNEL_ID")
username    = os.getenv("SLACK_USERNAME")
report_type = os.getenv("REPORT_TYPE", "json")  # json | txt | slack
date_from   = os.getenv("DATE_FROM", _default_date_from)
date_to     = os.getenv("DATE_TO", _default_date_to)