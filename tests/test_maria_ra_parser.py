from __future__ import annotations

import builtins

from parsers.maria_ra_parser import MariaRaParser


def test_age_gate_detection() -> None:
    assert MariaRaParser._is_age_gate_page("<html>Вам есть 18+ ?</html>")
    assert not MariaRaParser._is_age_gate_page("<html><body>Карта сети</body></html>")


def test_playwright_fallback_is_graceful_when_import_fails(monkeypatch, caplog) -> None:
    original_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if name.startswith("playwright"):
            raise OSError("libnspr4.so: cannot open shared object file")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    parser = MariaRaParser(client=None)

    with caplog.at_level("WARNING"):
        stores = parser._playwright_fallback()

    assert stores == []
    assert any("Playwright unavailable, skipping fallback" in record.message for record in caplog.records)
