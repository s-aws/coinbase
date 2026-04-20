"""Lightweight WebSocket server for trading engine dashboard.

Provides real-time order updates, engine status, and manual order placement.
Runs as a separate thread alongside the main trading engine.

Usage:
    python dashboard_server.py  # Starts on ws://localhost:8765
    Then open dashboard.html in browser
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from threading import Thread, Lock
from queue import Queue
from typing import Set, Dict, Any
import websockets
from websockets.server import WebSocketServerProtocol

# Import REST client for order placement
try:
    from configuration import REST_CLIENT
    REST_CLIENT_AVAILABLE = True
except ImportError:
    REST_CLIENT_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DashboardServer")

# Global state
connected_clients: Set[WebSocketServerProtocol] = set()
state_lock = Lock()
engine_state = {
    "orders": {},  # order_id -> order_data
    "positions": {},  # product_id -> position_data
    "stealth_orders": {},  # stealth_order_id -> order_data
    "engine_status": {
        "running": False,
        "threads_active": 0,
        "event_queue_depth": 0,
        "last_update": None,
    },
    "logs": [],  # Recent log entries
}
max_logs = 100

# Event loop reference (set when server starts)
server_event_loop = None

# Stealth order bridge reference (set during integration)
stealth_order_bridge = None


async def register_client(websocket: WebSocketServerProtocol):
    """Register a new connected client."""
    connected_clients.add(websocket)
    logger.info(f"Client connected. Total clients: {len(connected_clients)}")
    
    # Send products list first
    try:
        import json as json_lib
        from pathlib import Path
        products_file = Path(__file__).parent / "products.json"
        if products_file.exists():
            with open(products_file, 'r') as f:
                products_data = json_lib.load(f)
                products_payload = {
                    "type": "products_list",
                    "derivatives": products_data.get("derivatives", []),
                    "spot": products_data.get("spot", []),
                    "metadata": products_data.get("metadata", {}),
                }
                await websocket.send(json_lib.dumps(products_payload))
    except Exception as e:
        logger.error(f"Failed to send products list: {e}")
    
    # Send current state to newly connected client
    await broadcast_state(websocket)


async def unregister_client(websocket: WebSocketServerProtocol):
    """Unregister a disconnected client."""
    connected_clients.discard(websocket)
    logger.info(f"Client disconnected. Total clients: {len(connected_clients)}")


async def _async_broadcast_state():
    """Async version of broadcast_state for scheduling from event loop."""
    with state_lock:
        payload = {
            "type": "state_update",
            "data": engine_state,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    message = json.dumps(payload)
    
    for client in connected_clients.copy():
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            connected_clients.discard(client)


def _trigger_broadcast():
    """Trigger broadcast from sync code to all connected clients."""
    global server_event_loop
    if server_event_loop and connected_clients:
        try:
            asyncio.run_coroutine_threadsafe(_async_broadcast_state(), server_event_loop)
        except Exception as e:
            logger.error(f"Failed to trigger broadcast: {e}")


async def broadcast_state(websocket: WebSocketServerProtocol = None):
    """Broadcast current engine state to all connected clients."""
    with state_lock:
        payload = {
            "type": "state_update",
            "data": engine_state,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    message = json.dumps(payload)
    
    if websocket:
        # Send to single client
        try:
            await websocket.send(message)
        except websockets.exceptions.ConnectionClosed:
            pass
    else:
        # Broadcast to all
        for client in connected_clients.copy():
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                connected_clients.discard(client)


async def handle_client_message(websocket: WebSocketServerProtocol, message: str):
    """Handle incoming messages from client."""
    try:
        data = json.loads(message)
        msg_type = data.get("type")
        
        if msg_type == "place_order":
            # Place order via REST API
            order_params = data.get("params", {})
            logger.info(f"Order placement requested: {order_params}")
            
            if not REST_CLIENT_AVAILABLE:
                response = {
                    "type": "order_response",
                    "status": "error",
                    "message": "REST client not available",
                }
                await websocket.send(json.dumps(response))
                return
            
            try:
                # Generate unique client order ID
                client_order_id = str(uuid.uuid4())
                
                # Call REST API to create order
                result = REST_CLIENT.create_order(
                    client_order_id=client_order_id,
                    product_id=order_params.get("product_id"),
                    side=order_params.get("side"),
                    order_configuration=order_params.get("order_configuration"),
                )
                
                # Convert response object to dict if needed
                if hasattr(result, '__dict__'):
                    result_dict = result.__dict__
                else:
                    result_dict = result
                
                logger.info(f"Order response: {result_dict}")
                
                # Check if order was successful
                if hasattr(result, 'success') and not result.success:
                    error_msg = "Unknown error"
                    if hasattr(result, 'error_response'):
                        error_response = result.error_response
                        if isinstance(error_response, dict):
                            error_msg = error_response.get('message') or error_response.get('error', 'Unknown error')
                        elif hasattr(error_response, 'message'):
                            error_msg = error_response.message
                        elif hasattr(error_response, 'error'):
                            error_msg = error_response.error
                    
                    response = {
                        "type": "order_response",
                        "status": "error",
                        "message": f"Order failed: {error_msg}",
                    }
                    add_log_entry("ERROR", f"Order failed for {order_params.get('product_id')}: {error_msg}")
                else:
                    # Order successful
                    order_id = None
                    if hasattr(result, 'order_id'):
                        order_id = result.order_id
                    elif isinstance(result_dict, dict):
                        order_id = result_dict.get('order_id')
                    
                    response = {
                        "type": "order_response",
                        "status": "success",
                        "message": "Order created",
                        "order_id": order_id,
                    }
                    add_log_entry("INFO", f"Order created: {order_params.get('product_id')} {order_params.get('side')}")
                
            except Exception as e:
                logger.error(f"Order placement failed: {str(e)}")
                response = {
                    "type": "order_response",
                    "status": "error",
                    "message": str(e),
                }
                add_log_entry("ERROR", f"Order placement failed: {str(e)}")
            
            await websocket.send(json.dumps(response))
            
        elif msg_type == "cancel_order":
            # Cancel order via REST API
            order_id = data.get("order_id")
            logger.info(f"Cancel requested for order: {order_id}")
            
            if not REST_CLIENT_AVAILABLE:
                response = {
                    "type": "cancel_response",
                    "status": "error",
                    "message": "REST client not available",
                }
                await websocket.send(json.dumps(response))
                return
            
            try:
                # Call REST API to cancel order
                result = REST_CLIENT.cancel_orders(order_ids=[order_id])
                
                logger.info(f"Order cancelled successfully: {result}")
                response = {
                    "type": "cancel_response",
                    "status": "success",
                    "message": "Order cancelled",
                    "data": result,
                }
                add_log_entry("INFO", f"Order cancelled: {order_id}")
                
            except Exception as e:
                logger.error(f"Order cancellation failed: {str(e)}")
                response = {
                    "type": "cancel_response",
                    "status": "error",
                    "message": str(e),
                }
                add_log_entry("ERROR", f"Order cancellation failed: {str(e)}")
            
            await websocket.send(json.dumps(response))
            
        elif msg_type == "request_stealth_orders":
            # Send current stealth orders snapshot
            await send_stealth_orders_snapshot(websocket)
        
        elif msg_type == "create_stealth_order":
            # Create new stealth order
            order = data.get("order")
            if not order:
                response = {
                    "type": "error",
                    "message": "Missing order data"
                }
                await websocket.send(json.dumps(response))
                return
            
            if not stealth_order_bridge:
                response = {
                    "type": "error",
                    "message": "Stealth order system not initialized"
                }
                await websocket.send(json.dumps(response))
                return
            
            try:
                stealth_id = stealth_order_bridge.create_stealth_order(
                    product_id=order['product_id'],
                    side=order['side'],
                    total_size=order['total_size'],
                    limit_price=order['limit_price'],
                    reveal_condition=order['reveal_condition'],
                    sizing_strategy=order.get('sizing_strategy', {}),
                    follow_up_reveal_direction=order.get('follow_up_reveal_direction', 'same'),
                    notes=order.get('notes', '')
                )
                
                # Get the created order data and serialize for JSON
                order_data = stealth_order_bridge.stealth_manager.in_memory_orders.get(stealth_id)
                serialized_order = stealth_order_bridge.stealth_manager._serialize_order_for_json(order_data) if order_data else None
                
                response = {
                    "type": "stealth_order_created",
                    "stealth_order_id": str(stealth_id),
                    "order": serialized_order
                }
                
                with state_lock:
                    engine_state["stealth_orders"][str(stealth_id)] = serialized_order
                
                add_log_entry("INFO", f"Stealth order created: {order['product_id']} {order['side']} {order['total_size']}")
                logger.info(f"Stealth order created: {stealth_id}")
                
                # Broadcast to all clients
                await broadcast_stealth_order_update(response)
                
            except Exception as e:
                logger.error(f"Failed to create stealth order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to create order: {str(e)}"
                }
                add_log_entry("ERROR", f"Stealth order creation failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "cancel_stealth_order":
            # Cancel a stealth order
            stealth_order_id = data.get("stealth_order_id")
            if not stealth_order_id or not stealth_order_bridge:
                response = {
                    "type": "error",
                    "message": "Invalid order ID or system not initialized"
                }
                await websocket.send(json.dumps(response))
                return
            
            try:
                stealth_order_bridge.cancel_stealth_order(stealth_order_id, "user_cancelled")
                
                # Update state
                with state_lock:
                    if stealth_order_id in engine_state["stealth_orders"]:
                        engine_state["stealth_orders"][stealth_order_id]["status"] = "CANCELLED"
                
                response = {
                    "type": "stealth_order_cancelled",
                    "stealth_order_id": stealth_order_id
                }
                
                add_log_entry("INFO", f"Stealth order cancelled: {stealth_order_id}")
                logger.info(f"Stealth order cancelled: {stealth_order_id}")
                
                # Broadcast to all clients
                await broadcast_stealth_order_update(response)
                
            except Exception as e:
                logger.error(f"Failed to cancel stealth order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to cancel order: {str(e)}"
                }
                await websocket.send(json.dumps(response))
        
        elif msg_type == "request_parent_orders":
            # Send parent orders list
            try:
                from database.order_dashboard_helpers import get_all_parent_orders
                orders = get_all_parent_orders()
                
                # Convert to dict keyed by client_order_id
                orders_dict = {o['client_order_id']: o for o in orders}
                
                response = {
                    "type": "parent_orders_list",
                    "orders": orders_dict
                }
                await websocket.send(json.dumps(response))
                logger.info(f"Sent {len(orders)} parent orders to client")
                
            except Exception as e:
                logger.error(f"Failed to fetch parent orders: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to fetch orders: {str(e)}"
                }
                await websocket.send(json.dumps(response))
        
        elif msg_type == "create_parent_order":
            # Create new parent order
            try:
                from database.order_dashboard_helpers import insert_parent_order, get_parent_order_by_client_id
                order = data.get("order", {})
                
                client_order_id = str(uuid.uuid4())
                
                result = insert_parent_order(
                    client_order_id=client_order_id,
                    product_id=order.get('product_id'),
                    side=order.get('side'),
                    size=float(order.get('size', 0)),
                    price=float(order.get('price', 0)),
                    target_movement=float(order.get('target_movement')) if order.get('target_movement') else None,
                    max_order_replacement=int(order.get('max_order_replacement', 0)),
                    status=order.get('status', 'OPEN')
                )
                
                # Fetch the created order
                created_order = get_parent_order_by_client_id(client_order_id)
                
                response = {
                    "type": "parent_order_created",
                    "order": created_order
                }
                
                add_log_entry("INFO", f"Parent order created: {order.get('product_id')} {order.get('side')} {order.get('size')}")
                logger.info(f"Parent order created: {client_order_id}")
                
                # Broadcast to all clients
                message = json.dumps(response)
                for client in connected_clients.copy():
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        connected_clients.discard(client)
                
            except Exception as e:
                logger.error(f"Failed to create parent order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to create order: {str(e)}"
                }
                add_log_entry("ERROR", f"Parent order creation failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "update_parent_order":
            # Update existing parent order
            try:
                from database.order_dashboard_helpers import update_parent_order, get_parent_order_by_client_id
                order = data.get("order", {})
                
                client_order_id = order.get('client_order_id')
                update_data = {
                    'size': float(order.get('size', 0)),
                    'price': float(order.get('price', 0)),
                    'target_movement': float(order.get('target_movement')) if order.get('target_movement') else None,
                    'max_order_replacement': int(order.get('max_order_replacement', 0)),
                    'status': order.get('status', 'OPEN')
                }
                
                update_parent_order(client_order_id, update_data)
                
                # Fetch the updated order
                updated_order = get_parent_order_by_client_id(client_order_id)
                
                response = {
                    "type": "parent_order_updated",
                    "order": updated_order
                }
                
                add_log_entry("INFO", f"Parent order updated: {client_order_id}")
                logger.info(f"Parent order updated: {client_order_id}")
                
                # Broadcast to all clients
                message = json.dumps(response)
                for client in connected_clients.copy():
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        connected_clients.discard(client)
                
            except Exception as e:
                logger.error(f"Failed to update parent order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to update order: {str(e)}"
                }
                add_log_entry("ERROR", f"Parent order update failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "delete_parent_order":
            # Delete parent order
            try:
                from database.order_dashboard_helpers import delete_parent_order
                client_order_id = data.get('client_order_id')
                
                delete_parent_order(client_order_id)
                
                response = {
                    "type": "parent_order_deleted",
                    "client_order_id": client_order_id
                }
                
                add_log_entry("INFO", f"Parent order deleted: {client_order_id}")
                logger.info(f"Parent order deleted: {client_order_id}")
                
                # Broadcast to all clients
                message = json.dumps(response)
                for client in connected_clients.copy():
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        connected_clients.discard(client)
                
            except Exception as e:
                logger.error(f"Failed to delete parent order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to delete order: {str(e)}"
                }
                add_log_entry("ERROR", f"Parent order deletion failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "request_products":
            # Send products list to client
            try:
                products_file = Path(__file__).parent / "products.json"
                if products_file.exists():
                    with open(products_file, 'r') as f:
                        products_data = json.load(f)
                        response = {
                            "type": "products_list",
                            "derivatives": products_data.get("derivatives", []),
                            "spot": products_data.get("spot", []),
                        }
                        await websocket.send(json.dumps(response))
                else:
                    logger.warning("products.json not found")
                    response = {
                        "type": "products_list",
                        "derivatives": [],
                        "spot": [],
                    }
                    await websocket.send(json.dumps(response))
            except Exception as e:
                logger.error(f"Failed to send products: {e}")
                response = {"type": "error", "message": f"Failed to load products: {str(e)}"}
                await websocket.send(json.dumps(response))
        
        elif msg_type == "ping":
            response = {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
            await websocket.send(json.dumps(response))
            
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON received: {message}")


async def handler(websocket: WebSocketServerProtocol, path: str):
    """Main WebSocket connection handler."""
    await register_client(websocket)
    
    try:
        async for message in websocket:
            await handle_client_message(websocket, message)
    except websockets.exceptions.ConnectionClosed:
        await unregister_client(websocket)


def update_order(order_id: str, order_data: Dict[str, Any]):
    """Update order in dashboard state."""
    with state_lock:
        engine_state["orders"][order_id] = {
            **order_data,
            "updated_at": datetime.utcnow().isoformat(),
        }
    _trigger_broadcast()


def update_position(product_id: str, position_data: Dict[str, Any]):
    """Update position in dashboard state."""
    with state_lock:
        engine_state["positions"][product_id] = {
            **position_data,
            "updated_at": datetime.utcnow().isoformat(),
        }
    _trigger_broadcast()


def update_engine_status(status_data: Dict[str, Any]):
    """Update engine status in dashboard state."""
    with state_lock:
        engine_state["engine_status"].update(status_data)
        engine_state["engine_status"]["last_update"] = datetime.utcnow().isoformat()
    _trigger_broadcast()


def add_log_entry(level: str, message: str, context: Dict[str, Any] = None):
    """Add log entry to dashboard."""
    with state_lock:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            "context": context or {},
        }
        engine_state["logs"].append(entry)
        # Keep only recent logs
        if len(engine_state["logs"]) > max_logs:
            engine_state["logs"] = engine_state["logs"][-max_logs:]
    _trigger_broadcast()


async def _async_broadcast_ticker(ticker_data: Dict[str, Any]):
    """Async version of broadcast_ticker for scheduling from event loop."""
    payload = {
        "type": "ticker",
        "data": ticker_data,
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    message = json.dumps(payload)
    
    for client in connected_clients.copy():
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            connected_clients.discard(client)


def broadcast_ticker(product_id: str, price: float, price_24h: float = None):
    """Broadcast ticker/price update to all connected chart clients.
    
    Args:
        product_id: The product ID (e.g., 'BTC-USDC')
        price: Current price
        price_24h: Price 24 hours ago (optional, for % change calculation)
    
    Example:
        >>> broadcast_ticker('BTC-USDC', 42500.50, 41200.00)
    """
    global server_event_loop
    
    if not server_event_loop:
        # Server not started yet or stopping, silently skip
        return
    
    if not connected_clients:
        # No clients connected, nothing to broadcast
        return
    
    try:
        ticker_data = {
            "product_id": product_id,
            "price": float(price),
            "time": datetime.utcnow().timestamp(),
        }
        
        if price_24h is not None:
            ticker_data["price_24h"] = float(price_24h)
        
        # Schedule on the event loop without blocking
        asyncio.run_coroutine_threadsafe(
            _async_broadcast_ticker(ticker_data),
            server_event_loop
        )
    except Exception as e:
        logger.debug(f"Failed to broadcast ticker: {e}")


# Spread monitoring for arbitrage detection
spread_data = {}  # product_id -> { bids: [prices], asks: [prices], last_window: timestamp }
spread_lock = Lock()


def record_spread_tick(product_id: str, bid: float, ask: float):
    """Record a bid/ask tick for spread monitoring.
    
    Args:
        product_id: The product ID (e.g., 'BTC-USDC')
        bid: Best bid price
        ask: Best ask price
    
    Example:
        >>> record_spread_tick('BTC-USDC', 42500.00, 42501.50)
    """
    global spread_data
    
    with spread_lock:
        if product_id not in spread_data:
            spread_data[product_id] = {
                'bids': [],
                'asks': [],
                'last_window': datetime.utcnow().timestamp(),
            }
        
        spread_data[product_id]['bids'].append(float(bid))
        spread_data[product_id]['asks'].append(float(ask))


async def _async_broadcast_spread(spread_snapshot: list):
    """Async version of broadcast_spread for scheduling from event loop."""
    payload = {
        "type": "spread_snapshot",
        "data": spread_snapshot,
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    message = json.dumps(payload)
    
    for client in connected_clients.copy():
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            connected_clients.discard(client)


def broadcast_spread():
    """Aggregate and broadcast 1-second spread averages to all connected clients.
    
    Calculates average bid/ask for each product over the last second and sends
    to all connected spread monitor clients.
    """
    global server_event_loop, spread_data
    
    if not server_event_loop or not connected_clients:
        return
    
    try:
        snapshot = []
        
        with spread_lock:
            for product_id, data in spread_data.items():
                if not data['bids'] or not data['asks']:
                    continue
                
                avg_bid = sum(data['bids']) / len(data['bids'])
                avg_ask = sum(data['asks']) / len(data['asks'])
                mid = (avg_bid + avg_ask) / 2
                
                snapshot.append({
                    'product_id': product_id,
                    'bid': round(avg_bid, 8),
                    'ask': round(avg_ask, 8),
                    'mid': round(mid, 8),
                })
                
                # Reset for next window
                data['bids'] = []
                data['asks'] = []
                data['last_window'] = datetime.utcnow().timestamp()
        
        if snapshot:
            asyncio.run_coroutine_threadsafe(
                _async_broadcast_spread(snapshot),
                server_event_loop
            )
    except Exception as e:
        logger.debug(f"Failed to broadcast spread: {e}")


async def send_stealth_orders_snapshot(websocket: WebSocketServerProtocol):
    """Send current stealth orders to a client."""
    try:
        with state_lock:
            payload = {
                "type": "stealth_orders_snapshot",
                "orders": engine_state["stealth_orders"],
                "timestamp": datetime.utcnow().isoformat(),
            }
        
        await websocket.send(json.dumps(payload))
    except Exception as e:
        logger.error(f"Failed to send stealth orders snapshot: {e}")


async def broadcast_stealth_order_update(update: Dict[str, Any]):
    """Broadcast stealth order update to all connected clients."""
    global server_event_loop
    
    if not server_event_loop or not connected_clients:
        return
    
    try:
        message = json.dumps(update)
        
        for client in connected_clients.copy():
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                connected_clients.discard(client)
    except Exception as e:
        logger.debug(f"Failed to broadcast stealth order update: {e}")


async def _stealth_orders_refresh_loop():
    """Background task to refresh stealth orders from database every 30 seconds."""
    while True:
        try:
            await asyncio.sleep(30)
            
            # Reload active stealth orders from database
            if stealth_order_bridge:
                try:
                    # Get fresh orders from manager in JSON-serializable format
                    serialized_orders = stealth_order_bridge.stealth_manager.get_serializable_orders()
                    
                    with state_lock:
                        # Update with serialized orders
                        engine_state["stealth_orders"] = serialized_orders
                    
                    # Broadcast updated snapshot
                    payload = {
                        "type": "stealth_orders_snapshot",
                        "orders": serialized_orders,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    
                    message = json.dumps(payload)
                    for client in connected_clients.copy():
                        try:
                            await client.send(message)
                        except websockets.exceptions.ConnectionClosed:
                            connected_clients.discard(client)
                except Exception as e:
                    logger.debug(f"Error refreshing stealth orders: {e}")
        
        except Exception as e:
            logger.debug(f"Stealth orders refresh loop error: {e}")


async def _spread_broadcast_loop():
    """Background task to broadcast spread snapshots every second."""
    while True:
        try:
            await asyncio.sleep(1)
            broadcast_spread()
        except Exception as e:
            logger.debug(f"Spread broadcast loop error: {e}")


async def run_websocket_server(host: str = "localhost", port: int = 8765):
    """Start the WebSocket server."""
    global server_event_loop
    server_event_loop = asyncio.get_event_loop()
    
    logger.info(f"Starting WebSocket server on ws://{host}:{port}")
    
    # Start spread broadcast loop as background task
    asyncio.create_task(_spread_broadcast_loop())
    
    # Start stealth orders refresh loop as background task
    asyncio.create_task(_stealth_orders_refresh_loop())
    
    async with websockets.serve(handler, host, port):
        logger.info("WebSocket server running. Connect dashboard.html to ws://localhost:8765")
        await asyncio.Event().wait()  # Run forever


def start_dashboard_server(host: str = "localhost", port: int = 8765):
    """Start dashboard server in background thread."""
    
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_websocket_server(host, port))
    
    thread = Thread(target=run, daemon=True)
    thread.start()
    logger.info("Dashboard server thread started")
    return thread


def set_stealth_order_bridge(bridge):
    """Set the stealth order bridge reference for WebSocket handlers and order placement.
    
    Call this from main.py after initializing the stealth order bridge:
    
    Example:
        >>> from dashboard_server import set_stealth_order_bridge
        >>> stealth_manager = StealthOrderManager(DB_CLIENT)
        >>> stealth_bridge = StealthOrderBridge(stealth_manager, None)
        >>> set_stealth_order_bridge(stealth_bridge)
    """
    global stealth_order_bridge
    stealth_order_bridge = bridge
    logger.info("Stealth order bridge registered with dashboard server")
    
    # Also register with order.py so create_limit_order_span can use it
    try:
        from order import set_stealth_order_bridge as order_set_stealth_bridge
        order_set_stealth_bridge(bridge)
        logger.info("Stealth order bridge registered with order.py")
    except ImportError:
        logger.warning("Could not register stealth bridge with order.py")


# Demo/testing
if __name__ == "__main__":
    import time
    
    start_dashboard_server()
    
    # Simulate some data
    update_engine_status({
        "running": True,
        "threads_active": 5,
        "event_queue_depth": 3,
    })
    
    add_log_entry("INFO", "Trading engine started")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down dashboard server")
