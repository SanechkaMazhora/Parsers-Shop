from __future__ import annotations

import sys
from types import SimpleNamespace

from requests import HTTPError, Response

import main as main_module
from core.models import StoreRecord
from parsers.monetka_parser import MonetkaParser


def _make_store(*, network: str = "Test", city: str = "City", address: str = "Address 1") -> StoreRecord:
    return StoreRecord.build(
        network=network,
        region="Region",
        city=city,
        address=address,
        work_time=None,
        lat=None,
        lng=None,
        phone=None,
        store_format=None,
        status=None,
        source_url=f"https://example.com/{network}/{city}/{address}",
    )


def test_run_returns_non_zero_when_any_parser_fails_but_exports_partial_results(monkeypatch) -> None:
    exported: dict[str, object] = {}

    class GoodParser:
        def parse(self) -> list[StoreRecord]:
            return [_make_store(network="Good")]

    class BrokenParser:
        def parse(self) -> list[StoreRecord]:
            raise RuntimeError("fatal parser error")

    def fake_export(  # type: ignore[no-untyped-def]
        stores,
        output_path,
        snapshot_path,
        *,
        write_snapshot=True,
        treat_diff_as_initial=False,
    ):
        exported["stores"] = list(stores)
        exported["output_path"] = output_path
        exported["snapshot_path"] = snapshot_path
        exported["write_snapshot"] = write_snapshot
        exported["treat_diff_as_initial"] = treat_diff_as_initial
        return SimpleNamespace(added=[], removed=[], changed=[])

    monkeypatch.setattr(main_module, "setup_logging", lambda: None)
    monkeypatch.setattr(
        main_module,
        "get_selected_parsers",
        lambda network=None: [("good", GoodParser()), ("broken", BrokenParser())],
    )
    monkeypatch.setattr(main_module, "export_stores_to_excel", fake_export)

    exit_code = main_module.run(output_path="output/test.xlsx", snapshot_path="output/test.json")

    assert exit_code == main_module.EXIT_RUNTIME_FAILURE
    assert exported["output_path"] == "output/test.xlsx"
    assert exported["snapshot_path"] == "output/test.json"
    assert exported["write_snapshot"] is False
    assert exported["treat_diff_as_initial"] is True
    stores = exported["stores"]
    assert isinstance(stores, list)
    assert len(stores) == 1
    assert stores[0].network == "Good"


def test_run_stays_successful_when_monetka_handles_expected_404(monkeypatch) -> None:
    exported: dict[str, object] = {}

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

    monetka = MonetkaParser(client=FakeClient())

    def fake_export(  # type: ignore[no-untyped-def]
        stores,
        output_path,
        snapshot_path,
        *,
        write_snapshot=True,
        treat_diff_as_initial=False,
    ):
        exported["stores"] = list(stores)
        exported["write_snapshot"] = write_snapshot
        exported["treat_diff_as_initial"] = treat_diff_as_initial
        return SimpleNamespace(added=[], removed=[], changed=[])

    monkeypatch.setattr(main_module, "setup_logging", lambda: None)
    monkeypatch.setattr(main_module, "get_selected_parsers", lambda network=None: [("monetka", monetka)])
    monkeypatch.setattr(main_module, "export_stores_to_excel", fake_export)

    exit_code = main_module.run(network="monetka")

    assert exit_code == main_module.EXIT_SUCCESS
    stores = exported["stores"]
    assert isinstance(stores, list)
    assert len(stores) == 1
    assert stores[0].city == "City One"
    assert stores[0].region == "Region A"
    assert exported["write_snapshot"] is True
    assert exported["treat_diff_as_initial"] is False


def test_main_returns_run_exit_code_for_run_command(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(  # type: ignore[no-untyped-def]
        network=None,
        *,
        output_path=None,
        snapshot_path=None,
    ):
        captured["network"] = network
        captured["output_path"] = output_path
        captured["snapshot_path"] = snapshot_path
        return main_module.EXIT_RUNTIME_FAILURE

    monkeypatch.setattr(main_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(main_module, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "run",
            "--network",
            "kb",
            "--output",
            "custom.xlsx",
            "--snapshot",
            "custom.json",
        ],
    )

    exit_code = main_module.main()

    assert exit_code == main_module.EXIT_RUNTIME_FAILURE
    assert captured == {
        "network": "kb",
        "output_path": "custom.xlsx",
        "snapshot_path": "custom.json",
    }


def test_main_without_subcommand_defaults_to_full_run(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(  # type: ignore[no-untyped-def]
        network=None,
        *,
        output_path=None,
        snapshot_path=None,
    ):
        captured["network"] = network
        captured["output_path"] = output_path
        captured["snapshot_path"] = snapshot_path
        return main_module.EXIT_SUCCESS

    monkeypatch.setattr(main_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(main_module, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["main.py"])

    exit_code = main_module.main()

    assert exit_code == main_module.EXIT_SUCCESS
    assert captured == {
        "network": None,
        "output_path": None,
        "snapshot_path": None,
    }
