"""
Deterministic synthetic commerce dataset.

All data is hard-coded or generated with a fixed seed so that the application
behaves identically on every restart. This module is the single source of
truth for Phase 1 in-memory data. It will be replaced by database-seeded
fixtures when the persistence layer is introduced.
"""
from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
PRODUCTS: list[dict[str, Any]] = [
    {"id": "prod_headphones", "name": "Wireless Headphones",      "price": 1999, "category": "audio"},
    {"id": "prod_case",       "name": "Protective Headphone Case", "price": 299,  "category": "accessories"},
    {"id": "prod_earbuds",    "name": "Premium Earbuds",           "price": 1499, "category": "audio"},
    {"id": "prod_stand",      "name": "Aluminium Laptop Stand",    "price": 1299, "category": "desk"},
]

# --------------------------------------------------------------------------- #
# Customers  (50 deterministic records)
# --------------------------------------------------------------------------- #
CUSTOMERS: list[dict[str, Any]] = [
    {
        "id": f"cust_{i:03}",
        "name": f"Customer {i:03}",
        "segment": "returning" if i % 3 else "new",
    }
    for i in range(1, 51)
]

# --------------------------------------------------------------------------- #
# Orders  (200 deterministic records)
# Ordering pattern: 3 out of every 4 orders are for headphones, 1 for the case.
# --------------------------------------------------------------------------- #
ORDERS: list[dict[str, Any]] = [
    {
        "id": f"ord_{i:04}",
        "customer_id": CUSTOMERS[(i - 1) % len(CUSTOMERS)]["id"],
        "product_id":  "prod_headphones" if i % 4 else "prod_case",
        "amount":      1999 if i % 4 else 299,
        "status":      "paid",
    }
    for i in range(1, 201)
]
