from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from shapely.geometry import shape

from .models import (
    DatasetAvailability,
    GUNWAvailability,
    GUNWProduct,
    PlotGUNWAvailability,
    PlotRecord,
)


NO_DATA_MESSAGE = (
    "No archived GUNW product or Sentinel-1 SLC source scene was found for this land "
    "in the NASA ASF catalog."
)
SOURCE_AVAILABLE_MESSAGE = (
    "No archived GUNW product was found, but Sentinel-1 source scenes are available. "
    "On-demand interferogram processing may be possible."
)
CHECK_FAILED_MESSAGE = (
    "Your farm was saved, but satellite availability could not be checked right now. "
    "Please try the data check again later."
)


class GUNWCatalog(Protocol):
    def check(self, plots: list[PlotRecord]) -> GUNWAvailability: ...


class HTTPClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class ASFGUNWCatalog:
    """Checks ASF GUNW holdings and Sentinel-1 source coverage for every plot."""

    GUNW_DATASETS: tuple[tuple[str, str, dict[str, str]], ...] = (
        (
            "NISAR_L2_GUNW_PROVISIONAL_V1",
            "NISAR Provisional L2 GUNW",
            {"shortName": "NISAR_L2_GUNW_PROVISIONAL_V1"},
        ),
        (
            "ARIA_S1_GUNW",
            "ARIA Sentinel-1 GUNW",
            {"shortName": "ARIA_S1_GUNW"},
        ),
        (
            "NISAR_L2_GUNW_BETA_V1",
            "NISAR Beta L2 GUNW",
            {"shortName": "NISAR_L2_GUNW_BETA_V1"},
        ),
        (
            "NISAR_L2_GUNW_V1",
            "NISAR Validated L2 GUNW",
            {"shortName": "NISAR_L2_GUNW_V1"},
        ),
        (
            "NISAR_UR_L2_GUNW",
            "NISAR Urgent Response L2 GUNW",
            {
                "shortName": "NISAR_UR_L2",
                "granule_list": "NISAR_L2_UR_GUNW*",
                "maxResults": "250",
            },
        ),
    )
    SOURCE_DATASETS: tuple[tuple[str, str, dict[str, str]], ...] = (
        (
            "SENTINEL1_SLC",
            "Sentinel-1 SLC source scenes",
            {"dataset": "SENTINEL-1", "processingLevel": "SLC"},
        ),
    )

    def __init__(
        self,
        endpoint: str,
        timeout_seconds: float = 20.0,
        product_sample_limit: int = 20,
        http_client: HTTPClient | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout_seconds
        self._sample_limit = product_sample_limit
        self._http = http_client or httpx.Client(
            timeout=timeout_seconds,
            headers={"User-Agent": "Groundsignal/1.0 GUNW availability checker"},
        )

    def check(self, plots: list[PlotRecord]) -> GUNWAvailability:
        checked_at = datetime.now(UTC)
        workers = min(4, max(1, len(plots)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(self._check_plot, plots))
        available = sum(result.status == "available" for result in results)
        source_available = sum(result.status == "source_available" for result in results)
        failed = sum(result.status == "check_failed" for result in results)
        total_products = sum(result.archived_gunw_product_count for result in results)
        total_source_scenes = sum(result.source_scene_count for result in results)

        if available == len(results) and results:
            status = "available"
            message = "Archived GUNW products are available for every selected plot."
        elif available:
            status = "partial"
            message = "Archived GUNW products are available for some selected plots."
        elif source_available:
            status = "source_available"
            message = SOURCE_AVAILABLE_MESSAGE
        elif failed:
            status = "check_failed"
            message = CHECK_FAILED_MESSAGE
        else:
            status = "not_available"
            message = NO_DATA_MESSAGE

        return GUNWAvailability(
            status=status,
            checked_at=checked_at,
            matched_product_count=total_products,
            archived_gunw_product_count=total_products,
            sentinel1_source_scene_count=total_source_scenes,
            on_demand_processing_may_be_possible=total_source_scenes > 0,
            collections_checked=[
                dataset_id
                for dataset_id, _label, _params in (*self.GUNW_DATASETS, *self.SOURCE_DATASETS)
            ],
            plot_results=results,
            message=message,
        )

    def _check_plot(self, plot: PlotRecord) -> PlotGUNWAvailability:
        try:
            geometry = shape(plot.geometry).simplify(0.00005, preserve_topology=True)
            datasets = [
                self._check_dataset(geometry.wkt, dataset_id, label, "gunw", params)
                for dataset_id, label, params in self.GUNW_DATASETS
            ]
            datasets.extend(
                self._check_dataset(geometry.wkt, dataset_id, label, "source", params)
                for dataset_id, label, params in self.SOURCE_DATASETS
            )
            gunw_count = sum(
                result.matched_product_count
                for result in datasets
                if result.category == "gunw"
            )
            source_count = sum(
                result.matched_product_count
                for result in datasets
                if result.category == "source"
            )
            products = [
                product
                for result in datasets
                if result.category == "gunw"
                for product in result.products
            ]
            failed = any(result.status == "check_failed" for result in datasets)

            if gunw_count:
                status = "available"
                message = f"{gunw_count:,} archived GUNW plot-product matches were found."
            elif source_count:
                status = "source_available"
                message = SOURCE_AVAILABLE_MESSAGE
            elif failed:
                status = "check_failed"
                message = CHECK_FAILED_MESSAGE
            else:
                status = "not_available"
                message = NO_DATA_MESSAGE

            return PlotGUNWAvailability(
                plot_id=plot.plot_id,
                status=status,
                matched_product_count=gunw_count,
                archived_gunw_product_count=gunw_count,
                source_scene_count=source_count,
                products=products,
                datasets=datasets,
                results_truncated=any(result.results_truncated for result in datasets),
                message=message,
            )
        except (ValueError, TypeError, KeyError):
            return PlotGUNWAvailability(
                plot_id=plot.plot_id,
                status="check_failed",
                message=CHECK_FAILED_MESSAGE,
            )

    def _check_dataset(
        self,
        wkt: str,
        dataset_id: str,
        label: str,
        category: str,
        parameters: dict[str, str],
    ) -> DatasetAvailability:
        base = {**parameters, "intersectsWith": wkt}
        try:
            count_response = self._http.post(
                self._endpoint,
                data={**base, "output": "count"},
                timeout=self._timeout,
            )
            count_response.raise_for_status()
            count = int(count_response.text.strip())
            if count == 0:
                return DatasetAvailability(
                    dataset_id=dataset_id,
                    label=label,
                    category=category,
                    status="not_available",
                    message=f"No matching {label} products were found.",
                )

            results_response = self._http.post(
                self._endpoint,
                data={
                    **base,
                    "output": "geojson",
                    "maxResults": str(self._sample_limit),
                },
                timeout=self._timeout,
            )
            results_response.raise_for_status()
            features = results_response.json().get("features", [])
            products = [self._product(feature, dataset_id) for feature in features]
            return DatasetAvailability(
                dataset_id=dataset_id,
                label=label,
                category=category,
                status="available",
                matched_product_count=count,
                products=products,
                results_truncated=count > len(products),
                message=f"{count:,} matching {label} products were found.",
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return DatasetAvailability(
                dataset_id=dataset_id,
                label=label,
                category=category,
                status="check_failed",
                message=CHECK_FAILED_MESSAGE,
            )

    @staticmethod
    def _product(feature: dict[str, Any], collection: str) -> GUNWProduct:
        properties = feature.get("properties", {})
        product_id = properties.get("fileID") or properties.get("sceneName")
        if not product_id:
            raise ValueError("ASF product is missing an identifier.")
        return GUNWProduct(
            product_id=str(product_id),
            collection=collection,
            file_name=properties.get("fileName"),
            start_time=properties.get("startTime"),
            stop_time=properties.get("stopTime"),
            flight_direction=properties.get("flightDirection"),
            frame_number=properties.get("frameNumber"),
            platform=properties.get("platform"),
            download_url=properties.get("url"),
        )


class DisabledGUNWCatalog:
    def check(self, plots: list[PlotRecord]) -> GUNWAvailability:
        return GUNWAvailability(
            status="not_checked",
            message="Satellite availability checking is disabled in this environment.",
            plot_results=[
                PlotGUNWAvailability(
                    plot_id=plot.plot_id,
                    status="not_checked",
                    message="Satellite availability checking is disabled in this environment.",
                )
                for plot in plots
            ],
            earthdata_login_required_for_download=True,
        )
