"""One-shot: propagate placement-row status to chain root for the affected order."""
from database.order import get_parent_order, update_order_parent_status

PLACEMENT = "f6281a12-8b4d-43e1-9059-553bd832ed96"
ROOT = "2f274206-ec40-49db-8302-e53a951bdccb"

placement = get_parent_order(PLACEMENT)
root = get_parent_order(ROOT)
print("Placement status:", placement["status"])
print("Root status (before):", root["status"])

if placement["status"] != root["status"]:
    update_order_parent_status(ROOT, placement["status"])
    root_after = get_parent_order(ROOT)
    print("Root status (after):", root_after["status"])
else:
    print("No change needed.")
