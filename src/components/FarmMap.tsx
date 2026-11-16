import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { Feature, Geometry } from "geojson";
import maplibregl, { type Map as MapLibreMap, type Marker } from "maplibre-gl";
import {
  TerraDraw,
  TerraDrawFreehandMode,
  TerraDrawModeUndoRedo,
  TerraDrawPolygonMode,
  TerraDrawSelectMode,
  TerraDrawSessionUndoRedo,
  TerraDrawUndoRedoKeyboardShortcuts,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";
import type { MapConfiguration } from "../lib/config";
import { boundaryFromSnapshot } from "../lib/geometry";
import type { Assessment, BoundaryFeature, BoundaryGeometry, ConcernZoneProperties, DrawingTool, SearchResult } from "../types";

export interface FarmMapHandle {
  undo: () => void;
  clear: () => void;
}

interface FarmMapProps {
  configuration: MapConfiguration;
  activeTool: DrawingTool;
  location: SearchResult | null;
  onBoundaryChange: (feature: BoundaryFeature | null) => void;
  onToolChange: (tool: DrawingTool) => void;
  onUndoAvailability: (available: boolean) => void;
  onUseMyLocation: () => void;
  locating: boolean;
  assessment?: Assessment | null;
  selectedPlotId?: string | null;
  onZoneSelect?: (zone: ConcernZoneProperties) => void;
  savedBoundary?: BoundaryGeometry | null;
}

const INITIAL_CENTER: [number, number] = [-112.149, 49.788];

export const FarmMap = forwardRef<FarmMapHandle, FarmMapProps>(function FarmMap(
  {
    configuration,
    activeTool,
    location,
    onBoundaryChange,
    onToolChange,
    onUndoAvailability,
    onUseMyLocation,
    locating,
    assessment,
    selectedPlotId,
    onZoneSelect,
    savedBoundary,
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | undefined>(undefined);
  const drawRef = useRef<TerraDraw | undefined>(undefined);
  const locationMarkerRef = useRef<Marker | undefined>(undefined);
  const drawSyncFrame = useRef<number | null>(null);
  const zoneDetailsRef = useRef(new Map<string, ConcernZoneProperties>());
  const callbackRef = useRef({ onBoundaryChange, onToolChange, onUndoAvailability, onZoneSelect, activeTool });
  const [ready, setReady] = useState(false);
  const [basemapMode, setBasemapMode] = useState<"satellite" | "map">("satellite");
  const [resultMode, setResultMode] = useState<"concern" | "movement">("concern");

  callbackRef.current = { onBoundaryChange, onToolChange, onUndoAvailability, onZoneSelect, activeTool };

  function syncBoundary(draw = drawRef.current) {
    if (!draw) return;
    const boundary = boundaryFromSnapshot(draw.getSnapshot() as Array<Feature<Geometry>>);
    callbackRef.current.onBoundaryChange(boundary);
    callbackRef.current.onUndoAvailability(draw.canUndo());
  }

  useImperativeHandle(ref, () => ({
    undo() {
      const draw = drawRef.current;
      if (!draw) return;
      draw.undo();
      syncBoundary(draw);
    },
    clear() {
      const draw = drawRef.current;
      if (!draw) return;
      draw.clear();
      draw.clearUndoRedoHistory();
      callbackRef.current.onBoundaryChange(null);
      callbackRef.current.onUndoAvailability(false);
    },
  }));

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: configuration.style,
      center: INITIAL_CENTER,
      zoom: 13,
      minZoom: 2,
      maxZoom: 22,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial", maxWidth: 140 }), "bottom-left");

    map.once("load", () => {
      const draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({
          map,
          coordinatePrecision: 8,
        }),
        modes: [
          new TerraDrawPolygonMode({
            showCoordinatePoints: false,
            styles: {
              fillColor: "#d8ff70",
              fillOpacity: 0.28,
              outlineColor: "#ffffff",
              outlineWidth: 3,
              closingPointColor: "#d8ff70",
              closingPointWidth: 8,
              closingPointOutlineColor: "#183c2f",
              closingPointOutlineWidth: 2,
            },
          }),
          new TerraDrawFreehandMode({
            drawInteraction: "click-drag",
            autoClose: true,
            minDistance: 4,
            smoothing: 0.18,
            showCoordinatePoints: false,
            styles: {
              fillColor: "#d8ff70",
              fillOpacity: 0.28,
              outlineColor: "#ffffff",
              outlineWidth: 3,
              closingPointColor: "#d8ff70",
              closingPointWidth: 8,
              closingPointOutlineColor: "#183c2f",
              closingPointOutlineWidth: 2,
            },
          }),
          new TerraDrawSelectMode({
            allowManualDeselection: false,
            flags: {
              polygon: {
                feature: {
                  draggable: true,
                  coordinates: {
                    draggable: true,
                    deletable: true,
                    midpoints: { draggable: true },
                  },
                },
              },
              freehand: {
                feature: {
                  draggable: true,
                  coordinates: {
                    draggable: true,
                    deletable: true,
                    midpoints: false,
                  },
                },
              },
            },
            styles: {
              selectedPolygonColor: "#d8ff70",
              selectedPolygonFillOpacity: 0.38,
              selectedPolygonOutlineColor: "#f8ffe7",
              selectedPolygonOutlineWidth: 4,
              selectionPointColor: "#d8ff70",
              selectionPointWidth: 9,
              selectionPointOutlineColor: "#183c2f",
              selectionPointOutlineWidth: 3,
              midPointColor: "#ffffff",
              midPointWidth: 7,
              midPointOutlineColor: "#183c2f",
              midPointOutlineWidth: 2,
            },
          }),
        ],
        undoRedo: {
          modeLevel: new TerraDrawModeUndoRedo({ maxStackSize: 100 }),
          sessionLevel: new TerraDrawSessionUndoRedo({ maxStackSize: 100 }),
          keyboardShortcuts: new TerraDrawUndoRedoKeyboardShortcuts(),
        },
      });

      draw.start();
      draw.setMode("select");
      draw.on("finish", (id, context) => {
        syncBoundary(draw);
        if (context.action === "draw") {
          draw.setMode("select");
          draw.selectFeature(id);
          callbackRef.current.onToolChange("edit");
        }
      });
      draw.on("change", () => {
        if (drawSyncFrame.current !== null) return;
        drawSyncFrame.current = requestAnimationFrame(() => {
          drawSyncFrame.current = null;
          syncBoundary(draw);
        });
      });
      draw.on("history", () => callbackRef.current.onUndoAvailability(draw.canUndo()));
      drawRef.current = draw;
      setReady(true);
    });

    return () => {
      if (drawSyncFrame.current !== null) cancelAnimationFrame(drawSyncFrame.current);
      drawSyncFrame.current = null;
      setReady(false);
      locationMarkerRef.current?.remove();
      if (drawRef.current?.enabled) drawRef.current.stop();
      drawRef.current = undefined;
      map.remove();
      mapRef.current = undefined;
    };
  }, [configuration.style]);

  useEffect(() => {
    const draw = drawRef.current;
    if (!draw || !ready) return;
    const mode =
      activeTool === "polygon" || activeTool === "freehand"
        ? activeTool
        : "select";
    if (draw.getMode() !== mode) draw.setMode(mode);
  }, [activeTool, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !location) return;

    locationMarkerRef.current?.remove();
    const element = document.createElement("div");
    element.className = "location-marker";
    element.setAttribute("aria-label", `Search location: ${location.label}`);
    element.innerHTML = "<span></span>";
    locationMarkerRef.current = new maplibregl.Marker({ element })
      .setLngLat(location.center)
      .addTo(map);

    if (location.targetZoom) {
      map.flyTo({
        center: location.center,
        zoom: location.targetZoom,
        duration: 1200,
        essential: true,
      });
    } else if (location.bbox) {
      map.fitBounds(
        [[location.bbox[0], location.bbox[1]], [location.bbox[2], location.bbox[3]]],
        { padding: 90, maxZoom: 16, duration: 1200 },
      );
    } else {
      map.flyTo({ center: location.center, zoom: 15, duration: 1200, essential: true });
    }
  }, [location]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const sourceId = "concern-zones";
    const fillId = "concern-zones-fill";
    const lineId = "concern-zones-line";
    const movementId = "concern-zones-movement";
    if (!assessment) {
      zoneDetailsRef.current.clear();
      if (map.getLayer(lineId)) map.removeLayer(lineId);
      if (map.getLayer(movementId)) map.removeLayer(movementId);
      if (map.getLayer(fillId)) map.removeLayer(fillId);
      if (map.getSource(sourceId)) map.removeSource(sourceId);
      return;
    }
    zoneDetailsRef.current = new Map(assessment.concern_zones.features.map((feature) => [feature.properties.zone_id, feature.properties]));
    const mapData = {
      type: "FeatureCollection" as const,
      features: assessment.concern_zones.features.map((feature) => ({
        type: "Feature" as const,
        id: feature.id,
        geometry: feature.geometry,
        properties: { zone_id: feature.properties.zone_id, plot_id: feature.properties.plot_id, concern_level: feature.properties.concern_level, los_velocity_cm_year: feature.properties.los_velocity_cm_year },
      })),
    };
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: "geojson", data: mapData, tolerance: 0.375, buffer: 32, maxzoom: 17 });
      map.addLayer({
        id: fillId,
        type: "fill",
        source: sourceId,
        paint: {
          "fill-color": ["match", ["get", "concern_level"], "red", "#b83232", "yellow", "#f1c84b", "green", "#2f7d4b", "#7b8581"],
          "fill-opacity": 0.62,
        },
      });
      map.addLayer({
        id: lineId,
        type: "line",
        source: sourceId,
        paint: { "line-color": "#ffffff", "line-width": 1.5, "line-opacity": 0.9 },
      });
      map.addLayer({
        id: movementId,
        type: "fill",
        source: sourceId,
        layout: { visibility: "none" },
        paint: { "fill-color": ["interpolate", ["linear"], ["coalesce", ["get", "los_velocity_cm_year"], 0], -5, "#315a9b", 0, "#f2efdf", 5, "#b83232"], "fill-opacity": 0.72 },
      });
    } else {
      const mark = `concern-zones-${Date.now()}`;
      performance.mark(`${mark}-start`);
      (map.getSource(sourceId) as maplibregl.GeoJSONSource).setData(mapData);
      map.once("idle", () => {
        performance.mark(`${mark}-end`);
        performance.measure("concern-zones-update", `${mark}-start`, `${mark}-end`);
        performance.clearMarks(`${mark}-start`);
        performance.clearMarks(`${mark}-end`);
      });
    }
    const click = (event: maplibregl.MapLayerMouseEvent) => {
      const mapProperties = event.features?.[0]?.properties as { zone_id?: string } | undefined;
      if (["polygon", "freehand"].includes(callbackRef.current.activeTool)) return;
      const properties = mapProperties?.zone_id ? zoneDetailsRef.current.get(mapProperties.zone_id) : undefined;
      if (properties) callbackRef.current.onZoneSelect?.(properties);
    };
    const enter = () => { map.getCanvas().style.cursor = "pointer"; };
    const leave = () => { map.getCanvas().style.cursor = ""; };
    map.on("click", fillId, click);
    map.on("click", movementId, click);
    map.on("mouseenter", fillId, enter);
    map.on("mouseleave", fillId, leave);
    return () => {
      map.off("click", fillId, click);
      map.off("click", movementId, click);
      map.off("mouseenter", fillId, enter);
      map.off("mouseleave", fillId, leave);
    };
  }, [assessment, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const filter: maplibregl.FilterSpecification | null = selectedPlotId ? ["==", ["get", "plot_id"], selectedPlotId] : null;
    if (map.getLayer("concern-zones-fill")) map.setFilter("concern-zones-fill", filter);
    if (map.getLayer("concern-zones-line")) map.setFilter("concern-zones-line", filter);
    if (map.getLayer("concern-zones-movement")) map.setFilter("concern-zones-movement", filter);
  }, [ready, selectedPlotId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (map.getLayer("concern-zones-fill")) map.setLayoutProperty("concern-zones-fill", "visibility", resultMode === "concern" ? "visible" : "none");
    if (map.getLayer("concern-zones-line")) map.setLayoutProperty("concern-zones-line", "visibility", resultMode === "concern" ? "visible" : "none");
    if (map.getLayer("concern-zones-movement")) map.setLayoutProperty("concern-zones-movement", "visibility", resultMode === "movement" ? "visible" : "none");
  }, [ready, resultMode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const sourceId = "saved-farm";
    const fillId = "saved-farm-fill";
    const lineId = "saved-farm-line";
    if (!savedBoundary) {
      if (map.getLayer(lineId)) map.removeLayer(lineId);
      if (map.getLayer(fillId)) map.removeLayer(fillId);
      if (map.getSource(sourceId)) map.removeSource(sourceId);
      return;
    }
    const data = { type: "Feature" as const, properties: {}, geometry: savedBoundary };
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: "geojson", data });
      map.addLayer({ id: fillId, type: "fill", source: sourceId, paint: { "fill-color": "#d8ff70", "fill-opacity": 0.08 } });
      map.addLayer({ id: lineId, type: "line", source: sourceId, paint: { "line-color": "#f8ffe7", "line-width": 3 } });
    } else {
      (map.getSource(sourceId) as maplibregl.GeoJSONSource).setData(data);
    }
    const coordinates: [number, number][] = [];
    const collect = (value: unknown) => {
      if (!Array.isArray(value)) return;
      if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
        coordinates.push([value[0], value[1]]);
      } else value.forEach(collect);
    };
    collect(savedBoundary.coordinates);
    if (coordinates.length) {
      const bounds = coordinates.reduce((result, point) => result.extend(point), new maplibregl.LngLatBounds(coordinates[0], coordinates[0]));
      map.fitBounds(bounds, { padding: 90, maxZoom: 17, duration: 900 });
    }
  }, [ready, savedBoundary]);

  function changeBasemap(mode: "satellite" | "map") {
    const map = mapRef.current;
    const toggle = configuration.basemapToggle;
    if (!map || !toggle) return;
    for (const layerId of toggle.satelliteLayerIds) {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", mode === "satellite" ? "visible" : "none");
      }
    }
    for (const layerId of toggle.mapLayerIds) {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", mode === "map" ? "visible" : "none");
      }
    }
    setBasemapMode(mode);
  }

  const providerName = configuration.basemapToggle
    ? basemapMode === "satellite"
      ? configuration.basemapToggle.satelliteName
      : configuration.basemapToggle.mapName
    : configuration.providerName;
  const providerNotice = configuration.basemapToggle
    ? basemapMode === "satellite"
      ? configuration.basemapToggle.satelliteNotice
      : configuration.basemapToggle.mapNotice
    : configuration.providerNotice;

  return (
    <div className={`map-stage ${activeTool === "polygon" || activeTool === "freehand" ? "is-drawing" : ""}`}>
      <div ref={containerRef} className="map" aria-label="Interactive farm boundary map" />
      {!ready && <div className="map-loading"><span /> Loading map…</div>}
      {assessment && (
        <div className="basemap-switcher" role="group" aria-label="Analysis layer">
          <button type="button" className={resultMode === "concern" ? "active" : ""} aria-pressed={resultMode === "concern"} onClick={() => setResultMode("concern")}>Movement review</button>
          <button type="button" className={resultMode === "movement" ? "active" : ""} aria-pressed={resultMode === "movement"} onClick={() => setResultMode("movement")}>LOS movement</button>
        </div>
      )}
      {configuration.basemapToggle && (
        <div className="basemap-switcher" role="group" aria-label="Map appearance">
          <button
            type="button"
            className={basemapMode === "map" ? "active" : ""}
            aria-pressed={basemapMode === "map"}
            onClick={() => changeBasemap("map")}
          >
            Map
          </button>
          <button
            type="button"
            className={basemapMode === "satellite" ? "active" : ""}
            aria-pressed={basemapMode === "satellite"}
            onClick={() => changeBasemap("satellite")}
          >
            Satellite
          </button>
        </div>
      )}
      <button
        type="button"
        className="map-location-button"
        onClick={onUseMyLocation}
        disabled={locating}
        aria-label="Go to my current location"
        title="My location"
      >
        <span aria-hidden="true">◎</span>
        <b>{locating ? "Locating…" : "My location"}</b>
      </button>
      <div className="basemap-chip">
        <span className={basemapMode === "satellite" ? "satellite-dot" : "demo-dot"} />
        <strong>{providerName}</strong>
        <small>{providerNotice}</small>
      </div>
    </div>
  );
});
