"""Playwright smoke tests for the spot readiness dashboard panel."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import expect


def test_spot_readiness_panel_renders_dashboard_payload(page):
    ui_path = Path(__file__).resolve().parents[2] / "ui_stealth_orders_manager.html"

    page.add_init_script(
        """
        window.__sentMessages = [];
        window.__dashboardSocket = null;

        class MockDashboardSocket {
            static CONNECTING = 0;
            static OPEN = 1;
            static CLOSED = 3;

            constructor(url) {
                this.url = url;
                this.readyState = MockDashboardSocket.CONNECTING;
                window.__dashboardSocket = this;
                setTimeout(() => {
                    this.readyState = MockDashboardSocket.OPEN;
                    if (this.onopen) this.onopen();
                }, 0);
            }

            send(payload) {
                window.__sentMessages.push(JSON.parse(payload));
            }

            close() {
                this.readyState = MockDashboardSocket.CLOSED;
                if (this.onclose) this.onclose();
            }
        }

        window.WebSocket = MockDashboardSocket;
        window.__deliverDashboardMessage = (payload) => {
            if (!window.__dashboardSocket || !window.__dashboardSocket.onmessage) {
                throw new Error("dashboard websocket handler is not ready");
            }
            window.__dashboardSocket.onmessage({ data: JSON.stringify(payload) });
        };
        window.fetch = async () => ({
            json: async () => ({
                derivatives: [],
                spot: ["BTC-USD"],
                metadata: {
                    "BTC-USD": {
                        base_increment: "0.00000001",
                        price_increment: "0.01"
                    }
                }
            })
        });
        window.confirm = () => false;
        """
    )

    page.goto(ui_path.as_uri(), wait_until="domcontentloaded")

    panel = page.locator("#spot-readiness-panel")
    expect(panel).to_contain_text("Waiting for dashboard data")
    page.wait_for_function(
        "() => window.__sentMessages.some((msg) => msg.type === 'request_spot_readiness')"
    )

    page.evaluate(
        """payload => window.__deliverDashboardMessage(payload)""",
        {
            "type": "spot_readiness",
            "status": "success",
            "products": [
                {
                    "product_id": "BTC-USD",
                    "product_type": "SPOT",
                    "base_currency": "BTC",
                    "quote_currency": "USD",
                    "capabilities": {
                        "direct_placement": {"mode": "enabled"},
                        "stealth_planning": {"mode": "enabled"},
                        "stealth_reveal": {"mode": "enabled"},
                        "move_revealed": {"mode": "disabled"},
                        "reprice_revealed": {"mode": "disabled"},
                        "hotpoint_auto_placement": {"mode": "disabled"},
                    },
                    "inventory": {
                        "imported_baselines": {
                            "known_quantity": 0.25,
                            "unknown_cost_basis_quantity": 0.1,
                            "lots": [
                                {
                                    "source_id": "manual-baseline",
                                    "cost_basis_status": "known",
                                    "remaining_quantity": 0.25,
                                    "entry_price": 90000,
                                },
                                {
                                    "source_id": "external-wallet",
                                    "cost_basis_status": "unknown",
                                    "remaining_quantity": 0.1,
                                    "entry_price": None,
                                },
                            ],
                        },
                    },
                }
            ],
            "planned_budget": {"USD": 125.5},
            "wallet_snapshot": {
                "available": True,
                "age_seconds": 0,
                "currencies": {
                    "BTC": {"available_balance": 0.25},
                    "USD": {"available_balance": 1000.0},
                },
            },
            "action_guards": {
                "wallet_available": {"enabled": True},
                "known_inventory_available": {"enabled": True},
            },
            "action_guard_summary": [
                {
                    "condition": "wallet_available",
                    "label": "wallet availability",
                    "mode": "enabled",
                    "phases": ["planning", "reveal"],
                    "reason": "Coinbase wallet balance is checked before spot placement",
                },
                {
                    "condition": "planned_budget_available",
                    "label": "planned spot budget",
                    "mode": "enabled",
                    "phases": ["planning", "reveal"],
                    "reason": "spot wallet availability is reduced by local hidden, pending, and triggered spot commitments",
                },
                {
                    "condition": "known_inventory_available",
                    "label": "known profitable inventory",
                    "mode": "enabled",
                    "phases": ["planning", "reveal"],
                    "reason": "spot SELL admission requires known profitable fill-ledger or baseline lots",
                },
            ],
        },
    )

    expect(panel).to_contain_text("BTC-USD")
    expect(panel).to_contain_text("SPOT")
    expect(panel).to_contain_text("BTC / USD")
    expect(panel).to_contain_text("direct: enabled")
    expect(panel).to_contain_text("move: disabled")
    expect(panel).to_contain_text("USD 125.5")
    expect(panel).to_contain_text("BTC 0.25")
    expect(panel).to_contain_text("wallet availability: enabled")
    expect(panel).to_contain_text("planned spot budget: enabled")
    expect(panel).to_contain_text("known profitable inventory: enabled")
    expect(panel).to_contain_text("manual-baseline: known 0.25 @ 90000")
    expect(panel).to_contain_text("external-wallet: unknown 0.1")
