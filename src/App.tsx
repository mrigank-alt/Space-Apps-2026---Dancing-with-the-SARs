import { useMemo, useRef, useState } from "react";
import { FarmMap, type FarmMapHandle } from "./components/FarmMap";
import { LocationSearch } from "./components/LocationSearch";
import { createSelection, selectionRecordUrl } from "./lib/api";
import { getMapConfiguration } from "./lib/config";
import { boundaryArea, formatArea } from "./lib/geometry";
import type {
  BoundaryFeature,
  DrawingTool,
  SearchResult,
  SelectionResponse,
} from "./types";

export default function App() {
  const mapRef = useRef<FarmMapHandle>(null);
  const configuration = useMemo(() => getMapConfiguration(), []);
  const [location, setLocation] = useState<SearchResult | null>(null);
  const [boundary, setBoundary] = useState<BoundaryFeature | null>(null);
  const [activeTool, setActiveTool] = useState<DrawingTool>("idle");
  const [undoAvailable, setUndoAvailable] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string>();
  const [confirmed, setConfirmed] = useState<SelectionResponse | null>(null);
  const [selectionName, setSelectionName] = useState("");

  const area = boundary ? boundaryArea(boundary) : null;

  function beginDraw(tool: "polygon" | "freehand" | "rectangle") {
    if (boundary) mapRef.current?.clear();
    setBoundary(null);
    setConfirmed(null);
    setSelectionName("");
    setSubmitError(undefined);
    setActiveTool(tool);
  }

  function handleBoundaryChange(feature: BoundaryFeature | null) {
    setBoundary(feature);
    setSubmitError(undefined);
    setConfirmed(null);
    if (!feature && activeTool === "edit") setActiveTool("idle");
  }

  function useMyLocation() {
    setLocationError(undefined);
    if (!navigator.geolocation) {
      setLocationError("This browser does not support location access. Enter coordinates instead.");
      return;
    }

    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const center: [number, number] = [position.coords.longitude, position.coords.latitude];
        setLocation({
          id: "current-location",
          label: "Your current location",
          context: `Browser location · ±${Math.round(position.coords.accuracy)} m`,
          center,
          targetZoom: 18,
          kind: "geolocation",
        });
        setLocating(false);
      },
      (error: GeolocationPositionError) => {
        const denied = error.code === 1;
        setLocationError(
          denied
            ? "Location permission was not granted. Search a nearby town or enter coordinates instead."
            : "Your location could not be determined. Try again or enter coordinates.",
        );
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 12_000, maximumAge: 60_000 },
    );
  }

  async function confirmSelection() {
    const label = selectionName.trim();
    if (!boundary || !label) return;
    setSubmitting(true);
    setSubmitError(undefined);
    try {
      const response = await createSelection(boundary, label);
      setConfirmed(response);
      setActiveTool("idle");
    } catch (error) {
      setSubmitError(
        error instanceof Error
          ? error.message
          : "The boundary could not be validated. Check the backend and try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  function clearSelection() {
    mapRef.current?.clear();
    setBoundary(null);
    setConfirmed(null);
    setSelectionName("");
    setSubmitError(undefined);
    setActiveTool("idle");
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true"><span /></div>
          <div>
            <strong>Groundsignal</strong>
            <small>Farm boundary setup</small>
          </div>
        </div>
        <div className="iteration-label">
          <span />
          ITERATION 01 · BOUNDARY ONLY
        </div>
      </header>

      <div className="workspace">
        <aside className="side-panel" aria-label="Farm boundary workflow">
          <div className="panel-intro">
            <span className="eyebrow">START YOUR FARM PROFILE</span>
            <h1>Mark the land you want to monitor.</h1>
            <p>
              Find the general area, then draw the actual farm boundary. Environmental analysis comes in a later iteration.
            </p>
          </div>

          <section className="workflow-step is-complete">
            <div className="step-index">01</div>
            <div className="step-content">
              <div className="step-title">
                <h2>Find the area</h2>
                {location && <span className="step-check" aria-label="Complete">✓</span>}
              </div>
              <p>Search a place or coordinates, or use your location.</p>
              {location ? (
                <div className="location-summary">
                  <span aria-hidden="true">●</span>
                  <div><strong>{location.label}</strong><small>{location.context}</small></div>
                </div>
              ) : (
                <span className="pending-copy">Use the search bar on the map</span>
              )}
              <div className="separation-note">
                <b>Location is not the boundary.</b>
                <span>Search only moves the map. You choose the land in step 2.</span>
              </div>
            </div>
          </section>

          <section className={`workflow-step ${boundary ? "is-complete" : "is-active"}`}>
            <div className="step-index">02</div>
            <div className="step-content">
              <div className="step-title">
                <h2>Draw the farm</h2>
                {boundary && <span className="step-check" aria-label="Complete">✓</span>}
              </div>
              <p>Choose the tool that best matches the field edges.</p>
              <div className="drawing-tools" role="group" aria-label="Boundary drawing tools">
                <button
                  type="button"
                  className={activeTool === "polygon" ? "tool-button active" : "tool-button"}
                  aria-pressed={activeTool === "polygon"}
                  onClick={() => beginDraw("polygon")}
                >
                  <span className="polygon-icon" aria-hidden="true">⌁</span>
                  <span><strong>Polygon</strong><small>Click each corner</small></span>
                </button>
                <button
                  type="button"
                  className={activeTool === "freehand" ? "tool-button active" : "tool-button"}
                  aria-pressed={activeTool === "freehand"}
                  onClick={() => beginDraw("freehand")}
                >
                  <span className="trace-icon" aria-hidden="true">〰</span>
                  <span><strong>Trace</strong><small>Drag curved edges</small></span>
                </button>
                <button
                  type="button"
                  className={activeTool === "rectangle" ? "tool-button active" : "tool-button"}
                  aria-pressed={activeTool === "rectangle"}
                  onClick={() => beginDraw("rectangle")}
                >
                  <span className="rectangle-icon" aria-hidden="true" />
                  <span><strong>Rectangle</strong><small>Two opposite corners</small></span>
                </button>
              </div>
              {(activeTool === "polygon" || activeTool === "freehand" || activeTool === "rectangle") && (
                <div className="drawing-hint" role="status">
                  <span className="pulse" />
                  {activeTool === "polygon"
                    ? "Click around the field. Click the first point to finish."
                    : activeTool === "freehand"
                      ? "Press and drag around the field edge. Release to close the trace."
                    : "Click one corner, then the opposite corner."}
                </div>
              )}
              <div className="edit-actions">
                <button
                  type="button"
                  onClick={() => {
                    mapRef.current?.undo();
                    setConfirmed(null);
                  }}
                  disabled={!undoAvailable}
                >
                  <span aria-hidden="true">↶</span> Undo
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (boundary) setActiveTool("edit");
                  }}
                  disabled={!boundary}
                  className={activeTool === "edit" ? "active" : ""}
                >
                  <span aria-hidden="true">◇</span> Edit
                </button>
                <button type="button" onClick={clearSelection} disabled={!boundary}>
                  <span aria-hidden="true">×</span> Clear
                </button>
              </div>
            </div>
          </section>

          <section className={`workflow-step review-step ${boundary ? "is-active" : ""}`}>
            <div className="step-index">03</div>
            <div className="step-content">
              <div className="step-title"><h2>Review & confirm</h2></div>
              <label className="selection-name-field">
                <span>Farm or field name</span>
                <input
                  type="text"
                  value={selectionName}
                  maxLength={200}
                  placeholder="e.g. North pivot field"
                  disabled={!boundary || Boolean(confirmed)}
                  onChange={(event) => setSelectionName(event.target.value)}
                />
                <small>This name is saved with the GeoJSON boundary.</small>
              </label>
              {area ? (
                <>
                  <div className="area-card">
                    <div>
                      <span>SELECTED AREA</span>
                      <strong>{formatArea(area.acres)} <small>acres</small></strong>
                    </div>
                    <div>
                      <span>METRIC</span>
                      <strong>{formatArea(area.hectares)} <small>hectares</small></strong>
                    </div>
                  </div>
                  <p className="area-note">Calculated geodesically from the drawn EPSG:4326 boundary.</p>
                </>
              ) : (
                <div className="empty-review"><span aria-hidden="true">⌗</span> Area appears after drawing</div>
              )}
            </div>
          </section>

          <div className="confirm-zone">
            <button
              type="button"
              className="confirm-button"
              onClick={confirmSelection}
              disabled={
                !boundary || !selectionName.trim() || submitting || Boolean(confirmed)
              }
            >
              {submitting
                ? "Validating boundary…"
                : confirmed
                  ? "Selection confirmed"
                  : "Confirm selection"}
              <span aria-hidden="true">→</span>
            </button>
            <small>No satellite or groundwater analysis runs at this step.</small>
            {submitError && <div className="submit-error" role="alert">{submitError}</div>}
            {confirmed && (
              <div className="confirmation-card" role="status">
                <div className="confirmation-heading"><span>✓</span><strong>Boundary confirmed</strong></div>
                <h3>{confirmed.label}</h3>
                <p>Saved persistently and ready for future spatial queries.</p>
                <small className="confirmation-id-label">Selection ID · used to retrieve this boundary later</small>
                <code>{confirmed.selection_id}</code>
                <div className="confirmation-metrics">
                  <span>{formatArea(confirmed.area.acres)} acres</span>
                  <span>EPSG:4326</span>
                </div>
                <dl className="saved-data-summary">
                  <div><dt>Geometry</dt><dd>{confirmed.geometry.type}</dd></div>
                  <div><dt>Bounds</dt><dd>{confirmed.bbox.map((value) => value.toFixed(5)).join(", ")}</dd></div>
                </dl>
                <a
                  className="view-record-link"
                  href={selectionRecordUrl(confirmed.selection_id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  View saved GeoJSON data <span aria-hidden="true">↗</span>
                </a>
              </div>
            )}
          </div>
        </aside>

        <section className="map-workspace">
          <div className="search-overlay">
            <LocationSearch
              mapTilerKey={configuration.mapTilerKey}
              autocompleteGeocoderUrl={configuration.autocompleteGeocoderUrl}
              fallbackGeocoderUrl={configuration.fallbackGeocoderUrl}
              onSelect={(result) => {
                setLocation(result);
                setLocationError(undefined);
              }}
              onUseMyLocation={useMyLocation}
              locating={locating}
              locationError={locationError}
            />
          </div>
          <FarmMap
            ref={mapRef}
            configuration={configuration}
            activeTool={activeTool}
            location={location}
            onBoundaryChange={handleBoundaryChange}
            onToolChange={setActiveTool}
            onUndoAvailability={setUndoAvailable}
            onUseMyLocation={useMyLocation}
            locating={locating}
          />
          <div className="map-instruction">
            <span aria-hidden="true">i</span>
            <strong>{boundary ? "Boundary selected" : "Search, then draw"}</strong>
            <small>
              {boundary
                ? "Drag the white handles to refine field edges."
                : "The location pin is a reference point, not your farm boundary."}
            </small>
          </div>
        </section>
      </div>
    </main>
  );
}
