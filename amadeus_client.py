"""Amadeus flight-offers search wrapper."""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from amadeus import Client, ResponseError

logger = logging.getLogger(__name__)


@dataclass
class FlightOffer:
    price: float
    currency: str
    # outbound leg
    origin: str
    destination: str
    departure_at: str
    arrival_at: str
    duration: str
    stops: int
    max_layover_hours: float
    airline: str
    # return leg (None for one-way)
    return_departure_at: Optional[str] = field(default=None)
    return_arrival_at: Optional[str] = field(default=None)
    return_duration: Optional[str] = field(default=None)
    return_stops: Optional[int] = field(default=None)
    return_max_layover_hours: Optional[float] = field(default=None)
    return_airline: Optional[str] = field(default=None)


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
        return_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infants: int = 0,
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
        if return_date:
            params["returnDate"] = return_date
        if children > 0:
            params["children"] = children
        if infants > 0:
            params["infants"] = infants
        if max_stops == 0:
            params["nonStop"] = "true"

        try:
            response = self._client.shopping.flight_offers_search.get(**params)
        except ResponseError as exc:
            logger.error(
                "Amadeus error for %s->%s dep=%s ret=%s: %s",
                origin, destination, departure_date, return_date, exc,
            )
            return []

        offers: List[FlightOffer] = []
        for raw in response.data:
            try:
                offer = self._parse_offer(raw, currency)
            except Exception as exc:
                logger.warning("Skipping malformed offer: %s", exc)
                continue

            # apply per-leg stop filter
            if max_stops is not None and offer.stops > max_stops:
                continue
            if offer.return_stops is not None and max_stops is not None and offer.return_stops > max_stops:
                continue
            # apply per-leg layover filter
            if max_layover_hours is not None and offer.max_layover_hours > max_layover_hours:
                continue
            if (
                offer.return_max_layover_hours is not None
                and max_layover_hours is not None
                and offer.return_max_layover_hours > max_layover_hours
            ):
                continue

            offers.append(offer)

        return sorted(offers, key=lambda o: o.price)

    def _parse_offer(self, raw: dict, currency: str) -> FlightOffer:
        price = float(raw["price"]["grandTotal"])
        itin = raw["itineraries"][0]
        segs = itin["segments"]

        offer = FlightOffer(
            price=price,
            currency=currency,
            origin=segs[0]["departure"]["iataCode"],
            destination=segs[-1]["arrival"]["iataCode"],
            departure_at=segs[0]["departure"]["at"],
            arrival_at=segs[-1]["arrival"]["at"],
            duration=_fmt_duration(itin["duration"]),
            stops=len(segs) - 1,
            max_layover_hours=self._max_layover(segs),
            airline=segs[0]["carrierCode"],
        )

        if len(raw["itineraries"]) >= 2:
            ret = raw["itineraries"][1]
            ret_segs = ret["segments"]
            offer.return_departure_at = ret_segs[0]["departure"]["at"]
            offer.return_arrival_at = ret_segs[-1]["arrival"]["at"]
            offer.return_duration = _fmt_duration(ret["duration"])
            offer.return_stops = len(ret_segs) - 1
            offer.return_max_layover_hours = self._max_layover(ret_segs)
            offer.return_airline = ret_segs[0]["carrierCode"]

        return offer

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
