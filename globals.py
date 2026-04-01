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
    approx_from = today - timedelta(days=15)  # to get a rough estimate of the month
    date_from = datetime(approx_from.year, approx_from.month, 1).strftime("%Y-%m-%d")
    month_index = approx_from.month
    last_day_of_month = (datetime(approx_from.year, month_index, 1) + timedelta(days=31)).replace(
        day=1
    ) - timedelta(days=1)
    date_to = last_day_of_month.strftime("%Y-%m-%d")
    return date_from, date_to


_default_date_from, _default_date_to = _current_month_range()

api_token = os.getenv("SLACK_API_TOKEN")
channel_id = os.getenv("SLACK_CHANNEL_ID")
username = os.getenv("SLACK_USERNAME")
report_type = os.getenv("REPORT_TYPE", "json")  # json | txt | slack
date_from = os.getenv("DATE_FROM", _default_date_from)
date_to = os.getenv("DATE_TO", _default_date_to)
