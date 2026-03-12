from __future__ import annotations

from bs4 import BeautifulSoup

from core.models import StoreRecord
from parsers.monetka_parser import MonetkaParser


def test_extract_city_region_prefers_breadcrumb_names() -> None:
    html = """
    <div class="breadcrumbs">
      <a>Главная</a>
      <a>Магазины</a>
      <a>Свердловская область</a>
      <span>Екатеринбург</span>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")

    city, region = MonetkaParser._extract_city_region(soup, "https://www.monetka.ru/urfo/shops_map/ekb/1194")

    assert city == "Екатеринбург"
    assert region == "Свердловская область"


def test_extract_city_region_falls_back_to_url_slugs() -> None:
    soup = BeautifulSoup("<html><body>No breadcrumbs</body></html>", "lxml")

    city, region = MonetkaParser._extract_city_region(
        soup,
        "https://www.monetka.ru/orenburgskaya-oblasty/shops_map/aleksandrovka/123",
    )

    assert city == "Aleksandrovka"
    assert region == "Orenburgskaya Oblasty"


def test_pick_city_from_crumbs_skips_address_like_values() -> None:
    crumbs = ["Главная", "Магазины", "Тюменская область", "ул. Ленина, 1"]

    city = MonetkaParser._pick_city_from_crumbs(crumbs, city_slug=None)

    assert city is None


def test_extract_city_region_prefers_visible_text_over_url_slug() -> None:
    html = """
    <dl>
      <dt>Город</dt>
      <dd>Екатеринбург</dd>
      <dt>Регион</dt>
      <dd>Свердловская область</dd>
    </dl>
    """
    soup = BeautifulSoup(html, "lxml")

    city, region = MonetkaParser._extract_city_region(soup, "https://www.monetka.ru/urfo/shops_map/ekb/1194")

    assert city == "Екатеринбург"
    assert region == "Свердловская область"


def test_apply_city_context_overrides_generic_ekb_url_context() -> None:
    city, region = MonetkaParser._apply_city_context(
        city="Екатеринбург",
        region="Свердловская область",
        context_city="Асбест",
        context_region="Свердловская область",
        source_url="https://www.monetka.ru/shops_map/ekb/4187",
    )

    assert city == "Асбест"
    assert region == "Свердловская область"


def test_extract_city_context_uses_h1_and_region_hint_when_title_format_is_legacy() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <html>
      <head>
        <title>Адреса магазинов продуктов питания в г. Нижний Тагил - Торговая сеть "Монетка"</title>
      </head>
      <body>
        <span class="black dashed">Свердловская область</span>
        <h1>Карта магазинов в Нижнем Тагиле</h1>
      </body>
    </html>
    """

    city, region = parser._extract_city_context(html, "https://www.monetka.ru/urfo/shops_map/Nizhny_Tagil")

    assert city == "Нижнем Тагиле"
    assert region == "Свердловская область"


def test_extract_region_links_discovers_non_urfo_regions() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <a href="/urfo/shops_map/">УРФО</a>
    <a href="/orenburgskaya-oblasty/shops_map">Оренбургская область</a>
    <a href="/shops_map/ekb/1194">Store</a>
    """

    links = sorted(parser._extract_region_links(html, "https://www.monetka.ru/shops_map/"))

    assert "https://www.monetka.ru/urfo/shops_map/" in links
    assert "https://www.monetka.ru/orenburgskaya-oblasty/shops_map/" in links
    assert all("/shops_map/ekb/" not in link for link in links)


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


def test_extract_region_links_discovers_change_regions() -> None:
    parser = MonetkaParser(client=None)
    html = """
    <a href="/orenburgskaya-oblast/change">Orenburg</a>
    <a href="/Bashkortostan/change/">Bashkortostan</a>
    <a href="/shops_map/ekb/1194">Store</a>
    """

    links = sorted(parser._extract_region_links(html, "https://www.monetka.ru/shops_map/"))

    assert "https://www.monetka.ru/orenburgskaya-oblast/change/" in links
    assert "https://www.monetka.ru/Bashkortostan/change/" in links
    assert all("/shops_map/ekb/" not in link for link in links)


def test_collect_region_pages_uses_dynamic_change_links_from_root() -> None:
    class FakeClient:
        def get_text(self, url: str) -> str:  # type: ignore[no-untyped-def]
            if url == "https://www.monetka.ru/shops_map/":
                return """
                <a href="/orenburgskaya-oblast/change">Orenburg</a>
                <a href="/Bashkortostan/change">Bashkortostan</a>
                """
            raise RuntimeError(f"Unexpected URL: {url}")

    parser = MonetkaParser(client=FakeClient())

    regions = parser._collect_region_pages()

    assert regions == [
        "https://www.monetka.ru/Bashkortostan/change/",
        "https://www.monetka.ru/orenburgskaya-oblast/change/",
    ]


def test_parse_deduplicates_stores_by_network_city_address() -> None:
    class FakeClient:
        _pages = {
            "https://www.monetka.ru/shops_map/": """
                <a href="/region-a/change">Region A</a>
                <a href="/region-b/change">Region B</a>
            """,
            "https://www.monetka.ru/region-a/shops_map/": """
                <a href="/region-a/shops_map/city-one">City One</a>
            """,
            "https://www.monetka.ru/region-b/shops_map/": """
                <a href="/region-b/shops_map/city-two">City Two</a>
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

        def get_text(self, url: str) -> str:  # type: ignore[no-untyped-def]
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
    ) -> StoreRecord:
        if url.endswith("/1") or url.endswith("/99"):
            address = "ул. Ленина, 1"
        else:
            address = "ул. Советская, 10"
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
        ("City One", "ул. Ленина, 1"),
        ("City Two", "ул. Советская, 10"),
    ]
