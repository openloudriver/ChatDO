"""API Router for Tier 1 + Tier 2 data feeds.

Centralized access to external APIs for:
- Crypto prices (XMR, BTC, etc.)
- Monero network stats
- Stock/ETF quotes
- Weather data
- Geocoding
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import os
import logging
import httpx

logger = logging.getLogger(__name__)


# Request models
class CryptoPriceRequest(BaseModel):
    symbol: str  # e.g. "xmr", "btc"
    vs_currency: str = "usd"


class StockQuoteRequest(BaseModel):
    symbol: str  # e.g. "SCHD", "MSTY", "SPYI"


class WeatherRequest(BaseModel):
    location: str  # free-text, e.g. "Rome, NY, USA"


# Result models
class CryptoPriceResult(BaseModel):
    symbol: str
    vs_currency: str
    price: Optional[float]
    change_24h: Optional[float] = None
    source: str
    fetched_at: datetime


class MoneroNetworkStats(BaseModel):
    height: Optional[int]
    hashrate: Optional[float]
    difficulty: Optional[float]
    block_reward: Optional[float]
    avg_block_time: Optional[float]
    source: str
    fetched_at: datetime


class StockQuoteResult(BaseModel):
    symbol: str
    price: Optional[float]
    change_percent: Optional[float]
    previous_close: Optional[float]
    currency: Optional[str]
    source: str
    fetched_at: datetime
    # Dividend-related fields
    dividend_rate: Optional[float] = None  # forward annual dividend per share
    dividend_yield: Optional[float] = None  # forward annual yield (fraction, e.g. 0.035 for 3.5%)
    trailing_dividend_rate: Optional[float] = None  # trailing 12-month dividend per share
    trailing_dividend_yield: Optional[float] = None  # trailing 12-month yield (fraction)
    ex_dividend_date: Optional[int] = None  # Unix timestamp (seconds)
    payout_ratio: Optional[float] = None  # payout ratio (fraction, not percent)


class WeatherResult(BaseModel):
    location: str
    lat: Optional[float]
    lon: Optional[float]
    temperature_c: Optional[float]
    condition: Optional[str]
    wind_speed_kph: Optional[float]
    humidity: Optional[float]
    source: str
    fetched_at: datetime
    # Additional fields for unified provider support
    provider: Optional[str] = None  # "nws" or "open-meteo"
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    temperature_f: Optional[float] = None


class GeocodeResult(BaseModel):
    query: str
    lat: Optional[float]
    lon: Optional[float]
    display_name: Optional[str]
    source: str
    fetched_at: datetime
    country_code: Optional[str] = None


def _is_us_location(geo: Optional[GeocodeResult]) -> bool:
    """Helper to detect if a geocoded location is in the United States."""
    if not geo:
        return False
    
    # Prefer explicit country_code if present
    if getattr(geo, "country_code", None):
        return geo.country_code.lower() == "us"
    
    # Fallback: check display_name for "United States" substring
    display_name = getattr(geo, "display_name", None)
    if display_name:
        return "united states" in display_name.lower()
    
    return False


class ApiRouter:
    """
    Centralized, minimal API router for Tier 1 + Tier 2 data.
    
    All methods are async and safe: they handle errors, log, and return best-effort results.
    """
    _http_timeout = 8.0

    @classmethod
    async def get_crypto_price(cls, req: CryptoPriceRequest) -> CryptoPriceResult:
        """
        Fetch crypto price via CoinGecko (no API key).
        """
        base_url = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
        symbol = req.symbol.lower()
        vs = req.vs_currency.lower()
        
        try:
            async with httpx.AsyncClient(timeout=cls._http_timeout) as client:
                resp = await client.get(
                    f"{base_url}/simple/price",
                    params={
                        "ids": symbol,
                        "vs_currencies": vs,
                        "include_24hr_change": "true",
                    },
                )
                resp.raise_for_status()
                data = resp.json() or {}
        except Exception as e:
            logger.warning("ApiRouter.get_crypto_price error: %s", e)
            return CryptoPriceResult(
                symbol=req.symbol,
                vs_currency=req.vs_currency,
                price=None,
                change_24h=None,
                source="coingecko:error",
                fetched_at=datetime.utcnow(),
            )
        
        entry = data.get(symbol, {})
        price = entry.get(vs)
        change_24h = entry.get(f"{vs}_24h_change")
        
        return CryptoPriceResult(
            symbol=req.symbol.upper(),
            vs_currency=req.vs_currency.upper(),
            price=price,
            change_24h=change_24h,
            source="coingecko",
            fetched_at=datetime.utcnow(),
        )

    @classmethod
    async def get_monero_network_stats(cls) -> MoneroNetworkStats:
        """
        Fetch Monero network stats from a public API.
        Uses monero.observer-style endpoints if available.
        """
        base_url = os.getenv("MONERO_STATS_URL", "https://monero.observer/api/network")
        
        try:
            async with httpx.AsyncClient(timeout=cls._http_timeout) as client:
                resp = await client.get(base_url)
                resp.raise_for_status()
                data = resp.json() or {}
        except Exception as e:
            logger.warning("ApiRouter.get_monero_network_stats error: %s", e)
            return MoneroNetworkStats(
                height=None,
                hashrate=None,
                difficulty=None,
                block_reward=None,
                avg_block_time=None,
                source="monero_stats:error",
                fetched_at=datetime.utcnow(),
            )
        
        return MoneroNetworkStats(
            height=data.get("height"),
            hashrate=data.get("hashrate"),
            difficulty=data.get("difficulty"),
            block_reward=data.get("reward"),
            avg_block_time=data.get("avg_block_time"),
            source="monero_stats",
            fetched_at=datetime.utcnow(),
        )

    @classmethod
    async def get_stock_quote(cls, req: StockQuoteRequest) -> StockQuoteResult:
        """
        Fetch stock/ETF quote via Yahoo Finance (no API key required).
        """
        symbol = req.symbol.strip().upper()
        
        if not symbol:
            return StockQuoteResult(
                symbol=symbol,
                price=None,
                change_percent=None,
                previous_close=None,
                currency=None,
                source="yahoo_finance:invalid_symbol",
                fetched_at=datetime.utcnow(),
            )
        
        url = "https://query1.finance.yahoo.com/v7/finance/quote"
        params = {"symbols": symbol}
        
        try:
            async with httpx.AsyncClient(timeout=cls._http_timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json() or {}
        except Exception as e:
            logger.warning(f"Yahoo Finance request failed for {symbol}: {e}")
            return StockQuoteResult(
                symbol=symbol,
                price=None,
                change_percent=None,
                previous_close=None,
                currency=None,
                source="yahoo_finance:error",
                fetched_at=datetime.utcnow(),
            )
        
        try:
            quote_resp = data.get("quoteResponse", {})
            results = quote_resp.get("result", []) or []
            if not results:
                return StockQuoteResult(
                    symbol=symbol,
                    price=None,
                    change_percent=None,
                    previous_close=None,
                    currency=None,
                    source="yahoo_finance:no_results",
                    fetched_at=datetime.utcnow(),
                )
            
            q = results[0]
            
            # Core price/metadata
            price = q.get("regularMarketPrice")
            currency = q.get("currency")
            change = q.get("regularMarketChange")
            change_pct = q.get("regularMarketChangePercent")
            previous_close = q.get("regularMarketPreviousClose")
            
            # Dividend fields from Yahoo
            dividend_rate = q.get("dividendRate")
            dividend_yield = q.get("dividendYield")
            trailing_dividend_rate = q.get("trailingAnnualDividendRate")
            trailing_dividend_yield = q.get("trailingAnnualDividendYield")
            ex_dividend_date = q.get("exDividendDate")  # Unix seconds
            payout_ratio = q.get("payoutRatio")
            
            return StockQuoteResult(
                symbol=q.get("symbol", symbol),
                price=price,
                change_percent=change_pct,
                previous_close=previous_close,
                currency=currency,
                source="yahoo_finance",
                fetched_at=datetime.utcnow(),
                dividend_rate=dividend_rate,
                dividend_yield=dividend_yield,
                trailing_dividend_rate=trailing_dividend_rate,
                trailing_dividend_yield=trailing_dividend_yield,
                ex_dividend_date=ex_dividend_date,
                payout_ratio=payout_ratio,
            )
        except Exception as e:
            logger.warning(f"Error parsing Yahoo Finance response for {symbol}: {e}")
            return StockQuoteResult(
                symbol=symbol,
                price=None,
                change_percent=None,
                previous_close=None,
                currency=None,
                source="yahoo_finance:parse_error",
                fetched_at=datetime.utcnow(),
            )

    @classmethod
    async def geocode_location(cls, query: str) -> GeocodeResult:
        """
        Simple geocoder using Nominatim (OpenStreetMap).
        Used as a helper for weather lookups.
        """
        base_url = os.getenv("GEOCODE_BASE_URL", "https://nominatim.openstreetmap.org/search")
        
        try:
            async with httpx.AsyncClient(timeout=cls._http_timeout) as client:
                resp = await client.get(
                    base_url,
                    params={
                        "q": query,
                        "format": "json",
                        "limit": 1,
                    },
                    headers={"User-Agent": "ChatDO/ApiRouter"},
                )
                resp.raise_for_status()
                data = resp.json() or []
        except Exception as e:
            logger.warning("ApiRouter.geocode_location error: %s", e)
            return GeocodeResult(
                query=query,
                lat=None,
                lon=None,
                display_name=None,
                source="nominatim:error",
                fetched_at=datetime.utcnow(),
            )
        
        if not data:
            return GeocodeResult(
                query=query,
                lat=None,
                lon=None,
                display_name=None,
                source="nominatim:none",
                fetched_at=datetime.utcnow(),
            )
        
        first = data[0]
        try:
            lat = float(first.get("lat"))
            lon = float(first.get("lon"))
        except Exception:
            lat = None
            lon = None
        
        # Extract country_code from address
        address = first.get("address", {})
        country_code = address.get("country_code")
        if country_code:
            country_code = country_code.lower()
        
        return GeocodeResult(
            query=query,
            lat=lat,
            lon=lon,
            display_name=first.get("display_name"),
            source="nominatim",
            fetched_at=datetime.utcnow(),
            country_code=country_code,
        )

    @classmethod
    async def _get_weather_nws(
        cls,
        lat: float,
        lon: float,
        geocode: Optional[GeocodeResult] = None
    ) -> WeatherResult:
        """
        Fetch weather using U.S. National Weather Service (api.weather.gov).
        Uses the `points` endpoint to find the relevant forecast URLs and returns
        a WeatherResult populated from the first period (hourly if available,
        otherwise standard forecast).
        """
        # Build a reasonable User-Agent per NWS policy.
        user_agent = os.getenv(
            "NWS_USER_AGENT",
            "ChatDO/0.1 (contact: example@example.com)"
        )
        
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/geo+json, application/json;q=0.9"
        }
        
        try:
            async with httpx.AsyncClient(timeout=cls._http_timeout) as client:
                # 1) Get point metadata
                points_resp = await client.get(
                    f"https://api.weather.gov/points/{lat},{lon}",
                    headers=headers
                )
                points_resp.raise_for_status()
                points_data = points_resp.json()
                props = points_data.get("properties", {}) or {}
                
                # Relative location (city, state)
                rel = props.get("relativeLocation", {}) or {}
                rel_props = rel.get("properties", {}) or {}
                city = rel_props.get("city")
                state = rel_props.get("state")
                location_name = ", ".join(
                    part for part in [city, state] if part
                ) or (geocode.display_name if geocode else None)
                
                forecast_hourly_url = props.get("forecastHourly")
                forecast_url = props.get("forecast")
                
                period = None
                
                # 2) Prefer hourly forecast for "current-ish" conditions
                if forecast_hourly_url:
                    try:
                        hourly_resp = await client.get(
                            forecast_hourly_url,
                            headers=headers
                        )
                        hourly_resp.raise_for_status()
                        hourly_data = hourly_resp.json()
                        periods = (
                            hourly_data
                            .get("properties", {})
                            .get("periods", [])
                            or []
                        )
                        if periods:
                            period = periods[0]
                    except Exception:
                        # If hourly fails, silently fall back to regular forecast
                        period = None
                
                # 3) Fallback to standard forecast if needed
                if period is None and forecast_url:
                    forecast_resp = await client.get(
                        forecast_url,
                        headers=headers
                    )
                    forecast_resp.raise_for_status()
                    forecast_data = forecast_resp.json()
                    periods = (
                        forecast_data
                        .get("properties", {})
                        .get("periods", [])
                        or []
                    )
                    if periods:
                        period = periods[0]
                
                temperature_c = None
                temperature_f = None
                condition = None
                
                if period:
                    temp = period.get("temperature")
                    unit = period.get("temperatureUnit")
                    condition = period.get("shortForecast")
                    
                    if isinstance(temp, (int, float)):
                        if unit == "F":
                            temperature_f = float(temp)
                            temperature_c = (temperature_f - 32.0) * 5.0 / 9.0
                        elif unit == "C":
                            temperature_c = float(temp)
                            temperature_f = (temperature_c * 9.0 / 5.0) + 32.0
                
                location_display = location_name or (geocode.display_name if geocode else None)
                
                return WeatherResult(
                    location=location_display or "",
                    lat=lat,
                    lon=lon,
                    temperature_c=temperature_c,
                    condition=condition,
                    wind_speed_kph=None,  # NWS doesn't provide this in the basic forecast
                    humidity=None,
                    source="nws",
                    fetched_at=datetime.now(timezone.utc),
                    provider="nws",
                    location_name=location_name,
                    latitude=lat,
                    longitude=lon,
                    temperature_f=temperature_f,
                )
        
        except Exception as exc:
            logger.warning(f"NWS weather request failed: {exc}")
            # On any error, return a WeatherResult that signals failure.
            location_display = geocode.display_name if geocode else None
            return WeatherResult(
                location=location_display or "",
                lat=lat,
                lon=lon,
                temperature_c=None,
                temperature_f=None,
                condition=None,
                wind_speed_kph=None,
                humidity=None,
                source="nws:error",
                fetched_at=datetime.now(timezone.utc),
                provider="nws",
                location_name=location_display,
                latitude=lat,
                longitude=lon,
            )

    @classmethod
    async def _get_weather_open_meteo(
        cls,
        lat: float,
        lon: float,
        geocode: Optional[GeocodeResult] = None
    ) -> WeatherResult:
        """
        Existing global weather implementation using Open-Meteo.
        """
        base_url = os.getenv("OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1/forecast")
        
        try:
            async with httpx.AsyncClient(timeout=cls._http_timeout) as client:
                resp = await client.get(
                    base_url,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current_weather": "true",
                        "hourly": "relativehumidity_2m",
                    },
                )
                resp.raise_for_status()
                data = resp.json() or {}
        except Exception as e:
            logger.warning("ApiRouter._get_weather_open_meteo error: %s", e)
            location_display = geocode.display_name if geocode else None
            return WeatherResult(
                location=location_display or "",
                lat=lat,
                lon=lon,
                temperature_c=None,
                condition=None,
                wind_speed_kph=None,
                humidity=None,
                source="open_meteo:error",
                fetched_at=datetime.now(timezone.utc),
                provider="open-meteo",
                location_name=location_display,
                latitude=lat,
                longitude=lon,
                temperature_f=None,
            )
        
        current = data.get("current_weather") or {}
        temp = current.get("temperature")
        wind = current.get("windspeed")
        # We won't over-complicate humidity; set None for now or try hourly array.
        humidity = None
        
        # Convert Celsius to Fahrenheit if we have a temperature
        temperature_f = None
        if temp is not None:
            try:
                temp_c = float(temp)
                temperature_f = (temp_c * 9.0 / 5.0) + 32.0
            except Exception:
                pass
        
        location_display = geocode.display_name if geocode else None
        condition = str(current.get("weathercode")) if current.get("weathercode") is not None else None
        
        return WeatherResult(
            location=location_display or "",
            lat=lat,
            lon=lon,
            temperature_c=temp,
            condition=condition,
            wind_speed_kph=wind,
            humidity=humidity,
            source="open_meteo",
            fetched_at=datetime.now(timezone.utc),
            provider="open-meteo",
            location_name=location_display,
            latitude=lat,
            longitude=lon,
            temperature_f=temperature_f,
        )

    @classmethod
    async def get_weather(cls, req: WeatherRequest) -> WeatherResult:
        """
        Unified weather entrypoint:
        - Geocodes location (if needed)
        - Detects whether it's a US location
        - Uses NWS for US, Open-Meteo for global
        - Falls back to Open-Meteo if NWS fails
        """
        # 1) Determine lat/lon + geocode info
        geocode: Optional[GeocodeResult] = None
        
        if req.location:
            geocode = await cls.geocode_location(req.location)
            if geocode:
                lat = geocode.lat
                lon = geocode.lon
            else:
                lat = None
                lon = None
        else:
            lat = None
            lon = None
        
        if lat is None or lon is None:
            # If we still don't have coordinates, return a best-effort empty result
            return WeatherResult(
                location=req.location or "",
                lat=None,
                lon=None,
                temperature_c=None,
                condition=None,
                wind_speed_kph=None,
                humidity=None,
                source="weather:no_geocode",
                fetched_at=datetime.now(timezone.utc),
                provider=None,
                location_name=req.location,
                latitude=None,
                longitude=None,
                temperature_f=None,
            )
        
        is_us = _is_us_location(geocode)
        
        # 2) US → NWS primary, with Open-Meteo fallback
        if is_us:
            nws_result = await cls._get_weather_nws(lat, lon, geocode)
            
            # Detect whether NWS result is usable
            has_temp = (
                nws_result.temperature_c is not None
                or nws_result.temperature_f is not None
            )
            if has_temp:
                return nws_result
            
            # Fallback to global provider if NWS failed
            open_meteo_result = await cls._get_weather_open_meteo(lat, lon, geocode)
            return open_meteo_result
        
        # 3) Non-US → Open-Meteo
        return await cls._get_weather_open_meteo(lat, lon, geocode)

