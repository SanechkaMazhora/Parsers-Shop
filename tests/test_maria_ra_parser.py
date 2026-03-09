from __future__ import annotations

from parsers.maria_ra_parser import MariaRaParser


def test_age_gate_detection() -> None:
    assert MariaRaParser._is_age_gate_page("<html>Вам есть 18+ ?</html>")
    assert not MariaRaParser._is_age_gate_page("<html><body>Карта сети</body></html>")
