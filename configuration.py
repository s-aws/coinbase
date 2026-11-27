"""Passive runtime configuration loading.

Importing this module performs no environment reads, file reads, network I/O,
logging configuration, or runtime-object construction.  ``main.py`` calls the
loaders explicitly and remains the sole owner of live application composition.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from core.enums import ProductType


logger = logging.getLogger(__name__)

PRODUCTS_FILE = Path(__file__).parent / "products.json"

DEFAULT_DASHBOARD_HOST = "localhost"
DEFAULT_DASHBOARD_PORT = 8765
DEFAULT_DASHBOARD_STATE_PUBLISH_INTERVAL_SECONDS = 0.25

ORDER_POST_ONLY: Mapping[str, bool] = {
    "BUY": False,
    "SELL": False,
}


@dataclass(frozen=True)
class ProductConfiguration:
    """Immutable process-start snapshot of product configuration."""

    spot_product_ids: tuple[str, ...]
    derivatives_product_ids: tuple[str, ...]
    metadata: Mapping[str, Mapping[str, Any]]
    ticker_to_trading: Mapping[str, str]
    path: Path = PRODUCTS_FILE

    @property
    def product_ids(self) -> tuple[str, ...]:
        return self.derivatives_product_ids + self.spot_product_ids

    def resolve_trading_product_id(self, product_id: str) -> str:
        return self.ticker_to_trading.get(product_id, product_id)

    def local_products(self) -> dict[str, dict[str, Any]]:
        """Return cached metadata normalized to the REST product shape."""

        products: dict[str, dict[str, Any]] = {}
        for product_id in self.product_ids:
            trading_product_id = self.resolve_trading_product_id(product_id)
            metadata = self.metadata.get(product_id) or self.metadata.get(
                trading_product_id,
                {},
            )
            product_type = (
                metadata.get("product_type")
                or metadata.get("type")
                or ProductType.SPOT.value
            )
            product = {
                **deepcopy(dict(metadata)),
                "product_id": product_id,
                "product_type": product_type,
                "trading_disabled": bool(
                    metadata.get("trading_disabled", False)
                ),
            }
            if product_type == ProductType.FUTURE.value:
                product.setdefault(
                    "future_product_details",
                    {"contract_size": metadata.get("contract_size") or 1},
                )
            if not product["trading_disabled"]:
                products[product_id] = product
        return products


@dataclass(frozen=True)
class RuntimeSettings:
    """All environment and file configuration read for one process start."""

    api_key: Optional[str]
    api_secret: Optional[str]
    products: ProductConfiguration
    dashboard_host: str
    dashboard_port: int
    dashboard_state_publish_interval_seconds: float
    order_post_only: Mapping[str, bool]


@dataclass(frozen=True)
class Subscription:
    """Immutable WebSocket subscription topology for one runtime."""

    product_ids: tuple[str, ...]
    derivatives_product_ids: tuple[str, ...]
    public_channels: tuple[str, ...] = ("heartbeats", "ticker")
    private_channels: tuple[str, ...] = (
        "heartbeats",
        "user",
        "futures_balance_summary",
    )

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.public_channels + self.private_channels))

    @classmethod
    def from_products(cls, products: ProductConfiguration) -> "Subscription":
        return cls(
            product_ids=products.product_ids,
            derivatives_product_ids=products.derivatives_product_ids,
        )


def load_product_configuration(
    path: Path = PRODUCTS_FILE,
) -> ProductConfiguration:
    """Read one product configuration snapshot from ``path``."""

    try:
        with path.open("r", encoding="utf-8") as product_file:
            raw = json.load(product_file)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load product configuration %s: %s", path, exc)
        raw = {}

    metadata = raw.get("metadata") if isinstance(raw, dict) else {}
    ticker_mapping = raw.get("ticker_to_trading") if isinstance(raw, dict) else {}
    return ProductConfiguration(
        spot_product_ids=tuple(raw.get("spot", ()) if isinstance(raw, dict) else ()),
        derivatives_product_ids=tuple(
            raw.get("derivatives", ()) if isinstance(raw, dict) else ()
        ),
        metadata=deepcopy(metadata) if isinstance(metadata, Mapping) else {},
        ticker_to_trading=(
            dict(ticker_mapping) if isinstance(ticker_mapping, Mapping) else {}
        ),
        path=path,
    )


def load_runtime_settings(
    *,
    environ: Optional[Mapping[str, str]] = None,
    products_path: Path = PRODUCTS_FILE,
) -> RuntimeSettings:
    """Read environment and product-file settings for one process start."""

    source = os.environ if environ is None else environ
    dashboard_host = source.get(
        "DASHBOARD_SERVER_HOST",
        source.get("HOSTNAME", DEFAULT_DASHBOARD_HOST),
    )
    dashboard_port = int(
        source.get("DASHBOARD_SERVER_PORT", str(DEFAULT_DASHBOARD_PORT))
    )
    publish_interval = max(
        0.01,
        float(
            source.get(
                "DASHBOARD_STATE_PUBLISH_INTERVAL_SECONDS",
                str(DEFAULT_DASHBOARD_STATE_PUBLISH_INTERVAL_SECONDS),
            )
        ),
    )
    return RuntimeSettings(
        api_key=source.get("COINBASE_API_KEY"),
        api_secret=source.get("COINBASE_API_SECRET"),
        products=load_product_configuration(products_path),
        dashboard_host=dashboard_host,
        dashboard_port=dashboard_port,
        dashboard_state_publish_interval_seconds=publish_interval,
        order_post_only=dict(ORDER_POST_ONLY),
    )


def build_persisted_product_document(
    products: Mapping[str, Mapping[str, Any]],
    *,
    ticker_to_trading: Mapping[str, str],
) -> dict[str, Any]:
    """Build the stable ``products.json`` representation for live products."""

    derivatives: list[str] = []
    spot: list[str] = []
    metadata: dict[str, dict[str, Any]] = {}

    for product_id, product_data in products.items():
        product_type = str(product_data.get("product_type") or "").upper()
        if product_type in {"PERPETUAL_FUTURE", ProductType.FUTURE.value}:
            derivatives.append(product_id)
        else:
            spot.append(product_id)
        metadata[product_id] = {
            "type": (
                product_type
                if product_type in {"SPOT", "FUTURE", "PERPETUAL_FUTURE"}
                else "UNKNOWN"
            ),
            "base_currency": product_data.get("base_currency"),
            "quote_currency": product_data.get("quote_currency"),
            "base_increment": str(product_data.get("base_increment", "")),
            "quote_increment": str(product_data.get("quote_increment", "")),
            "price_increment": str(product_data.get("price_increment", "")),
            "base_min_size": str(product_data.get("base_min_size", "")),
            "quote_min_size": str(product_data.get("quote_min_size", "")),
            "display_name": product_data.get("display_name"),
            "status": product_data.get("status"),
            "mid_price": product_data.get("mid_price"),
            "trading_disabled": product_data.get("trading_disabled", False),
            "contract_size": (
                str(product_data.get("contract_size", ""))
                if "contract_size" in product_data
                else None
            ),
            "expiry": product_data.get("expiry"),
        }

    return {
        "spot": sorted(spot),
        "derivatives": sorted(derivatives),
        "ticker_to_trading": dict(ticker_to_trading),
        "metadata": metadata,
    }


def persist_product_configuration(
    products: Mapping[str, Mapping[str, Any]],
    *,
    ticker_to_trading: Mapping[str, str],
    path: Path = PRODUCTS_FILE,
) -> None:
    """Atomically persist a successful live product refresh."""

    document = build_persisted_product_document(
        products,
        ticker_to_trading=ticker_to_trading,
    )
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as product_file:
            json.dump(document, product_file, indent=2)
            product_file.write("\n")
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove product-config temporary file %s", temporary_path)
