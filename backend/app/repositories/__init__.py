"""Repository package — exports all repository classes."""
from backend.app.repositories.merchant import MerchantRepository
from backend.app.repositories.product import ProductRepository
from backend.app.repositories.customer import CustomerRepository
from backend.app.repositories.order import OrderRepository
from backend.app.repositories.payment import PaymentRepository
from backend.app.repositories.opportunity import GrowthOpportunityRepository

__all__ = [
    "MerchantRepository",
    "ProductRepository",
    "CustomerRepository",
    "OrderRepository",
    "PaymentRepository",
    "GrowthOpportunityRepository",
]
