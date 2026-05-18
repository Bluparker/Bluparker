#!/usr/bin/env python3
"""Daily flight price monitor.

Usage:
  python monitor.py           # start scheduler (runs daily at the configured time)
  python monitor.py --once    # run a single check immediately and exit
"""

import logging
import os
import sys
import time
from datetime import date, timedelta
from typing import List

import schedule
import yaml
from dotenv import load_dotenv

from amadeus_client import AmadeusClient
from notifier import format_alert, send_alert
from storage import (
    already_alerted,
    get_previous_best_price,
    init_db,
    log_alert,
    save_snapshot,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("flight_monitor.log"),
    ],
)
logger = logging.getLogger(__name__)

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")


def load_config() -> dict:
    with open(CONFIG_PATH) as fh:
        return yaml.safe_load(fh)


def date_range(start: str, end: str) -> List[str]:
    d = date.fromisoformat(start)
    last = date.fromisoformat(end)
    dates: List[str] = []
    while d <= last:
        dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates


def run_monitor() -> None:
    logger.info("=== Flight monitor run started ===")
    config = load_config()
    client = AmadeusClient()
    drop_threshold: float = config.get("price_drop_threshold_pct", 5)

    for watch in config.get("watches", []):
        name: str = watch["name"]
        origin: str = watch["origin"].upper()
        destination: str = watch["destination"].upper()
        currency: str = watch.get("currency", "USD")
        adults: int = watch.get("adults", 1)
        cabin: str = watch.get("cabin_class", "ECONOMY")
        max_price = watch.get("max_price")
        max_stops = watch.get("max_stops")
        max_layover = watch.get("max_layover_hours")

        dr = watch.get("departure_date_range", {})
        start_date: str = dr.get("from", date.today().isoformat())
        end_date: str = dr.get("to", start_date)
        max_dates: int = config.get("max_dates_per_watch", 30)

        dates = date_range(start_date, end_date)[:max_dates]
        logger.info(
            "Checking watch '%s' (%s->%s) across %d date(s)",
            name, origin, destination, len(dates),
        )

        for dep_date in dates:
            offers = client.search_cheapest(
                origin=origin,
                destination=destination,
                departure_date=dep_date,
                adults=adults,
                currency=currency,
                cabin_class=cabin,
                max_stops=max_stops,
                max_layover_hours=max_layover,
            )

            if not offers:
                logger.info("  %s: no matching offers", dep_date)
                continue

            best = offers[0]
            logger.info(
                "  %s: best %s %.0f  (%d stop(s), airline %s)",
                dep_date, currency, best.price, best.stops, best.airline,
            )

            save_snapshot(
                name, origin, destination, dep_date,
                best.price, currency, best.airline, best.stops,
            )

            prev_price = get_previous_best_price(name, origin, destination, dep_date)
            alert_type = None

            if max_price is not None and best.price <= max_price:
                alert_type = "below_threshold"
            elif prev_price is not None:
                drop_pct = (prev_price - best.price) / prev_price * 100
                if drop_pct >= drop_threshold:
                    alert_type = "price_drop"

            if alert_type and not already_alerted(name, origin, destination, dep_date, best.price):
                msg = format_alert(name, best, alert_type, prev_price)
                send_alert(msg)
                log_alert(name, origin, destination, dep_date, best.price, alert_type)
                logger.info("  Alert sent (%s)", alert_type)

    logger.info("=== Flight monitor run complete ===")


def main() -> None:
    init_db()

    if "--once" in sys.argv:
        run_monitor()
        return

    config = load_config()
    run_time: str = config.get("schedule", {}).get("time", "08:00")
    logger.info("Scheduler started — daily run at %s", run_time)

    schedule.every().day.at(run_time).do(run_monitor)
    run_monitor()  # run immediately on startup

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
