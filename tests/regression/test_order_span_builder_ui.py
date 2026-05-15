from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = REPO_ROOT / "ui_order_span_builder.html"


def _function_body_before(next_function_name: str, source: str) -> str:
    start = source.index("function createOrderSpan()")
    end = source.index(f"function {next_function_name}", start)
    return source[start:end]


def test_create_span_preserves_submitted_form_values():
    source = HTML_PATH.read_text(encoding="utf-8")

    create_span_body = _function_body_before("createIndependentParents", source)

    assert "resetForm(" not in create_span_body
    assert 'onclick="resetForm()"' in source
