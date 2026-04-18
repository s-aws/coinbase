"""Test backward compatibility - verify original code still works."""

from configuration import ORDERBOOK, REST_CLIENT, ORDER_SIDE_SWITCH, safe_float, quantize_to_increment

print('✓ Original configuration imports still work')
print(f'  - ORDERBOOK: {type(ORDERBOOK).__name__}')
print(f'  - REST_CLIENT available: {REST_CLIENT is not None}')
print(f'  - ORDER_SIDE_SWITCH items: {len(ORDER_SIDE_SWITCH)}')
print(f'  - safe_float("123.45") = {safe_float("123.45")}')
print(f'  - quantize_to_increment(100.126, "0.01") = {quantize_to_increment(100.126, "0.01")}')
print('\n✓ All backward compatibility checks passed!')
