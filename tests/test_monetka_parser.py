from __future__ import annotations

import logging

import pytest
from requests import HTTPError, Response, Timeout
from bs4 import BeautifulSoup

from core.models import StoreRecord
from parsers.monetka_parser import MonetkaParser


def test_extract_city_region_requires_explicit_detail_geography() -> None:
    soup = BeautifulSoup("<html><body>No breadcrumbs</body></html>", "lxml")

    city, region = MonetkaParser._extract_city_region(
        soup,
        "https://www.monetka.ru/orenburgskaya-oblasty/shops_map/aleksandrovka/123",
    )

    assert city is None
    assert region is None


def test_apply_city_context_backfills_missing_region_when_city_matches() -> None:
    city, region = MonetkaParser._apply_city_context(
        city="Asbest",
        region=None,
        context_city="Asbest",
        context_region="Sverdlovskaya Oblast",
        source_url="https://www.monetka.ru/shops_map/ekb/4187",
    )

    assert city == "Asbest"
    assert region == "Sverdlovskaya Oblast"


def test_apply_city_context_keeps_explicit_detail_geography_on_conflict() -> None:
    city, region = MonetkaParser._apply_city_context(
        city="Asbest",
        region="Sverdlovskaya Oblast",
        context_city="Abatskoye",
        context_region="Tyumenskaya Oblast",
        source_url="https://www.monetka.ru/shops_map/ekb/4187",
    )

    assert city == "Asbest"
    assert region == "Sverdlovskaya Oblast"


def test_extract_pagination_links_supports_pagen_query() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <a href="?PAGEN_1=2">2</a>
    <a href="?page=3">3</a>
    <a href="/shops_map/ekb/page/4">4</a>
    """

    links = sorted(parser._extract_pagination_links(html, "https://www.monetka.ru/shops_map/ekb"))

    assert "https://www.monetka.ru/shops_map/ekb?PAGEN_1=2" in links
    assert "https://www.monetka.ru/shops_map/ekb?page=3" in links
    assert "https://www.monetka.ru/shops_map/ekb/page/4" in links


def test_extract_region_links_uses_only_change_paths() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <a href="/orenburgskaya-oblast/change">Orenburg</a>
    <a href="/Bashkortostan/change/">Bashkortostan</a>
    <a href="/urfo/shops_map/">URFO</a>
    <a href="/orenburgskaya-oblasty/shops_map">Legacy region page</a>
    <a href="/shops_map/ekb/1194">Store</a>
    """

    links = sorted(parser._extract_region_links(html, "https://www.monetka.ru/shops_map/"))

    assert links == [
        "https://www.monetka.ru/Bashkortostan/change/",
        "https://www.monetka.ru/orenburgskaya-oblast/change",
    ]


def test_collect_region_pages_uses_seed_page_only_and_change_links() -> None:
    class FakeClient:
        calls: list[str] = []

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(url)
            if url == "https://www.monetka.ru/shops_map/":
                return """
                <a href="/orenburgskaya-oblast/change">Orenburg</a>
                <a href="/Bashkortostan/change">Bashkortostan</a>
                """
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    regions = parser._collect_region_pages()

    assert regions == [
        "https://www.monetka.ru/Bashkortostan/change",
        "https://www.monetka.ru/orenburgskaya-oblast/change",
    ]
    assert parser.client.calls == ["https://www.monetka.ru/shops_map/"]  # type: ignore[attr-defined]


def test_collect_city_hints_for_region_uses_shop_city_list_links_only() -> None:
    class FakeClient:
        calls: list[str] = []

        headers_seen: list[dict | None] = []

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(url)
            self.headers_seen.append(kwargs.get("headers"))
            if url == "https://www.monetka.ru/Nsk_obl/change":
                return """
                <a href="/Nsk_obl/shops_map/ignored-outside-list">Outside</a>
                <ul class="shop_city_list_ul">
                  <li><a href="/urfo/shops_map/Aramil">Aramil</a></li>
                  <li><a href="/urfo/shops_map/Asbest">Asbest</a></li>
                </ul>
                """
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    city_hints = parser._collect_city_hints_for_region("https://www.monetka.ru/Nsk_obl/change")

    assert sorted(city_hints) == [
        "https://www.monetka.ru/urfo/shops_map/Aramil",
        "https://www.monetka.ru/urfo/shops_map/Asbest",
    ]
    assert parser.client.calls == ["https://www.monetka.ru/Nsk_obl/change"]  # type: ignore[attr-defined]
    assert parser.client.headers_seen[0] == {"Referer": "https://www.monetka.ru/shops_map/"}  # type: ignore[attr-defined]


