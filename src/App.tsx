import { useEffect, useMemo, useRef, useState } from "react";
import { FarmMap, type FarmMapHandle } from "./components/FarmMap";
import { AssessmentPanel } from "./components/AssessmentPanel";
import { FarmProfileForm, type FarmFormValues } from "./components/FarmProfileForm";
import { LocationSearch } from "./components/LocationSearch";
import { createSelection, getAssessment, getGunwAvailability, getProcessingRun, getSelection, listAssessments, listProcessingRuns, startProcessing } from "./lib/api";
import { getMapConfiguration } from "./lib/config";
import { boundaryArea, boundaryPlotAreas, formatArea } from "./lib/geometry";
import { PRESENTATION_DEMO_ASSESSMENT, PRESENTATION_DEMO_LOCATION, PRESENTATION_DEMO_SELECTION } from "./lib/presentationDemo";
import type {
  Assessment,
  BoundaryFeature,
  DrawingTool,
  ProcessingRun,
  SearchResult,
  SelectionResponse,
  ConcernZoneProperties,
} from "./types";

const LAST_SELECTION_KEY = "groundsignal:last-selection-id";

export default function App() {
  const mapRef = useRef<FarmMapHandle>(null);
  const confirmationRef = useRef<HTMLDivElement>(null);
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
  const [processingRun, setProcessingRun] = useState<ProcessingRun | null>(null);
  const [processingError, setProcessingError] = useState<string>();
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [assessmentHistory, setAssessmentHistory] = useState<Assessment[]>([]);
  const [selectedPlotId, setSelectedPlotId] = useState<string | null>(null);
  const [selectedZone, setSelectedZone] = useState<ConcernZoneProperties | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  const [farmForm, setFarmForm] = useState<FarmFormValues>({
    farmName: "",
    operatorName: "",
    email: "",
    phone: "",
    cropOrLandUse: "",
    waterSource: "",
    consent: false,
  });

  const area = boundary ? boundaryArea(boundary) : null;
  const plotAreas = boundary ? boundaryPlotAreas(boundary) : [];
  const plotCount = plotAreas.length;
  const profileComplete = Boolean(
    farmForm.farmName.trim()
      && farmForm.operatorName.trim().length >= 2
      && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(farmForm.email.trim())
      && farmForm.cropOrLandUse.trim().length >= 2
      && farmForm.waterSource
      && farmForm.consent,
  );
  const confirmedSelectionId = confirmed?.selection_id;
  const availabilityStatus = confirmed?.gunw_availability?.status;

  useEffect(() => {
    if (!confirmed) return;
    confirmationRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [confirmed]);

  useEffect(() => {
    const parameters = new URLSearchParams(window.location.search);
    if (parameters.get("demo") === "1") {
      loadPresentationDemo();
      return;
    }
    const selectionId = parameters.get("selection")
      || window.localStorage.getItem(LAST_SELECTION_KEY);
    if (!selectionId) return;
    void (async () => {
      try {
        const saved = await getSelection(selectionId);
        setConfirmed(saved);
        const [history, runs] = await Promise.all([
          listAssessments(selectionId),
          listProcessingRuns(selectionId),
        ]);
        setAssessmentHistory(history);
        setAssessment(history[0] ?? null);
        setProcessingRun(runs[0] ?? null);
      } catch {
        window.localStorage.removeItem(LAST_SELECTION_KEY);
      }
    })();
  }, []);

  useEffect(() => {
    if (!processingRun || !["queued", "running"].includes(processingRun.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        setProcessingRun(await getProcessingRun(processingRun.run_id));
      } catch (error) {
        setProcessingError(error instanceof Error ? error.message : "We could not check the analysis status.");
      }
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [processingRun]);

  useEffect(() => {
    if (!confirmedSelectionId || availabilityStatus !== "checking") return;
    let cancelled = false;
    let timer: number | undefined;
    let attempts = 0;

    const pollAvailability = async () => {
      attempts += 1;
      try {
        const availability = await getGunwAvailability(confirmedSelectionId);
        if (cancelled) return;
        setConfirmed((current) => current?.selection_id === confirmedSelectionId
          ? { ...current, gunw_availability: availability }
          : current);
        if (availability.status !== "checking") return;
      } catch {
        if (cancelled) return;
      }
      if (attempts < 150) timer = window.setTimeout(pollAvailability, 2000);
    };

    timer = window.setTimeout(pollAvailability, 1200);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [availabilityStatus, confirmedSelectionId]);

  useEffect(() => {
    if (processingRun?.status !== "completed" || !processingRun.assessment_id) return;
    void getAssessment(processingRun.assessment_id)
      .then((result) => {
        setAssessment(result);
        if (confirmed) {
          void listAssessments(confirmed.selection_id).then(setAssessmentHistory);
        }
        setSelectedPlotId(null);
        setSelectedZone(null);
      })
      .catch((error: unknown) => setProcessingError(error instanceof Error ? error.message : "The concern map could not be loaded."));
  }, [confirmed, processingRun]);

  function beginDraw(tool: "polygon" | "freehand") {
    setConfirmed(null);
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
    if (!boundary || !profileComplete || !farmForm.waterSource) return;
    setSubmitting(true);
    setSubmitError(undefined);
    try {
      const response = await createSelection(boundary, {
        label: farmForm.farmName.trim(),
        farmer: {
          operator_name: farmForm.operatorName.trim(),
          contact_email: farmForm.email.trim(),
          ...(farmForm.phone.trim() ? { contact_phone: farmForm.phone.trim() } : {}),
        },
        farm_profile: {
          primary_crop_or_land_use: farmForm.cropOrLandUse.trim(),
          water_source: farmForm.waterSource,
          monitoring_goal: "groundwater_risk",
          ...(location?.label ? { location_label: location.label } : {}),
          ...(location?.context ? { location_context: location.context } : {}),
        },
        data_processing_consent: true,
      });
      setConfirmed(response);
      window.localStorage.setItem(LAST_SELECTION_KEY, response.selection_id);
      window.history.replaceState({}, "", `?selection=${encodeURIComponent(response.selection_id)}`);
      setAssessment(null);
      setAssessmentHistory([]);
      setProcessingRun(null);
      setProcessingError(undefined);
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

  async function prepareSatelliteResults() {
    if (!confirmed) return;
    setProcessingError(undefined);
    try {
      setProcessingRun(await startProcessing(confirmed.selection_id));
    } catch (error) {
      setProcessingError(error instanceof Error ? error.message : "The satellite analysis could not be started.");
    }
  }

  function clearSelection() {
    mapRef.current?.clear();
    setBoundary(null);
    setConfirmed(null);
    setProcessingRun(null);
    setAssessment(null);
    setAssessmentHistory([]);
    setSelectedPlotId(null);
    setSelectedZone(null);
    setDemoMode(false);
    window.localStorage.removeItem(LAST_SELECTION_KEY);
    window.history.replaceState({}, "", window.location.pathname);
    setProcessingError(undefined);
    setFarmForm({
      farmName: "",
      operatorName: "",
      email: "",
      phone: "",
      cropOrLandUse: "",
      waterSource: "",
      consent: false,
    });
    setSubmitError(undefined);
    setActiveTool("idle");
  }

  function loadPresentationDemo() {
    setDemoMode(true);
    setConfirmed(PRESENTATION_DEMO_SELECTION);
    setAssessment(PRESENTATION_DEMO_ASSESSMENT);
    setAssessmentHistory([PRESENTATION_DEMO_ASSESSMENT]);
    setProcessingRun(null);
    setProcessingError(undefined);
    setSelectedPlotId(null);
    setSelectedZone(null);
    setLocation(PRESENTATION_DEMO_LOCATION);
    window.history.replaceState({}, "", "?demo=1");
  }

  function exitPresentationDemo() {
    const savedSelection = window.localStorage.getItem(LAST_SELECTION_KEY);
    window.location.href = savedSelection
      ? `?selection=${encodeURIComponent(savedSelection)}`
      : window.location.pathname;
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true"><span /></div>
          <div>
            <strong>Groundsignal</strong>
            <small>{confirmed ? "Farm monitoring" : "Farm setup"}</small>
          </div>
        </div>
        <div className="header-actions">
          <button type="button" className="demo-button" onClick={demoMode ? exitPresentationDemo : loadPresentationDemo}>
            {demoMode ? "Close sample" : "View San Joaquin Valley sample"}
          </button>
          <div className="product-status">
            <span />
            {demoMode ? "SAN JOAQUIN SAMPLE" : confirmed ? "FARM MONITORING" : "FARM SETUP"}
          </div>
        </div>
      </header>

      <div className="workspace">
        <aside className={`side-panel ${confirmed ? "has-saved-farm" : ""}`} aria-label="Farm boundary workflow">
          <div className="panel-intro">
            <span className="eyebrow">START YOUR FARM PROFILE</span>
            <h1>Tell us about your farm.</h1>
            <p>
              Add your farm details, find your land, and mark each plot you want included.
            </p>
          </div>

          <section className={`workflow-step ${profileComplete ? "is-complete" : "is-active"}`}>
            <div className="step-index">01</div>
            <div className="step-content">
              <div className="step-title">
                <h2>About your farm</h2>
                {profileComplete && <span className="step-check" aria-label="Complete">✓</span>}
              </div>
              <p>These details help us keep your farm and plots organized.</p>
              <FarmProfileForm
                values={farmForm}
                disabled={Boolean(confirmed)}
                onChange={(values) => {
                  setFarmForm(values);
                  setConfirmed(null);
                  setSubmitError(undefined);
                }}
              />
            </div>
          </section>

          <section className={`workflow-step ${location ? "is-complete" : ""}`}>
            <div className="step-index">02</div>
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
                <span>Search only moves the map. You mark the actual plots in the next step.</span>
              </div>
            </div>
          </section>

          <section className={`workflow-step ${boundary ? "is-complete" : "is-active"}`}>
            <div className="step-index">03</div>
            <div className="step-content">
              <div className="step-title">
                <h2>Draw your plots</h2>
                {boundary && <span className="step-check" aria-label="Complete">✓</span>}
              </div>
              <p>Add every separate plot you want included. You can mix drawing tools.</p>
              <div className="drawing-tools" role="group" aria-label="Boundary drawing tools">
                <button
                  type="button"
                  className={activeTool === "polygon" ? "tool-button active" : "tool-button"}
                  aria-pressed={activeTool === "polygon"}
                  onClick={() => beginDraw("polygon")}
                >
                  <span className="polygon-icon" aria-hidden="true">⌁</span>
                  <span><strong>{boundary ? "Add polygon" : "Polygon"}</strong><small>Click each corner</small></span>
                </button>
                <button
                  type="button"
                  className={activeTool === "freehand" ? "tool-button active" : "tool-button"}
                  aria-pressed={activeTool === "freehand"}
                  onClick={() => beginDraw("freehand")}
                >
                  <span className="trace-icon" aria-hidden="true">〰</span>
                  <span><strong>{boundary ? "Add trace" : "Trace"}</strong><small>Drag curved edges</small></span>
                </button>
              </div>
              {(activeTool === "polygon" || activeTool === "freehand") && (
                <div className="drawing-hint" role="status">
                  <span className="pulse" />
                  {activeTool === "polygon"
                    ? "Click around the field. Click the first point to finish."
                    : "Press and drag around the field edge. Release to close the trace."}
                </div>
              )}
              {boundary && (
                <div className="plot-count-banner" role="status">
                  <strong>{plotCount} {plotCount === 1 ? "plot" : "plots"} selected</strong>
                  <span>Choose a drawing tool again to add another plot.</span>
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
            <div className="step-index">04</div>
            <div className="step-content">
              <div className="step-title"><h2>Review your plots</h2></div>
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
                  <div className="plot-area-list" aria-label="Selected plot areas">
                    {plotAreas.map((plotArea, index) => (
                      <div key={index}>
                        <span>Plot {index + 1}</span>
                        <strong>{formatArea(plotArea.acres)} acres</strong>
                      </div>
                    ))}
                  </div>
                  <p className="area-note">Area is estimated from the boundary you drew.</p>
                </>
              ) : (
                <div className="empty-review"><span aria-hidden="true">⌗</span> Area appears after drawing</div>
              )}
            </div>
          </section>

          <div className="confirm-zone">
            {!confirmed && (
              <>
                <button
                  type="button"
                  className="confirm-button"
                  onClick={confirmSelection}
                  disabled={!boundary || !profileComplete || submitting}
                >
                  {submitting ? "Saving your farm…" : `Save ${plotCount} ${plotCount === 1 ? "plot" : "plots"}`}
                  <span aria-hidden="true">→</span>
                </button>
                <small>Your farm saves immediately. We’ll check satellite imagery in the background.</small>
              </>
            )}
            {boundary && !profileComplete && !confirmed && (
              <div className="form-reminder" role="status">
                Complete the required farm details and consent in step 1 before saving.
              </div>
            )}
            {submitError && <div className="submit-error" role="alert">{submitError}</div>}
            {confirmed && (
              <div ref={confirmationRef} className="confirmation-card" role="status" tabIndex={-1}>
                <div className="confirmation-heading"><span>✓</span><strong>Your farm is saved</strong></div>
                <h3>{confirmed.label}</h3>
                <p>Your farm details and boundaries were saved successfully.</p>
                <div className="confirmation-metrics">
                  <span>{formatArea(confirmed.area.acres)} acres</span>
                  <span>{confirmed.plot_count} {confirmed.plot_count === 1 ? "plot" : "plots"}</span>
                </div>
                <dl className="saved-data-summary">
                  <div><dt>Farm contact</dt><dd>{confirmed.farmer?.operator_name ?? "Not provided"}</dd></div>
                  <div><dt>Land use</dt><dd>{confirmed.farm_profile?.primary_crop_or_land_use ?? "Not provided"}</dd></div>
                </dl>
                {confirmed.gunw_availability && (
                  <div className={`satellite-result ${confirmed.gunw_availability.status}`}>
                    <div className="satellite-result-heading">
                      <span aria-hidden="true">
                        {["available", "partial", "source_available"].includes(confirmed.gunw_availability.status) ? "✓" : "i"}
                      </span>
                      <strong>
                        {["available", "partial", "source_available"].includes(confirmed.gunw_availability.status)
                          ? "Satellite imagery found"
                          : confirmed.gunw_availability.status === "not_available"
                            ? "Imagery is not available yet"
                            : confirmed.gunw_availability.status === "checking"
                              ? "Checking satellite imagery…"
                              : "Availability check pending"}
                      </strong>
                    </div>
                    <p>
                      {["available", "partial", "source_available"].includes(confirmed.gunw_availability.status)
                        ? confirmed.gunw_availability.message
                        : confirmed.gunw_availability.status === "not_available"
                          ? confirmed.gunw_availability.message
                          : confirmed.gunw_availability.status === "checking"
                            ? "You can continue using the app while we check coverage for your plots."
                            : "Your farm is saved. We’ll need to check imagery availability again later."}
                    </p>
                    <div className="plot-coverage-list">
                      {confirmed.gunw_availability.plot_results.map((result, index) => (
                        <div key={result.plot_id}>
                          <span>Plot {index + 1}</span>
                          <strong>
                            {result.status === "available" || result.status === "source_available"
                              ? "Imagery found"
                              : result.status === "not_available" ? "Not available yet" : "Check pending"}
                          </strong>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {confirmed.gunw_availability && confirmed.gunw_availability.archived_gunw_product_count > 0 && (
                  <div className="processing-panel">
                    {!processingRun && !assessment ? (
                      <button type="button" className="prepare-results-button" onClick={prepareSatelliteResults}>
                        Analyze my land
                      </button>
                    ) : processingRun ? (
                      <div className={`processing-status ${processingRun.status}`} role="status">
                        <strong>
                          {processingRun.status === "completed"
                            ? "Satellite results are ready"
                            : processingRun.status === "credentials_required"
                              ? "Imagery confirmed"
                              : processingRun.status === "no_data"
                                ? "No imagery available yet"
                                : processingRun.status === "failed"
                                  ? "Analysis needs attention"
                                  : "Preparing satellite results"}
                        </strong>
                        <p>{processingRun.message}</p>
                        {["queued", "running"].includes(processingRun.status) && (
                          <div className="progress-track" aria-label={`${processingRun.progress_percent}% complete`}>
                            <span style={{ width: `${processingRun.progress_percent}%` }} />
                            <small>{processingRun.stage} · {processingRun.progress_percent}%</small>
                          </div>
                        )}
                        {processingRun.status === "completed" && processingRun.result_summary?.pair_count != null && (
                          <small>{processingRun.result_summary.pair_count} image pairs were processed for this farm.</small>
                        )}
                        {["credentials_required", "failed", "no_data"].includes(processingRun.status) && (
                          <button type="button" className="prepare-results-button retry" onClick={prepareSatelliteResults}>
                            Try analysis again
                          </button>
                        )}
                      </div>
                    ) : null}
                    {processingError && <div className="submit-error" role="alert">{processingError}</div>}
                  </div>
                )}
                {assessment && (
                  <AssessmentPanel
                    assessment={assessment}
                    history={assessmentHistory}
                    selectedPlotId={selectedPlotId}
                    selectedZone={selectedZone}
                    refreshing={Boolean(processingRun && ["queued", "running"].includes(processingRun.status))}
                    onSelectPlot={(plotId) => {
                      setSelectedPlotId(plotId);
                      setSelectedZone(null);
                    }}
                    onRefresh={prepareSatelliteResults}
                    onSelectAssessment={(item) => {
                      setAssessment(item);
                      setSelectedPlotId(null);
                      setSelectedZone(null);
                    }}
                  />
                )}
                <button type="button" className="new-farm-button" onClick={clearSelection}>
                  Set up another farm
                </button>
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
            assessment={assessment}
            selectedPlotId={selectedPlotId}
            onZoneSelect={(zone) => setSelectedZone(zone)}
            savedBoundary={confirmed?.geometry ?? null}
          />
          <div className="map-instruction">
            <span aria-hidden="true">i</span>
            <strong>{assessment ? "Latest movement result" : boundary ? `${plotCount} ${plotCount === 1 ? "plot" : "plots"} selected` : "Search, then draw"}</strong>
            <small>
              {assessment
                ? "Click a colored area for a plain-language explanation."
                : boundary
                ? "Add another plot with a drawing tool, or edit the selected plot using its white handles."
                : "The location pin is a reference point, not your farm boundary."}
            </small>
          </div>
        </section>
      </div>
    </main>
  );
}
