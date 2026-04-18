#!/usr/bin/env python3
"""Monitor which products are receiving ticker data."""

import time
from collections import defaultdict
from configuration import Subscription

ticker_counts = defaultdict(int)

# Quick monkey patch to track tickers
original_stdout = __import__('sys').stdout

class TickerMonitor:
    def write(self, text):
        if "[TICKER-EVENT]" in text:
            # Extract products from log line
            import re
            match = re.search(r"\['([^']+)'\]", text)
            if match:
                product = match.group(1)
                ticker_counts[product] += 1
        original_stdout.write(text)
    
    def flush(self):
        original_stdout.flush()

__import__('sys').stdout = TickerMonitor()

# Run engine for N seconds
print("\n=== Monitoring ticker data (run engine in another terminal) ===")
print(f"Subscribed products: {len(Subscription.product_ids)}")
print("Waiting for tickers...\n")

try:
    while True:
        time.sleep(5)
        if ticker_counts:
            print(f"\n=== Products receiving ticker data ({len(ticker_counts)} of {len(Subscription.product_ids)}) ===")
            for product in sorted(ticker_counts.keys(), key=lambda x: ticker_counts[x], reverse=True)[:10]:
                print(f"  {product}: {ticker_counts[product]} events")
except KeyboardInterrupt:
    print("\n=== Final Report ===")
    products_with_data = set(ticker_counts.keys())
    missing_products = set(Subscription.product_ids) - products_with_data
    
    print(f"Products WITH data ({len(products_with_data)}):")
    for p in sorted(products_with_data):
        print(f"  ✓ {p}: {ticker_counts[p]} events")
    
    if missing_products:
        print(f"\nProducts WITHOUT data ({len(missing_products)}):")
        for p in sorted(missing_products)[:10]:
            print(f"  ✗ {p}")
        if len(missing_products) > 10:
            print(f"  ... and {len(missing_products) - 10} more")