def test_is_valid_city_page_path_accepts_only_strict_city_paths() -> None:
    assert MonetkaParser._is_valid_city_page_path("/urfo/shops_map/Aramil")
    assert MonetkaParser._is_valid_city_page_path("/Nsk_obl/shops_map/Novosibirsk")
    assert not MonetkaParser._is_valid_city_page_path("/shops_map/Aramil")
    assert not MonetkaParser._is_valid_city_page_path("/urfo/shops_map")
    assert not MonetkaParser._is_valid_city_page_path("/urfo/shops_map/+Purovsk")
    assert not MonetkaParser._is_valid_city_page_path("/shops_map/ekb/1241")


def test_extract_city_links_with_hint_filters_malformed_hrefs() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <ul class="shop_city_list_ul">
      <li><a href="/urfo/shops_map/Aramil">Aramil</a></li>
      <li><a href="/urfo/shops_map/+Purovsk">Bad Plus</a></li>
      <li><a href="javascript:void(0)">JS</a></li>
      <li><a href="#">Hash</a></li>
      <li><a href="  ">Empty</a></li>
    </ul>
    """

    links = list(parser._extract_city_links_with_hint(html, "https://www.monetka.ru/Nsk_obl/change"))

    assert links == [("https://www.monetka.ru/urfo/shops_map/Aramil", "Aramil")]
    assert parser._city_links_filtered_count == 4


def test_extract_city_context_does_not_use_city_page_url_slug_without_visible_signal() -> None:
    parser = MonetkaParser(client=None)

    city, region = parser._extract_city_context(
        "<html><body>blank city page</body></html>",
        "https://www.monetka.ru/urfo/shops_map/Asbest",
    )

    assert city is None
    assert region is None


def test_extract_store_summaries_reads_address_and_work_time_from_city_page() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <div class="shopstore">
      <a href="/shops_map/ekb/1004">ул Зелёная, 35А</a>
      <div>8:00-21:00</div>
    </div>
    """

    summaries = parser._extract_store_summaries(html, "https://www.monetka.ru/urfo/shops_map/abat")

    assert summaries == {
        "https://www.monetka.ru/shops_map/ekb/1004": {
            "address": "ул. Зелёная, 35А",
            "work_time": "08:00-21:00",
            "phone": None,
            "store_format": None,
        }
    }


def test_build_partial_store_record_uses_city_page_summary() -> None:
    parser = MonetkaParser(client=None)

    record = parser._build_partial_store_record(
        "https://www.monetka.ru/shops_map/ekb/1004",
        context_city="Абатское",
        context_region="Тюменская область",
        fallback_summary={"address": "ул Зелёная, 35А", "work_time": "8:00-21:00", "phone": None, "store_format": None},
    )

    assert record is not None
    assert record.city == "Абатское"
    assert record.region == "Тюменская область"
    assert record.address == "ул. Зелёная, 35А"
    assert record.work_time == "08:00-21:00"


def test_build_partial_store_record_preserves_phone_and_store_format_from_summary() -> None:
    parser = MonetkaParser(client=None)

    record = parser._build_partial_store_record(
        "https://www.monetka.ru/shops_map/ekb/1004",
        context_city="Абатское",
        context_region="Тюменская область",
        fallback_summary={
            "address": "ул Зелёная, 35А",
            "work_time": "8:00-21:00",
            "phone": "8-800-123-45-67",
            "store_format": "Магазин у дома",
        },
    )

    assert record is not None
    assert record.city == "Абатское"
    assert record.region == "Тюменская область"
    assert record.address == "ул. Зелёная, 35А"
    assert record.work_time == "08:00-21:00"
    assert record.phone == "8-800-123-45-67"
    assert record.store_format == "Магазин у дома"
    assert record.status is None


