"""MCP servers — one module per provider surface.

Each module declares its tools (``TOOLS``) and the legacy MarketingAGI tool
names they replace (``ALIASES``). Handlers delegate to the EXISTING
provider implementations and services; MCP standardizes the contract,
policy and observability around them without duplicating their logic.

    internal_marketing  CRM + analytics + knowledge reads (tenant-scoped)
    email               Resend connection reads + approval-gated send
    google_ads          live Google Ads reads + approval-gated PAUSED create
    meta_ads            live Meta Ads reads + approval-gated PAUSED create
    instagram           verified identity read + approval-gated publish
"""