import { useMemo, useState } from "react";
import type { Assessment, ConcernLevel, ConcernZoneProperties } from "../types";

const levelLabel: Record<ConcernLevel, string> = {
  green: "Low measured movement",
  yellow: "Movement / uncertainty to review",
  red: "Strong movement: prompt review",
  grey: "More information needed",
};

type InsightView = "overview" | "actions" | "details";

interface Props {
  assessment: Assessment;
  history: Assessment[];
  selectedPlotId: string | null;
  selectedZone: ConcernZoneProperties | null;
  refreshing: boolean;
  onSelectPlot: (plotId: string | null) => void;
  onRefresh: () => void;
  onSelectAssessment: (assessment: Assessment) => void;
}

function actionSteps(assessment: Assessment) {
  return assessment.recommendations.map((item) => [item.title, item.detail]);
}

export function AssessmentPanel({ assessment, history, selectedPlotId, selectedZone, refreshing, onSelectPlot, onRefresh, onSelectAssessment }: Props) {
  const [view, setView] = useState<InsightView>("overview");
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(new Set());
  const created = new Date(assessment.created_at).toLocaleString();
  const steps = useMemo(() => actionSteps(assessment), [assessment]);
  const visibleFeatures = assessment.concern_zones.features.filter((feature) => !selectedPlotId || feature.properties.plot_id === selectedPlotId);
  const attentionCount = visibleFeatures.filter((feature) => feature.properties.concern_level === "yellow" || feature.properties.concern_level === "red").length;
  const selectedLevel = selectedZone?.concern_level;
  const isDemo = assessment.provenance.demo === true;

  function toggleStep(index: number) {
    setCompletedSteps((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  return (
    <section className="assessment-panel" aria-labelledby="assessment-title">
      {isDemo && (
        <div className="demo-disclaimer" role="note">
          <strong>San Joaquin Valley sample</strong>
          <span>These colors, measurements, groundwater records, and deadlines are simulated—not real farm advice.</span>
        </div>
      )}
      <div className={`farmer-status level-${assessment.overall_concern}`}>
        <span className="concern-dot" aria-hidden="true" />
        <div>
          <small>Your latest land check</small>
          <h3 id="assessment-title">{levelLabel[assessment.overall_concern]}</h3>
          <p>
            {attentionCount > 0
              ? `${attentionCount} mapped ${attentionCount === 1 ? "area may be" : "areas may be"} showing movement or uncertainty that needs verification.`
              : assessment.summary}
          </p>
        </div>
      </div>

      <div className="insight-tabs" role="tablist" aria-label="Land insights">
        <button type="button" role="tab" aria-selected={view === "overview"} className={view === "overview" ? "active" : ""} onClick={() => setView("overview")}>What we found</button>
        <button type="button" role="tab" aria-selected={view === "actions"} className={view === "actions" ? "active" : ""} onClick={() => setView("actions")}>What to do</button>
        <button type="button" role="tab" aria-selected={view === "details"} className={view === "details" ? "active" : ""} onClick={() => setView("details")}>Why we say this</button>
      </div>

      {view === "overview" && (
        <div className="insight-view" role="tabpanel">
          <div className="plot-switcher" role="group" aria-label="Choose a plot">
            <button type="button" className={!selectedPlotId ? "active" : ""} onClick={() => onSelectPlot(null)}>All plots</button>
            {assessment.plot_summaries.map((plot) => (
              <button key={plot.plot_id} type="button" className={selectedPlotId === plot.plot_id ? "active" : ""} onClick={() => onSelectPlot(plot.plot_id)}>
                Plot {plot.plot_index} · {levelLabel[plot.overall_concern]}
              </button>
            ))}
          </div>

          <div className="simple-legend" aria-label="Map colors">
            <span className="legend-green"><i />Low measured movement</span>
            <span className="legend-yellow"><i />Movement / uncertainty to review</span>
            <span className="legend-red"><i />Strong movement: prompt review</span>
            <span className="legend-grey"><i />More information needed</span>
          </div>
          <p className="plain-language-note">Use “LOS movement” on the map to view measured line-of-sight velocity. “Movement review” screens farm-wide movement, local differences, and unresolved uncertainty; neither layer alone identifies groundwater causation.</p>

          {selectedZone ? (
            <div className={`farmer-zone-card level-${selectedLevel}`}>
              <small>Selected area · Plot {selectedZone.plot_index}</small>
              <h4>{levelLabel[selectedZone.concern_level]}</h4>
              <div>
                <strong>What we found</strong>
                <p>{selectedZone.concern_level === "green" ? "This area does not stand out from the rest of your farm." : selectedZone.concern_level === "grey" ? "The satellite readings here are not clear enough to judge." : "This area moved more consistently than most of the farm during the dates checked."}</p>
              </div>
              <div>
                <strong>What to do</strong>
                <p>{selectedZone.concern_level === "green" ? "Keep monitoring during normal field checks." : selectedZone.concern_level === "grey" ? "Check again after new imagery and keep field records in the meantime." : "Walk this area before the next irrigation cycle and note cracks, sinking, ponding, or pipe damage."}</p>
              </div>
              <button type="button" className="zone-action-link" onClick={() => setView("actions")}>Show my action steps →</button>
            </div>
          ) : (
            <div className="map-prompt-card">
              <strong>Tap a colored area on the map</strong>
              <span>We’ll explain what may be happening there and what you can check.</span>
            </div>
          )}
        </div>
      )}

      {view === "actions" && (
        <div className="insight-view" role="tabpanel">
          <div className="action-plan-heading">
            <small>Simple field plan</small>
            <h4>Start with these steps</h4>
            <p>Mark each step as you complete it. These checks help turn the satellite signal into a useful farm decision.</p>
          </div>
          <div className="farmer-checklist">
            {steps.map(([title, detail], index) => (
              <button type="button" key={title} className={completedSteps.has(index) ? "complete" : ""} aria-pressed={completedSteps.has(index)} onClick={() => toggleStep(index)}>
                <span>{completedSteps.has(index) ? "✓" : index + 1}</span>
                <div><strong>{title}</strong><small>{detail}</small></div>
              </button>
            ))}
          </div>

          <div className={`deadline-card ${assessment.forecast.status}`}>
            <small>Pumping and land deadline</small>
            <h4>{assessment.forecast.status === "available" ? assessment.forecast.title : "No safe deadline yet"}</h4>
            <p>{assessment.forecast.summary}</p>
            {assessment.forecast.status === "available" && assessment.forecast.action_deadline_days != null ? (
              <div className="deadline-number"><strong>{assessment.forecast.action_deadline_days}</strong><span>days for qualified action review</span></div>
            ) : (
              <div className="deadline-missing">
                <strong>What would make this possible?</strong>
                <span>Local well levels</span><span>Pumping records</span><span>A locally validated damage threshold</span>
              </div>
            )}
          </div>
        </div>
      )}

      {view === "details" && (
        <div className="insight-view" role="tabpanel">
          <div className="plain-language-note">
            <strong>How to read this result</strong>
            <p>We screen LOS movement and uncertainty. Yellow includes measurements needing verification; green requires small movement and calibrated uncertainty. The summary uses the dominant class by land area.</p>
          </div>
          <div className="confidence-card">
            <div><strong>How certain are we?</strong><span className={`quality-${assessment.evidence_quality}`}>{assessment.evidence_quality}</span></div>
            <p>{assessment.evidence_quality === "limited" ? "Useful as an early field-check signal, but not enough for a pumping or damage deadline." : "The signal is useful for prioritizing field checks, with the limitations below."}</p>
          </div>
          <div className="evidence-card">
            <strong>Groundwater information</strong>
            <p>{assessment.groundwater.summary}</p>
            {assessment.groundwater.trend_summary && <p>{assessment.groundwater.trend_summary}</p>}
            {!assessment.groundwater.relationship_eligible && <small>We are not claiming groundwater caused the movement.</small>}
          </div>
          {assessment.climate && (
            <details className="limitations">
              <summary>Monthly weather context: {assessment.climate.status.replaceAll("_", " ")}</summary>
              <p>{assessment.climate.summary}</p>
              <p>Plot reference: {assessment.climate.location.coordinates[1].toFixed(4)} latitude, {assessment.climate.location.coordinates[0].toFixed(4)} longitude. No validated local seasonal subsidence baseline is available.</p>
              {assessment.climate.monthly.length > 0 && <table>
                <thead><tr><th>Month</th><th>Mean Celsius</th><th>Rain mm</th></tr></thead>
                <tbody>{assessment.climate.monthly.map((month) => <tr key={month.month}>
                  <td>{month.month}{month.partial_calendar_month ? " (partial)" : ""}</td>
                  <td>{month.mean_temperature_c?.toFixed(1) ?? "Unavailable"}</td>
                  <td>{month.precipitation_mm?.toFixed(1) ?? "Incomplete"}</td>
                </tr>)}</tbody>
              </table>}
              <a href={assessment.climate.source_url} target="_blank" rel="noreferrer">Open-Meteo weather source and attribution</a>
            </details>
          )}
          <details className="limitations">
            <summary>See the measurement details</summary>
            {selectedZone && <p>Selected area movement: {selectedZone.observed_los_change_cm == null ? "not available" : `${selectedZone.observed_los_change_cm.toFixed(2)} cm along the satellite view`}.</p>}
            <ul>{assessment.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
          </details>
          {history.length > 1 && (
            <details className="assessment-history">
              <summary>Previous checks ({history.length})</summary>
              <div>{history.map((item) => (
                <button type="button" key={item.assessment_id} className={item.assessment_id === assessment.assessment_id ? "active" : ""} onClick={() => onSelectAssessment(item)}>
                  {new Date(item.created_at).toLocaleDateString()} · {levelLabel[item.overall_concern]}
                </button>
              ))}</div>
            </details>
          )}
        </div>
      )}

      <div className="assessment-footer">
        <span>Checked {assessment.observation_start} to {assessment.observation_end}<br />Updated {created}</span>
        {!isDemo && <button type="button" className="refresh-assessment" onClick={onRefresh} disabled={refreshing}>{refreshing ? "Checking…" : "Check for new imagery"}</button>}
      </div>
    </section>
  );
}
