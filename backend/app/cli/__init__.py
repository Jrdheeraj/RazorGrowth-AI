"""Operational entry points for RazorGrowth AI.

Deliberately a thin package: each module is a runnable ``python -m`` entry point
that wires an existing service to a process. No business logic lives here, so
adding an operator command never risks forking the behaviour it invokes.
"""