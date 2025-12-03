import React from 'react';

type WeatherData = {
  kind: 'api_weather_current';
  location: string;
  temperature_c?: number | null;
  temperature_f?: number | null;
  condition?: string | null;
  provider?: string;
  lat?: number | null;
  lon?: number | null;
};

type CryptoData = {
  kind: 'api_crypto_price';
  symbol: string;
  vs_currency: string;
  price?: number | null;
  change_24h?: number | null;
};

type StockData = {
  kind: 'api_stock_price';
  symbol: string;
  price?: number | null;
  change_percent?: number | null;
  previous_close?: number | null;
  currency?: string | null;
  dividend_rate?: number | null;
  dividend_yield?: number | null;
  trailing_dividend_rate?: number | null;
  trailing_dividend_yield?: number | null;
  ex_dividend_date?: number | null;
  payout_ratio?: number | null;
};

type APICardProps =
  | { kind: 'api_weather_current'; data: WeatherData }
  | { kind: 'api_crypto_price'; data: CryptoData }
  | { kind: 'api_stock_price'; data: StockData };

const APICard: React.FC<APICardProps> = ({ kind, data }) => {
  if (kind === 'api_weather_current') {
    const weatherData = data as WeatherData;
    const temp = weatherData.temperature_f ?? weatherData.temperature_c;
    const tempUnit = weatherData.temperature_f !== null && weatherData.temperature_f !== undefined ? '°F' : '°C';
    const providerName = weatherData.provider === 'nws' ? 'NWS' : weatherData.provider === 'open-meteo' ? 'Open-Meteo' : weatherData.provider || 'Weather';
    
    return (
      <div className="rounded-lg bg-[var(--card-bg)] border border-[var(--border)] p-4 my-2">
        <div className="flex flex-col gap-2">
          <div className="font-semibold text-[var(--text-primary)]">{weatherData.location}</div>
          {temp !== null && temp !== undefined && (
            <div className="text-2xl font-bold text-[var(--text-primary)]">
              {Math.round(temp)}{tempUnit}
            </div>
          )}
          {weatherData.condition && (
            <div className="text-sm text-[var(--text-secondary)]">{weatherData.condition}</div>
          )}
          <div className="text-xs text-[var(--text-tertiary)] mt-1">Source: {providerName}</div>
        </div>
      </div>
    );
  }
  
  if (kind === 'api_crypto_price') {
    const cryptoData = data as CryptoData;
    const price = cryptoData.price;
    const change24h = cryptoData.change_24h;
    const changeColor = change24h && change24h >= 0 ? 'text-green-500' : 'text-red-500';
    
    return (
      <div className="rounded-lg bg-[var(--card-bg)] border border-[var(--border)] p-4 my-2">
        <div className="flex flex-col gap-2">
          <div className="font-semibold text-[var(--text-primary)]">{cryptoData.symbol.toUpperCase()}</div>
          {price !== null && price !== undefined && (
            <div className="text-2xl font-bold text-[var(--text-primary)]">
              ${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          )}
          {change24h !== null && change24h !== undefined && (
            <div className={`text-sm ${changeColor}`}>
              {change24h >= 0 ? '+' : ''}{change24h.toFixed(2)}% (24h)
            </div>
          )}
          <div className="text-xs text-[var(--text-tertiary)] mt-1">Source: CoinGecko</div>
        </div>
      </div>
    );
  }
  
  if (kind === 'api_stock_price') {
    const stockData = data as StockData;
    const price = stockData.price;
    const changePercent = stockData.change_percent;
    const changeColor = changePercent && changePercent >= 0 ? 'text-green-500' : 'text-red-500';
    const dividendYield = stockData.dividend_yield ?? stockData.trailing_dividend_yield;
    
    return (
      <div className="rounded-lg bg-[var(--card-bg)] border border-[var(--border)] p-4 my-2">
        <div className="flex flex-col gap-2">
          <div className="font-semibold text-[var(--text-primary)]">{stockData.symbol}</div>
          {price !== null && price !== undefined && (
            <div className="text-2xl font-bold text-[var(--text-primary)]">
              ${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              {stockData.currency && stockData.currency !== 'USD' && ` ${stockData.currency}`}
            </div>
          )}
          {changePercent !== null && changePercent !== undefined && (
            <div className={`text-sm ${changeColor}`}>
              {changePercent >= 0 ? '+' : ''}{changePercent.toFixed(2)}%
            </div>
          )}
          {dividendYield !== null && dividendYield !== undefined && (
            <div className="text-sm text-[var(--text-secondary)]">
              Dividend Yield: {(dividendYield * 100).toFixed(2)}%
            </div>
          )}
          {stockData.dividend_rate !== null && stockData.dividend_rate !== undefined && (
            <div className="text-xs text-[var(--text-tertiary)]">
              Annual Dividend: ${stockData.dividend_rate.toFixed(2)}
            </div>
          )}
          <div className="text-xs text-[var(--text-tertiary)] mt-1">Source: Yahoo Finance</div>
        </div>
      </div>
    );
  }
  
  return null;
};

export default APICard;

