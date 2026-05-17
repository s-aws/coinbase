#!/usr/bin/env python3
"""Debug script to inspect order_event_stream table."""

from _bootstrap import ensure_repo_root

ensure_repo_root()

from database.database import PostgresDB

db = PostgresDB()

try:
    # Check if order_event_stream has any rows
    count_result = db.execute_query('SELECT COUNT(*) as cnt FROM order_event_stream')
    total_rows = count_result[0].get('cnt', 0) if count_result else 0
    print(f'Total rows in order_event_stream: {total_rows}')

    # Get event types and their counts
    print(f'\nEvent types in database:')
    samples = db.execute_query('''
        SELECT event_type, COUNT(*) as cnt 
        FROM order_event_stream 
        GROUP BY event_type 
        ORDER BY cnt DESC
    ''')
    
    if samples:
        for row in samples:
            print(f'  - {row.get("event_type")}: {row.get("cnt")} events')
    else:
        print('  (no event types found)')

    # Check schema columns
    print(f'\norder_event_stream columns:')
    schema = db.execute_query('''
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'order_event_stream'
        ORDER BY ordinal_position
    ''')
    
    for col in schema:
        print(f'  - {col.get("column_name")}: {col.get("data_type")}')

    # Get a few sample rows
    print(f'\nSample rows (first 3):')
    sample_rows = db.execute_query('''
        SELECT event_type, event_time_exchange, price, size, product_id
        FROM order_event_stream
        LIMIT 3
    ''')
    
    if sample_rows:
        for i, row in enumerate(sample_rows, 1):
            print(f'\n  Row {i}:')
            print(f'    event_type: {row.get("event_type")}')
            print(f'    event_time_exchange: {row.get("event_time_exchange")}')
            print(f'    price: {row.get("price")}')
            print(f'    size: {row.get("size")}')
            print(f'    product_id: {row.get("product_id")}')
    else:
        print('  (no rows found)')

    # Test the actual query used in snapshot
    print(f'\n\nTesting snapshot query (60 minute window):')
    test_query = '''
    SELECT 
        created_at as event_time,
        price,
        size,
        product_id,
        event_type
    FROM order_event_stream
    WHERE created_at >= NOW() - INTERVAL '60 minutes'
        AND price IS NOT NULL
        AND size IS NOT NULL
        AND event_type IN ('order_filled')
    ORDER BY created_at
    LIMIT 5
    '''
    
    test_results = db.execute_query(test_query)
    print(f'Query returned {len(test_results)} rows')
    if test_results:
        for row in test_results:
            print(f'  - {row}')
    
    # Try without time filter
    print(f'\n\nAll order_filled events (no time filter):')
    all_query = '''
    SELECT 
        created_at,
        price,
        size,
        event_type
    FROM order_event_stream
    WHERE event_type = 'order_filled'
    ORDER BY created_at DESC
    LIMIT 5
    '''
    
    all_results = db.execute_query(all_query)
    print(f'Found {len(all_results)} total order_filled events')
    if all_results:
        for i, row in enumerate(all_results, 1):
            print(f'\n  Event {i}:')
            print(f'    created_at: {row.get("created_at")}')
            print(f'    price: {row.get("price")}')
            print(f'    size: {row.get("size")}')

finally:
    db.disconnect()
    print('\nDone!')
