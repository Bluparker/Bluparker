"""Amadeus flight-offers search wrapper."""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from amadeus import Client, ResponseError

logger = logging.getLogger(__name__)


@dataclass
class FlightOffer:
    price: float
    currency: str
    origin: str
    destination: str
    departure_at: str
    arrival_at: str
    duration: str
    stops: int
    max_layover_hours: float
    airline: str


def _iso_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _fmt_duration(raw: str) -> str:
    """Convert ISO 8601 duration 'PT10H30M' to '10h 30m'."""
    return raw.replace("PT", "").replace("H", "h ").replace("M", "m").strip()


class AmadeusClient:
    def __init__(self) -> None:
        hostname = os.environ.get("AMADEUS_HOSTNAME", "test")
        self._client = Client(
            client_id=os.environ["AMADEUS_CLIENT_ID"],
            client_secret=os.environ["AMADEUS_CLIENT_SECRET"],
            hostname=hostname,
        )
        logger.info("Amadeus client initialised (hostname=%s)", hostname)

    def search_cheapest(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        adults: int = 1,
        currency: str = "USD",
        cabin_class: str = "ECONOMY",
        max_stops: Optional[int] = None,
        max_layover_hours: Optional[float] = None,
    ) -> List[FlightOffer]:
        params: dict = dict(
            originLocationCode=origin,
            destinationLocationCode=destination,
            departureDate=departure_date,
            adults=adults,
            currencyCode=currency,
            travelClass=cabin_class,
            max=50,
        )
        if max_stops == 0:
            params["nonStop"] = "true"

        try:
            response = self._client.shopping.flight_offers_search.get(**params)
        except ResponseError as exc:
            logger.error(
                "Amadeus error for %s->%s on %s: %s",
                origin, destination, departure_date, exc,
            )
            return []

        offers: List[FlightOffer] = []
        for raw in response.data:
            try:
                offer = self._parse_offer(raw, currency)
            except Exception as exc:
                logger.warning("Skipping malformed offer: %s", exc)
                continue

            if max_stops is not None and offer.stops > max_stops:
                continue
            if max_layover_hours is not None and offer.max_layover_hours > max_layover_hours:
                continue

            offers.append(offer)

        return sorted(offers, key=lambda o: o.price)

    def _parse_offer(self, raw: dict, currency: str) -> FlightOffer:
        price = float(raw["price"]["grandTotal"])
        itin = raw["itineraries"][0]
        segs = itin["segments"]
        stops = len(segs) - 1
        max_layover = self._max_layover(segs)

        return FlightOffer(
            price=price,
            currency=currency,
            origin=segs[0]["departure"]["iataCode"],
            destination=segs[-1]["arrival"]["iataCode"],
            departure_at=segs[0]["departure"]["at"],
            arrival_at=segs[-1]["arrival"]["at"],
            duration=_fmt_duration(itin["duration"]),
            stops=stops,
            max_layover_hours=max_layover,
            airline=segs[0]["carrierCode"],
        )

    @staticmethod
    def _max_layover(segments: list) -> float:
        if len(segments) <= 1:
            return 0.0
        max_h = 0.0
        for i in range(len(segments) - 1):
            arr = _iso_to_dt(segments[i]["arrival"]["at"])
            dep = _iso_to_dt(segments[i + 1]["departure"]["at"])
            max_h = max(max_h, (dep - arr).total_seconds() / 3600)
        return max_h
