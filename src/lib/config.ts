import type { StyleSpecification } from "maplibre-gl";

export interface MapConfiguration {
  style: StyleSpecification | string;
  providerName: string;
  providerNotice: string;
  isSatellite: boolean;
  mapTilerKey?: string;
  autocompleteGeocoderUrl: string;
  fallbackGeocoderUrl: string;
  basemapToggle?: {
    satelliteLayerIds: string[];
    mapLayerIds: string[];
    satelliteName: string;
    satelliteNotice: string;
    mapName: string;
    mapNotice: string;
  };
}

const env = import.meta.env;

export const API_BASE_URL = (env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export function getMapConfiguration(): MapConfiguration {
  const mapTilerKey = env.VITE_MAPTILER_API_KEY?.trim();
  const customStyle = env.VITE_MAP_STYLE_URL?.trim();
  const satelliteTiles = env.VITE_SATELLITE_TILE_URL?.trim();
  const configuredAttribution = env.VITE_BASEMAP_ATTRIBUTION?.trim();
  const configuredName = env.VITE_BASEMAP_NAME?.trim();
  const fallbackGeocoderUrl =
    env.VITE_FALLBACK_GEOCODER_URL?.trim() || "https://nominatim.openstreetmap.org";
  const autocompleteGeocoderUrl =
    env.VITE_AUTOCOMPLETE_GEOCODER_URL?.trim() || "https://photon.komoot.io";

  if (customStyle) {
    return {
      style: customStyle.replaceAll("{key}", encodeURIComponent(mapTilerKey ?? "")),
      providerName: configuredName || "Configured imagery",
      providerNotice: configuredAttribution || "Attribution supplied by map style",
      isSatellite: true,
      mapTilerKey,
      autocompleteGeocoderUrl,
      fallbackGeocoderUrl,
    };
  }

  if (satelliteTiles && configuredAttribution) {
    const toggle = switchableRasterStyle(satelliteTiles, configuredAttribution);
    return {
      style: toggle.style,
      providerName: configuredName || "Configured satellite imagery",
      providerNotice: configuredAttribution.replace(/<[^>]+>/g, ""),
      isSatellite: true,
      mapTilerKey,
      autocompleteGeocoderUrl,
      fallbackGeocoderUrl,
      basemapToggle: {
        ...toggle.layers,
        satelliteName: configuredName || "Satellite",
        satelliteNotice: configuredAttribution.replace(/<[^>]+>/g, ""),
        mapName: "Map",
        mapNotice: "© OpenStreetMap contributors",
      },
    };
  }

  if (mapTilerKey) {
    return {
      style: `https://api.maptiler.com/maps/satellite-v4/style.json?key=${encodeURIComponent(mapTilerKey)}`,
      providerName: "MapTiler Satellite",
      providerNotice: "© MapTiler · imagery sources shown in map attribution",
      isSatellite: true,
      mapTilerKey,
      autocompleteGeocoderUrl,
      fallbackGeocoderUrl,
    };
  }

  const demoSatelliteAttribution =
    '<a href="https://cloudless.eox.at" target="_blank">EOxCloudless</a> by EOX IT Services GmbH (modified Copernicus Sentinel data 2025) · <a href="https://www.openstreetmap.org/copyright" target="_blank">© OpenStreetMap contributors</a>';
  const toggle = switchableRasterStyle(
    "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg",
    demoSatelliteAttribution,
    "https://tiles.maps.eox.at/wmts/1.0.0/overlay_3857/default/g/{z}/{y}/{x}.png",
  );
  return {
    style: toggle.style,
    providerName: "Sentinel-2 satellite demo",
    providerNotice: "EOxCloudless 2025 · non-commercial demo imagery",
    isSatellite: true,
    autocompleteGeocoderUrl,
    fallbackGeocoderUrl,
    basemapToggle: {
      ...toggle.layers,
      satelliteName: "Satellite",
      satelliteNotice: "EOxCloudless 2025 · non-commercial demo",
      mapName: "Map",
      mapNotice: "© OpenStreetMap contributors",
    },
  };
}

function switchableRasterStyle(
  satelliteTileUrl: string,
  satelliteAttribution: string,
  referenceTileUrl?: string,
): {
  style: StyleSpecification;
  layers: { satelliteLayerIds: string[]; mapLayerIds: string[] };
} {
  const mapAttribution =
    '<a href="https://www.openstreetmap.org/copyright" target="_blank">© OpenStreetMap contributors</a>';
  const sources: StyleSpecification["sources"] = {
    satellite: {
      type: "raster",
      tiles: [satelliteTileUrl],
      tileSize: 256,
      attribution: satelliteAttribution,
      maxzoom: 14,
    },
    streets: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: mapAttribution,
      maxzoom: 19,
    },
  };
  const satelliteLayerIds = ["satellite"];
  const layers: StyleSpecification["layers"] = [
    { id: "satellite", type: "raster", source: "satellite" },
    { id: "streets", type: "raster", source: "streets", layout: { visibility: "none" } },
  ];
  if (referenceTileUrl) {
    sources.reference = {
      type: "raster",
      tiles: [referenceTileUrl],
      tileSize: 256,
      attribution: mapAttribution,
      maxzoom: 19,
    };
    layers.push({ id: "satellite-reference", type: "raster", source: "reference" });
    satelliteLayerIds.push("satellite-reference");
  }
  return {
    style: { version: 8, name: "Groundsignal switchable basemap", sources, layers },
    layers: { satelliteLayerIds, mapLayerIds: ["streets"] },
  };
}