def test_clean_address_removes_garbage_u_prefix_without_inventing_street_type() -> None:
    assert MonetkaParser._clean_address("Адрес: у Кирова, 10") == "Кирова, 10"
    assert MonetkaParser._clean_address("у Ильича, 2а") == "Ильича, 2а"
    assert MonetkaParser._clean_address("у Сибирская, 2") == "Сибирская, 2"
    assert MonetkaParser._clean_address("у ул. Ленина, 1") == "ул. Ленина, 1"


def test_collect_city_hints_includes_seed_city_list_for_active_region() -> None:
    class FakeClient:
        calls: list[str] = []

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(url)
            if url == "https://www.monetka.ru/shops_map/":
                return """
                <ul class="shop_city_list_ul">
                  <li><a href="/urfo/shops_map/Aramil">Aramil</a></li>
                </ul>
                """
            if url == "https://www.monetka.ru/Nsk_obl/change":
                return """
                <ul class="shop_city_list_ul">
                  <li><a href="/Nsk_obl/shops_map/Novosibirsk">Novosibirsk</a></li>
                </ul>
                """
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    city_hints = parser._collect_city_hints(region_pages=["https://www.monetka.ru/Nsk_obl/change"])

    assert sorted(city_hints) == [
        "https://www.monetka.ru/Nsk_obl/shops_map/Novosibirsk",
        "https://www.monetka.ru/urfo/shops_map/Aramil",
    ]


def test_parse_deduplicates_stores_by_network_city_address_and_avoids_list_urls() -> None:
    class FakeClient:
        calls: list[str] = []
        _pages = {
            "https://www.monetka.ru/shops_map/": """
                <a href="/region-a/change">Region A</a>
                <a href="/region-b/change">Region B</a>
            """,
            "https://www.monetka.ru/region-a/change": """
                <ul class="shop_city_list_ul">
                  <li><a href="/region-a/shops_map/city-one">City One</a></li>
                </ul>
            """,
            "https://www.monetka.ru/region-b/change": """
                <ul class="shop_city_list_ul">
                  <li><a href="/region-b/shops_map/city-two">City Two</a></li>
                </ul>
            """,
            "https://www.monetka.ru/region-a/shops_map/city-one": """
                <a href="/shops_map/ekb/1">Store 1</a>
                <a href="/shops_map/ekb/99">Store Duplicate</a>
            """,
            "https://www.monetka.ru/region-b/shops_map/city-two": """
                <a href="/shops_map/ekb/2">Store 2</a>
            """,
            "https://www.monetka.ru/shops_map/ekb/1": "<html></html>",
            "https://www.monetka.ru/shops_map/ekb/99": "<html></html>",
            "https://www.monetka.ru/shops_map/ekb/2": "<html></html>",
        }

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(url)
            if url in self._pages:
                return self._pages[url]
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    def fake_parse_store_page(  # type: ignore[no-untyped-def]
        _html: str,
        url: str,
        *,
        context_city: str | None = None,
        context_region: str | None = None,
        fallback_summary: dict[str, str | None] | None = None,
    ) -> StoreRecord:
        if url.endswith("/1") or url.endswith("/99"):
            address = "Address 1"
        else:
            address = "Address 2"
        return StoreRecord.build(
            network=parser.NETWORK_NAME,
            region=context_region,
            city=context_city,
            address=address,
            work_time=None,
            lat=None,
            lng=None,
            phone=None,
            store_format=None,
            status=None,
            source_url=url,
        )

    parser._parse_store_page = fake_parse_store_page  # type: ignore[method-assign]

    stores = parser.parse()

    assert len(stores) == 2
    assert sorted((store.city, store.address) for store in stores) == [
        ("City One", "Address 1"),
        ("City Two", "Address 2"),
    ]
    assert all("/list" not in call for call in parser.client.calls)  # type: ignore[attr-defined]


