""" Configuration """

from os import getenv
from coinbase.rest import RESTClient

API_KEY = getenv("COINBASE_API_KEY")
API_SECRET = getenv("COINBASE_API_SECRET")

REST_CLIENT = RESTClient(
    api_key = API_KEY,
    api_secret = API_SECRET)

ORDER_SIDE_SWITCH = {
    "BUY": "SELL",
    "SELL": "BUY"
}

ORDER_POST_ONLY = { # allow this to be based on side
    "BUY": False, # set both to True when testing to keep accidental orders to a min
    "SELL": False
}

ORDER_POSITION_SIDE = {
    "SHORT": "SELL",
    "LONG": "BUY",
    "SELL": "SHORT",
    "BUY": "LONG"
}

ORDER_DIRECTION = { # ensure the direction is correct (away from last fill)
    "SELL": 1, # price gets larger
    "BUY": -1 # price gets smaller
    # unless it's backwards day
}

DERIVATIVES_MANDATORY_FEE_PER_CONTRACT = 0.15 # this is the fee per contract that is charged on all future close orders, so we need to factor this into our move calculations to ensure we are still profitable after fees

DERIVATIVES_PRODUCT_IDS = [
    "BIP-20DEC30-CDE",
    "ETP-20DEC30-CDE",
    "XPP-20DEC30-CDE",
    "SLP-20DEC30-CDE",
    "ADP-20DEC30-CDE",
    "DOP-20DEC30-CDE",
    "BCP-20DEC30-CDE",
    "SUP-20DEC30-CDE",
    "AVP-20DEC30-CDE",
    "XLP-20DEC30-CDE",
    "LNP-20DEC30-CDE",
    "LCP-20DEC30-CDE",
    "POP-20DEC30-CDE",
    "HEP-20DEC30-CDE",
    "SLR-28APR26-CDE",
    "GOL-27MAR26-CDE",
    "NOL-19MAR26-CDE",
    "PT-27MAR26-CDE",
    "CU-28APR26-CDE",
    "PAU-20DEC30-CDE"
]

SPOT_PRODUCT_IDS = [
    "DOT-BTC",
    "NCT-USDC",
    "BTC-USDC",
    "LTC-USDC",
    "ETH-USDC",
    "MON-USDC",
    "ZKP-USDC",
    "WET-USDC",
    "XPL-USDC",
    "DOGE-USDC",
    "SENT-USDC"
]

def format_based_on_reference(value_to_format: float, reference_float: str):
    """
    Formats a float to match the number of decimal places of a reference float.
    """

    result = "0"

    result = f"{value_to_format:.{len(str(reference_float).rsplit('.', maxsplit=1)[-1]) \
        if '.' in str(reference_float) else 0}f}"

    return result

def rest_get_account_wallets() -> dict:
    """ Create a dictionary in the format
    { "currency1": {}, "currency2": {} } """

    accounts_list = REST_CLIENT.get_accounts()["accounts"]

    account_wallets = {
        item["currency"]: item for item in accounts_list if item["deleted_at"] is None
    }

    return account_wallets

def rest_get_products() -> dict:
    """ Create a dictionary in the format
    { "currency1": {}, "currency2": {} } """

    products_list = [
        REST_CLIENT.get_product(product_id) for
            product_id in DERIVATIVES_PRODUCT_IDS + SPOT_PRODUCT_IDS]

    products = {
        item["product_id"]: item for item in products_list if item["trading_disabled"] is False
    }

    return products

def get_futures_positions() -> dict:
    """ Create a dictionary in the format
    { "product_id1": {}, "product_id2": {} } """

    futures_list = REST_CLIENT.list_futures_positions().to_dict()["positions"]

    if futures_list:
        positions = {
            position["product_id"]: position for position in futures_list
        }
    else:
        positions = {}

    return positions

