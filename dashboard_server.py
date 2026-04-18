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


async def register_client(websocket: WebSocketServerProtocol):
    """Register a new connected client."""
    connected_clients.add(websocket)
    logger.info(f"Client connected. Total clients: {len(connected_clients)}")
    
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


async def run_websocket_server(host: str = "localhost", port: int = 8765):
    """Start the WebSocket server."""
    global server_event_loop
    server_event_loop = asyncio.get_event_loop()
    
    logger.info(f"Starting WebSocket server on ws://{host}:{port}")
    
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
