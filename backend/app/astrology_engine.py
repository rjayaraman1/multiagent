from __future__ import annotations

import calendar
import hashlib
import math
from datetime import datetime
from functools import lru_cache
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import ephem
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from timezonefinder import TimezoneFinder

from .schemas import BirthInput, ChartResponse, PlanetPlacement

_geocoder = Nominatim(user_agent="multiagent-vedicastro")
_tf = TimezoneFinder()

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishtha",
    "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]


def _nakshatra(sidereal_degree: float) -> str:
    """Return the Nakshatra name for a given sidereal longitude (0–360°)."""
    idx = int((sidereal_degree % 360) / (360 / 27))
    return NAKSHATRAS[idx]

PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]

HOUSE_LABELS = [
    "1st House", "2nd House", "3rd House", "4th House", "5th House", "6th House",
    "7th House", "8th House", "9th House", "10th House", "11th House", "12th House",
]

@lru_cache(maxsize=256)
def _city_coords(place: str) -> Tuple[float, float]:
    """Geocode a place string to (lat, lon) using Nominatim. Results are cached in-process."""
    try:
        location = _geocoder.geocode(place, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except (GeocoderTimedOut, GeocoderServiceError) as exc:
        print(f"[geocoder] {exc} — falling back to central India coords")
    print(f"[geocoder] could not resolve '{place}' — falling back to central India coords")
    return (20.0, 78.0)


def _parse_tz(tz: str) -> float:
    """'+05:30' → 5.5 hours."""
    s = tz.strip()
    sign = -1 if s.startswith("-") else 1
    parts = s.lstrip("+-").split(":")
    return sign * (int(parts[0]) + int(parts[1]) / 60)


def _auto_tz(lat: float, lon: float, birth_date: str, birth_time: str) -> Tuple[Optional[float], str]:
    """Detect UTC offset (hours) and timezone name from coordinates + birth datetime.
    Returns (offset_hours, tz_name). offset_hours is None if detection fails."""
    tz_name = _tf.timezone_at(lat=lat, lng=lon)
    if not tz_name:
        return None, "unknown"
    try:
        year, month, day = map(int, birth_date.split("-"))
        h, m = map(int, birth_time.split(":"))
        dt = datetime(year, month, day, h, m, tzinfo=ZoneInfo(tz_name))
        offset = dt.utcoffset()
        if offset is not None:
            return offset.total_seconds() / 3600, tz_name
    except (ZoneInfoNotFoundError, ValueError) as exc:
        print(f"[timezone] {exc}")
    return None, tz_name


def _fmt_offset(tz_hours: float) -> str:
    """Format a UTC offset in hours as ±HH:MM, e.g. -7.0 → '-07:00'."""
    sign = '+' if tz_hours >= 0 else '-'
    total_minutes = int(abs(tz_hours) * 60)
    return f"{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _make_observer(payload: BirthInput) -> Tuple[ephem.Observer, float, str, str]:
    """Return (observer, T_julian_centuries, tz_name, utc_offset_str)."""
    lat, lon = _city_coords(payload.birth_place)

    tz_hours, tz_name = _auto_tz(lat, lon, payload.birth_date, payload.birth_time)
    if tz_hours is None:
        tz_hours = _parse_tz(payload.timezone)
        tz_name = f"manual ({payload.timezone})"
        print(f"[timezone] auto-detection failed for {payload.birth_place}, using {payload.timezone}")
    else:
        print(f"[timezone] auto-detected {tz_name} (UTC{tz_hours:+.2f}h) for {payload.birth_place}")

    year, month, day = map(int, payload.birth_date.split("-"))
    h, m = map(int, payload.birth_time.split(":"))

    ut_h = h + m / 60.0 - tz_hours
    ut_day = day + ut_h / 24.0

    # Handle day underflow into previous month
    if ut_day < 1:
        month -= 1
        if month < 1:
            month = 12
            year -= 1
        ut_day += calendar.monthrange(year, month)[1]
    # Handle day overflow into next month
    else:
        days_in_month = calendar.monthrange(year, month)[1]
        if ut_day > days_in_month:
            ut_day -= days_in_month
            month += 1
            if month > 12:
                month = 1
                year += 1

    obs = ephem.Observer()
    obs.date = ephem.Date((year, month, ut_day))
    obs.lat = str(lat)
    obs.lon = str(lon)
    obs.pressure = 0  # No atmospheric refraction

    T = (obs.date - ephem.Date("2000/1/1.5")) / 36525.0
    return obs, T, tz_name, _fmt_offset(tz_hours)


def _lahiri_ayanamsha(T: float) -> float:
    """Lahiri (Chitrapaksha) ayanamsha in degrees for T Julian centuries since J2000."""
    return 23.8532 + 1.3966 * T


def _moon_ascending_node(T: float) -> float:
    """Mean tropical longitude of Moon's ascending node (Rahu) in degrees."""
    omega = (
        125.0445479
        - 1934.1362608 * T
        + 0.0020754 * T ** 2
        + T ** 3 / 467441
        - T ** 4 / 60616000
    )
    return omega % 360


def _ecliptic_lon(body: ephem.Body, obs: ephem.Observer) -> float:
    """Geocentric tropical ecliptic longitude in degrees (0–360)."""
    body.compute(obs)
    ecl = ephem.Ecliptic(body, epoch=obs.date)
    return math.degrees(ecl.lon) % 360


def _ascendant_tropical(obs: ephem.Observer, T: float) -> float:
    """Tropical ascendant longitude (degrees) using Koch/standard formula."""
    eps = math.radians(23.439291111 - 0.013004167 * T)
    lst_deg = math.degrees(obs.sidereal_time())   # ephem gives radians; 2π ≡ 360° RAMC
    ramc = math.radians(lst_deg)
    lat = math.radians(math.degrees(float(obs.lat)))

    num = -math.cos(ramc)
    den = math.sin(eps) * math.tan(lat) + math.cos(eps) * math.sin(ramc)
    # atan2(num, den) yields the descending node; +180° gives the ascending node (Lagna)
    return (math.degrees(math.atan2(num, den)) + 180) % 360


# ── Main calculation engine ──────────────────────────────────────────────────

def _build_chart_local(payload: BirthInput) -> ChartResponse:
    obs, T, tz_name, utc_offset = _make_observer(payload)
    ayanamsha = _lahiri_ayanamsha(T)

    _EPHEM = {
        "Sun": ephem.Sun(), "Moon": ephem.Moon(), "Mars": ephem.Mars(),
        "Mercury": ephem.Mercury(), "Jupiter": ephem.Jupiter(),
        "Venus": ephem.Venus(), "Saturn": ephem.Saturn(),
    }

    tropical: dict[str, float] = {
        name: _ecliptic_lon(body, obs) for name, body in _EPHEM.items()
    }
    tropical["Rahu"] = _moon_ascending_node(T)
    tropical["Ketu"] = (tropical["Rahu"] + 180.0) % 360

    asc_trop = _ascendant_tropical(obs, T)
    asc_sid = (asc_trop - ayanamsha) % 360
    asc_idx = int(asc_sid // 30)
    asc_sign = SIGNS[asc_idx]

    placements: List[PlanetPlacement] = []
    for body in PLANETS:
        sid = (tropical[body] - ayanamsha) % 360
        sign_idx = int(sid // 30)
        sign = SIGNS[sign_idx]
        house = (sign_idx - asc_idx + 12) % 12 + 1
        placements.append(PlanetPlacement(
            body=body,
            degree=round(sid, 2),
            sign=sign,
            house=house,
        ))

    moon_placement = next(p for p in placements if p.body == "Moon")
    moon_sign = moon_placement.sign
    sun_sign = next(p.sign for p in placements if p.body == "Sun")

    profile = {
        "ascendant_sign": asc_sign,
        "moon_sign": moon_sign,
        "moon_nakshatra": _nakshatra(moon_placement.degree),
        "sun_sign": sun_sign,
        "chart_method": "ephem-lahiri",
        "detected_timezone": tz_name,
        "detected_utc_offset": utc_offset,
    }
    return ChartResponse(profile=profile, placements=placements, house_labels=HOUSE_LABELS)


def build_chart(payload: BirthInput) -> ChartResponse:
    try:
        return _build_chart_local(payload)
    except Exception as exc:
        print(f"[astrology] ephem error ({exc}), falling back to demo chart")
        return build_demo_chart(payload)


# ── Demo / fallback engine ────────────────────────────────────────────────────

def _seed_value(payload: BirthInput) -> int:
    raw = f"{payload.birth_date}|{payload.birth_time}|{payload.birth_place}|{payload.name}".encode()
    return int(hashlib.sha256(raw).hexdigest(), 16)


def build_demo_chart(payload: BirthInput) -> ChartResponse:
    seed = _seed_value(payload)
    asc_index = seed % 12

    placements: List[PlanetPlacement] = []
    for i, body in enumerate(PLANETS):
        segment = (seed >> (i * 11)) & 0x7FF
        degree = float(segment % 360) + round(((seed >> (i * 3)) % 100) / 100.0, 2)
        sign_idx = int(degree // 30) % 12
        sign = SIGNS[sign_idx]
        house = (sign_idx - asc_index + 12) % 12 + 1
        placements.append(PlanetPlacement(body=body, degree=round(degree, 2), sign=sign, house=house))

    demo_moon_degree = float(((seed // 13) % 360))
    profile = {
        "ascendant_sign": SIGNS[asc_index],
        "moon_sign": SIGNS[(seed // 13) % 12],
        "moon_nakshatra": _nakshatra(demo_moon_degree),
        "sun_sign": SIGNS[(seed // 29) % 12],
        "chart_method": "demo-deterministic-hash",
    }
    return ChartResponse(profile=profile, placements=placements, house_labels=HOUSE_LABELS)


def summarize_chart(chart: ChartResponse) -> str:
    asc = chart.profile.get("ascendant_sign", "Unknown")
    moon = chart.profile.get("moon_sign", "Unknown")
    sun = chart.profile.get("sun_sign", "Unknown")
    top = ", ".join(f"{p.body} in {p.sign} / {p.house}H" for p in chart.placements[:4])
    return f"Ascendant: {asc}; Moon: {moon}; Sun: {sun}; Key placements: {top}"