def test_parse_continues_when_one_city_page_returns_404() -> None:
    class FakeClient:
        calls: list[str] = []

        _pages = {
            "https://www.monetka.ru/shops_map/": """
                <a href="/region-a/change">Region A</a>
            """,
            "https://www.monetka.ru/region-a/change": """
                <ul class="shop_city_list_ul">
                  <li><a href="/region-a/shops_map/city-one">City One</a></li>
                  <li><a href="/region-a/shops_map/city-two">City Two</a></li>
                </ul>
            """,
            "https://www.monetka.ru/region-a/shops_map/city-two": """
                <div class="shopstore">
                  <a href="/shops_map/ekb/2">ул Лесная, 5</a>
                  <div>9:00-21:00</div>
                </div>
            """,
            "https://www.monetka.ru/shops_map/ekb/2": "<html></html>",
        }

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(url)
            if url in self._pages:
                return self._pages[url]
            if url == "https://www.monetka.ru/region-a/shops_map/city-one":
                response = Response()
                response.status_code = 404
                response.url = url
                raise HTTPError("404 Client Error: Not Found", response=response)
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    def fake_parse_store_page(  # type: ignore[no-untyped-def]
        _html: str,
        url: str,
        *,
        context_city: str | None = None,
        context_region: str | None = None,
        fallback_summary: dict[str, str | None] | None = None,
    ) -> StoreRecord:
        return StoreRecord.build(
            network=parser.NETWORK_NAME,
            region=context_region,
            city=context_city,
            address=fallback_summary["address"] if fallback_summary else "ул. Лесная, 5",
            work_time=fallback_summary["work_time"] if fallback_summary else "09:00-21:00",
            lat=None,
            lng=None,
            phone=None,
            store_format=None,
            status=None,
            source_url=url,
        )

    parser._parse_store_page = fake_parse_store_page  # type: ignore[method-assign]

    stores = parser.parse()

    assert len(stores) == 1
    assert stores[0].city == "City Two"
    assert stores[0].region == "Region A"
    assert stores[0].address == "ул. Лесная, 5"
    assert "https://www.monetka.ru/region-a/shops_map/city-one" in parser.client.calls  # type: ignore[attr-defined]
    assert "https://www.monetka.ru/region-a/shops_map/city-two" in parser.client.calls  # type: ignore[attr-defined]


def test_parse_logs_expected_city_page_404_as_warning_not_error(caplog) -> None:
    class FakeClient:
        _pages = {
            "https://www.monetka.ru/shops_map/": """
                <a href="/region-a/change">Region A</a>
            """,
            "https://www.monetka.ru/region-a/change": """
                <ul class="shop_city_list_ul">
                  <li><a href="/region-a/shops_map/city-one">City One</a></li>
                  <li><a href="/region-a/shops_map/city-two">City Two</a></li>
                </ul>
            """,
            "https://www.monetka.ru/region-a/shops_map/city-two": """
                <div class="shopstore">
                  <a href="/shops_map/ekb/2">ул Лесная, 5</a>
                  <div>9:00-21:00</div>
                </div>
            """,
            "https://www.monetka.ru/shops_map/ekb/2": "<html></html>",
        }

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            if url in self._pages:
                return self._pages[url]
            if url == "https://www.monetka.ru/region-a/shops_map/city-one":
                response = Response()
                response.status_code = 404
                response.url = url
                raise HTTPError("404 Client Error: Not Found", response=response)
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    with caplog.at_level(logging.WARNING):
        stores = parser.parse()

    assert len(stores) == 1
    warning_records = [
        record
        for record in caplog.records
        if "city/pagination page unavailable" in record.message and "status_code=404" in record.message
    ]
    assert warning_records
    assert all(record.levelno == logging.WARNING for record in warning_records)
    assert not any(
        record.levelno >= logging.ERROR and "city/pagination page unavailable" in record.message
        for record in caplog.records
    )


