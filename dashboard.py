import logging
import os
import re
import urllib.request
from datetime import datetime, timedelta
import json
from pathlib import Path

from flask import Flask, Response, redirect, render_template_string, request, url_for

from alpaca_stock_bot import (
    AlpacaStockBot,
    StrategyConfig,
    NY_TZ,
    load_state,
    normalize_ticker,
    read_trade_levels,
    read_watchlist,
    save_state,
    save_trade_levels,
    save_watchlist,
)


app = Flask(__name__)


@app.before_request
def require_dashboard_password():
    password = os.getenv("DASHBOARD_PASSWORD", "").strip()
    if not password:
        return None

    expected_user = os.getenv("DASHBOARD_USER", "admin").strip() or "admin"
    auth = request.authorization
    if auth and auth.username == expected_user and auth.password == password:
        return None

    return Response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="Trading Console"'},
    )


CONFIG = StrategyConfig()
SCHD_DEFAULT_YIELD_PCT = 3.31
SCHD_YIELD_CACHE_PATH = Path("schd_yield_cache.json")
SCHD_YIELD_CACHE_DAYS = 7
SCHD_YIELD_SOURCE_URL = "https://stockanalysis.com/etf/schd/dividend/"
SPACEX_INFO = {
    "summary": "SpaceX is a private aerospace, launch, Starlink satellite internet, and Starship company led by Elon Musk. You usually cannot buy SpaceX directly in a normal brokerage unless it has a public listing or your broker offers a private-market product.",
    "market_links": "Closest public-market links: TSLA sentiment, defense/aerospace names, satellite/space ETFs, and risk appetite in QQQ/SPY. Treat direct SpaceX claims as watchlist research unless your broker shows a real listed ticker.",
}


PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>Trading Console</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      background: #f4f5f7;
      color: #17212f;
      --ink: #17212f;
      --muted: #657384;
      --line: #d9e1ea;
      --panel: #ffffff;
      --brand: #2f5d62;
      --brand-dark: #1f2933;
      --good: #087443;
      --bad: #b42318;
      --warn-bg: #fff8e6;
    }

    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; }

    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 14px 20px;
      background: #ffffff;
      color: var(--ink);
      border-bottom: 1px solid var(--line);
    }

    main {
      padding: 18px;
      max-width: 1160px;
      margin: 0 auto;
    }

    h1 {
      font-size: 18px;
      line-height: 1.1;
      margin: 0;
      letter-spacing: 0;
    }

    h2 {
      font-size: 14px;
      line-height: 1.2;
      margin: 0 0 12px;
      letter-spacing: 0;
    }

    .topline {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 13px;
      margin-top: 5px;
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: {{ '#1fbf75' if clock_open else '#ff6b5f' }};
      display: inline-block;
      flex: 0 0 auto;
    }

    .metric-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }

    .content-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.6fr) minmax(280px, .9fr);
      gap: 14px;
      align-items: start;
    }

    .stack {
      display: grid;
      gap: 14px;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px;
      box-shadow: none;
    }

    .metric-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .04em;
      text-transform: uppercase;
    }

    .metric {
      font-size: 24px;
      font-weight: 700;
      margin: 7px 0 3px;
      letter-spacing: 0;
    }

    .subtle {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }

    .plan-box {
      display: grid;
      gap: 6px;
      margin: 10px 0;
      padding: 10px 12px;
      border: 1px solid #dbe6f2;
      border-radius: 6px;
      background: #f8fbff;
      color: #2d4056;
      font-size: 13px;
      line-height: 1.4;
    }

    .row-title {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 8px;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 4px 9px;
      border-radius: 999px;
      background: #edf3fb;
      color: #2d4f77;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }

    th, td {
      text-align: left;
      border-bottom: 1px solid #e8edf3;
      padding: 10px 8px;
    }

    th {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .05em;
    }

    td.numeric, th.numeric { text-align: right; }

    button {
      border: 0;
      border-radius: 5px;
      background: var(--brand);
      color: white;
      padding: 10px 15px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }

    button:hover { background: #24494d; }
    .header-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .secondary-button {
      background: #eef3f8;
      color: #263445;
      border: 1px solid #dce5ee;
      padding: 6px 8px;
      font-size: 12px;
    }
    .secondary-button:hover { background: #dfe8f1; }
    .danger-button {
      background: #9f2d20;
      color: white;
    }
    .danger-button:hover { background: #8f1c13; }
    .ok { color: var(--good); }
    .bad { color: var(--bad); }

    .notice {
      margin-bottom: 16px;
      padding: 12px 14px;
      border-radius: 8px;
      background: var(--warn-bg);
      border: 1px solid #ead28a;
      color: #4d3b00;
    }

    pre {
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      font-size: 12px;
      line-height: 1.45;
      color: #263445;
      background: #f7f9fb;
      border: 1px solid #e5ebf1;
      border-radius: 7px;
      padding: 11px;
      max-height: 260px;
      overflow: auto;
    }

    .universe {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
    }

    .ticker {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      border: 1px solid #dce5ee;
      border-radius: 6px;
      padding: 4px 5px 4px 8px;
      background: #f8fafc;
      font-size: 12px;
      font-weight: 700;
      color: #263445;
    }

    .ticker form { margin: 0; }
    .inline-form {
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }
    input {
      min-width: 0;
      flex: 1;
      border: 1px solid #d5dee8;
      border-radius: 7px;
      padding: 9px 10px;
      font: inherit;
    }
    .mini-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 10px;
    }
    .input-label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .result-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }
    .result-box {
      border: 1px solid #e5ebf1;
      border-radius: 7px;
      padding: 10px;
      background: #f8fafc;
    }
    .result-box strong {
      display: block;
      font-size: 16px;
      margin-top: 4px;
    }

    .reason-list {
      margin: 0;
      padding-left: 17px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .decision-box {
      border: 1px solid #e5ebf1;
      border-radius: 7px;
      background: #f8fafc;
      padding: 10px;
      margin-bottom: 12px;
    }
    .decision-box .reason-list {
      margin-top: 8px;
      margin-bottom: 8px;
    }

    .status-pass { color: var(--good); font-weight: 700; }
    .status-blocked { color: var(--bad); font-weight: 700; }
    summary {
      cursor: pointer;
      color: var(--ink);
      font-size: 14px;
      font-weight: 700;
      list-style: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    summary::-webkit-details-marker { display: none; }
    summary::before {
      content: "+";
      display: inline-grid;
      place-items: center;
      width: 22px;
      height: 22px;
      border-radius: 999px;
      background: #eef3f8;
      color: #2d4f77;
      margin-right: 8px;
      flex: 0 0 auto;
    }
    details[open] > summary::before { content: "-"; }
    .compact-section { padding: 12px 15px; }
    .compact-section > summary { margin: 0; }
    .compact-section[open] > summary { margin-bottom: 10px; }
    .nested-details {
      margin-top: 12px;
      border-top: 1px solid #e8edf3;
      padding-top: 12px;
    }
    .nested-details summary {
      color: var(--muted);
      font-size: 13px;
      justify-content: flex-start;
    }

    @media (max-width: 860px) {
      header {
        align-items: flex-start;
        flex-direction: column;
      }

      .metric-grid,
      .content-grid,
      .mini-grid,
      .result-grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Trading Console</h1>
      <div class="topline">
        <span class="dot"></span>
        <span>{{ market_status }}</span>
        <span>Auto refresh every 30 seconds</span>
      </div>
    </div>
    <div class="header-actions">
      <form method="post" action="{{ pause_url }}">
        <input type="hidden" name="paused" value="{{ 'false' if controls.trading_paused else 'true' }}">
        <button class="{{ 'secondary-button' if controls.trading_paused else 'danger-button' }}" type="submit">
          {{ "Resume Trading" if controls.trading_paused else "Pause Trading" }}
        </button>
      </form>
      <form method="post" action="{{ run_url }}">
        <button type="submit">Run One Scan</button>
      </form>
    </div>
  </header>

  <main>
    {% if message %}
      <div class="notice">{{ message }}</div>
    {% endif %}

    <section class="metric-grid">
      <div class="panel">
        <div class="metric-label">Market</div>
        <div class="metric {{ 'ok' if clock_open else 'bad' }}">{{ market_status }}</div>
        <div class="subtle">Next open {{ next_open }}</div>
      </div>
      <div class="panel">
        <div class="metric-label">Equity</div>
        <div class="metric">${{ account.portfolio_value }}</div>
        <div class="subtle">Cash ${{ account.cash }}</div>
      </div>
      <div class="panel">
        <div class="metric-label">Bot Buying Power</div>
        <div class="metric">${{ remaining_bot_budget }}</div>
        <div class="subtle">${{ current_bot_exposure }} used of ${{ paper_equity_cap }} cap</div>
      </div>
      <div class="panel">
        <div class="metric-label">Tracked</div>
        <div class="metric">{{ state_positions_count }}/{{ max_positions }}</div>
        <div class="subtle">Open bot positions</div>
      </div>
      <div class="panel">
        <div class="metric-label">Account Buying Power</div>
        <div class="metric">${{ account.buying_power }}</div>
        <div class="subtle">Paper account total</div>
      </div>
      <div class="panel">
        <div class="metric-label">Daily P/L Guard</div>
        <div class="metric {{ 'bad' if daily_risk.blocked else 'ok' }}">${{ daily_risk.pnl }}</div>
        <div class="subtle">Account equity change. Stops new entries at -${{ daily_risk.limit }}</div>
      </div>
      <div class="panel">
        <div class="metric-label">Open Bot P/L</div>
        <div class="metric {{ 'bad' if open_bot_pnl_float < 0 else 'ok' }}">${{ open_bot_pnl }}</div>
        <div class="subtle">Unrealized from visible bot positions</div>
      </div>
      <div class="panel">
        <div class="metric-label">Closed Bot P/L</div>
        <div class="metric {{ 'bad' if closed_bot_pnl_float < 0 else 'ok' }}">${{ closed_bot_pnl }}</div>
        <div class="subtle">{{ closed_trade_count }} closed trade(s) recorded</div>
      </div>
      <div class="panel">
        <div class="metric-label">Control</div>
        <div class="metric {{ 'bad' if controls.trading_paused else 'ok' }}">{{ "Paused" if controls.trading_paused else "Active" }}</div>
        <div class="subtle">{{ "Options-only entries" if options_only else "Stocks and options" }}</div>
      </div>
    </section>

    <section class="content-grid">
      <div class="stack">
        <div class="panel">
          <div class="row-title">
            <h2>Risk Checks</h2>
            <span class="pill">{{ safety.status }}</span>
          </div>
          <table>
            <tbody>
              <tr>
                <th>Last Check</th>
                <td>{{ safety.checked_at or "not checked" }}</td>
              </tr>
              <tr>
                <th>Open Orders</th>
                <td>{{ safety.open_order_count }}</td>
              </tr>
              <tr>
                <th>Unmanaged Positions</th>
                <td>{{ safety.unmanaged_symbols_text }}</td>
              </tr>
              <tr>
                <th>Market Regime</th>
                <td class="{{ 'ok' if last_scan.market.is_clear else 'bad' }}">
                  {{ "Clear" if last_scan.market.is_clear else "Blocked" }}
                </td>
              </tr>
              <tr>
                <th>Market Score</th>
                <td>{{ last_scan.market.score }}/{{ last_scan.market.required }}</td>
              </tr>
              <tr>
                <th>News Check</th>
                <td>
                  {{ news_status }} <span class="subtle">{{ news_detail }}</span>
                  {% if news_sources_text %}
                    <div class="subtle">{{ news_sources_text }}</div>
                  {% endif %}
                </td>
              </tr>
              <tr>
                <th>News Risk</th>
                <td class="{{ 'bad' if macro_news.status == 'blocked' else 'ok' }}">
                  {{ news_risk_label }}
                  <div class="subtle">Big market-moving news check, like war, attacks, sanctions, tariffs, or crash risk.</div>
                </td>
              </tr>
              <tr>
                <th>Daily Guard</th>
                <td class="{{ 'bad' if daily_risk.blocked else 'ok' }}">{{ daily_risk.status }}</td>
              </tr>
              <tr>
                <th>Risk Buckets</th>
                <td>{{ bucket_counts_text }}</td>
              </tr>
            </tbody>
          </table>
          {% if market_reasons %}
            <ul class="reason-list">
              {% for reason in market_reasons %}
                <li>{{ reason }}</li>
              {% endfor %}
            </ul>
          {% endif %}
          {% if macro_news.reasons %}
            <ul class="reason-list">
              {% for reason in macro_news.reasons %}
                <li>{{ reason }}</li>
              {% endfor %}
            </ul>
          {% endif %}
        </div>

        <div class="panel">
          <div class="row-title">
            <h2>Open Orders</h2>
            <span class="pill">{{ open_orders|length }} pending</span>
          </div>
          <form method="post" action="{{ cancel_orders_url }}" style="margin-bottom: 10px;">
            <button class="secondary-button" type="submit">Cancel Bot Open Orders</button>
          </form>
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Asset</th>
                <th>Action</th>
                <th class="numeric">Quantity</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {% for order in open_orders %}
                <tr>
                  <td><strong>{{ order.symbol }}</strong><div class="subtle">{{ order.id }}</div></td>
                  <td>{{ order.asset_type }}</td>
                  <td>{{ order.action_label }}</td>
                  <td class="numeric">{{ order.qty_label }}</td>
                  <td>{{ order.status_label }}</td>
                </tr>
              {% else %}
                <tr><td colspan="5" class="subtle">No pending bot-related orders.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>

        <details class="panel compact-section">
          <summary>
            <span>Learning</span>
            <span class="pill">{{ learning.updated_at or "not trained" }}</span>
          </summary>
          <table>
            <tbody>
              <tr>
                <th>Closed Trades</th>
                <td>{{ learning.closed_trade_count }}</td>
              </tr>
              <tr>
                <th>Opened Trades</th>
                <td>{{ learning.opened_trade_count }}</td>
              </tr>
              <tr>
                <th>Risk Multiplier</th>
                <td>{{ learning.risk_multiplier }}</td>
              </tr>
              <tr>
                <th>Win Rate</th>
                <td>{{ learning.win_rate }}</td>
              </tr>
              <tr>
                <th>Profit Factor</th>
                <td>{{ learning.profit_factor }}</td>
              </tr>
              <tr>
                <th>Downside Score</th>
                <td>{{ learning.downside_adjusted_return }}</td>
              </tr>
              <tr>
                <th>Score Adjustments</th>
                <td>{{ learning.adjustment_count }}</td>
              </tr>
            </tbody>
          </table>
          {% if learning_adjustments %}
            <ul class="reason-list">
              {% for item in learning_adjustments %}
                <li>{{ item }}</li>
              {% endfor %}
            </ul>
          {% else %}
            <div class="subtle">Needs closed trades before it can adapt.</div>
          {% endif %}
        </details>

        <div class="panel">
          <div class="row-title">
            <h2>Open Positions</h2>
            <span class="pill">{{ positions|length }} live</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th class="numeric">Quantity</th>
                <th class="numeric">Avg Entry</th>
                <th class="numeric">Market Value</th>
                <th class="numeric">Unrealized P/L</th>
                <th>Exit Plan</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {% for p in positions %}
                <tr>
                  <td><strong>{{ p.display_symbol }}</strong><div class="subtle">{{ p.symbol_detail or p.asset_type }}</div></td>
                  <td class="numeric">{{ p.qty_label }}</td>
                  <td class="numeric">${{ p.avg_entry_price }}</td>
                  <td class="numeric">${{ p.market_value }}</td>
                  <td class="numeric {{ 'ok' if p.unrealized_pl_float >= 0 else 'bad' }}">${{ p.unrealized_pl }}</td>
                  <td class="subtle">{{ p.exit_plan }}</td>
                  <td>
                    <form method="post" action="{{ trim_position_url }}" style="display:inline;">
                      <input type="hidden" name="symbol" value="{{ p.symbol }}">
                      <button class="secondary-button" type="submit">Trim</button>
                    </form>
                    <form method="post" action="{{ close_position_url }}" style="display:inline;">
                      <input type="hidden" name="symbol" value="{{ p.symbol }}">
                      <button class="danger-button" type="submit">Close</button>
                    </form>
                  </td>
                </tr>
              {% else %}
                <tr><td colspan="7" class="subtle">No open broker positions.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>

        <details class="panel compact-section">
          <summary>
            <span>Recent Closed Trades</span>
            <span class="pill">{{ closed_trades|length }} shown</span>
          </summary>
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Type</th>
                <th class="numeric">P/L</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {% for trade in closed_trades %}
                <tr>
                  <td>
                    <strong>{{ trade.ticker }}</strong>
                    <div class="subtle">{{ trade.closed_at }}</div>
                    {% if trade.loss_diagnosis %}
                      <div class="subtle">Diagnosis: {{ trade.loss_diagnosis }}</div>
                    {% endif %}
                  </td>
                  <td>{{ trade.asset_type }} {{ trade.direction }}</td>
                  <td class="numeric {{ 'ok' if trade.pnl_float >= 0 else 'bad' }}">${{ trade.pnl }}</td>
                  <td>
                    {{ trade.reason }}
                    {% if trade.entry_model_price %}
                      <div class="subtle">Model ${{ trade.entry_model_price }} | IV proxy {{ trade.entry_realized_vol }}</div>
                    {% endif %}
                    {% if trade.greeks_text %}
                      <div class="subtle">{{ trade.greeks_text }}</div>
                    {% endif %}
                  </td>
                </tr>
              {% else %}
                <tr><td colspan="4" class="subtle">No closed trades recorded yet.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </details>

        <details class="panel compact-section">
          <summary>
            <span>Option Signal</span>
            <span class="pill">{{ option_best }}</span>
          </summary>
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Side</th>
                <th class="numeric">Score</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {% for ticker, result in option_candidate_rows %}
                <tr>
                  <td><strong>{{ ticker }}</strong><div class="subtle">{{ result.reason_text }}</div></td>
                  <td>{{ result.direction or "-" }}</td>
                  <td class="numeric">{{ result.score }}</td>
                  <td class="status-{{ result.status }}">{{ result.status }}</td>
                </tr>
              {% else %}
                <tr><td colspan="4" class="subtle">Run one scan to populate option results.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </details>

        <details class="panel compact-section">
          <summary>
            <span>Trade Universe</span>
            <span class="pill">{{ ticker_count }} tickers</span>
          </summary>
          <div class="universe">
            {% for ticker in tickers %}
              <span class="ticker">
                {{ ticker }}
                <form method="post" action="{{ remove_ticker_url }}">
                  <input type="hidden" name="ticker" value="{{ ticker }}">
                  <button class="secondary-button" type="submit">x</button>
                </form>
              </span>
            {% endfor %}
          </div>
          <form class="inline-form" method="post" action="{{ add_ticker_url }}">
            <input name="ticker" placeholder="Add ticker, e.g. TSLA" maxlength="12" autocomplete="off">
            <button type="submit">Add</button>
          </form>
        </details>

        <details class="panel compact-section">
          <summary>
            <span>Chart + GEX Levels</span>
            <span class="pill">{{ levels_count }} symbols</span>
          </summary>
          <p class="subtle">Used as confirmation with chart score and news, not by itself. {{ gex_status_text }}</p>
          <form method="post" action="{{ update_levels_url }}">
            <div class="mini-grid">
              <label class="input-label">
                Symbol
                <input name="symbol" value="SPY" maxlength="12" autocomplete="off">
              </label>
              <label class="input-label">
                Support / retest
                <input name="support" placeholder="733, 737.05, 743">
              </label>
              <label class="input-label">
                Resistance / targets
                <input name="resistance" placeholder="749, 754.62">
              </label>
              <label class="input-label">
                Confirmations
                <input name="confirmation" placeholder="743, 747, 749">
              </label>
              <label class="input-label">
                Failure
                <input name="failure" placeholder="733">
              </label>
              <label class="input-label">
                GEX levels
                <input name="gex" placeholder="733, 743, 747, 749">
              </label>
              <label class="input-label">
                Tolerance
                <input name="tolerance" type="number" min="0" step="0.05" value="1.25">
              </label>
              <div style="display:flex; align-items:end;">
                <button type="submit">Save Levels</button>
              </div>
            </div>
          </form>
          {% if levels_summary %}
            <ul class="reason-list">
              {% for line in levels_summary %}
                <li>{{ line }}</li>
              {% endfor %}
            </ul>
          {% endif %}
        </details>
      </div>

        <details class="panel compact-section">
          <summary>
            <span>Scanner Results</span>
            <span class="pill">best: {{ last_scan.best or "none" }}</span>
          </summary>
        {% if last_entry_decision.reasons %}
          <div class="decision-box">
            <strong>Last entry decision: {{ last_entry_decision.status }}</strong>
            <div class="subtle">{{ last_entry_decision.time }}</div>
            <ul class="reason-list">
              {% for reason in last_entry_decision.reasons %}
                <li>{{ reason }}</li>
              {% endfor %}
            </ul>
            {% if last_entry_decision.details_text %}
              <div class="subtle">{{ last_entry_decision.details_text }}</div>
            {% endif %}
          </div>
        {% endif %}
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th class="numeric">Score</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {% for ticker, result in candidate_rows %}
              <tr>
                <td><strong>{{ ticker }}</strong><div class="subtle">{{ result.reason_text }}</div></td>
                <td class="numeric">{{ result.score }}</td>
                <td class="status-{{ result.status }}">{{ result.status }}</td>
              </tr>
            {% else %}
              <tr><td colspan="3" class="subtle">Run one scan to populate candidate results.</td></tr>
            {% endfor %}
          </tbody>
        </table>
        <details class="nested-details">
          <summary>Raw local state</summary>
          <div class="subtle" style="margin: 8px 0;">{{ state_path }}</div>
          <pre>{{ state_json }}</pre>
          </details>
        </details>

      <div class="panel">
        <div class="row-title">
          <h2>Swing Research</h2>
          <span class="pill">{{ swing_plan.status }}</span>
        </div>
        <div class="metric">
          {% if swing_plan.ticker %}
            {{ swing_plan.ticker }} {{ swing_plan.direction }}
          {% else %}
            No setup
          {% endif %}
        </div>
        <div class="subtle">
          Score {{ swing_plan.score }}{% if swing_plan.price %} near ${{ swing_plan.price }}{% endif %}.
          Built for after-hours/weekend planning, not automatic overnight order entry.
        </div>
        {% if swing_plan.hold_plan or swing_plan.entry_plan or swing_plan.exit_plan %}
          <div class="plan-box">
            {% if swing_plan.hold_plan %}<div>{{ swing_plan.hold_plan }}</div>{% endif %}
            {% if swing_plan.entry_plan %}<div>{{ swing_plan.entry_plan }}</div>{% endif %}
            {% if swing_plan.exit_plan %}<div>{{ swing_plan.exit_plan }}</div>{% endif %}
          </div>
        {% endif %}
        {% if swing_plan.reasons %}
          <ul class="reason-list">
            {% for reason in swing_plan.reasons %}
              <li>{{ reason }}</li>
            {% endfor %}
          </ul>
        {% endif %}
        {% if swing_plan.catalysts %}
          <table>
            <thead>
              <tr>
                <th>Catalyst</th>
                <th>Direction</th>
              </tr>
            </thead>
            <tbody>
              {% for catalyst in swing_plan.catalysts %}
                <tr>
                  <td>
                    <strong>{{ catalyst.type }}</strong>
                    <div class="subtle">{{ catalyst.headline or catalyst.summary }}</div>
                  </td>
                  <td>{{ catalyst.direction }}</td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        {% endif %}
        <div class="subtle" style="margin-top:10px;">Updated {{ swing_plan.updated_at }} from closed-market ticker research.</div>
      </div>

      <details class="panel compact-section">
        <summary>
          <span>SpaceX Watch</span>
          <span class="pill">private / catalyst</span>
        </summary>
        <p class="subtle">{{ spacex.summary }}</p>
        <p class="subtle">{{ spacex.market_links }}</p>
      </details>

      <div class="panel">
        <div class="row-title">
          <h2>SCHD Dividend Calculator</h2>
          <span class="pill">estimate</span>
        </div>
        <form method="get" action="{{ index_url }}">
          <div class="mini-grid">
            <label class="input-label">
              Dollars per day
              <input name="schd_daily" type="number" min="0" step="1" value="{{ schd.daily }}">
            </label>
            <label class="input-label">
              Years
              <input name="schd_years" type="number" min="1" max="50" step="1" value="{{ schd.years }}">
            </label>
            <label class="input-label">
              Current yield %
              <input type="number" min="0" max="20" step="0.01" value="{{ schd.yield_pct }}" readonly>
            </label>
            <div style="display:flex; align-items:end;">
              <button type="submit">Calculate</button>
            </div>
          </div>
        </form>
        <div class="result-grid">
          <div class="result-box">
            <span class="subtle">Money added</span>
            <strong>${{ schd.invested }}</strong>
          </div>
          <div class="result-box">
            <span class="subtle">Estimated value</span>
            <strong>${{ schd.future_value }}</strong>
          </div>
          <div class="result-box">
            <span class="subtle">Estimated yearly dividends</span>
            <strong>${{ schd.annual_dividend }}</strong>
          </div>
          <div class="result-box">
            <span class="subtle">Estimated monthly dividends</span>
            <strong>${{ schd.monthly_dividend }}</strong>
          </div>
        </div>
        <div class="subtle" style="margin-top:10px;">
          Yield source: {{ schd.source }}. Last updated {{ schd.updated_at }}. Refreshes weekly and assumes dividends are reinvested.
        </div>
      </div>
    </section>
  </main>
</body>
</html>
"""


def money(value) -> str:
    return f"{float(value):,.2f}"


def json_dumps(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def plain_enum(value) -> str:
    text = str(value or "")
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.replace("_", " ").title()


def option_type_from_symbol(symbol: str) -> str | None:
    match = re.search(r"\d{6}([CP])\d{8}$", str(symbol or "").upper())
    if not match:
        return None
    return "Call" if match.group(1) == "C" else "Put"


def option_symbol_parts(symbol: str) -> dict | None:
    match = re.match(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$", str(symbol or "").upper())
    if not match:
        return None
    expiry = match.group(2)
    return {
        "underlying": match.group(1),
        "expiry": f"20{expiry[:2]}-{expiry[2:4]}-{expiry[4:]}",
        "right": "Call" if match.group(3) == "C" else "Put",
        "strike": int(match.group(4)) / 1000,
    }


def display_position_symbol(symbol: str, tracked_option: dict | None = None) -> tuple[str, str]:
    if tracked_option:
        underlying = str(tracked_option.get("underlying") or "").upper()
        direction = str(tracked_option.get("direction") or "").title()
        if underlying and direction:
            return f"{underlying} {direction}", f"Contract: {symbol}"
    parsed = option_symbol_parts(symbol)
    if parsed:
        detail = f"{parsed['expiry']} ${parsed['strike']:.2f} | Contract: {symbol}"
        return f"{parsed['underlying']} {parsed['right']}", detail
    return str(symbol), ""


def order_action_label(order: dict) -> str:
    side = plain_enum(order.get("side"))
    asset_type = order.get("asset_type")
    if asset_type in {"Call", "Put"}:
        return "Open" if side == "Buy" else "Close"
    return side


def asset_type_from_symbol(symbol: str) -> str:
    return option_type_from_symbol(symbol) or "Stock"


def quantity_label(qty, asset_type: str) -> str:
    unit = "contract" if asset_type in {"Call", "Put"} else "share"
    try:
        value = float(qty)
        qty_text = str(int(value)) if value.is_integer() else str(qty)
    except (TypeError, ValueError):
        qty_text = str(qty)
    suffix = unit if qty_text == "1" else f"{unit}s"
    return f"{qty_text} {suffix}"


def request_float(name: str, default: float, min_value: float, max_value: float) -> float:
    try:
        value = float(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def read_schd_yield_cache() -> dict | None:
    if not SCHD_YIELD_CACHE_PATH.exists():
        return None
    try:
        with SCHD_YIELD_CACHE_PATH.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        fetched_at = datetime.fromisoformat(payload.get("fetched_at", ""))
        if datetime.now(NY_TZ) - fetched_at <= timedelta(days=SCHD_YIELD_CACHE_DAYS):
            return payload
    except Exception:
        return None
    return None


def fetch_schd_yield_from_web() -> dict:
    request_obj = urllib.request.Request(
        SCHD_YIELD_SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 AlpacaPaperBotDashboard/1.0"},
    )
    with urllib.request.urlopen(request_obj, timeout=10) as response:
        html_text = response.read(750_000).decode("utf-8", errors="ignore")
    patterns = (
        r"Dividend Yield</[^>]+>\s*<[^>]+>\s*([0-9]+(?:\.[0-9]+)?)%",
        r"Dividend Yield[^0-9%]{0,120}([0-9]+(?:\.[0-9]+)?)%",
        r"yield of\s+([0-9]+(?:\.[0-9]+)?)%",
    )
    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            yield_pct = float(match.group(1))
            if 0 < yield_pct < 20:
                return {
                    "yield_pct": yield_pct,
                    "source": SCHD_YIELD_SOURCE_URL,
                    "fetched_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
                    "status": "web",
                }
    raise RuntimeError("Could not find SCHD dividend yield on source page.")


def current_schd_yield() -> dict:
    cached = read_schd_yield_cache()
    if cached:
        cached["status"] = cached.get("status", "cache")
        return cached
    try:
        fetched = fetch_schd_yield_from_web()
        with SCHD_YIELD_CACHE_PATH.open("w", encoding="utf-8") as file:
            json.dump(fetched, file, indent=2)
        return fetched
    except Exception as exc:
        logging.warning("SCHD yield refresh failed: %s", exc)
        return {
            "yield_pct": SCHD_DEFAULT_YIELD_PCT,
            "source": "fallback default",
            "fetched_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            "status": f"fallback: {exc}",
        }


def read_ticker_research() -> dict:
    path = Path(os.getenv("BOT_TICKER_RESEARCH_PATH", "ticker_research.json"))
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as exc:
        logging.warning("Could not read ticker research from %s: %s", path, exc)
        return {}


def dashboard_swing_plan() -> dict:
    payload = read_ticker_research()
    plan = payload.get("swing_plan") or {}
    if not plan:
        return {
            "status": "not researched",
            "ticker": "",
            "direction": "",
            "score": "0.00",
            "price": "",
            "reasons": ["Closed-market ticker research has not produced a swing plan yet."],
            "catalysts": [],
            "hold_plan": "",
            "entry_plan": "",
            "exit_plan": "",
            "updated_at": payload.get("created_at", "not checked"),
        }
    plan = dict(plan)
    plan["score"] = f"{float(plan.get('score', 0.0) or 0.0):.2f}"
    price = float(plan.get("price", 0.0) or 0.0)
    plan["price"] = f"{price:,.2f}" if price > 0 else ""
    plan["updated_at"] = payload.get("created_at", "not checked")
    plan["reasons"] = plan.get("reasons") or []
    plan["catalysts"] = plan.get("catalysts") or []
    plan["hold_plan"] = plan.get("hold_plan", "")
    plan["entry_plan"] = plan.get("entry_plan", "")
    plan["exit_plan"] = plan.get("exit_plan", "")
    return plan


def schd_projection() -> dict:
    daily = request_float("schd_daily", 10.0, 0.0, 100_000.0)
    years = int(request_float("schd_years", 10.0, 1.0, 50.0))
    yield_info = current_schd_yield()
    yield_pct = max(0.0, min(20.0, float(yield_info.get("yield_pct", SCHD_DEFAULT_YIELD_PCT))))
    invested = daily * 365 * years
    monthly_rate = yield_pct / 100 / 12
    months = years * 12
    monthly_contribution = daily * 365 / 12
    if monthly_rate > 0:
        future_value = monthly_contribution * (((1 + monthly_rate) ** months - 1) / monthly_rate)
    else:
        future_value = invested
    annual_dividend = future_value * yield_pct / 100
    return {
        "daily": f"{daily:.0f}" if daily.is_integer() else f"{daily:.2f}",
        "years": years,
        "yield_pct": f"{yield_pct:.2f}",
        "source": yield_info.get("source", "unknown"),
        "updated_at": yield_info.get("fetched_at", "unknown"),
        "yield_status": yield_info.get("status", "unknown"),
        "invested": money(invested),
        "future_value": money(future_value),
        "annual_dividend": money(annual_dividend),
        "monthly_dividend": money(annual_dividend / 12),
    }


def friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "insufficient qty available for order" in text and "held_for_orders" in text:
        return "That position already has an open order holding part of the quantity. I cancelled the conflicting bot order first; wait a few seconds and press Close again if it still shows."
    return text


def risk_reward_label(reward: float, risk: float) -> str:
    if risk <= 0:
        return "R/R unavailable"
    ratio = reward / risk
    status = "below target" if ratio < CONFIG.min_reward_risk_ratio else "ok"
    return f"R/R {ratio:.1f} ({status})"


def position_exit_plan(
    symbol: str,
    position,
    tracked_stock: dict | None,
    tracked_option: dict | None,
    open_order: dict | None,
) -> str:
    if not tracked_option:
        if tracked_stock:
            entry = float(tracked_stock.get("entry_price", position.avg_entry_price) or 0)
            current = float(position.current_price or 0)
            target = float(tracked_stock.get("take_profit_price") or 0)
            stop = float(tracked_stock.get("stop_loss_price") or 0)
            held_order = ""
            if open_order:
                held_order = f" Open {plain_enum(open_order.get('side'))} order pending."
            if entry > 0 and target > entry and 0 < stop < entry:
                reward = target - entry
                risk = entry - stop
                return (
                    f"Stock bracket: target ${target:.2f}, stop ${stop:.2f}, "
                    f"{risk_reward_label(reward, risk)}. Now ${current:.2f}.{held_order}"
                )
            return f"Stock entry is tracked, but the saved stop/target is missing.{held_order}"
        if open_order:
            return f"Open {plain_enum(open_order.get('side'))} order pending."
        parsed = option_symbol_parts(symbol)
        if parsed:
            current = float(position.current_price or 0)
            avg = float(position.avg_entry_price or 0)
            target = avg * (1 + CONFIG.option_profit_target_pct) if avg > 0 else 0
            stop = avg * (1 - CONFIG.option_stop_loss_pct) if avg > 0 else 0
            return (
                f"{parsed['underlying']} {parsed['right']} strike ${parsed['strike']:.2f}, exp {parsed['expiry']}. "
                f"Untracked by state, using broker avg: TP option >=${target:.2f}, stop <=${stop:.2f}. "
                f"Now ${current:.2f}. Use Close if you do not want to hold it."
            )
        return "Untracked position. Use Close if you do not want to hold it."
    entry = float(tracked_option.get("entry_price", position.avg_entry_price) or 0)
    current = float(position.current_price or 0)
    held_order = ""
    if open_order:
        held_order = f" Sell order pending for {open_order.get('qty')} at limit ${open_order.get('limit_price', '?')}."
    if entry <= 0:
        return (
            f"Option exit: +{CONFIG.option_profit_target_pct:.0%} profit, "
            f"-{CONFIG.option_stop_loss_pct:.0%} loss, or {CONFIG.option_max_hold_days} day time stop.{held_order}"
        )
    profit_trigger = entry * (1 + CONFIG.option_profit_target_pct)
    stop_trigger = entry * (1 - CONFIG.option_stop_loss_pct)
    saved_profit_trigger = float(tracked_option.get("take_profit_price") or profit_trigger)
    saved_stop_trigger = float(tracked_option.get("stop_loss_price") or stop_trigger)
    strike = float(tracked_option.get("strike") or 0)
    underlying = str(tracked_option.get("underlying") or "").upper()
    direction = str(tracked_option.get("direction") or "").title()
    underlying_target = tracked_option.get("underlying_target_price")
    contract_detail = ""
    if underlying and direction and strike > 0:
        contract_detail = f"{underlying} {direction} strike ${strike:.2f}. "
    if underlying_target:
        contract_detail += f"Underlying guide ${float(underlying_target):.2f}. "
    rr = risk_reward_label(saved_profit_trigger - entry, entry - saved_stop_trigger)
    if current >= saved_profit_trigger:
        status = "Profit target reached."
    elif current <= saved_stop_trigger:
        status = "Stop-loss reached."
    else:
        status = "Holding."
    return (
        f"{status} {contract_detail}TP ${saved_profit_trigger:.2f} (+{CONFIG.option_profit_target_pct:.0%}) | "
        f"Stop ${saved_stop_trigger:.2f} (-{CONFIG.option_stop_loss_pct:.0%}). "
        f"Time stop after {CONFIG.option_max_hold_days} days. {rr}. Now ${current:.2f}.{held_order}"
    )


def build_snapshot() -> dict:
    bot = AlpacaStockBot(CONFIG)
    account = bot.trading.get_account()
    clock = bot.trading.get_clock()
    bot.update_daily_risk_snapshot()
    bot.reconcile_open_orders(block_new_entries=False)
    bot.get_option_positions()
    bot.refresh_option_exit_targets()
    save_state(bot.state_path, bot.state)
    state = bot.state
    last_scan = state.get("last_scan") or {
        "time": "",
        "best": "",
        "market": {"is_clear": False, "status": "not run", "score": 0, "required": CONFIG.min_market_score, "reasons": []},
        "candidates": {},
    }
    market = last_scan.setdefault("market", {})
    if "is_clear" not in market:
        market["is_clear"] = bool(market.get("clear", False))
    candidate_rows = []
    for ticker, result in (last_scan.get("candidates") or {}).items():
        result = dict(result)
        result["reason_text"] = "; ".join(result.get("reasons") or [])
        candidate_rows.append((ticker, result))
    last_option_scan = state.get("last_option_scan") or {"time": "", "best": None, "candidates": {}}
    option_candidate_rows = []
    for ticker, result in (last_option_scan.get("candidates") or {}).items():
        result = dict(result)
        result["reason_text"] = "; ".join(result.get("reasons") or [])
        option_candidate_rows.append((ticker, result))
    option_best_raw = last_option_scan.get("best")
    option_best = "none"
    if option_best_raw:
        option_best = f"{option_best_raw.get('ticker')} {option_best_raw.get('direction')} {option_best_raw.get('score')}"
    learning_raw = state.get("learning") or {}
    trade_history = state.get("trade_history") or {}
    score_adjustments = learning_raw.get("score_adjustments") or {}
    learning_stats = learning_raw.get("stats") or {}
    learning = {
        "updated_at": learning_raw.get("updated_at", ""),
        "closed_trade_count": learning_raw.get("closed_trade_count", 0),
        "opened_trade_count": len(trade_history.get("opened_trades") or []),
        "risk_multiplier": f"{float(learning_raw.get('risk_multiplier', 1.0)):.2f}x",
        "adjustment_count": len(score_adjustments),
        "win_rate": (
            f"{float(learning_stats.get('win_rate')):.0%}"
            if learning_stats.get("win_rate") is not None
            else "needs sample"
        ),
        "profit_factor": (
            f"{float(learning_stats.get('profit_factor')):.2f}"
            if learning_stats.get("profit_factor") is not None
            else "needs sample"
        ),
        "downside_adjusted_return": (
            f"{float(learning_stats.get('downside_adjusted_return')):.2f}"
            if learning_stats.get("downside_adjusted_return") is not None
            else "needs sample"
        ),
    }
    learning_adjustments = [
        f"{key}: {value:+.3f}" for key, value in sorted(score_adjustments.items(), key=lambda item: abs(float(item[1])), reverse=True)[:8]
    ]
    levels_payload = read_trade_levels()
    levels_symbols = levels_payload.get("symbols") or {}
    levels_summary = []
    for symbol, level in sorted(levels_symbols.items()):
        levels_summary.append(
            f"{symbol}: support {level.get('support', [])}; resistance {level.get('resistance', [])}; "
            f"confirm {level.get('confirmation', [])}; failure {level.get('failure', [])}; GEX {level.get('gex', [])}"
        )
    insiderfinance_summary = []
    for symbol, gex in sorted((state.get("insiderfinance_gex") or {}).items()):
        if gex.get("status") == "ok":
            insiderfinance_summary.append(
                f"{symbol}: {gex.get('regime', 'unknown')} net {gex.get('net_gex', 0) / 1_000_000_000:.1f}B; "
                f"put wall {gex.get('put_wall')}; zero gamma {gex.get('zero_gamma')}; call wall {gex.get('call_wall')}"
            )
    safety_raw = state.get("safety") or {}
    controls_raw = state.get("controls") or {}
    daily_raw = state.get("daily_risk") or {}
    macro_news_raw = state.get("macro_news") or {}
    last_news_check = state.get("last_news_check") or {}
    external_macro_raw = state.get("external_macro_news") or {}
    insiderfinance_status = state.get("insiderfinance_gex_status") or {}
    last_entry_raw = state.get("last_entry_decision") or {}
    entry_details = last_entry_raw.get("details") or {}
    detail_parts = []
    if "option_attempts" in entry_details:
        detail_parts.append(f"option attempts {entry_details.get('option_attempts')}")
    if "option_entries_opened" in entry_details:
        detail_parts.append(f"option entries {entry_details.get('option_entries_opened')}")
    if entry_details.get("failed_option_underlyings"):
        detail_parts.append(f"failed options: {', '.join(entry_details.get('failed_option_underlyings') or [])}")
    if "risk_multiplier" in entry_details:
        detail_parts.append(f"risk {float(entry_details.get('risk_multiplier') or 0):.2f}x")
    if "current_bot_exposure" in entry_details and "remaining_bot_budget" in entry_details:
        detail_parts.append(
            f"budget used ${float(entry_details.get('current_bot_exposure') or 0):,.2f}; "
            f"left ${float(entry_details.get('remaining_bot_budget') or 0):,.2f}"
        )
    source_stats = external_macro_raw.get("source_stats") or {}
    news_source_parts = []
    for source_url, source_info in source_stats.items():
        try:
            domain = re.sub(r"^www\.", "", source_url.split("/")[2])
        except Exception:
            domain = source_url
        news_source_parts.append(f"{domain}: {source_info.get('items', 0)}")
    unmanaged_symbols = safety_raw.get("unmanaged_symbols") or []
    safety = {
        "status": safety_raw.get("status", "unknown"),
        "checked_at": safety_raw.get("checked_at", ""),
        "open_order_count": safety_raw.get("open_order_count", 0),
        "unmanaged_symbols_text": ", ".join(unmanaged_symbols) if unmanaged_symbols else "none",
    }
    open_orders = []
    open_orders_by_symbol = {}
    for order_id, order in (state.get("open_orders") or {}).items():
        order = dict(order)
        order["id"] = order_id
        order["side_label"] = plain_enum(order.get("side"))
        order["status_label"] = plain_enum(order.get("status"))
        order["limit_price"] = order.get("limit_price", "")
        order["asset_type"] = asset_type_from_symbol(order.get("symbol", ""))
        order["action_label"] = order_action_label(order)
        order["qty_label"] = quantity_label(order.get("qty"), order["asset_type"])
        open_orders.append(order)
        open_orders_by_symbol[str(order.get("symbol", ""))] = order
    closed_trades = []
    closed_bot_pnl_float = 0.0
    all_closed_trades = trade_history.get("closed_trades") or []
    for trade in all_closed_trades:
        try:
            closed_bot_pnl_float += float(trade.get("pnl", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
    for trade in reversed((trade_history.get("closed_trades") or [])[-10:]):
        trade = dict(trade)
        trade["pnl_float"] = float(trade.get("pnl", 0.0))
        trade["pnl"] = money(trade.get("pnl", 0.0))
        greeks = trade.get("entry_greeks") or {}
        trade["greeks_text"] = (
            f"Delta {greeks.get('delta')} | Theta {greeks.get('theta')} | Vega {greeks.get('vega')}"
            if greeks
            else ""
        )
        closed_trades.append(trade)
    positions = []
    open_bot_pnl_float = 0.0

    for position in bot.trading.get_all_positions():
        tracked_stock = (state.get("positions") or {}).get(position.symbol)
        tracked_option = (state.get("option_positions") or {}).get(position.symbol)
        asset_type = asset_type_from_symbol(position.symbol)
        display_symbol, symbol_detail = display_position_symbol(position.symbol, tracked_option)
        position_pnl = float(position.unrealized_pl)
        open_bot_pnl_float += position_pnl
        positions.append(
            {
                "symbol": position.symbol,
                "display_symbol": display_symbol,
                "symbol_detail": symbol_detail,
                "qty": str(position.qty),
                "qty_label": quantity_label(position.qty, asset_type),
                "asset_type": asset_type,
                "avg_entry_price": money(position.avg_entry_price),
                "market_value": money(position.market_value),
                "unrealized_pl": money(position.unrealized_pl),
                "unrealized_pl_float": position_pnl,
                "exit_plan": position_exit_plan(
                    position.symbol,
                    position,
                    tracked_stock,
                    tracked_option,
                    open_orders_by_symbol.get(position.symbol),
                ),
            }
        )
    bucket_counts = bot.bucket_counts()
    bucket_counts_text = ", ".join(f"{bucket}: {count}" for bucket, count in sorted(bucket_counts.items())) if bucket_counts else "none"
    market_reasons = [
        reason
        for reason in ((last_scan.get("market") or {}).get("reasons") or [])
        if not str(reason).startswith("macro news:")
    ]

    return {
        "account": {
            "portfolio_value": money(account.portfolio_value),
            "cash": money(account.cash),
            "buying_power": money(account.buying_power),
        },
        "positions": positions,
        "clock_open": bool(clock.is_open),
        "market_status": "Open" if clock.is_open else "Closed",
        "next_open": clock.next_open,
        "state_positions_count": len(state.get("positions", {})),
        "state_json": json_dumps(state),
        "state_path": str(bot.state_path),
        "current_bot_exposure": money(bot.current_bot_exposure_cash()),
        "remaining_bot_budget": money(bot.remaining_bot_budget()),
        "paper_equity_cap": money(bot.config.paper_equity_cap),
        "open_bot_pnl": money(open_bot_pnl_float),
        "open_bot_pnl_float": open_bot_pnl_float,
        "closed_bot_pnl": money(closed_bot_pnl_float),
        "closed_bot_pnl_float": closed_bot_pnl_float,
        "closed_trade_count": len(all_closed_trades),
        "last_scan": last_scan,
        "last_entry_decision": {
            "status": plain_enum(last_entry_raw.get("status", "not checked")),
            "time": last_entry_raw.get("time", ""),
            "reasons": last_entry_raw.get("reasons") or [],
            "details_text": " | ".join(detail_parts),
        },
        "candidate_rows": candidate_rows,
        "last_option_scan": last_option_scan,
        "option_candidate_rows": option_candidate_rows,
        "option_best": option_best,
        "learning": learning,
        "learning_adjustments": learning_adjustments,
        "safety": safety,
        "daily_risk": {
            "status": daily_raw.get("status", "not checked"),
            "blocked": daily_raw.get("status") == "blocked_daily_loss",
            "pnl": money(daily_raw.get("pnl", 0.0)),
            "limit": money(daily_raw.get("max_daily_loss_cash", CONFIG.max_daily_loss_cash)),
            "checked_at": daily_raw.get("checked_at", ""),
        },
        "macro_news": {
            "status": macro_news_raw.get("status", "not checked"),
            "reasons": macro_news_raw.get("reasons") or [],
            "checked_at": macro_news_raw.get("checked_at", ""),
        },
        "news_risk_label": {
            "blocked": "Blocked",
            "ok": "Clear",
            "disabled": "Off",
            "not checked": "Not checked",
        }.get(str(macro_news_raw.get("status", "not checked")), plain_enum(macro_news_raw.get("status", "not checked"))),
        "market_reasons": market_reasons,
        "bucket_counts_text": bucket_counts_text,
        "controls": {
            "trading_paused": bool(controls_raw.get("trading_paused", False)),
            "updated_at": controls_raw.get("updated_at", ""),
            "reason": controls_raw.get("reason", ""),
        },
        "open_orders": open_orders,
        "closed_trades": closed_trades,
        "news_status": state.get("news_status", "not checked"),
        "news_detail": (
            f"{last_news_check.get('items', 0)} total, "
            f"{last_news_check.get('items_with_content', 0)} with body/summary, "
            f"{last_news_check.get('external_macro_items', 0)} external macro"
            if last_news_check
            else ""
        ),
        "news_sources_text": ", ".join(news_source_parts[:6]),
        "gex_status_text": (
            f"InsiderFinance GEX {insiderfinance_status.get('status', 'not checked')}: "
            f"{insiderfinance_status.get('ok', 0)} ok, "
            f"{insiderfinance_status.get('empty', 0)} empty, "
            f"{insiderfinance_status.get('unavailable', 0)} unavailable"
            if insiderfinance_status
            else "InsiderFinance GEX not checked"
        ),
        "tickers": bot.config.tickers,
        "ticker_count": len(bot.config.tickers),
        "levels_count": len(levels_symbols),
        "levels_summary": (insiderfinance_summary + levels_summary)[:10],
        "max_positions": bot.config.max_positions,
        "options_only": not bot.config.trade_stocks,
        "run_url": url_for("run_scan"),
        "pause_url": url_for("pause_trading"),
        "cancel_orders_url": url_for("cancel_orders"),
        "trim_position_url": url_for("trim_position"),
        "close_position_url": url_for("close_position"),
        "add_ticker_url": url_for("add_ticker"),
        "remove_ticker_url": url_for("remove_ticker"),
        "update_levels_url": url_for("update_levels"),
        "index_url": url_for("index"),
        "schd": schd_projection(),
        "swing_plan": dashboard_swing_plan(),
        "spacex": SPACEX_INFO,
    }


@app.get("/")
def index():
    snapshot = build_snapshot()
    snapshot["message"] = request.args.get("message", "")
    return render_template_string(PAGE, **snapshot)


@app.post("/run")
def run_scan():
    try:
        bot = AlpacaStockBot(CONFIG)
        if bot.trading.get_clock().is_open:
            bot.run_once()
            message = "Live scan finished. Check account and positions below."
        else:
            bot.scan_only()
            message = "Preview scan finished. Market is closed, so no orders were submitted."
    except Exception as exc:
        logging.exception("Dashboard scan failed")
        message = f"Scan failed: {friendly_error(exc)}"
    return redirect(url_for("index", message=message))


@app.post("/pause")
def pause_trading():
    paused = request.form.get("paused", "true").lower() == "true"
    bot = AlpacaStockBot(CONFIG)
    bot.set_trading_paused(paused, "dashboard")
    message = "Trading paused. Exits and trims can still run." if paused else "Trading resumed."
    return redirect(url_for("index", message=message))


@app.post("/orders/cancel")
def cancel_orders():
    try:
        bot = AlpacaStockBot(CONFIG)
        count = bot.cancel_bot_open_orders()
        message = f"Cancel requested for {count} bot-related open order(s)."
    except Exception as exc:
        logging.exception("Cancel orders failed")
        message = f"Cancel failed: {friendly_error(exc)}"
    return redirect(url_for("index", message=message))


@app.post("/positions/trim")
def trim_position():
    symbol = normalize_ticker(request.form.get("symbol", ""))
    if not symbol:
        return redirect(url_for("index", message="Position symbol was blank."))
    try:
        bot = AlpacaStockBot(CONFIG)
        order_id = bot.trim_tracked_position(symbol)
        message = f"Trim submitted for {symbol}. Order {order_id}." if order_id else f"{symbol} is already within bot limits."
    except Exception as exc:
        logging.exception("Trim failed")
        message = f"Trim failed for {symbol}: {friendly_error(exc)}"
    return redirect(url_for("index", message=message))


@app.post("/positions/close")
def close_position():
    symbol = normalize_ticker(request.form.get("symbol", ""))
    if not symbol:
        return redirect(url_for("index", message="Position symbol was blank."))
    try:
        bot = AlpacaStockBot(CONFIG)
        order_id = bot.close_tracked_position(symbol)
        message = f"Close submitted for {symbol}. Order {order_id}."
    except Exception as exc:
        logging.exception("Close failed")
        message = f"Close failed for {symbol}: {friendly_error(exc)}"
    return redirect(url_for("index", message=message))


@app.post("/tickers/add")
def add_ticker():
    ticker = normalize_ticker(request.form.get("ticker", ""))
    if not ticker:
        return redirect(url_for("index", message="Ticker was blank."))
    tickers = read_watchlist()
    if ticker not in tickers:
        tickers.append(ticker)
        save_watchlist(None, tickers)
        message = f"Added {ticker} to the watchlist. Restarted scans will use it."
    else:
        message = f"{ticker} is already in the watchlist."
    return redirect(url_for("index", message=message))


@app.post("/tickers/remove")
def remove_ticker():
    ticker = normalize_ticker(request.form.get("ticker", ""))
    tickers = [item for item in read_watchlist() if item != ticker]
    save_watchlist(None, tickers)
    return redirect(url_for("index", message=f"Removed {ticker} from the watchlist."))


@app.post("/levels/update")
def update_levels():
    symbol = normalize_ticker(request.form.get("symbol", ""))
    if not symbol:
        return redirect(url_for("index", message="Enter a symbol for the levels."))

    def parse_levels(field: str) -> list[float]:
        raw = request.form.get(field, "")
        values = []
        for part in re.split(r"[,\s]+", raw.strip()):
            if not part:
                continue
            try:
                values.append(float(part))
            except ValueError:
                continue
        return values

    try:
        tolerance = float(request.form.get("tolerance", "0") or 0)
    except ValueError:
        tolerance = 0
    levels = read_trade_levels()
    levels.setdefault("symbols", {})[symbol] = {
        "support": parse_levels("support"),
        "resistance": parse_levels("resistance"),
        "confirmation": parse_levels("confirmation"),
        "failure": parse_levels("failure"),
        "gex": parse_levels("gex"),
        "tolerance": tolerance,
        "updated_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
    }
    save_trade_levels(None, levels)
    return redirect(url_for("index", message=f"Updated chart/GEX levels for {symbol}."))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    now = datetime.now(NY_TZ)
    try:
        startup_clock = AlpacaStockBot(CONFIG).trading.get_clock()
        market_text = "open" if startup_clock.is_open else f"closed, next open {startup_clock.next_open}"
    except Exception as exc:
        market_text = f"unknown ({exc})"
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5050"))
    print(f"Dashboard running at http://{host}:{port}")
    print(f"Eastern time: {now:%Y-%m-%d %I:%M:%S %p %Z}; market is {market_text}")
    app.run(host=host, port=port)
