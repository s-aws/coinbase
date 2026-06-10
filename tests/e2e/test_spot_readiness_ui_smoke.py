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

    page.wait_for_function(
        "() => window.__sentMessages.some((msg) => msg.type === 'request_spot_campaign_status')"
    )
    page.evaluate(
        """payload => window.__deliverDashboardMessage(payload)""",
        {
            "type": "spot_campaign_status",
            "status": "success",
            "state_file": "runtime_state/spot_campaigns.jsonl",
            "operator_status": {
                "campaign_count": 1,
                "snapshot_count": 2,
                "total_submitted_notional_usdc": "2",
                "total_executed_notional_usdc": "1.98",
                "operator_summary": {
                    "readiness_status": "ready",
                    "ready": True,
                    "blocked": False,
                    "gate_status": "passed",
                    "automation_decision": "due",
                    "next_run_at": "2026-01-01T06:00:00+00:00",
                    "run_count": 1,
                    "max_runs": 3,
                    "operation_lock_status": "released",
                    "operation_lock_exists": False,
                    "operation_lock_stale": False,
                    "recovery_status": "passed",
                    "planned_reconciliation_run_count": 0,
                    "planned_backfill_order_count": 0,
                    "planned_order_count": 2,
                    "planned_skip_count": 1,
                    "safety_decision": "allowed",
                    "latest_live_run_id": "spot-sweep-live-1",
                    "latest_live_status": "completed",
                    "latest_live_skipped_order_count": 1,
                    "total_submitted_notional_usdc": "2",
                    "total_executed_notional_usdc": "1.98",
                    "portfolio_total_pnl": "0.25",
                    "portfolio_mark_value": "10",
                    "portfolio_fees": "0.01",
                    "latest_readiness_generated_at": "2026-01-01T00:00:00+00:00",
                },
                "latest_snapshot": {
                    "campaign_id": "spot-campaign-example",
                    "mode": "live_canary",
                    "status": "ready",
                },
                "latest_readiness_snapshot": {
                    "campaign_id": "spot-campaign-example",
                    "mode": "release_gate",
                    "status": "ready",
                    "generated_at": "2026-01-01T00:00:00+00:00",
                    "config": {
                        "side": "BUY",
                        "quote_notional": "1",
                        "order_type": "market_ioc",
                    },
                    "dry_run": {
                        "plan": {"planned_count": 2, "skipped_count": 1},
                        "safety_evaluation": {"decision": "allowed"},
                        "pnl_snapshot": {
                            "portfolio": {
                                "total_pnl": "0.25",
                                "mark_value": "10",
                                "fees": "0.01",
                            },
                        },
                    },
                    "release_gate": {
                        "gate_status": "passed",
                        "failures": [],
                        "warnings": [],
                    },
                },
                "latest_live_snapshot": {
                    "mode": "live_canary",
                    "sweep_summary": {
                        "run_id": "spot-sweep-live-1",
                        "status": "completed",
                        "skipped_order_count": 1,
                    },
                },
            },
        },
    )

    campaign_panel = page.locator("#spot-campaign-status-panel")
    expect(campaign_panel).to_contain_text("Operator State")
    expect(campaign_panel).to_contain_text("due")
    expect(campaign_panel).to_contain_text("spot-sweep-live-1")
    expect(campaign_panel).to_contain_text("reconcile 0")
    expect(campaign_panel).to_contain_text("submitted 2 USDC")
    expect(campaign_panel).to_contain_text("total 0.25 USDC")

    page.evaluate(
        """payload => window.__deliverDashboardMessage(payload)""",
        {
            "type": "spot_campaign_status",
            "status": "error",
            "message": "campaign status failed: synthetic failure",
        },
    )
    expect(campaign_panel).to_contain_text("synthetic failure")