def test_parse_raises_when_region_frontier_page_is_unavailable(caplog) -> None:
    class FakeClient:
        _pages = {
            "https://www.monetka.ru/shops_map/": """
                <a href="/region-a/change">Region A</a>
            """,
        }

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            if url in self._pages:
                return self._pages[url]
            if url == "https://www.monetka.ru/region-a/change":
                raise Timeout("region request timed out")
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="Monetka frontier unavailable"):
            parser.parse()

    assert any(
        record.levelno == logging.ERROR and "region page unavailable" in record.message
        for record in caplog.records
    )


def test_parse_raises_when_seed_page_has_no_region_links() -> None:
    class FakeClient:
        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            if url == "https://www.monetka.ru/shops_map/":
                return """
                <ul class="shop_city_list_ul">
                  <li><a href="/region-a/shops_map/city-one">City One</a></li>
                </ul>
                """
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    with pytest.raises(RuntimeError, match="no region links"):
        parser.parse()


def test_parse_logs_unexpected_city_page_failure_as_error(caplog) -> None:
    class FakeClient:
        _pages = {
            "https://www.monetka.ru/shops_map/": """
                <a href="/region-a/change">Region A</a>
            """,
            "https://www.monetka.ru/region-a/change": """
                <ul class="shop_city_list_ul">
                  <li><a href="/region-a/shops_map/city-one">City One</a></li>
                  <li><a href="/region-a/shops_map/city-two">City Two</a></li>
                </ul>
            """,
            "https://www.monetka.ru/region-a/shops_map/city-two": """
                <div class="shopstore">
                  <a href="/shops_map/ekb/2">ул Лесная, 5</a>
                  <div>9:00-21:00</div>
                </div>
            """,
            "https://www.monetka.ru/shops_map/ekb/2": "<html></html>",
        }

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            if url in self._pages:
                return self._pages[url]
            if url == "https://www.monetka.ru/region-a/shops_map/city-one":
                raise RuntimeError("broken city page renderer")
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    with caplog.at_level(logging.WARNING):
        stores = parser.parse()

    assert len(stores) == 1
    error_records = [
        record
        for record in caplog.records
        if record.levelno == logging.ERROR and "failed city/pagination page" in record.message
    ]
    assert error_records


def test_parse_uses_partial_record_when_store_page_returns_404() -> None:
    class FakeClient:
        calls: list[str] = []

        _pages = {
            "https://www.monetka.ru/shops_map/": """
                <a href="/region-a/change">Region A</a>
            """,
            "https://www.monetka.ru/region-a/change": """
                <ul class="shop_city_list_ul">
                  <li><a href="/region-a/shops_map/city-one">City One</a></li>
                </ul>
            """,
            "https://www.monetka.ru/region-a/shops_map/city-one": """
                <div class="shopstore">
                  <a href="/shops_map/ekb/1">ул Зелёная, 35А</a>
                  <div>8:00-21:00</div>
                </div>
            """,
        }

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(url)
            if url in self._pages:
                return self._pages[url]
            if url == "https://www.monetka.ru/shops_map/ekb/1":
                response = Response()
                response.status_code = 404
                response.url = url
                raise HTTPError("404 Client Error: Not Found", response=response)
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    stores = parser.parse()

    assert len(stores) == 1
    assert stores[0].city == "City One"
    assert stores[0].region == "Region A"
    assert stores[0].address == "ул. Зелёная, 35А"
    assert stores[0].work_time == "08:00-21:00"
    assert stores[0].latitude is None
    assert stores[0].longitude is None
    assert stores[0].store_format is None
    assert stores[0].status is None
    assert stores[0].source_url == "https://www.monetka.ru/shops_map/ekb/1"
    assert set(stores[0].to_dict()) == {
        "network",
        "region",
        "city",
        "address",
        "work_time",
        "latitude",
        "longitude",
        "phone",
        "store_format",
        "status",
        "source_url",
        "collected_at",
    }