class OrderBook():
    """ Container for Order tracking """
    transaction_summary = REST_CLIENT.get_transaction_summary() # includes fees

    should_replace = {
        "CANCELLED": True,
        "FILLED": True
    }

    cancelled = {}
    filled = {}
    order = {}
    price = {}
    product = rest_get_products()
    mandatory_fee_per_contract = {
        product_id: {
            "mandatory_fee_per_contract": (
                DERIVATIVES_MANDATORY_FEE_PER_CONTRACT / float(this.to_dict().get("future_product_details", {}).get("contract_size", 1))
            ) if this["product_type"] == "FUTURE" else 0
        } for product_id, this in product.items()
    }

    active = {
        # "MON-USDC": {
        #     "0.021430": ["69cd5aeb-3d4e-41e6-8b2d-2cb5b24007ec"],
        #     "0.021410": ["d9cd5aeb-3d4e-41e6-8b2d-2cb5b24007af"],
        #     "0.021530": ["39cd5aeb-3d4e-41e6-8b2d-2cb5b2400700"],
        # } # sample
    }

    profit = {
        "SPOT": { 
            "BUY": float(transaction_summary["fee_tier"]["taker_fee_rate"]) * 4,
            "SELL": float(transaction_summary["fee_tier"]["taker_fee_rate"]) * 4
        },
        "FUTURE": {
            "BUY": 0.02,
            "SELL": 0.02
        }
    }

    positions = {
        "FUTURE": get_futures_positions()
    }

    def calculate_new_order_move(self, order_id) -> dict:
        """ Return the new order after calculations
            the current order is treated as the last filled or cancelled order that we are trying to move from,
            so we can calculate the new price based on the last price and the profit target,
            and then we can place a new order at the new price with the same size as the original order
            
            filled orders go in the opposite direction
            cancelled orders go in the same direction
            
            we currently do not take into account partial fills or partial cancellations for simplicity,
            but this could be added in the future by calculating the move based on the filled or cancelled size
            instead of the original order size (would require two different move calculations) """

        order = self.order.get(order_id)
        if not order:
            print(f"ORDER NOT FOUND {order_id}")
            return {}

        order_product_id = order["product_id"]
        order_product_type = order["product_type"]
        order_status = order["status"]
        order_side = order["order_side"]
        order_size = float(
            order["leaves_quantity"] if float(order["leaves_quantity"]) > 0
                else order["cumulative_quantity"])

        mandatory_fee = self.mandatory_fee_per_contract[order_product_id]["mandatory_fee_per_contract"]
        base_increment = ORDERBOOK.product[order_product_id]["base_increment"]
        quote_increment = ORDERBOOK.product[order_product_id]["quote_increment"]
        price_increment = self.product[order_product_id]["price_increment"]

        if order_status == "FILLED":
            order_side = ORDER_SIDE_SWITCH[order_side]

        if order_status == "CANCELLED":
            order_size = float(order["leaves_quantity"])

        if order.get("limit_price"):
            order_float_price = float(order["limit_price"])
        elif order.get("avg_price") != "0":
            order_float_price = float(order["avg_price"])
        else:
            print(f"UNKNOWN PRICE FROM ORDER {order}")
            return {}

        # get the two different ways to calculate move amount

        minimum_move_amount = float(price_increment)
        fee_move_calculated_from_pct = order_float_price * self.profit[order_product_type][order_side]

        order_move_amount = fee_move_calculated_from_pct if (
            minimum_move_amount < fee_move_calculated_from_pct) else minimum_move_amount 

        # set direction here
        order_move_difference = order_move_amount * ORDER_DIRECTION[order_side]

        # If FUTURE, include a 0.15 per contract mandatory fee on close orders
        if order_product_type == "FUTURE":
            if order_product_id not in self.positions[order_product_type]:
                 # update all positions via rest call
                self.positions[order_product_type] = get_futures_positions()
                print(self.positions[order_product_type])

            if order_status == "FILLED":
                if order_product_type not in self.positions:
                    self.positions[order_product_type] = {}

                if order_product_id in self.positions[order_product_type]:
                    number_of_contracts = float(self.positions[order_product_type][order_product_id]["number_of_contracts"])
                    if ORDER_POSITION_SIDE[self.positions[order_product_type][order_product_id]["side"]] == order_side: # an open was just filled so we need to create a close order
                        number_of_contracts -= order_size # an open was just filled so we decrease the current number of contracts in the position by the order size
                        mandatory_fee *= ORDER_DIRECTION[order_side] # this fee is for the new order we are generating, so we flip the direction to ensure it is added to the price properly

                        if number_of_contracts < 0:
                            number_of_contracts = abs(number_of_contracts) # if we are closing more contracts than we have in the position, we can't have negative contracts, so we set it to 0
                            self.positions[order_product_type][order_product_id]["side"] = ORDER_POSITION_SIDE[ORDER_SIDE_SWITCH[order_side]] # if we flip from long to short or vice versa, we need to update the position side for fee calculation on the next move

                    else: # a close was just filled so we need to create an open order
                        number_of_contracts += order_size # a close was just filled so we increase the current number of contracts in the position by the order size
                        mandatory_fee *= ORDER_DIRECTION[order_side] # to keep orders from sliding in one direction due to mandatory fees on closed positions
                    
                    self.positions[order_product_type][order_product_id]["number_of_contracts"] = str(number_of_contracts)

        # finalize floats
        order_new_price = order_float_price + order_move_difference + mandatory_fee

        order_new_price = float(format_based_on_reference(
            order_new_price,
            quote_increment))

        order_new_size = float(format_based_on_reference(
            order_size,
            base_increment))

        price_increment_len = len(price_increment)-2 if (
            len(price_increment) > 3) else 1

        base_increment_len = len(base_increment)-2 if (
            len(base_increment) > 3) else 1

        order_new_price -= order_new_price % float(price_increment)

        return {
            "current_contract_count": self.positions[order_product_type][order_product_id]["number_of_contracts"] if order_product_type == "FUTURE" and order_product_id in self.positions.get(order_product_type, {}) else "N/A",
            "mandatory_fee": mandatory_fee,
            "profit_move_pct": self.profit[order_product_type][order_side],
            "fee_move_calculated_from_pct": fee_move_calculated_from_pct,
            "minimum_move_amount": minimum_move_amount,
            "product_id": order_product_id,
            "side": order_side,
            "order_base_size": f"{order_new_size:.{base_increment_len}f}",
            "order_price_difference": f"{abs(order_move_difference):.{price_increment_len}f}",
            "start_price": f"{order_new_price:.{price_increment_len}f}"
        }

class Subscription():
    """ Websocket connection details """

    product_ids = DERIVATIVES_PRODUCT_IDS + SPOT_PRODUCT_IDS
    derivatives_product_ids = DERIVATIVES_PRODUCT_IDS

    channels = [
        "heartbeats",
        "user",
        "ticker",
        # "level2",
        # "market_trades"
    ]

ORDERBOOK = OrderBook()
