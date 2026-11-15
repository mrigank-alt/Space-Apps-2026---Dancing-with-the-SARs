from __future__ import annotations

import argparse
import json

from backend.app.config import Settings
from backend.app.repository import SQLiteSelectionRepository
from backend.app.satellite import ASFGUNWCatalog


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recheck NASA ASF GUNW collections and Sentinel-1 source coverage "
            "for a saved farm selection."
        )
    )
    parser.add_argument("selection_id", help="Saved Groundsignal selection ID")
    args = parser.parse_args()

    settings = Settings.from_environment()
    repository = SQLiteSelectionRepository(settings.database_path)
    selection = repository.get(args.selection_id)
    if selection is None:
        parser.error(f"No saved farm exists with ID {args.selection_id}")

    catalog = ASFGUNWCatalog(
        settings.asf_search_api_url,
        settings.gunw_catalog_timeout_seconds,
        settings.gunw_product_sample_limit,
    )
    availability = catalog.check(selection.plots)
    updated = selection.model_copy(update={"gunw_availability": availability})
    repository.save(updated)
    print(json.dumps(availability.model_dump(mode="json"), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
