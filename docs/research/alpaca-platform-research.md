# Alpaca platform research for the Conviction Spread Agent

**Checked:** 2026-08-20
**Scope:** Alpaca Trading API paper environment, options trading and data, official MCP server, official CLI, and `alpaca-py`.
**Source policy:** Alpaca documentation and Alpaca-owned GitHub repositories only. Public documentation describes the platform but cannot prove the permissions, subscriptions, or behavior of a particular new paper account; those items are listed under **Account/API verification checklist**.

## Executive findings

- The hackathon agent should connect its trading client to `https://paper-api.alpaca.markets` with paper-only credentials. Live trading uses a different host and different credentials. Market data remains on `https://data.alpaca.markets`, and real-time data remains on `wss://stream.data.alpaca.markets/...`. ([Authentication](https://docs.alpaca.markets/us/docs/authentication-1), [Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq))
- Options capability is enabled by default in the paper environment, and Level 3 multi-leg strategies are available in paper. The account response exposes `options_buying_power`, `options_approved_level`, and `options_trading_level`; a spread agent must confirm trading level 3 before it tries to submit a spread. ([Options Trading](https://docs.alpaca.markets/us/docs/options-trading), [Level 3 in paper changelog](https://docs.alpaca.markets/us/v1.1/changelog/multi-leg-level-3-options-trading-in-paper), [`TradeAccount` model](https://alpaca.markets/sdks/python/api_reference/trading/models.html))
- The correct atomic spread order is `order_class: "mleg"` with two to four legs. For a net-debit spread, `limit_price` is positive; a net credit is negative. Use `day`, `limit`, integer strategy quantity, and explicit per-leg `position_intent`. ([Create Order reference](https://docs.alpaca.markets/us/reference/postorder), [Level 3 guide](https://docs.alpaca.markets/us/docs/options-level-3-trading), [`alpaca-py` request validation](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/trading/requests.py))
- Equity-style `bracket`, `OCO`, and `OTO` classes are not listed as supported for options; the order reference lists only `simple` and `mleg` for options. Therefore, exits for a debit spread should be implemented by an agent-side monitor that submits an opposing closing MLeg order, not by assuming an attached options stop/take-profit exists. ([Create Order reference](https://docs.alpaca.markets/us/reference/postorder), [Orders guide](https://docs.alpaca.markets/us/docs/orders-at-alpaca))
- Free/Basic options data uses Alpaca's Indicative feed, while Algo Trader Plus supplies OPRA. The Indicative quotes are derived/modified rather than actual OPRA quotes, and Indicative trades are delayed by 15 minutes. Historical option data begins in February 2024. ([Market Data plans](https://docs.alpaca.markets/us/docs/about-market-data-api), [Historical Option Data](https://docs.alpaca.markets/us/docs/historical-option-data))
- Alpaca supplies Greeks and implied volatility in option snapshots and chains, but values can be missing. Alpaca documents prerequisites including non-zero bid/ask, a latest SIP trade for the underlying, non-expired contracts, and a valid/convergent IV calculation; 0DTE contracts do not receive Greeks. ([Option chain](https://docs.alpaca.markets/us/reference/optionchain), [Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq))
- The official MCP v2 server is suitable for satisfying the MCP requirement and defaults to paper. Its current docs expose 65 tools and allow server-side toolset filtering. However, an open issue in Alpaca's repository reports that a particular Claude Desktop/Cowork bridge serializes the `legs` array incorrectly for `place_option_order`; the exact hackathon MCP client must be tested before making MCP the only spread-execution path. ([MCP documentation](https://docs.alpaca.markets/us/docs/alpaca-mcp-server), [official MCP repository](https://github.com/alpacahq/alpaca-mcp-server), [open issue #97](https://github.com/alpacahq/alpaca-mcp-server/issues/97))
- The official CLI is an Alpha Preview. It returns structured JSON by default and offers raw API access, which is a dependable way to demonstrate CLI use even if a high-level command lacks a needed MLeg flag. Pin and record the tested CLI version because commands, flags, and output may change. ([Trading CLI documentation](https://docs.alpaca.markets/us/docs/alpacas-cli), [official CLI repository](https://github.com/alpacahq/cli))

## 1. Paper account, hosts, credentials, and submission identity

### Paper setup

Anyone can create an Alpaca Paper Only Account with an email address. A paper account has its own API key pair, distinct from live credentials, and uses `https://paper-api.alpaca.markets`; Alpaca says the API specification is otherwise the same between paper and live. The dashboard currently creates and deletes paper accounts, and a newly created account needs newly generated keys. ([Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading), [Authentication](https://docs.alpaca.markets/us/docs/authentication-1))

For the hackathon, create the fresh judging account only after the software is stable. Keep development and manual experiments on another paper account. The judging account should contain only agent-attributable activity, because the hackathon account ID is intended to let judges associate the submitted project with its trading history. This workflow recommendation is an inference from the event requirement; Alpaca's API fact is that `GET /v2/account` returns the authenticated paper account. ([Get Account](https://docs.alpaca.markets/us/reference/getaccount-1))

### Host map

| Purpose | Trading API paper-account host | Source |
|---|---|---|
| Account, orders, positions, contracts, calendar/clock | `https://paper-api.alpaca.markets` | [Authentication](https://docs.alpaca.markets/us/docs/authentication-1) |
| Historical/latest market data | `https://data.alpaca.markets` | [Historical API](https://docs.alpaca.markets/us/docs/historical-api), [Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq) |
| Market-data WebSockets | `wss://stream.data.alpaca.markets/...` | [WebSocket Stream](https://docs.alpaca.markets/us/docs/streaming-market-data) |
| Paper order/account updates | `wss://paper-api.alpaca.markets/stream` | [Websocket Streaming](https://docs.alpaca.markets/us/docs/websocket-streaming) |
| Live trading, not for the hackathon | `https://api.alpaca.markets` | [Authentication](https://docs.alpaca.markets/us/docs/authentication-1) |

Do not confuse a retail Trading API paper account with the Broker API sandbox. URLs such as `broker-api.sandbox.alpaca.markets` and `data.sandbox.alpaca.markets` are documented for broker-partner integration testing, not as the normal market-data hosts for a Trading API paper account. ([Historical API](https://docs.alpaca.markets/us/docs/historical-api), [Broker integration setup](https://docs.alpaca.markets/us/docs/integration-setup-with-alpaca))

### Authentication and secret handling

Private Trading API calls use `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY` HTTP headers. Do not commit keys, put them in frontend code, print them in logs, or paste them into model prompts; supply them to the backend process through environment variables or a secret store. Alpaca's CLI and MCP instructions likewise configure credentials via environment variables. ([Authentication](https://docs.alpaca.markets/us/docs/authentication-1), [MCP configuration](https://docs.alpaca.markets/us/docs/alpaca-mcp-server), [CLI configuration](https://docs.alpaca.markets/us/docs/alpacas-cli))

Persist Alpaca's `X-Request-ID` response header alongside failures and order audit records. Alpaca says it identifies the API call chain and asks users to include it in support requests. ([Getting Started with Trading API](https://docs.alpaca.markets/us/docs/getting-started-with-trading-api))

### Which account identifier should be submitted?

The account model contains both `id` (a UUID described as the account ID) and `account_number` (a string described as the account number). The hackathon wording supplied to this project says "paper trading account ID" but does not specify which field its submission form expects. Record both values from `GET /v2/account`, show the human-readable account number in the dashboard, and verify the form/organizer's exact expectation before final submission. ([`TradeAccount` model](https://alpaca.markets/sdks/python/api_reference/trading/models.html), [Get Account](https://docs.alpaca.markets/us/reference/getaccount-1))

## 2. Options permissions, buying power, and lifecycle risk

Alpaca's paper-options page says options are enabled by default in paper. The configured `options_trading_level` cannot exceed `options_approved_level`, and the `max_options_trading_level` account configuration can lower or disable the active level. The documented levels are: 0 disabled; 1 covered call/cash-secured put; 2 long call/put plus level 1; and 3 spreads/straddles plus lower levels. ([Options Trading](https://docs.alpaca.markets/us/docs/options-trading), [`TradeAccount` and configuration models](https://alpaca.markets/sdks/python/api_reference/trading/models.html))

Opening option positions is checked against `options_buying_power`. Long calls and puts require enough power for the premium; short strategies require the documented collateral. The API can reject a strategy above the account's level or an order without adequate power. ([Options Trading Overview](https://docs.alpaca.markets/us/docs/options-trading-overview))

For the judging account, startup preflight should fail closed unless all of the following are true: account status is active, `trading_blocked` is false, `options_trading_level >= 3`, `options_buying_power` is positive, and the target contracts return `tradable: true`. The account and contract fields are documented by Alpaca; failing closed is a project safety decision. ([`TradeAccount` model](https://alpaca.markets/sdks/python/api_reference/trading/models.html), [Option Contracts](https://docs.alpaca.markets/us/reference/get-options-contracts))

### Exercise, assignment, and expiration

Alpaca provides exercise and do-not-exercise endpoints. The exercise endpoint exercises all available held contracts, processes the request immediately, rejects requests between market close and midnight, and says ITM contracts auto-exercise by default at expiry. ([Exercise an Options Position](https://docs.alpaca.markets/us/reference/optionexercise), [Options Trading Overview](https://docs.alpaca.markets/us/docs/options-trading-overview))

Short options can be assigned overnight. Alpaca records option assignment, exercise, and expiry through option-specific account activities. On expiration day, Alpaca begins evaluating expiring positions at 3:30 p.m. ET, can stop accepting orders that open or extend them, and may liquidate positions that cannot support exercise; even slightly OTM positions may be closed based on market conditions. The project should therefore avoid holding spreads into expiration unless expiry handling is an explicit, tested part of the strategy. ([Options Trading Overview](https://docs.alpaca.markets/us/docs/options-trading-overview), [Non-Trade Activities for Option Events](https://docs.alpaca.markets/us/v1.1/docs/non-trade-activities-for-option-events))

The general options pages describe the live lifecycle, but the public docs do not separately specify every assignment/exercise simulation assumption for a retail paper account. Verify paper behavior with small, controlled positions well before judging. ([Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading), [Options Trading Overview](https://docs.alpaca.markets/us/docs/options-trading-overview))

## 3. Option contract discovery

Use `GET /v2/options/contracts` on the paper Trading API host to discover contracts. Filters include underlying symbols, active/inactive status, exact or ranged expiration dates, call/put type, style, strike range, root symbol, and Penny Program indicator; the response is paginated and allows up to 10,000 contracts per page. If no expiration ceiling is provided, the endpoint defaults to contracts expiring by the upcoming weekend, so a swing agent must explicitly set `expiration_date_gte` and `expiration_date_lte`. ([Get Option Contracts](https://docs.alpaca.markets/us/reference/get-options-contracts))

`GET /v2/options/contracts/{symbol_or_id}` returns one contract by OCC-style symbol or contract UUID. Contract data includes status/tradability, expiration, underlying, call/put type, exercise style, strike, multiplier/size, open interest and its date, and prior close fields. ([Get option contract](https://docs.alpaca.markets/us/reference/get-option-contract-symbol_or_id), [Options Trading Overview](https://docs.alpaca.markets/us/docs/options-trading-overview))

Contract selection should require an active, tradable contract; a chosen DTE band; sensible strike distance; fresh quote; non-zero bid/ask; bounded bid/ask spread; adequate open interest; and a valid strategy-level net debit. Alpaca supplies the source fields, while the thresholds are strategy policy. ([Get Option Contracts](https://docs.alpaca.markets/us/reference/get-options-contracts), [Option chain](https://docs.alpaca.markets/us/reference/optionchain))

## 4. Options market data, plans, history, IV, and Greeks

### Endpoints relevant to the spread agent

| Need | Endpoint | Important details | Source |
|---|---|---|---|
| Historical bars | `GET /v1beta1/options/bars` | Multiple symbols, timeframe, date range, pagination; maximum 100 input symbols | [Historical option bars](https://docs.alpaca.markets/us/reference/optionbars) |
| Historical trades | `GET /v1beta1/options/trades` | Multiple symbols/date range, paginated and sorted by symbol then time | [Historical option trades](https://docs.alpaca.markets/us/reference/optiontrades) |
| Latest trades | `GET /v1beta1/options/trades/latest` | Up to 100 symbols; `indicative` or `opra` | [Latest option trades](https://docs.alpaca.markets/us/reference/optionlatesttrades) |
| Latest quotes | `GET /v1beta1/options/quotes/latest` | Bid/ask for up to 100 symbols; `indicative` or `opra` | [Latest option quotes](https://docs.alpaca.markets/us/reference/optionlatestquotes) |
| Selected-contract snapshots | `GET /v1beta1/options/snapshots` | Latest trade, quote, and Greeks; up to 100 requested symbols and paginated results | [Option snapshots](https://docs.alpaca.markets/us/reference/optionsnapshots) |
| Chain by underlying | `GET /v1beta1/options/snapshots/{underlying_symbol}` | Latest trade, quote, Greeks; filters for type, strikes, expiration, root; paginated | [Option chain](https://docs.alpaca.markets/us/reference/optionchain) |

The official options overview lists historical bars and trades, but not a historical options-quote endpoint. Do not assume tick-level historical bid/ask is available through Alpaca merely because real-time/latest quotes are available; confirm the installed SDK/API surface before designing a quote-level backtest. ([Options Trading Overview](https://docs.alpaca.markets/us/docs/options-trading-overview), [Historical Option Data](https://docs.alpaca.markets/us/docs/historical-option-data))

### Subscription facts

The Basic Trading API plan is free and is the default for paper and live accounts. For options, Basic provides the Indicative Pricing Feed, up to 200 WebSocket quote subscriptions, a latest-15-minutes historical-data restriction, and 200 historical API calls per minute. Algo Trader Plus is documented at $99/month and supplies OPRA, up to 1,000 option quote subscriptions, no 15-minute restriction, and 10,000 historical calls per minute. For equities, Basic uses IEX and Plus supplies all US exchanges/SIP. ([About Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api))

Alpaca describes Indicative options quotes as derivatives that are not actual OPRA quotes, and its Indicative trades as derived and delayed by 15 minutes. OPRA is the subscribed consolidated BBO source. Historical options data is available only from February 2024 onward. ([Historical Option Data](https://docs.alpaca.markets/us/docs/historical-option-data))

This has a direct project consequence: Basic is sufficient to wire the application and demonstrate autonomous paper execution, but its indicative prices are a weak basis for evaluating live-like spread liquidity, slippage, and fill quality. Ask whether the hackathon supplies or permits Algo Trader Plus; otherwise disclose the feed and avoid claiming OPRA-quality execution analytics. ([About Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api), [Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading))

### Greeks and implied volatility

Option snapshots and chains return Greeks; Alpaca's data models include implied volatility alongside delta, gamma, rho, theta, and vega. These are latest/snapshot analytics, not a documented historical IV time-series endpoint. ([Option snapshots](https://docs.alpaca.markets/us/reference/optionsnapshots), [Option chain](https://docs.alpaca.markets/us/reference/optionchain), [`alpaca-py` option data reference](https://alpaca.markets/sdks/python/api_reference/data/option.html))

Greeks/IV may be absent even on a valid subscription. Alpaca uses Black-Scholes and requires a non-zero bid and ask, a latest SIP underlying trade, an unexpired contract, and a valid/convergent IV; 0DTE Greeks are undefined and omitted. Deep OTM or near-expiry contracts may also fail to converge. The agent must treat Greeks as nullable and skip or fall back rather than substituting zero. ([Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq))

## 5. Multi-leg order request and constraints

### Recommended debit-spread request

The current order reference documents a positive MLeg `limit_price` as a debit and a negative value as a credit. `qty` is the number of complete strategy units, parent `symbol` and `side` are omitted for MLeg, and the legs carry the individual symbols, ratios, sides, and position intents. Options and MLeg options support market and limit order types; the same reference lists options time-in-force as `day`. ([Create Order](https://docs.alpaca.markets/us/reference/postorder))

```json
{
  "client_order_id": "csa-entry-SPY-20260831-001",
  "order_class": "mleg",
  "qty": "1",
  "type": "limit",
  "limit_price": "1.25",
  "time_in_force": "day",
  "legs": [
    {
      "symbol": "SPY260918C00650000",
      "ratio_qty": "1",
      "side": "buy",
      "position_intent": "buy_to_open"
    },
    {
      "symbol": "SPY260918C00660000",
      "ratio_qty": "1",
      "side": "sell",
      "position_intent": "sell_to_open"
    }
  ]
}
```

The symbols above are illustrative, not a statement that those contracts exist or are tradable on the submission date. Discover and validate actual contracts immediately before ordering. ([Get Option Contracts](https://docs.alpaca.markets/us/reference/get-options-contracts))

To exit atomically, submit another MLeg order with `buy_to_close`/`sell_to_close` as appropriate. Alpaca's Level 3 guide includes rolling examples that mix closing and opening intents in one parent order. ([Options Level 3 Trading](https://docs.alpaca.markets/us/docs/options-level-3-trading))

### Documented constraints and caveats

- The REST order schema permits no more than four legs; Alpaca's official Python request validation requires at least two MLeg legs, at most four, unique symbols, and an MLeg `qty`. ([Create Order](https://docs.alpaca.markets/us/reference/postorder), [`alpaca-py` requests](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/trading/requests.py))
- Ratios must be in simplest form: their greatest common divisor must be one. ([Options Level 3 Trading](https://docs.alpaca.markets/us/docs/options-level-3-trading))
- Current Level 3 guidance says equity-plus-option combo legs are not supported, despite introductory language and error text elsewhere that mentions equity legs. Treat the restrictive statement as the safe implementation rule and verify against the paper API if combo orders ever become relevant. ([Options Level 3 Trading](https://docs.alpaca.markets/us/docs/options-level-3-trading), [Options Trading Overview error table](https://docs.alpaca.markets/us/docs/options-trading-overview))
- The guide says every short leg in an MLeg must be covered within that same MLeg order. It explicitly warns that this restriction affects some rolls. Defined-risk vertical debit spreads satisfy the intended covered-leg shape. ([Options Level 3 Trading](https://docs.alpaca.markets/us/docs/options-level-3-trading))
- European-style option legs in an MLeg must have the same expiration, all legs must share an underlying, `position_intent` is required per leg, and invalid price/TIF combinations are rejected. ([Options Trading Overview error table](https://docs.alpaca.markets/us/docs/options-trading-overview))
- `GET /v2/orders?nested=true` and the single-order equivalent nest MLeg child orders under the parent. Alpaca's `trade_updates` WebSocket also provides parent/leg fill data for MLeg fills. ([Get All Orders](https://docs.alpaca.markets/us/reference/getallorders-1), [Websocket Streaming](https://docs.alpaca.markets/us/docs/websocket-streaming))

### Options order-class and TIF documentation discrepancy

The specific current Create Order API reference says option and MLeg order types are `market`/`limit`, option TIF is `day`, and option order classes are `simple`/`mleg`. The options overview says the same narrow surface. A broader general Orders guide currently contains a conflicting table that shows GTC and stop variants for options. Until an authenticated paper test proves otherwise, use the narrower, asset-specific API reference: MLeg limit + day. ([Create Order](https://docs.alpaca.markets/us/reference/postorder), [Options Trading Overview](https://docs.alpaca.markets/us/docs/options-trading-overview), [conflicting Orders guide](https://docs.alpaca.markets/us/docs/orders-at-alpaca))

## 6. Bracket, OCO, and OTO behavior for options

Alpaca defines `bracket`, `OCO`, and `OTO` as advanced order classes with attached take-profit/stop-loss behavior in its general orders guide. However, the current Create Order reference maps those classes to equities and maps options only to `simple` and `mleg`. Therefore:

- do not send `take_profit`/`stop_loss` on an options or spread entry;
- store the strategy's target, stop, time exit, and invalidation rule in the agent's own state;
- monitor the parent plus leg positions and close with an opposing MLeg limit order;
- make restart recovery reconstruct live positions/open orders before it acts; and
- cancel/replace the working MLeg exit rather than submitting duplicate exits.

The first statement is the documented support boundary; the remaining items are implementation implications. ([Create Order](https://docs.alpaca.markets/us/reference/postorder), [Orders guide](https://docs.alpaca.markets/us/docs/orders-at-alpaca), [Get All Orders](https://docs.alpaca.markets/us/reference/getallorders-1))

## 7. Order lifecycle and idempotency

Every submitted order has both an Alpaca order ID and a `client_order_id`; the latter is generated if omitted and may be supplied by the client up to 128 characters. Query by order ID/client ID and use the streaming interface to maintain current state. Common states include `new`, `partially_filled`, `filled`, `done_for_day`, `canceled`, `expired`, `replaced`, `pending_cancel`, and `pending_replace`; rarer terminal or intermediate states include `accepted`, `pending_new`, `rejected`, `suspended`, and `calculated`. ([Create Order](https://docs.alpaca.markets/us/reference/postorder), [Placing Orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca))

Use deterministic, unique `client_order_id` values and persist the decision before sending the order. On timeouts or restarts, look up that client ID before retrying; this is the agent's idempotency guard against duplicate exposure. The API supplies the identifier and lookup capability; the retry protocol is project design. ([Placing Orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca))

An order may be canceled until it reaches `filled`, `canceled`, or `expired`. Replace creates an updated order chain, so reconciliation must follow `replaced_by`/`replaces` and not treat the replacement as an unrelated position. ([Placing Orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca))

## 8. Clock and calendar

For a US-options agent, the legacy Trading API endpoints remain straightforward: `GET /v2/clock` returns the current timestamp, open/closed status, next open and next close; `GET /v2/calendar` returns trading days, open/close times, and early closures. ([US Market Clock](https://docs.alpaca.markets/us/reference/legacyclock), [US Market Calendar](https://docs.alpaca.markets/us/reference/legacycalendar))

Alpaca also documents newer multi-market Trading API endpoints: `GET /v3/clock?markets=...` and `GET /v3/calendar/{market}`. `OPRA` is an explicit supported market code for US options. These are useful if the agent needs an options-specific clock/calendar rather than a generic US equities session. ([Market Clock v3](https://docs.alpaca.markets/us/reference/clock-1), [Market Calendar v3](https://docs.alpaca.markets/us/reference/calendar-2), [2026 market-code changelog](https://docs.alpaca.markets/us/changelog/2026-06-04-market-codes-e8e76b9))

Use server-provided clock/calendar data instead of local weekday logic; gate opening trades to the chosen entry window and stop opening new positions before the project's end-of-day and expiration-risk cutoffs. The endpoints are Alpaca capability; the gates are strategy policy. ([Market Clock v3](https://docs.alpaca.markets/us/reference/clock-1), [Options expiration handling](https://docs.alpaca.markets/us/docs/options-trading-overview))

## 9. News, earnings, and corporate actions

Alpaca's News API at `GET /v1beta1/news` returns latest/historical stock and crypto news with symbol filters, time range, pagination, optional full content, and a maximum 50 items per page. Alpaca says historical news dates to 2015 and is supplied by Benzinga; real-time news is also available at `wss://stream.data.alpaca.markets/v1beta1/news`. ([News articles](https://docs.alpaca.markets/us/reference/news-3), [Historical News Data](https://docs.alpaca.markets/us/docs/historical-news-data), [Real-time News](https://docs.alpaca.markets/us/docs/streaming-real-time-news))

The current market-data Corporate Actions endpoint is `GET /v1/corporate-actions`, with symbol, date, and action-type filters. Alpaca warns that creation time is not guaranteed and announcements may be delayed. A new SSE stream can deliver insert/update/delete events and replay by timestamp or event ID. The older `/v2/corporate_actions/announcements` Trading API endpoint is marked deprecated. ([Corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1), [Corporate Actions SSE](https://docs.alpaca.markets/us/reference/subscribetocorporateactionseventssse), [deprecated announcements endpoint](https://docs.alpaca.markets/us/reference/get-v2-corporate_actions-announcements-1))

The reviewed public Trading/Market Data API documentation does not expose a dedicated forward earnings-calendar endpoint. News may mention earnings, and repository metadata for the MCP server uses the word "earnings" under corporate actions, but that is not a documented substitute for a structured earnings schedule. If the strategy needs known earnings dates, add another explicitly licensed provider or manually maintained calendar rather than inferring a reliable calendar from Alpaca news. ([Historical News Data](https://docs.alpaca.markets/us/docs/historical-news-data), [MCP server metadata](https://github.com/alpacahq/alpaca-mcp-server/blob/main/server.yaml), [Corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1))

## 10. Streaming and event processing

### Market data

The general market-data WebSocket form is `wss://stream.data.alpaca.markets/{version}/{feed}` and covers stocks, crypto, options, and news. Authentication may use Trading API headers or an auth message sent within 10 seconds. Many subscriptions allow only one connection to an endpoint; a second connection returns code 406. Alpaca provides an always-on test stream at `/v2/test` using symbol `FAKEPACA`. ([WebSocket Stream](https://docs.alpaca.markets/us/docs/streaming-market-data))

Options use `wss://stream.data.alpaca.markets/v1beta1/{indicative|opra}`. The option stream is MessagePack-only, supplies trade and quote channels, and forbids `*` for quote subscriptions. Use `OptionDataStream` from `alpaca-py` so binary decoding is handled by the SDK. ([Real-time Option Data](https://docs.alpaca.markets/us/docs/real-time-option-data), [`alpaca-py` option data reference](https://alpaca.markets/sdks/python/api_reference/data/option.html))

### Orders/account

Paper trade updates use `wss://paper-api.alpaca.markets/stream`; subscribe to `trade_updates`. Paper sends binary frames. Events include new, fill, partial fill, cancel, expire, replace, reject, and other lifecycle states, and MLeg events can include per-leg executions and resulting position quantities. ([Websocket Streaming](https://docs.alpaca.markets/us/docs/websocket-streaming))

The agent should make the stream its low-latency source but periodically reconcile REST account, open orders, and positions after disconnect/reconnect. Alpaca recommends streaming for order state; reconciliation is the project's resilience layer. ([Placing Orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca), [Websocket Streaming](https://docs.alpaca.markets/us/docs/websocket-streaming))

## 11. Rate limits

Current published Trading API market-data limits are plan-specific: Basic has 200 historical calls/minute and Algo Trader Plus has 10,000. Basic/Plus streaming symbol caps are 30/unlimited for equities and 200/1,000 option quotes. ([About Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api))

The current regular-account Trading API docs reviewed here do not publish a clearly current numeric order/account REST limit. An Alpaca-owned legacy Python client README says 200 requests per minute per account and HTTP 429 on excess, but that repository is not the current `alpaca-py` SDK and should not be treated as stronger than live response headers. Implement global throttling, inspect `X-RateLimit-*` where returned, honor `Retry-After`, and back off with jitter on 429. Confirm the fresh paper account's observed headers before finalizing polling intervals. ([legacy official SDK README](https://github.com/alpacahq/alpaca-trade-api-python), [current reference 429 guidance](https://docs.alpaca.markets/us/reference/optionsnapshots))

Broker API limits are a separate system: Alpaca now documents per-partner limits, `X-RateLimit-Limit/Remaining/Reset`, lower sandbox limits, and a prohibition on treating sandbox as a load-test target. Those Broker figures should not be copied into a retail Trading API configuration. ([Broker API Rate Limits](https://docs.alpaca.markets/us/docs/broker-api-rate-limits))

## 12. Official MCP server

### Setup and capability

Alpaca's MCP v2 requires Python 3.10+, `uv`/`uvx`, API keys, and an MCP-compatible client. A typical local configuration runs `uvx alpaca-mcp-server` with `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`; `ALPACA_PAPER_TRADE` defaults to `true`. Alpaca's docs list 65 tools across accounts, orders/positions, assets/contracts, market data, news, corporate actions, and watchlists, including option-chain/Greeks access and single-/multi-leg order placement. ([Trading MCP Server](https://docs.alpaca.markets/us/docs/alpaca-mcp-server), [official MCP repository](https://github.com/alpacahq/alpaca-mcp-server))

MCP v2 is a rewrite based on FastMCP/OpenAPI and is not drop-in compatible with v1. Tool names, parameters, and schemas may differ; restart the client, clear cached tool definitions, and start a fresh session after upgrades. Pin the package version used for judging and capture the dynamically discovered tool schema as an artifact. ([official MCP repository](https://github.com/alpacahq/alpaca-mcp-server))

### Tool filtering and security

`ALPACA_TOOLSETS` controls server-side capability groups. For this project, a tight operational set is `account,trading,assets,stock-data,options-data,news`; omit crypto, watchlists, and other unused surfaces. For analysis-only development sessions, omit `trading`. This is coarse toolset restriction, not a substitute for application-level risk checks. ([MCP configuration and toolsets](https://docs.alpaca.markets/us/docs/alpaca-mcp-server))

Run the MCP process with paper credentials only, keep the transport local unless a remote MCP deployment is intentionally secured, and never expose the environment or logs containing keys. Alpaca's repository supports local stdio and HTTP transports and advises tunneling/authenticated proxying for remote use; the current docs do not identify a generally hosted Alpaca remote Trading MCP endpoint. ([official MCP repository](https://github.com/alpacahq/alpaca-mcp-server))

The repository describes a trust-boundary middleware that wraps tool outputs to mitigate prompt injection, and marks third-party prose such as news as external text. The application must still keep news/LLM output advisory: only deterministic code should enforce allowed symbols, maximum debit, position count, daily loss, session time, and exact order payload validation. ([MCP repository architecture](https://github.com/alpacahq/alpaca-mcp-server/blob/main/AGENTS.md))

### MLeg verification gate

Alpaca MCP issue #97, opened 2026-07-01 and still shown open at research time, reports that Claude Desktop/Cowork passed the `legs` array as a string and blocked multi-leg `place_option_order`; single-leg orders worked. This report is client/bridge-specific, not proof that all MCP clients fail. Test the exact client with a dry-run or minimal paper spread. Keep REST/`alpaca-py` as the execution implementation while using MCP for visible account/data/decision interaction if the selected client cannot serialize MLeg correctly. ([official issue #97](https://github.com/alpacahq/alpaca-mcp-server/issues/97))

## 13. Official Alpaca CLI

Alpaca's CLI is an Alpha Preview; commands, flags, and output formats may change. Install with `go install github.com/alpacahq/cli/cmd/alpaca@latest` or Homebrew, then check `alpaca version` and `alpaca doctor`. Paper is the default; `--live` or `ALPACA_LIVE_TRADE=true` is an explicit live opt-in. ([Trading CLI](https://docs.alpaca.markets/us/docs/alpacas-cli), [CLI repository](https://github.com/alpacahq/cli))

OAuth login is available for paper; API-key login covers paper or live. Automation can use `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. API commands return structured JSON on stdout by default and JSON errors on stderr; documented exit codes are 0 success, 1 API/general error, and 2 authentication error. CSV, built-in jq filtering, quiet, schema, and timeout modes are also available. The CLI supports account, orders, positions, option contracts/exercise, option chains/snapshots/latest quotes, news, corporate actions, clock/calendar, and raw API access. ([Trading CLI documentation](https://docs.alpaca.markets/us/docs/alpacas-cli), [CLI output contract](https://github.com/alpacahq/cli#output))

The documented high-level order examples do not provide a stable MLeg `--legs` example. The raw command can send the exact supported JSON:

```powershell
$payload | alpaca api POST /v2/orders
```

Generate `$payload` from validated application state without embedding keys, and capture stdout/stderr and exit code in the agent audit log. Verify the pinned binary with `alpaca order submit --help`, `--schema`, and a paper call because the CLI is OpenAPI-generated and still Alpha. ([Trading CLI raw API and commands](https://docs.alpaca.markets/us/docs/alpacas-cli), [CLI repository](https://github.com/alpacahq/cli))

For unattended submissions, the CLI docs recommend `--client-order-id`; `--dry-run` previews a supported high-level order. The client retries HTTP 429 and 5xx responses with exponential backoff for up to three attempts and honors `Retry-After`. These behaviors reduce, but do not replace, the agent's persisted idempotency/reconciliation logic. ([CLI automation notes](https://github.com/alpacahq/cli#automation-notes))

The CLI documentation warns that commands such as cancel-all and close-all execute without confirmation. Do not expose these broad commands to the autonomous agent; call narrow order-ID or position-specific operations. ([Trading CLI important considerations](https://docs.alpaca.markets/us/docs/alpacas-cli))

## 14. Python SDK (`alpaca-py`)

`alpaca-py` is Alpaca's current official Python SDK. The current repository requires Python 3.10+ and installs with `pip install alpaca-py`. It separates clients by concern: `TradingClient` for account/trading; `OptionHistoricalDataClient` and `OptionDataStream` for options data; `StockHistoricalDataClient`/`StockDataStream` for underlyings; `NewsClient`/`NewsDataStream` for news; and `TradingStream` for account/order updates. ([official `alpaca-py` repository](https://github.com/alpacahq/alpaca-py), [SDK option data reference](https://alpaca.markets/sdks/python/api_reference/data/option.html))

`TradingClient(KEY, SECRET, paper=True)` defaults to paper, and typed Pydantic request/response models validate payloads. `OptionLegRequest` and MLeg-capable order requests are present; official SDK validation enforces two to four unique legs for MLeg. ([`TradingClient` reference](https://alpaca.markets/sdks/python/api_reference/trading/trading-client.html), [`alpaca-py` requests](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/trading/requests.py))

Use `alpaca-py` for the production agent loop because it gives typed requests, streams, and REST reconciliation. Use MCP or CLI as the hackathon-required integration and as a demonstrable operator interface, without forcing all internal orchestration through an LLM tool call. This is an architecture recommendation based on the official capabilities above. ([Trading MCP Server](https://docs.alpaca.markets/us/docs/alpaca-mcp-server), [Trading CLI](https://docs.alpaca.markets/us/docs/alpacas-cli), [`alpaca-py`](https://github.com/alpacahq/alpaca-py))

## 15. Paper simulation and testing limitations

Paper orders are not routed to an exchange; Alpaca simulates fills from real-time quotes. The simulator does not account for market impact, information leakage, latency slippage, order-queue position, price improvement, regulatory fees, or dividends. It does not check order size against available NBBO quantity, and eligible orders receive a random partial fill 10% of the time. Alpaca also simulates PDT checks. ([Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading))

These assumptions can inflate fill quality and capacity, particularly for multi-leg options. Treat paper P&L as the judging metric, not evidence of deployable live performance. Log the feed, quote timestamp, displayed bid/ask, theoretical mid, submitted net limit, fills, and latency so judges can see what the agent actually observed. The simulator facts come from Alpaca; the logging requirement is project design. ([Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading), [Options Level 3 Trading](https://docs.alpaca.markets/us/docs/options-level-3-trading))

Testing layers should be:

1. pure unit tests for thesis, sizing, risk gates, and order construction;
2. recorded fixture tests for nullable Greeks and sparse/zero quotes;
3. integration tests against the development paper account;
4. an always-on market-data socket test using `FAKEPACA` outside market hours;
5. small paper MLeg open/cancel/replace/close tests during market hours; and
6. a fresh-account smoke test before the judging run.

Alpaca provides the paper environment and test stream; the layered sequence is a recommended implementation plan. ([Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading), [WebSocket Stream](https://docs.alpaca.markets/us/docs/streaming-market-data), [MCP repository integration tests](https://github.com/alpacahq/alpaca-mcp-server/blob/main/AGENTS.md))

## 16. Implications for the Conviction Spread Agent

### Recommended architecture

1. **Deterministic market/risk core:** use `alpaca-py` to obtain underlying bars, contract metadata, option snapshots/chains, account state, and to construct validated MLeg requests. ([`alpaca-py`](https://github.com/alpacahq/alpaca-py))
2. **LLM thesis layer:** provide compact, structured market/news features and ask for a thesis, invalidation, confidence, and explanation. Treat news as untrusted external text and never let it determine raw order parameters directly. ([MCP security architecture](https://github.com/alpacahq/alpaca-mcp-server/blob/main/AGENTS.md), [News API](https://docs.alpaca.markets/us/reference/news-3))
3. **Hard risk gate:** allow only a small liquid universe, Level 3 account, defined-risk verticals, one-unit MVP orders, a maximum debit, maximum concurrent exposure, daily loss stop, fresh quotes, and market/expiry time windows. Account and order capabilities are documented; thresholds are project policy. ([Options Trading](https://docs.alpaca.markets/us/docs/options-trading), [Create Order](https://docs.alpaca.markets/us/reference/postorder))
4. **Atomic execution:** submit one MLeg limit/day order with deterministic `client_order_id`; monitor `trade_updates`, then reconcile REST. ([Options Level 3 Trading](https://docs.alpaca.markets/us/docs/options-level-3-trading), [Websocket Streaming](https://docs.alpaca.markets/us/docs/websocket-streaming))
5. **Agent-managed exit:** because options bracket/OCO/OTO are not in the supported option classes, send an opposing MLeg close when target, stop, invalidation, time, or global risk gate fires. ([Create Order](https://docs.alpaca.markets/us/reference/postorder))
6. **Hackathon MCP/CLI evidence:** run official MCP v2 with paper credentials and restricted toolsets for account/data/order inspection. If the selected client fails the MLeg-array test, execute through `alpaca-py` and use the official CLI raw POST or MCP for non-MLeg interactions; document the integration honestly. ([MCP docs](https://docs.alpaca.markets/us/docs/alpaca-mcp-server), [MCP issue #97](https://github.com/alpacahq/alpaca-mcp-server/issues/97), [CLI raw API](https://docs.alpaca.markets/us/docs/alpacas-cli))

### Data policy

- Prefer OPRA if the event supplies it; otherwise explicitly label the Indicative feed and its 15-minute/derived limitations. ([Historical Option Data](https://docs.alpaca.markets/us/docs/historical-option-data))
- Do not require Greeks for every candidate. Skip missing values or use a documented fallback rank based on DTE, moneyness, spread, and open interest; never coerce missing Greeks/IV to zero. ([Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq))
- Avoid 0DTE for the MVP because Greeks are unavailable and expiration liquidation begins late in the session. ([Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq), [Options Trading Overview](https://docs.alpaca.markets/us/docs/options-trading-overview))
- Use an explicit expiration range when listing contracts because the contracts endpoint otherwise defaults to the upcoming weekend. ([Get Option Contracts](https://docs.alpaca.markets/us/reference/get-options-contracts))

### Minimal proving trade

The first live-market integration proof should be one paper bull-call or bear-put debit spread on a liquid ETF, quantity one, with a marketable but capped net limit. Prove: discovery, nullable-Greeks handling, Level 3 preflight, MLeg acceptance, parent/leg event capture, cancel/replace, and opposing MLeg close. This is a recommended validation sequence derived from the official order/data surfaces. ([Options Level 3 Trading](https://docs.alpaca.markets/us/docs/options-level-3-trading), [Websocket Streaming](https://docs.alpaca.markets/us/docs/websocket-streaming))

## 17. Account/API verification checklist

These are unknown from public documentation or can vary by account/client. Verify them with the development account, then repeat the non-destructive checks on the fresh judging account.

- [ ] `GET /v2/account`: save both `id` and `account_number`; confirm with organizers which value the form calls "account ID." ([Get Account](https://docs.alpaca.markets/us/reference/getaccount-1), [`TradeAccount` model](https://alpaca.markets/sdks/python/api_reference/trading/models.html))
- [ ] Confirm `status`, `trading_blocked`, `options_buying_power`, `options_approved_level`, and `options_trading_level == 3`. ([`TradeAccount` model](https://alpaca.markets/sdks/python/api_reference/trading/models.html))
- [ ] Confirm the judging account's market-data plan and whether OPRA is available/allowed; the hackathon text does not state this. ([About Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api))
- [ ] Call option chain/snapshot with no explicit feed and with `feed=indicative`; record what fields/Greeks are populated. If entitled, repeat with `feed=opra`. ([Option chain](https://docs.alpaca.markets/us/reference/optionchain))
- [ ] Measure actual `X-RateLimit-*`/`Retry-After` behavior for account, order, contract, and data calls; current public docs do not provide one definitive retail Trading API number for every surface. ([Option snapshots 429 response](https://docs.alpaca.markets/us/reference/optionsnapshots))
- [ ] Verify exact paper MLeg rules with a quantity-one vertical: `day` limit, positive debit, two unique legs, simplified 1:1 ratios, explicit intents. ([Create Order](https://docs.alpaca.markets/us/reference/postorder), [Options Level 3 Trading](https://docs.alpaca.markets/us/docs/options-level-3-trading))
- [ ] Test cancel and replace of an unfilled parent MLeg and inspect the returned replacement chain. ([Options Trading Overview error table](https://docs.alpaca.markets/us/docs/options-trading-overview), [Placing Orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca))
- [ ] Test `trade_updates` disconnect/reconnect and compare the recovered state to REST open orders and positions. ([Websocket Streaming](https://docs.alpaca.markets/us/docs/websocket-streaming))
- [ ] Test the exact MCP client/version with `place_option_order` and a real array-valued `legs` parameter; issue #97 shows this is client-sensitive. ([MCP issue #97](https://github.com/alpacahq/alpaca-mcp-server/issues/97))
- [ ] Pin and record MCP, CLI, and `alpaca-py` versions and archive their discovered schemas/help output. MCP v2 and the Alpha CLI can change. ([MCP repository](https://github.com/alpacahq/alpaca-mcp-server), [CLI docs](https://docs.alpaca.markets/us/docs/alpacas-cli), [`alpaca-py`](https://github.com/alpacahq/alpaca-py))
- [ ] Ask organizers whether a dedicated earnings calendar is expected or supplied; Alpaca's documented News API is not a structured forward earnings calendar. ([Historical News Data](https://docs.alpaca.markets/us/docs/historical-news-data))
- [ ] Verify paper assignment/exercise behavior with the intended DTE policy only if the agent might hold through expiration; public paper docs do not spell out every options-specific simulator assumption. ([Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading), [Options Trading Overview](https://docs.alpaca.markets/us/docs/options-trading-overview))

## Bottom line

Alpaca can support the proposed project end to end in paper: contract discovery, underlying/options data, latest IV/Greeks, Level 3 atomic vertical spreads, account/order streams, news, and autonomous account management are all present. The safest implementation is a deterministic `alpaca-py` trading core with official MCP v2 as the required AI-tool interface, an optional pinned CLI/raw-API fallback, and strict agent-owned risk and exit logic. The three facts to prove first are **Level 3 on the actual account**, **usable data feed/Greeks**, and **MLeg serialization in the chosen MCP client**. ([Options Trading](https://docs.alpaca.markets/us/docs/options-trading), [Options snapshots](https://docs.alpaca.markets/us/reference/optionsnapshots), [MCP documentation](https://docs.alpaca.markets/us/docs/alpaca-mcp-server))