def test_parse_logs_warning_when_store_page_returns_404_and_partial_record_is_saved(caplog) -> None:
    class FakeClient:
        _pages = {
            "https://www.monetka.ru/shops_map/": """
                <a href="/region-a/change">Region A</a>
            """,
            "https://www.monetka.ru/region-a/change": """
                <ul class="shop_city_list_ul">
                  <li><a href="/region-a/shops_map/city-one">City One</a></li>
                </ul>
            """,
            "https://www.monetka.ru/region-a/shops_map/city-one": """
                <div class="shopstore">
                  <a href="/shops_map/ekb/1">ул Зелёная, 35А</a>
                  <div>8:00-21:00</div>
                </div>
            """,
        }

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            if url in self._pages:
                return self._pages[url]
            if url == "https://www.monetka.ru/shops_map/ekb/1":
                response = Response()
                response.status_code = 404
                response.url = url
                raise HTTPError("404 Client Error: Not Found", response=response)
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    with caplog.at_level("WARNING"):
        stores = parser.parse()

    assert len(stores) == 1
    assert any("detail page unavailable, saved partial record" in record.message for record in caplog.records)
    assert any("status_code=404" in record.message for record in caplog.records)
    assert not any(
        record.levelno >= logging.ERROR and "detail page unavailable, saved partial record" in record.message
        for record in caplog.records
    )


def test_parse_uses_partial_record_when_store_page_times_out() -> None:
    class FakeClient:
        _pages = {
            "https://www.monetka.ru/shops_map/": """
                <a href="/region-a/change">Region A</a>
            """,
            "https://www.monetka.ru/region-a/change": """
                <ul class="shop_city_list_ul">
                  <li><a href="/region-a/shops_map/city-one">City One</a></li>
                </ul>
            """,
            "https://www.monetka.ru/region-a/shops_map/city-one": """
                <div class="shopstore">
                  <a href="/shops_map/ekb/1">ул Зелёная, 35А</a>
                  <div>8:00-21:00</div>
                </div>
            """,
        }

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            if url in self._pages:
                return self._pages[url]
            if url == "https://www.monetka.ru/shops_map/ekb/1":
                raise Timeout("Request timed out")
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    stores = parser.parse()

    assert len(stores) == 1
    assert stores[0].city == "City One"
    assert stores[0].region == "Region A"
    assert stores[0].address == "ул. Зелёная, 35А"
    assert stores[0].work_time == "08:00-21:00"
    assert stores[0].source_url == "https://www.monetka.ru/shops_map/ekb/1"


