import dashboard_server as ds
s = ds._build_investor_storyboard_snapshot()
print('Candles with group_id:')
for c in s['candles'][:5]:
    group = c.get('group_id')
    group_str = group[:8] + '...' if group else 'None'
    print(f"  {c['label']}: group={group_str}")
