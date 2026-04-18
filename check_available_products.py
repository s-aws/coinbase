#!/usr/bin/env python3
"""Get actual available products from Coinbase."""

from configuration import REST_CLIENT

try:
    # Get all products
    products_response = REST_CLIENT.get_products()
    
    # Handle different response formats
    if isinstance(products_response, dict):
        products = products_response.get('products', [])
    elif isinstance(products_response, list):
        products = products_response
    else:
        print(f"Unexpected response type: {type(products_response)}")
        print(f"Response: {products_response}")
        products = []
    
    # Filter out None values
    products = [p for p in products if p is not None]
    
    # Separate into spot and derivatives
    spot = []
    derivatives = []
    
    for product in products:
        if not isinstance(product, dict):
            continue
        product_id = product.get('id')
        product_type = product.get('product_type', 'SPOT')
        
        if product_id:
            if product_type == 'SPOT':
                spot.append(product_id)
            else:
                derivatives.append(product_id)
    
    print(f"=== Available Products from Coinbase ===")
    print(f"Spot products ({len(spot)}):")
    for p in sorted(spot)[:20]:
        print(f"  {p}")
    if len(spot) > 20:
        print(f"  ... and {len(spot) - 20} more")
    
    print(f"\nDerivatives products ({len(derivatives)}):")
    for p in sorted(derivatives)[:20]:
        print(f"  {p}")
    if len(derivatives) > 20:
        print(f"  ... and {len(derivatives) - 20} more")
    
    # Check what we're subscribed to
    print(f"\n=== Current Subscription ===")
    from configuration import Subscription
    print(f"Subscribed spot: {Subscription.product_ids[len(Subscription.derivatives_product_ids):]}")
    print(f"Subscribed derivatives: {Subscription.derivatives_product_ids}")
    
    # Find mismatches
    print(f"\n=== Product Mismatches ===")
    subscribed = set(Subscription.product_ids)
    available = set(spot + derivatives)
    
    not_available = subscribed - available
    if not_available:
        print(f"Subscribed but not available: {not_available}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
