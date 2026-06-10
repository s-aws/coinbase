"""Playwright smoke tests for direct dashboard order acknowledgement."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import expect


def test_direct_order_form_requires_manual_live_acknowledgement(page):
    ui_path = Path(__file__).resolve().parents[2] / "ui_dashboard.html"

    page.add_init_script(
        """
        window.__sentMessages = [];
        window.__alerts = [];

        class MockDashboardSocket {
            static CONNECTING = 0;
            static OPEN = 1;
            static CLOSED = 3;

            constructor(url) {
                this.url = url;
                this.readyState = MockDashboardSocket.CONNECTING;
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
        window.alert = (message) => window.__alerts.push(message);
        """
    )

    page.goto(ui_path.as_uri(), wait_until="domcontentloaded")
    page.fill("#productId", "BTC-USD")
    page.fill("#size", "0.001")
    page.fill("#limitPrice", "100000")

    page.get_by_role("button", name="📤 Submit Order").click()

    expect(page.locator("#manualLiveAcknowledgement")).not_to_be_checked()
    assert page.evaluate("window.__sentMessages.length") == 0
    assert "submit live immediately" in page.evaluate("window.__alerts[0]")

    page.check("#manualLiveAcknowledgement")
    page.get_by_role("button", name="📤 Submit Order").click()

    page.wait_for_function(
        "() => window.__sentMessages.some((msg) => msg.type === 'place_order')"
    )
    sent = page.evaluate(
        "() => window.__sentMessages.find((msg) => msg.type === 'place_order')"
    )
    assert sent["params"]["manual_live_acknowledgement"] is True
