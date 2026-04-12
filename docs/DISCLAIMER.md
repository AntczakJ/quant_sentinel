# Legal Disclaimer & Terms of Use

**READ BEFORE USING THIS SOFTWARE. USE AT YOUR OWN RISK.**

## Nature of the Software

Quant Sentinel is an **experimental personal research tool** for algorithmic
trading of XAU/USD (gold). It is NOT a licensed financial product, broker,
investment adviser, or regulated service.

## No Financial Advice

Nothing produced by this software constitutes financial, investment,
trading, tax, or legal advice. All signals, predictions, and analytics
are experimental outputs of machine learning models and technical
indicators — they may be wrong, lagging, or generated from corrupted
data.

**You are solely responsible for any trading decisions you make.**

## Trading Risk Warning

- Trading leveraged instruments (CFDs, futures, spot gold with margin)
  can result in losses exceeding your deposit.
- Past performance (including backtest results) does NOT guarantee
  future results. Historical data, backtests, and Monte Carlo
  simulations are informational only.
- This system was developed on yfinance/Twelve Data historical data
  which has known gaps, revisions, and may differ from actual broker
  execution prices. Live slippage, spread, swap, and commission may
  substantially exceed backtested estimates.
- Model predictions degrade over time ("model drift"). What worked
  in backtest may not work tomorrow.
- The author(s) make no claim that the software is profitable.

## No Warranty

The software is provided "AS IS", without warranty of any kind, express
or implied, including but not limited to:

- Merchantability
- Fitness for a particular purpose
- Non-infringement
- Absence of bugs or vulnerabilities
- Uptime or availability
- Accuracy of data, predictions, or calculations

## Limitation of Liability

In no event shall the author(s) or contributor(s) be liable for any:

- Direct, indirect, incidental, special, or consequential damages
- Loss of profits, revenue, data, goodwill, or business opportunity
- Trading losses, margin calls, or broker disputes
- Damages arising from third-party API failures (Twelve Data, Finnhub,
  Telegram, OpenAI, yfinance, etc.)
- Damages arising from software bugs, including but not limited to
  the critical bugs documented in CHANGELOG.md (scanner cache stale
  data, double-gate relaxation leaks, wall-clock timestamp, etc.)

## Third-Party Services

The software integrates with third-party APIs under separate terms:

- **Twelve Data** — market data (https://twelvedata.com/terms)
- **Finnhub** — news sentiment (https://finnhub.io/terms-of-service)
- **OpenAI** — AI agent (https://openai.com/policies/terms-of-use)
- **Telegram Bot API** — notifications (https://core.telegram.org/api/terms)
- **Yahoo Finance (yfinance)** — historical data (for personal use only)
- **FRED** — macro data (https://fred.stlouisfed.org/legal/)
- **Myfxbook** — retail sentiment (optional)

Users are responsible for complying with these third-party terms.

## Personal Use Only

This software is intended for personal research and learning. It is NOT
licensed for:

- Sale, resale, or redistribution as a service (SaaS)
- Use by unlicensed financial professionals offering services to clients
- Deployment in regulated environments without appropriate authorisation

If you are a professional trader, hedge fund, or investment adviser,
consult regulated vendors (Bloomberg, Refinitiv, QuantConnect, etc.)
and your compliance officer.

## Kill Switch Reminder

If you deploy this software live:

1. Fund only risk capital you can afford to lose entirely.
2. Start with smallest position sizes your broker allows.
3. Monitor the first weeks of live trading constantly (Telegram alerts
   from health_monitor should be reviewed daily).
4. Use the manual halt: `rm.halt("precautionary")` from Python REPL
   if anything looks wrong.
5. Stop-loss is a TARGET not a GUARANTEE — gaps, slippage, and broker
   liquidity may cause fills far worse than SL level.

## Jurisdictional Notice

Some jurisdictions may regulate or prohibit:

- Algorithmic trading without disclosure
- Retail use of leveraged derivatives
- Use of automated systems for financial trading

Ensure you comply with your local law. Consult a licensed attorney and
financial advisor before deploying live.

## No Guarantee of Maintenance

This project is maintained at the author's discretion. Security patches,
bug fixes, and feature updates are not guaranteed. The project may be
abandoned or archived without notice.

---

**By using Quant Sentinel, you acknowledge that you have read, understood,
and accepted these terms. If you do not accept these terms, do not use
the software.**

Last updated: 2026-04-12
