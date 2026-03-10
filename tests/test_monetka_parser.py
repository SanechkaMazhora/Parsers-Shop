from __future__ import annotations

from bs4 import BeautifulSoup

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
