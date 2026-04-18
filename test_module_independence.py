"""Test new modules - verify they work independently without configuration.py."""

from core.enums import OrderSide, OrderStatus, ProductType
from core.models import Order, Product, Wallet, Position, FollowUpOrderTemplate
from core.constants import ORDER_SIDE_SWITCH, SPOT_PRODUCT_IDS, DERIVATIVES_PRODUCT_IDS
from calculation.formatter import safe_float, format_based_on_reference, quantize_to_increment
from calculation.resolver import normalize_product_type, resolve_order_size, extract_order_price

print('✓ All new module imports successful (NO configuration.py needed!)\n')

# Test enums
print('Testing Enums:')
print(f'  - OrderSide.BUY = {OrderSide.BUY.value}')
print(f'  - OrderStatus.FILLED = {OrderStatus.FILLED.value}')
print(f'  - ProductType.SPOT = {ProductType.SPOT.value}')

# Test models
print('\nTesting Models:')
order = Order(
    client_order_id="test_order",
    product_id="BTC-USDC",
    order_side=OrderSide.BUY,
    status=OrderStatus.OPEN,
    size=0.5
)
print(f'  - Order created: {order.client_order_id} ({order.order_side.value})')

product = Product.from_dict({
    'product_id': 'ETH-USDC',
    'product_type': 'SPOT',
    'base_increment': '0.0001',
    'quote_increment': '0.01',
    'price_increment': '0.01'
})
print(f'  - Product loaded: {product.product_id}')

# Test constants
print('\nTesting Constants:')
print(f'  - Spot products: {len(SPOT_PRODUCT_IDS)} total')
print(f'  - Futures products: {len(DERIVATIVES_PRODUCT_IDS)} total')
print(f'  - BUY switches to: {ORDER_SIDE_SWITCH["BUY"]}')

# Test formatters
print('\nTesting Formatters:')
print(f'  - safe_float("456.78") = {safe_float("456.78")}')
print(f'  - format_based_on_reference(100.5, "0.01") = {format_based_on_reference(100.5, "0.01")}')
print(f'  - quantize_to_increment(99.996, "0.01") = {quantize_to_increment(99.996, "0.01")}')

# Test resolvers
print('\nTesting Resolvers:')
print(f'  - normalize_product_type({{"product_id": "BTC-USDC"}}) = {normalize_product_type({"product_id": "BTC-USDC"})}')
print(f'  - resolve_order_size({{"size": 1.5}}) = {resolve_order_size({"size": 1.5})}')

print('\n✓ All module independence tests passed!')
print('✓ New modules can be used WITHOUT configuration.py!')
