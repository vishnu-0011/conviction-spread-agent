# Alpaca MCP — read-only Phase 5 profile

This profile requests Alpaca MCP v2's `assets`, `stock-data`, and `options-data`
toolsets while deliberately omitting `trading`. Alpaca also registers built-in
read-only documentation, crypto-data, calendar, and screener tools. The verified
registry contains no account or trading tools.

## Local setup

1. Copy `alpaca-readonly.example.json` into the MCP configuration location used by
   your client.
2. Replace the two placeholder values locally with development paper credentials.
3. Never commit the populated configuration. Keep paper mode set to `true`.
4. Start or reload the MCP client. `uvx` downloads and launches the pinned server.
5. Confirm the available Alpaca tools cover assets, stock data, and option data—and
   that no trading tools are listed.

Alpaca MCP 2.2.0 currently declares `fastmcp>=3.1.0`, which allowed the incompatible
FastMCP 4.0.0 release to install. The server then failed on the removed
`fastmcp.tools.tool` module. The example pins FastMCP 3.1.0, which was verified against
an actual tool-list handshake and live IEX SPY snapshot call.

Run the reproducible verifier from the repository root:

```powershell
python scripts/verify_mcp_readonly.py `
  --output docs/evidence/phase-5-mcp-readonly-proof.json
```

The committed example contains placeholders only. The main shadow runner reads
credentials from the ignored repository `.env`; it does not read this example.

Official references:

- [Alpaca MCP Server documentation](https://docs.alpaca.markets/us/docs/alpaca-mcp-server)
- [Alpaca MCP Server source](https://github.com/alpacahq/alpaca-mcp-server)
