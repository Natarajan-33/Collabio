from app.adapters.gemini import format_document, format_query


def test_format_document():
    assert format_document("Maya", "tech") == "title: Maya | text: tech"


def test_format_document_no_title():
    assert format_document("", "x") == "title: none | text: x"


def test_format_query():
    assert format_query("tech creators") == "task: search result | query: tech creators"
