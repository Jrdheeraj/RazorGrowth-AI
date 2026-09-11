"""MarketingAGI — autonomous marketing employee (isolated module).

This package is a COMPLETELY SEPARATE agent system from the legacy
MarketingAgent (backend/app/agents/marketing_agent.py). It shares only
generic platform infrastructure (auth, tenancy, DB session, LLM provider
abstraction, action/approval pipeline, knowledge store). No logic is
imported from or shared with the legacy agent.
"""
