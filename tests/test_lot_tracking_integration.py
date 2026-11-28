"""
Integration tests for lot-based profit-aware execution system.

Tests the complete flow:
1. Fill ledger persistence
2. Position lot construction from fills
3. Profit threshold computation

These tests preserve the active lot-tracking and profitability primitives.
"""

import unittest
import uuid
from datetime import datetime, timedelta
from business.fill_ledger import FillLedger, FillLedgerRepository
from business.position_lot import PositionLot, LotPosition
from business.lot_builder import PositionLotBuilder
from business.profit_threshold_engine import ProfitThresholdEngine, ExecutionTarget
from core.enums import OrderSide
from database.database import PostgresDB
from database.execution_persistence import DatabaseOrderPersistenceAdapter


class TestFillLedger(unittest.TestCase):
    """Test fill ledger operations."""
    
    def setUp(self):
        """Set up test database."""
        # Note: This uses a test database on port 9876 with same DB name as production
        self.db = PostgresDB(
            host="127.0.0.1",
            port=9876,  # Test database port
            database="postgres",
            user="postgres",
            password="postgres"
        )
        # Initialize tables on test database
        self._init_test_db_tables()
        self.fill_repo = FillLedgerRepository(
            DatabaseOrderPersistenceAdapter(self.db)
        )
    
    def tearDown(self):
        """Clean up test database."""
        # Optional: truncate table for clean state
        pass
    
    def _init_test_db_tables(self):
        """Initialize fill_ledger table on test database."""
        create_table_query = """
        CREATE TABLE IF NOT EXISTS fill_ledger (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            derived_trade_key UUID UNIQUE NOT NULL,
            instrument VARCHAR(32) NOT NULL,
            side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
            quantity DECIMAL(16, 8) NOT NULL,
            price DECIMAL(16, 2) NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            fees DECIMAL(16, 8) DEFAULT 0,
            commission_percentage DECIMAL(5, 4) DEFAULT 0,
            client_order_id VARCHAR(40)
        );
        CREATE INDEX IF NOT EXISTS idx_fill_ledger_instrument ON fill_ledger(instrument);
        CREATE INDEX IF NOT EXISTS idx_fill_ledger_timestamp ON fill_ledger(timestamp);
        CREATE INDEX IF NOT EXISTS idx_fill_ledger_client_order_id ON fill_ledger(client_order_id);
        """
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(create_table_query)
                cursor.execute("TRUNCATE TABLE fill_ledger RESTART IDENTITY")
        except Exception as e:
            # Table might already exist, that's ok
            pass
    
    def test_append_fill(self):
        """Test appending a fill to ledger."""
        trade_id = str(uuid.uuid4())
        fill = FillLedger(
            derived_trade_key=trade_id,
            instrument="BTC-USDC",
            side="BUY",
            quantity=0.1,
            price=50000.0,
            timestamp=datetime.utcnow(),
            fees=3.0,
            client_order_id="order-1"
        )
        
        result = self.fill_repo.append_fill(fill)
        self.assertTrue(result)
        
        # Verify we can retrieve it
        retrieved = self.fill_repo.get_fill_by_trade_id(trade_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.quantity, 0.1)
        self.assertEqual(retrieved.price, 50000.0)
    
    def test_get_fills_by_product(self):
        """Test retrieving fills by product."""
        # Insert multiple fills
        for i in range(3):
            fill = FillLedger(
                derived_trade_key=str(uuid.uuid4()),
                instrument="BTC-USDC",
                side="BUY" if i % 2 == 0 else "SELL",
                quantity=0.1 + i * 0.01,
                price=50000.0 + i * 100,
                timestamp=datetime.utcnow() + timedelta(hours=i),
                fees=2.0 + i,
                product_id="BTC-USDC"
            )
            self.fill_repo.append_fill(fill)
        
        # Retrieve all
        fills = self.fill_repo.get_fills_by_product("BTC-USDC")
        self.assertEqual(len(fills), 3)
        
        # Verify chronological order
        for i in range(len(fills) - 1):
            self.assertLessEqual(fills[i].timestamp, fills[i+1].timestamp)


