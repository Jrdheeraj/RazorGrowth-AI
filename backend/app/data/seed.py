"""
Deterministic database seed script.

Produces a realistic synthetic dataset that intentionally contains patterns
useful for the Growth Engine:
  - Headphones are the dominant product (~75% of orders)
  - Headphone cases are under-purchased relative to headphone buyers
  - Returning customers have higher AOV than new customers
  - Some customers have multiple purchases
  - Some payments failed (retryable)
  - Some customers have never bought accessories

Running this script twice produces identical data — idempotency is achieved
by keying every record on a stable natural key and using get-or-create logic.

Usage:
    python -m backend.app.data.seed
    # or via the helper at project root:
    python scripts/seed.py
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.db.engine import build_engine
from backend.app.db.session import init_db, get_session_factory
from backend.app.core.config import get_settings
from backend.app.models import (
    Merchant,
    Product,
    Customer,
    Order,
    OrderItem,
    Payment,
    GrowthOpportunity,
)
from backend.app.models.enums import (
    Currency,
    CustomerSegment,
    MerchantStatus,
    OpportunityStatus,
    OpportunityType,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
)

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Deterministic UUID helpers
# All UUIDs are derived from a stable namespace + natural key so the same
# logical record always gets the same UUID across seed runs.
# --------------------------------------------------------------------------- #
_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(_NS, key)


# --------------------------------------------------------------------------- #
# Raw seed data definitions
# --------------------------------------------------------------------------- #

MERCHANT_DATA = {
    "key": "merchant_demo",
    "name": "Demo Electronics Store",
    "slug": "demo-electronics",
    "email": "admin@demo-electronics.example",
    "status": MerchantStatus.active,
    "currency": Currency.INR,
}

PRODUCT_DATA = [
    {
        "key": "prod_headphones",
        "name": "Wireless Headphones",
        "description": "Premium over-ear wireless headphones with ANC.",
        "category": "audio",
        "price": Decimal("1999.00"),
        "sku": "SKU-HEADPHONES-001",
        "stock_quantity": 500,
        "active": True,
    },
    {
        "key": "prod_case",
        "name": "Protective Headphone Case",
        "description": "Hard-shell protective case for wireless headphones.",
        "category": "accessories",
        "price": Decimal("299.00"),
        "sku": "SKU-CASE-001",
        "stock_quantity": 300,
        "active": True,
    },
    {
        "key": "prod_earbuds",
        "name": "Premium Earbuds",
        "description": "True wireless earbuds with active noise cancellation.",
        "category": "audio",
        "price": Decimal("1499.00"),
        "sku": "SKU-EARBUDS-001",
        "stock_quantity": 400,
        "active": True,
    },
    {
        "key": "prod_stand",
        "name": "Aluminium Laptop Stand",
        "description": "Adjustable aluminium laptop stand for desk ergonomics.",
        "category": "desk",
        "price": Decimal("1299.00"),
        "sku": "SKU-STAND-001",
        "stock_quantity": 200,
        "active": True,
    },
    {
        "key": "prod_cable",
        "name": "USB-C Braided Cable 2m",
        "description": "Premium braided USB-C to USB-C cable, 2 metre.",
        "category": "accessories",
        "price": Decimal("199.00"),
        "sku": "SKU-CABLE-001",
        "stock_quantity": 1000,
        "active": True,
    },
    {
        "key": "prod_hub",
        "name": "7-in-1 USB-C Hub",
        "description": "USB-C hub with HDMI, USB-A, SD card reader and more.",
        "category": "desk",
        "price": Decimal("2499.00"),
        "sku": "SKU-HUB-001",
        "stock_quantity": 150,
        "active": True,
    },
    {
        "key": "prod_mousepad",
        "name": "XL Desk Mousepad",
        "description": "Extra-large desk mousepad with stitched edges.",
        "category": "desk",
        "price": Decimal("499.00"),
        "sku": "SKU-MOUSEPAD-001",
        "stock_quantity": 250,
        "active": True,
    },
    {
        "key": "prod_speaker",
        "name": "Portable Bluetooth Speaker",
        "description": "Waterproof portable Bluetooth speaker, 20W.",
        "category": "audio",
        "price": Decimal("2999.00"),
        "sku": "SKU-SPEAKER-001",
        "stock_quantity": 180,
        "active": True,
    },
    {
        "key": "prod_webcam",
        "name": "1080p USB Webcam",
        "description": "Full HD webcam with built-in microphone.",
        "category": "desk",
        "price": Decimal("1799.00"),
        "sku": "SKU-WEBCAM-001",
        "stock_quantity": 120,
        "active": True,
    },
    {
        "key": "prod_keyboard",
        "name": "Mechanical Wireless Keyboard",
        "description": "Compact TKL mechanical keyboard, Bluetooth + 2.4GHz.",
        "category": "desk",
        "price": Decimal("3499.00"),
        "sku": "SKU-KEYBOARD-001",
        "stock_quantity": 100,
        "active": True,
    },
]

# --------------------------------------------------------------------------- #
# Customer generation — 60 deterministic customers
# Segments: every 3rd customer is "new", others are "returning"
# --------------------------------------------------------------------------- #
def _build_customers(count: int = 60) -> list[dict]:
    customers = []
    for i in range(1, count + 1):
        segment = CustomerSegment.new if i % 3 == 0 else CustomerSegment.returning
        customers.append(
            {
                "key": f"customer_{i:03}",
                "name": f"Customer {i:03}",
                "email": f"customer{i:03}@example.com",
                "phone": f"+91900000{i:04}",
                "segment": segment,
            }
        )
    return customers


CUSTOMER_DATA = _build_customers(60)

# --------------------------------------------------------------------------- #
# Order generation helpers
# --------------------------------------------------------------------------- #
_BASE_DATE = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def _order_date(offset_days: int) -> datetime:
    return _BASE_DATE + timedelta(days=offset_days)


# --------------------------------------------------------------------------- #
# Seeding functions
# --------------------------------------------------------------------------- #

def _get_or_create_merchant(db: Session) -> Merchant:
    merchant_id = _uuid(MERCHANT_DATA["key"])
    merchant = db.get(Merchant, merchant_id)
    if merchant:
        log.info("Merchant already exists — skipping.")
        return merchant

    merchant = Merchant(
        id=merchant_id,
        name=MERCHANT_DATA["name"],
        slug=MERCHANT_DATA["slug"],
        email=MERCHANT_DATA["email"],
        status=MERCHANT_DATA["status"],
        currency=MERCHANT_DATA["currency"],
    )
    db.add(merchant)
    db.flush()
    log.info("Created merchant: %s", merchant.slug)
    return merchant


def _get_or_create_products(db: Session, merchant: Merchant) -> dict[str, Product]:
    products: dict[str, Product] = {}
    for p in PRODUCT_DATA:
        product_id = _uuid(f"{merchant.id}_{p['key']}")
        product = db.get(Product, product_id)
        if not product:
            product = Product(
                id=product_id,
                merchant_id=merchant.id,
                name=p["name"],
                description=p["description"],
                category=p["category"],
                price=p["price"],
                currency=merchant.currency,
                sku=p["sku"],
                stock_quantity=p["stock_quantity"],
                active=p["active"],
            )
            db.add(product)
            log.debug("Created product: %s", p["name"])
        products[p["key"]] = product
    db.flush()
    log.info("Products seeded: %d", len(products))
    return products


def _get_or_create_customers(db: Session, merchant: Merchant) -> list[Customer]:
    customers: list[Customer] = []
    for c in CUSTOMER_DATA:
        cust_id = _uuid(f"{merchant.id}_{c['key']}")
        customer = db.get(Customer, cust_id)
        if not customer:
            customer = Customer(
                id=cust_id,
                merchant_id=merchant.id,
                name=c["name"],
                email=c["email"],
                phone=c["phone"],
                segment=c["segment"],
            )
            db.add(customer)
        customers.append(customer)
    db.flush()
    log.info("Customers seeded: %d", len(customers))
    return customers


def _get_or_create_orders(
    db: Session,
    merchant: Merchant,
    customers: list[Customer],
    products: dict[str, Product],
) -> None:
    """
    Create 240 deterministic orders.

    Order pattern (intentional for growth engine analysis):
      - 75% headphone orders
      -  8% case orders (intentionally low — cross-sell signal)
      -  7% earbuds
      -  4% laptop stand
      -  3% speaker
      -  3% keyboard
    VIP customers (i % 5 == 0) also buy the hub or webcam as a second item.
    Every 7th payment fails (retry signal).
    """
    product_rotation = [
        "prod_headphones", "prod_headphones", "prod_headphones",
        "prod_case",
        "prod_headphones", "prod_headphones", "prod_headphones",
        "prod_earbuds",
        "prod_headphones", "prod_headphones",
        "prod_stand",
        "prod_headphones",
        "prod_speaker",
        "prod_headphones", "prod_headphones",
        "prod_keyboard",
    ]

    for i in range(1, 241):
        order_key = f"order_{i:04}"
        order_id = _uuid(f"{merchant.id}_{order_key}")
        if db.get(Order, order_id):
            continue

        customer = customers[(i - 1) % len(customers)]
        primary_product_key = product_rotation[(i - 1) % len(product_rotation)]
        primary_product = products[primary_product_key]

        # Build line items
        items_data: list[tuple[Product, int]] = [(primary_product, 1)]

        # VIP customers occasionally buy a secondary desk item
        if i % 5 == 0:
            secondary = products.get("prod_hub") or products.get("prod_webcam")
            if secondary and secondary.id != primary_product.id:
                items_data.append((secondary, 1))

        subtotal = sum(p.price * qty for p, qty in items_data)
        total = subtotal  # no discount/tax in seed data

        # Determine order status
        if i % 7 == 0:
            order_status = OrderStatus.confirmed  # payment will fail
        else:
            order_status = OrderStatus.paid

        order = Order(
            id=order_id,
            merchant_id=merchant.id,
            customer_id=customer.id,
            order_number=f"ORD-{i:05}",
            status=order_status,
            subtotal=subtotal,
            discount=Decimal("0.00"),
            tax=Decimal("0.00"),
            total=total,
            currency=merchant.currency,
        )
        order.created_at = _order_date(i % 180)  # spread over ~6 months
        db.add(order)
        db.flush()

        # Order items
        for product, qty in items_data:
            item_key = f"item_{i:04}_{product.sku}"
            item_id = _uuid(f"{merchant.id}_{item_key}")
            item = OrderItem(
                id=item_id,
                order_id=order.id,
                product_id=product.id,
                quantity=qty,
                unit_price=product.price,
                line_total=product.price * qty,
            )
            db.add(item)

        # Payment
        payment_key = f"payment_{i:04}"
        payment_id = _uuid(f"{merchant.id}_{payment_key}")
        if i % 7 == 0:
            # Intentionally failed payment — useful for recovery opportunity
            payment = Payment(
                id=payment_id,
                merchant_id=merchant.id,
                order_id=order.id,
                provider=PaymentProvider.synthetic,
                provider_payment_id=None,
                amount=total,
                currency=merchant.currency,
                status=PaymentStatus.failed,
                failure_code="INSUFFICIENT_FUNDS",
                failure_reason="Synthetic failed payment for growth engine testing.",
            )
        else:
            payment = Payment(
                id=payment_id,
                merchant_id=merchant.id,
                order_id=order.id,
                provider=PaymentProvider.synthetic,
                provider_payment_id=f"pay_synthetic_{i:06}",
                amount=total,
                currency=merchant.currency,
                status=PaymentStatus.captured,
            )
        db.add(payment)

    db.flush()
    log.info("Orders and payments seeded.")


def _update_customer_stats(db: Session, merchant: Merchant) -> None:
    """Recompute total_orders / total_spend for each customer from orders."""
    from sqlalchemy import func, select
    from backend.app.models.order import Order as OrderModel

    rows = (
        db.execute(
            select(
                OrderModel.customer_id,
                func.count(OrderModel.id).label("cnt"),
                func.sum(OrderModel.total).label("spend"),
            )
            .where(
                OrderModel.merchant_id == merchant.id,
                OrderModel.status.in_([OrderStatus.paid, OrderStatus.delivered]),
            )
            .group_by(OrderModel.customer_id)
        )
        .all()
    )
    for row in rows:
        customer = db.get(Customer, row.customer_id)
        if customer:
            customer.total_orders = row.cnt
            customer.total_spend = row.spend or Decimal("0.00")
    db.flush()
    log.info("Customer stats updated for %d customers.", len(rows))


def ensure_catalog_for_merchant(db: Session, merchant: Merchant) -> dict[str, Product]:
    """
    Provision the standard product catalog for an existing merchant.

    Idempotent: reuses the same deterministic natural-key pattern as
    _get_or_create_products, so calling it twice creates nothing new.

    Intended for merchants created through Razorpay TEST ingestion, which
    auto-create only a single generic placeholder product (price ₹0, no
    stock) for orders without line items. This gives such merchants the
    same real, purchasable catalog used across the system.
    """
    return _get_or_create_products(db, merchant)


def run_seed(db: Session) -> None:
    """
    Execute the full seed sequence inside a caller-managed transaction.

    The caller is responsible for commit() and rollback().
    """
    log.info("Starting deterministic seed…")
    merchant = _get_or_create_merchant(db)
    products = _get_or_create_products(db, merchant)
    customers = _get_or_create_customers(db, merchant)
    _get_or_create_orders(db, merchant, customers, products)
    _update_customer_stats(db, merchant)
    log.info("Seed complete.")


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        stream=sys.stdout,
    )
    settings = get_settings()
    engine = build_engine(settings.DATABASE_URL)
    init_db(engine)
    factory = get_session_factory()
    with factory() as db:
        try:
            run_seed(db)
            db.commit()
            print("Seed committed successfully.")
        except Exception:
            db.rollback()
            log.exception("Seed failed — rolled back.")
            sys.exit(1)
