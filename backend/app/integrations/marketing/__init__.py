"""Marketing provider package — real external adapters.

One module per provider (resend, google_ads, meta_ads, instagram), plus
oauth_state for signed OAuth state tokens. All network I/O goes through
httpx with timeouts; all failures map to structured error codes.
"""
