from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from backend.app.models import AreaMetrics, PlotRecord, PointFeature, PointGeometry
from backend.app.satellite import (
    ASFGUNWCatalog,
    NO_DATA_MESSAGE,
    SOURCE_AVAILABLE_MESSAGE,
)


class FakeHTTPClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[dict[str, str]] = []

    def post(self, _url: str, **kwargs: object) -> httpx.Response:
        self.requests.append(kwargs["data"])  # type: ignore[arg-type]
        return self.responses.pop(0)


def plot() -> PlotRecord:
    point = PointFeature(
        geometry=PointGeometry(coordinates=(-118.25, 34.05)),
        properties={"method": "test"},
    )
    return PlotRecord(
        plot_id="sel_test_plot_001",
        plot_index=1,
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [-118.26, 34.04],
                [-118.24, 34.04],
                [-118.24, 34.06],
                [-118.26, 34.06],
                [-118.26, 34.04],
            ]],
        },
        bbox=(-118.26, 34.04, -118.24, 34.06),
        centroid=point,
        reference_point=point,
        area=AreaMetrics(square_meters=100, hectares=0.01, acres=0.02471),
    )


def response(status: int, body: str, content_type: str = "text/plain") -> httpx.Response:
    return httpx.Response(
        status,
        text=body,
        headers={"content-type": content_type},
        request=httpx.Request("POST", "https://example.test/search"),
    )


def test_available_products_are_normalized_for_downstream_analysis() -> None:
    feature_collection = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": None,
            "properties": {
                "fileID": "S1-GUNW-example",
                "fileName": "S1-GUNW-example.nc",
                "startTime": datetime(2025, 1, 2, tzinfo=UTC).isoformat(),
                "stopTime": datetime(2025, 1, 2, 1, tzinfo=UTC).isoformat(),
                "flightDirection": "ASCENDING",
                "frameNumber": 123,
                "platform": "Sentinel-1A",
                "url": "https://example.test/S1-GUNW-example.nc",
            },
        }],
    }
    fake = FakeHTTPClient([
        response(200, "42"),
        response(200, json.dumps(feature_collection), "application/geo+json"),
        response(200, "0"),
        response(200, "0"),
        response(200, "0"),
        response(200, "0"),
    ])
    catalog = ASFGUNWCatalog("https://example.test/search", http_client=fake)

    availability = catalog.check([plot()])

    assert availability.status == "available"
    assert availability.matched_product_count == 42
    assert availability.archived_gunw_product_count == 42
    assert availability.collections_checked == [
        "ARIA_S1_GUNW",
        "NISAR_L2_GUNW_BETA_V1",
        "NISAR_L2_GUNW_V1",
        "NISAR_UR_L2_GUNW",
        "SENTINEL1_SLC",
    ]
    assert availability.plot_results[0].results_truncated is True
    assert availability.plot_results[0].products[0].product_id == "S1-GUNW-example"
    assert fake.requests[0]["shortName"] == "ARIA_S1_GUNW"
    assert fake.requests[0]["intersectsWith"].startswith("POLYGON")


def test_no_results_returns_clean_no_data_message() -> None:
    catalog = ASFGUNWCatalog(
        "https://example.test/search",
        http_client=FakeHTTPClient([response(200, "0") for _ in range(5)]),
    )

    availability = catalog.check([plot()])

    assert availability.status == "not_available"
    assert availability.message == NO_DATA_MESSAGE
    assert availability.plot_results[0].message == NO_DATA_MESSAGE


def test_catalog_failure_is_not_misreported_as_no_coverage() -> None:
    catalog = ASFGUNWCatalog(
        "https://example.test/search",
        http_client=FakeHTTPClient([response(503, "unavailable") for _ in range(5)]),
    )

    availability = catalog.check([plot()])

    assert availability.status == "check_failed"
    assert "could not be checked" in availability.message


def test_source_scenes_are_distinguished_from_archived_gunw() -> None:
    source_feature = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": None,
            "properties": {"fileID": "S1A_SOURCE_SCENE"},
        }],
    }
    fake = FakeHTTPClient([
        response(200, "0"),
        response(200, "0"),
        response(200, "0"),
        response(200, "0"),
        response(200, "17"),
        response(200, json.dumps(source_feature), "application/geo+json"),
    ])
    catalog = ASFGUNWCatalog("https://example.test/search", http_client=fake)

    availability = catalog.check([plot()])

    assert availability.status == "source_available"
    assert availability.message == SOURCE_AVAILABLE_MESSAGE
    assert availability.archived_gunw_product_count == 0
    assert availability.sentinel1_source_scene_count == 17
    assert availability.on_demand_processing_may_be_possible is True
    assert availability.plot_results[0].status == "source_available"
