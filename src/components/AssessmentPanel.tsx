import type { Assessment, ConcernLevel, ConcernZoneProperties } from "../types";

const levelLabel: Record<ConcernLevel, string> = {
  green: "Lower concern",
  yellow: "Review",
  red: "Prompt review",
  grey: "Insufficient data",
};

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

export function AssessmentPanel({ assessment, history, selectedPlotId, selectedZone, refreshing, onSelectPlot, onRefresh, onSelectAssessment }: Props) {
  const created = new Date(assessment.created_at).toLocaleString();
  return (
    <section className="assessment-panel" aria-labelledby="assessment-title">
      <div className={`assessment-summary level-${assessment.overall_concern}`}>
        <span className="concern-dot" aria-hidden="true" />
        <div>
          <small>Latest land movement check</small>
          <h3 id="assessment-title">{levelLabel[assessment.overall_concern]}</h3>
          <p>{assessment.summary}</p>
        </div>
      </div>

      <div className="assessment-meta">
        <span>{assessment.observation_start} to {assessment.observation_end}</span>
        <span>Updated {created}</span>
      </div>
      {history.length > 1 && (
        <details className="assessment-history">
          <summary>Previous checks ({history.length})</summary>
          <div>
            {history.map((item) => (
              <button
                type="button"
                key={item.assessment_id}
                className={item.assessment_id === assessment.assessment_id ? "active" : ""}
                onClick={() => onSelectAssessment(item)}
              >
                {new Date(item.created_at).toLocaleDateString()} · {levelLabel[item.overall_concern]}
              </button>
            ))}
          </div>
        </details>
      )}
      <div className="plain-language-note">
        <strong>What this map means</strong>
        <p>This compares reliable movement measurements across your own farm. It is an early review tool, not a pumping diagnosis or a forecast.</p>
      </div>

      <div className="map-legend" aria-label="Concern map legend">
        {(Object.keys(levelLabel) as ConcernLevel[]).map((level) => (
          <span key={level} className={`legend-${level}`}><i />{levelLabel[level]}</span>
        ))}
      </div>

      <div className="plot-switcher" role="group" aria-label="Choose a plot">
        <button type="button" className={!selectedPlotId ? "active" : ""} onClick={() => onSelectPlot(null)}>All plots</button>
        {assessment.plot_summaries.map((plot) => (
          <button key={plot.plot_id} type="button" className={selectedPlotId === plot.plot_id ? "active" : ""} onClick={() => onSelectPlot(plot.plot_id)}>
            Plot {plot.plot_index} · {levelLabel[plot.overall_concern]}
          </button>
        ))}
      </div>

      {selectedZone ? (
        <div className={`zone-detail level-${selectedZone.concern_level}`}>
          <small>Selected map area · Plot {selectedZone.plot_index}</small>
          <strong>{selectedZone.label}</strong>
          <p>{selectedZone.explanation}</p>
          <dl>
            <div><dt>Observed change</dt><dd>{selectedZone.observed_los_change_cm == null ? "Not available" : `${selectedZone.observed_los_change_cm.toFixed(2)} cm LOS`}</dd></div>
            <div><dt>Measurement confidence</dt><dd>{selectedZone.uncertainty_available ? "Uncertainty estimated" : "Limited—uncertainty unavailable"}</dd></div>
          </dl>
        </div>
      ) : <p className="map-click-hint">Click a colored area on the map for its explanation.</p>}

      <div className="evidence-card">
        <strong>Groundwater context</strong>
        <p>{assessment.groundwater.summary}</p>
        {assessment.groundwater.trend_summary && <p>{assessment.groundwater.trend_summary}</p>}
        {!assessment.groundwater.relationship_eligible && <small>This result is shown as land movement only. It does not claim groundwater caused the movement.</small>}
      </div>

      <div className="recommendation-list">
        <h4>Recommended next steps</h4>
        {assessment.recommendations.map((item) => (
          <div key={item.title}><strong>{item.title}</strong><p>{item.detail}</p></div>
        ))}
      </div>

      <details className="limitations">
        <summary>Data quality and limitations</summary>
        <p>Evidence quality: <strong>{assessment.evidence_quality}</strong></p>
        <ul>{assessment.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        <p>{assessment.forecast.summary}</p>
      </details>
      <button type="button" className="refresh-assessment" onClick={onRefresh} disabled={refreshing}>
        {refreshing ? "Checking for newer imagery…" : "Refresh with available imagery"}
      </button>
    </section>
  );
}
