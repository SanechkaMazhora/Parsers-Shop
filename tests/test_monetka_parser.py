from __future__ import annotations

from requests import HTTPError, Response
from bs4 import BeautifulSoup

from core.models import StoreRecord
from parsers.monetka_parser import MonetkaParser


def test_extract_city_region_falls_back_to_url_slugs() -> None:
    soup = BeautifulSoup("<html><body>No breadcrumbs</body></html>", "lxml")

    city, region = MonetkaParser._extract_city_region(
        soup,
        "https://www.monetka.ru/orenburgskaya-oblasty/shops_map/aleksandrovka/123",
    )

    assert city == "Aleksandrovka"
    assert region == "Orenburgskaya Oblasty"


def test_apply_city_context_overrides_generic_ekb_url_context() -> None:
    city, region = MonetkaParser._apply_city_context(
        city="Ekaterinburg",
        region="Sverdlovskaya Oblast",
        context_city="Asbest",
        context_region="Sverdlovskaya Oblast",
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
    assert stores[0].source_url == "https://www.monetka.ru/shops_map/ekb/1"
