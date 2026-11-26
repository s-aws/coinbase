"""Candidate in-memory reporting structures.

Production order state and persistence are owned by ``core.orderbook`` and
``database.order``. ``data.order_inventory`` remains available for a separate
architecture review, but it is not currently wired by the runtime entry point.
Import that submodule explicitly when reviewing or testing it.
"""
