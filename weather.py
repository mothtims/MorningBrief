"""
Weather fetcher: UK postcode -> coordinates (postcodes.io) -> forecast
(Open-Meteo) -> plain practical advice text. No API key for either.
"""

from __future__ import annotations

import urllib.parse

from httputil import get_json
from logutil import get_logger

log = get_logger("weather")

POSTCODES_IO_BASE = "https://api.postcodes.io/postcodes"
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes (Open-Meteo), collapsed to plain-English categories.
_WMO_DESCRIPTIONS = {
    0: "clear skies",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy with frost",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "rain showers",
    82: "heavy rain showers",
    95: "thunderstorms",
}


def postcode_to_coords(postcode: str) -> tuple[float, float]:
    encoded = urllib.parse.quote(postcode)
    data = get_json(f"{POSTCODES_IO_BASE}/{encoded}", log)
    result = data["result"]
    return result["latitude"], result["longitude"]


def get_forecast(latitude: float, longitude: float) -> dict:
    query = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
            "timezone": "Europe/London",
            "forecast_days": 1,
        }
    )
    return get_json(f"{OPEN_METEO_BASE}?{query}", log)


def summarize_weather(postcode: str) -> str:
    try:
        lat, lon = postcode_to_coords(postcode)
        forecast = get_forecast(lat, lon)
    except Exception as exc:
        log.error("Weather fetch failed after retries: %s", exc, exc_info=True)
        return f"Weather unavailable right now ({exc})."

    daily = forecast["daily"]
    temp_max = daily["temperature_2m_max"][0]
    temp_min = daily["temperature_2m_min"][0]
    rain_chance = daily["precipitation_probability_max"][0]
    code = daily["weathercode"][0]
    description = _WMO_DESCRIPTIONS.get(code, "mixed conditions")

    advice_bits = [f"{description.capitalize()}, {temp_min:.0f}-{temp_max:.0f}°C."]

    if rain_chance >= 50:
        advice_bits.append(f"{rain_chance}% chance of rain — take an umbrella.")
    elif rain_chance >= 20:
        advice_bits.append(f"{rain_chance}% chance of rain — maybe pack a brolly.")

    if temp_max <= 5:
        advice_bits.append("Bitterly cold — wrap up.")
    elif temp_min <= 2:
        advice_bits.append("Cold start — extra layer this morning.")
    elif temp_max >= 27:
        advice_bits.append("Hot — light clothing, water.")

    return " ".join(advice_bits)


if __name__ == "__main__":
    import sys

    print(summarize_weather(sys.argv[1]))
