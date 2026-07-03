import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

class Config:
    DATA_API_URL = os.getenv("API_URL")
    HEADERS = json.loads(
        os.environ.get("HEADERS")
    )
    PAYLOAD = json.loads(
        os.environ.get("PAYLOAD")
        )

    GG_API = os.environ.get("GG_API_KEY", "").strip()
    CALENDAR_URL = os.environ.get("CALENDAR_URL", "").strip()
    DATA_DIR = Path("data")

    CONFIG_FUNDS = [f.strip() for f in os.getenv("CONFIG_FUNDS", "").split(",") if f.strip()]

def validate_config():
    if not Config.DATA_API_URL or not Config.CONFIG_FUNDS:
        print(
            "[ERROR] Missing required configuration: API_URL or CONFIG_FUNDS."
        )
        sys.exit(1)


def isHoliday(date_obj, session):
    if not Config.GG_API or not Config.CALENDAR_URL:
        print(f"[WARNING] Missing Calendar API configuration. Stop Processing ...")
        sys.exit(0)
        return False

    try:
        start_of_day = date_obj.strftime("%Y-%m-%dT00:00:00Z")
        end_of_day = date_obj.strftime("%Y-%m-%dT23:59:59Z")
        url = Config.CALENDAR_URL
        params = {
            "key": Config.GG_API,
            "timeMin": start_of_day,
            "timeMax": end_of_day,
            "singleEvents": "true",
        }

        response = session.get(url, params=params, timeout=10)

        if response.status_code == 200:
            events = response.json().get("items", [])
            if events:
                holiday_name = events[0].get("summary", "Ngày lễ")
                print(
                    f"-> Holiday: {holiday_name}"
                )
                return True
        else:
            print(f"[WARNING] Calendar API error (Status: {response.status_code}). Stop Processing ...")
            sys.exit(0)
    except Exception:
        print(
            "[WARNING] Unable to connect to Calendar API. Stop Processing ..."
        )
        sys.exit(0)

    return False


def get_last_date_in_csv(file_path):
    if not file_path.is_file():
        return None
    try:
        with open(file_path, mode="rb") as f:
            try:
                f.seek(-2, os.SEEK_END)
                while f.read(1) != b"\n":
                    f.seek(-2, os.SEEK_CUR)
            except OSError:
                f.seek(0)
            last_line = f.readline().decode("utf-8").strip()
            if last_line:
                return last_line.split(",")[0]
    except Exception:
        pass
    return None

def parse_fund_row(row, now):
    short_name = row.get("shortName")
    extra = row.get("extra", {})
    current_nav = extra.get("currentNAV")
    last_nav_date_ts = extra.get("lastNAVDate")

    if last_nav_date_ts:
        date_str = datetime.fromtimestamp(last_nav_date_ts / 1000).strftime(
            "%d-%m-%y"
        )
    else:
        date_str = now.strftime("%d-%m-%y")

    nav_per_unit = f"{float(current_nav):.2f}" if current_nav is not None else "0.00"
    return short_name, date_str, nav_per_unit

def save_to_csv(short_name, date_str, nav_per_unit):
    csv_file_path = Config.DATA_DIR / f"{short_name}.csv"
    file_exists = csv_file_path.is_file()

    if get_last_date_in_csv(csv_file_path) == date_str:
        print(f"[SKIP] Fund {short_name} has data for {date_str} in the file."
        )
        return False

    with open(csv_file_path, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["date", "nav_per_unit", "short_name"])
        writer.writerow([date_str, nav_per_unit, short_name])

    print(
        f"[SUCCESS] Added data for {date_str} to file: {csv_file_path}"
    )
    return True

def fetch_and_save_by_fund():
    validate_config()

    now = datetime.now()
    weekday = now.weekday()

    if weekday in (5, 6):
        day_name = "Saturday" if weekday == 5 else "Sunday"
        print(
            f"Today is {day_name} ({now.strftime('%d-%m-%Y')}). The market is closed. Stopping the script!"
        )
        sys.exit(0)
    with requests.Session() as session:
        if isHoliday(now, session):
            print(
                f"Today is a holiday ({now.strftime('%d-%m-%Y')}). Stopping the script!"
            )
            sys.exit(0)


        Config.DATA_DIR.mkdir(parents=True, exist_ok=True)

        try:
            print("Connecting to data API to fetch NAV data...")
            response = session.post(
                Config.DATA_API_URL, json=Config.PAYLOAD, headers=Config.HEADERS
            )
            response.raise_for_status()
            result = response.json()

            if result.get("status") != 200 or "data" not in result:
                print("API returned an error or no data.")
                return

            rows = result["data"].get("rows", [])
            updated_funds = 0

            for row in rows:
                short_name, date_str, nav_per_unit = parse_fund_row(row, now)

                if short_name in Config.CONFIG_FUNDS:
                    if save_to_csv(short_name, date_str, nav_per_unit):
                        updated_funds += 1

            print(
                f"Process completed! Updated {updated_funds}/{len(Config.CONFIG_FUNDS)} funds in the directory '{Config.DATA_DIR}'."
            )

        except requests.exceptions.RequestException:
            print("Error connecting to data API.")
        except Exception:
            print("An error occurred during processing.")

if __name__ == "__main__":
    fetch_and_save_by_fund()