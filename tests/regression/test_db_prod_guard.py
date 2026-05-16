"""Regression: direct test-shaped DB runs must not default to production."""

import pytest

from database.database import PostgresDB


@pytest.mark.regression
def test_direct_test_script_refuses_local_prod_port(monkeypatch):
    monkeypatch.delenv("ALLOW_PROD_DB", raising=False)
    monkeypatch.setattr("sys.argv", ["test_production_fill_flow.py"])

    db = PostgresDB(host="127.0.0.1", port=5432, database="postgres")
    with pytest.raises(RuntimeError, match="REFUSED: test-shaped process"):
        db._refuse_test_process_prod_connection()


@pytest.mark.regression
def test_normal_runtime_name_does_not_trip_test_process_guard(monkeypatch):
    monkeypatch.delenv("ALLOW_PROD_DB", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py"])

    db = PostgresDB(host="127.0.0.1", port=5432, database="postgres")
    db._refuse_test_process_prod_connection()