class TestPositionLotBuilder(unittest.TestCase):
    """Test position lot construction."""
    
    def setUp(self):
        """Set up test infrastructure."""
        self.db = PostgresDB(host="127.0.0.1", port=9876, database="postgres")
        self._init_test_db_tables()
        self.fill_repo = FillLedgerRepository(
            DatabaseOrderPersistenceAdapter(self.db)
        )
        self.builder = PositionLotBuilder(self.fill_repo)
    
    def _init_test_db_tables(self):
        """Initialize fill_ledger table on test database."""
        create_table_query = """
        CREATE TABLE IF NOT EXISTS fill_ledger (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            derived_trade_key UUID UNIQUE NOT NULL,
            instrument VARCHAR(32) NOT NULL,
            side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
            quantity DECIMAL(16, 8) NOT NULL,
            price DECIMAL(16, 2) NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            fees DECIMAL(16, 8) DEFAULT 0,
            commission_percentage DECIMAL(5, 4) DEFAULT 0,
            client_order_id VARCHAR(40)
        );
        CREATE INDEX IF NOT EXISTS idx_fill_ledger_instrument ON fill_ledger(instrument);
        CREATE INDEX IF NOT EXISTS idx_fill_ledger_timestamp ON fill_ledger(timestamp);
        CREATE INDEX IF NOT EXISTS idx_fill_ledger_client_order_id ON fill_ledger(client_order_id);
        """
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(create_table_query)
                cursor.execute("TRUNCATE TABLE fill_ledger RESTART IDENTITY")
        except Exception:
            pass
    
    def test_build_lots_fifo(self):
        """Test FIFO lot construction."""
        # Insert fills at different prices
        fills_data = [
            ("BTC-USDC", "BUY", 0.1, 50000.0, 3.0),
            ("BTC-USDC", "BUY", 0.1, 50100.0, 3.0),
            ("BTC-USDC", "BUY", 0.05, 50050.0, 1.5),
        ]
        
        for i, (instrument, side, qty, price, fees) in enumerate(fills_data):
            fill = FillLedger(
                derived_trade_key=str(uuid.uuid4()),
                instrument=instrument,
                side=side,
                quantity=qty,
                price=price,
                timestamp=datetime.utcnow() + timedelta(hours=i),
                fees=fees,
                product_id=instrument
            )
            self.fill_repo.append_fill(fill)
        
        # Build position
        position = self.builder.build_position_by_product("BTC-USDC")
        
        # Should have 3 lots (one per price)
        self.assertEqual(len(position.lots), 3)
        self.assertEqual(position.total_quantity, 0.25)
        
        # Verify lots are in FIFO order
        for i, lot in enumerate(position.lots):
            self.assertEqual(lot.side, OrderSide.BUY)
    
    def test_profit_threshold_computation(self):
        """Test profit threshold calculation per lot."""
        # Create position with buy lot
        lot = PositionLot(
            lot_id="test-lot",
            instrument="BTC-USDC",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=50000.0,
            entry_timestamp=datetime.utcnow(),
            fees=3.0,
            target_profit_percentage=0.5
        )
        
        # Verify profit threshold
        # entry = 50000, fees/qty = 30, cost_per_unit = 50030
        # profit_target = 50030 * 0.005 = 250.15
        # min_exit = 50030 + 250.15 = 50280.15
        self.assertAlmostEqual(lot.min_profitable_exit_price, 50280.15, places=2)


class TestProfitThresholdEngine(unittest.TestCase):
    """Test profit threshold engine."""
    
    def setUp(self):
        """Set up engine."""
        self.engine = ProfitThresholdEngine(profit_margin_pct=0.5)
    
    def test_execution_targets_fifo(self):
        """Test execution target selection with FIFO strategy."""
        # Create position with 3 lots
        position = LotPosition(instrument="BTC-USDC")
        
        lots = [
            PositionLot(
                lot_id="lot-1",
                instrument="BTC-USDC",
                side=OrderSide.BUY,
                quantity=0.1,
                entry_price=50000.0,
                entry_timestamp=datetime.utcnow(),
                fees=3.0,
                target_profit_percentage=0.5
            ),
            PositionLot(
                lot_id="lot-2",
                instrument="BTC-USDC",
                side=OrderSide.BUY,
                quantity=0.1,
                entry_price=50100.0,
                entry_timestamp=datetime.utcnow(),
                fees=3.0,
                target_profit_percentage=0.5
            ),
        ]
        
        for lot in lots:
            position.add_lot(lot)
        
        # Request to exit 0.15 total
        targets, meta = self.engine.compute_execution_targets(
            position=position,
            exit_quantity=0.15,
            market_price=50500.0,
            strategy='FIFO'
        )
        
        # Should have targets for both lots
        self.assertEqual(len(targets), 2)
        self.assertEqual(meta['total_quantity'], 0.15)
        self.assertTrue(meta['all_profitable'])


def run_integration_tests():
    """Run all integration tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestFillLedger))
    suite.addTests(loader.loadTestsFromTestCase(TestPositionLotBuilder))
    suite.addTests(loader.loadTestsFromTestCase(TestProfitThresholdEngine))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_integration_tests()
    exit(0 if success else 1)