def test_parse_uses_partial_record_when_store_page_parsing_fails() -> None:
    class FakeClient:
        _pages = {
            "https://www.monetka.ru/shops_map/": """
                <a href="/region-a/change">Region A</a>
            """,
            "https://www.monetka.ru/region-a/change": """
                <ul class="shop_city_list_ul">
                  <li><a href="/region-a/shops_map/city-one">City One</a></li>
                </ul>
            """,
            "https://www.monetka.ru/region-a/shops_map/city-one": """
                <div class="shopstore">
                  <a href="/shops_map/ekb/1">ул Зелёная, 35А</a>
                  <div>8:00-21:00</div>
                </div>
            """,
            "https://www.monetka.ru/shops_map/ekb/1": "<html><body>broken detail</body></html>",
        }

        def get_text(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            if url in self._pages:
                return self._pages[url]
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    def fake_parse_store_page(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("unexpected markup")

    parser._parse_store_page = fake_parse_store_page  # type: ignore[method-assign]

    stores = parser.parse()

    assert len(stores) == 1
    assert stores[0].city == "City One"
    assert stores[0].region == "Region A"
    assert stores[0].address == "ул. Зелёная, 35А"
    assert stores[0].work_time == "08:00-21:00"


def test_parse_store_page_prefers_explicit_location_and_extracts_status_and_coordinates() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <html>
      <head>
        <meta property="place:location:latitude" content="55,1234" />
        <meta property="place:location:longitude" content="82.9876" />
      </head>
      <body>
        <dl>
          <dt>Город</dt><dd>Асбест</dd>
          <dt>Регион</dt><dd>Свердловская область</dd>
          <dt>Адрес</dt><dd>Адрес: у Кирова, 10</dd>
          <dt>Формат магазина</dt><dd>Супермаркет</dd>
          <dt>Статус</dt><dd>Открыт</dd>
        </dl>
      </body>
    </html>
    """

    record = parser._parse_store_page(html, "https://www.monetka.ru/shops_map/ekb/1")

    assert record.city == "Асбест"
    assert record.region == "Свердловская область"
    assert record.address == "Кирова, 10"
    assert record.latitude == 55.1234
    assert record.longitude == 82.9876
    assert record.store_format == "Супермаркет"
    assert record.status == "Открыт"


def test_parse_store_page_keeps_explicit_store_phone_only_from_store_details() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <html>
      <body>
        <dl>
          <dt>Город</dt><dd>Асбест</dd>
          <dt>Регион</dt><dd>Свердловская область</dd>
          <dt>Телефон</dt><dd>8 800 555 35 35</dd>
        </dl>
      </body>
    </html>
    """

    record = parser._parse_store_page(html, "https://www.monetka.ru/shops_map/ekb/1")

    assert record.phone == "8 800 555 35 35"


def test_parse_store_page_does_not_take_global_site_footer_phone_as_store_phone() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <html>
      <body>
        <footer>
          <a href="tel:88001008500"></a>
          <a href="tel:+73432161970">тел: +7 (343) 216-19-70</a>
          <a href="tel:+73432161972">факс: +7 (343) 216-19-72</a>
        </footer>
      </body>
    </html>
    """

    record = parser._parse_store_page(html, "https://www.monetka.ru/shops_map/ekb/1")

    assert record.phone is None


def test_parse_store_page_ignores_detail_title_and_technical_url_slug_without_context() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <html>
      <head>
        <title>Карта магазинов в Екатеринбурге — Магазины «Монетка» — Свердловская область</title>
      </head>
      <body>
        <h1>Карта магазинов в Екатеринбурге</h1>
        <span class="black dashed">Свердловская область</span>
      </body>
    </html>
    """

    record = parser._parse_store_page(html, "https://www.monetka.ru/shops_map/ekb/1")

    assert record.city is None
    assert record.region is None


def test_parse_store_page_uses_crawl_context_when_detail_page_has_only_generic_title() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <html>
      <head>
        <title>Карта магазинов в Екатеринбурге — Магазины «Монетка» — Свердловская область</title>
      </head>
      <body>
        <h1>Карта магазинов в Екатеринбурге</h1>
        <span class="black dashed">Свердловская область</span>
      </body>
    </html>
    """

    record = parser._parse_store_page(
        html,
        "https://www.monetka.ru/shops_map/ekb/4187",
        context_city="Асбест",
        context_region="Свердловская область",
    )

    assert record.city == "Асбест"
    assert record.region == "Свердловская область"


def test_parse_store_page_prefers_explicit_detail_geography_over_conflicting_city_page_context() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <html>
      <head>
        <title>Карта магазинов в Екатеринбурге — Магазины «Монетка» — Свердловская область</title>
      </head>
      <body>
        <h1>Карта магазинов в Екатеринбурге</h1>
        <span class="black dashed">Свердловская область</span>
        <dl>
          <dt>Город</dt><dd>Асбест</dd>
          <dt>Регион</dt><dd>Свердловская область</dd>
        </dl>
      </body>
    </html>
    """

    record = parser._parse_store_page(
        html,
        "https://www.monetka.ru/shops_map/ekb/4187",
        context_city="Абатское",
        context_region="Тюменская область",
    )

    assert record.city == "Асбест"
    assert record.region == "Свердловская область"


def test_parse_store_page_does_not_mix_explicit_detail_city_with_conflicting_context_region() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <html>
      <head>
        <title>Карта магазинов в Екатеринбурге — Магазины «Монетка» — Свердловская область</title>
      </head>
      <body>
        <h1>Карта магазинов в Екатеринбурге</h1>
        <span class="black dashed">Свердловская область</span>
        <dl>
          <dt>Город</dt><dd>Асбест</dd>
        </dl>
      </body>
    </html>
    """

    record = parser._parse_store_page(
        html,
        "https://www.monetka.ru/shops_map/ekb/4187",
        context_city="Абатское",
        context_region="Тюменская область",
    )

    assert record.city == "Асбест"
    assert record.region is None
