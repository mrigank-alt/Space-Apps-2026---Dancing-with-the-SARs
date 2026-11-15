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
  TerraDrawRectangleMode,
  TerraDrawSelectMode,
  TerraDrawSessionUndoRedo,
  TerraDrawUndoRedoKeyboardShortcuts,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";
import type { MapConfiguration } from "../lib/config";
import { boundaryFromSnapshot } from "../lib/geometry";
import type { BoundaryFeature, DrawingTool, SearchResult } from "../types";

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
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | undefined>(undefined);
  const drawRef = useRef<TerraDraw | undefined>(undefined);
  const locationMarkerRef = useRef<Marker | undefined>(undefined);
  const callbackRef = useRef({ onBoundaryChange, onToolChange, onUndoAvailability });
  const [ready, setReady] = useState(false);
  const [pointer, setPointer] = useState<[number, number] | null>(null);
  const [basemapMode, setBasemapMode] = useState<"satellite" | "map">("satellite");

  callbackRef.current = { onBoundaryChange, onToolChange, onUndoAvailability };

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
    map.on("mousemove", (event) => setPointer([event.lngLat.lng, event.lngLat.lat]));
    map.on("mouseout", () => setPointer(null));

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
          new TerraDrawRectangleMode({
            styles: {
              fillColor: "#d8ff70",
              fillOpacity: 0.28,
              outlineColor: "#ffffff",
              outlineWidth: 3,
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
              rectangle: {
                feature: {
                  draggable: true,
                  coordinates: {
                    draggable: true,
                    deletable: false,
                    resizable: "opposite",
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
      draw.on("change", () => syncBoundary(draw));
      draw.on("history", () => callbackRef.current.onUndoAvailability(draw.canUndo()));
      drawRef.current = draw;
      setReady(true);
    });

    return () => {
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
      activeTool === "polygon" || activeTool === "freehand" || activeTool === "rectangle"
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
    <div className={`map-stage ${activeTool === "polygon" || activeTool === "freehand" || activeTool === "rectangle" ? "is-drawing" : ""}`}>
      <div ref={containerRef} className="map" aria-label="Interactive farm boundary map" />
      {!ready && <div className="map-loading"><span /> Loading map…</div>}
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
      <div className="coordinate-readout" aria-hidden="true">
        {pointer ? `${pointer[1].toFixed(5)}, ${pointer[0].toFixed(5)}` : "EPSG:4326 · lon/lat"}
      </div>
    </div>
  );
});
