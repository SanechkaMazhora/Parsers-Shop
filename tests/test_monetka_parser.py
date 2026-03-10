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
