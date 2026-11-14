"use client";

import { useEffect, useMemo, useRef, useState } from "react";

const dates = ["Jun 17", "Jul 11", "Aug 04", "Aug 28", "Sep 21", "Oct 15", "Nov 08"];

const hotspots = [
  { name: "Corcoran Bowl", place: "Kings County", rate: -42, confidence: 92, x: 54, y: 62, exposed: "Canals · SR-43" },
  { name: "Tulare West", place: "Tulare County", rate: -31, confidence: 88, x: 67, y: 70, exposed: "Farms · wells" },
  { name: "Mendota Reach", place: "Fresno County", rate: -24, confidence: 84, x: 41, y: 43, exposed: "Delta–Mendota Canal" },
  { name: "Wasco North", place: "Kern County", rate: -18, confidence: 79, x: 59, y: 84, exposed: "Rail · SR-99" },
];

function MapCanvas({ step, quality }: { step: number; quality: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const box = canvas.getBoundingClientRect();
    canvas.width = box.width * dpr;
    canvas.height = box.height * dpr;
    ctx.scale(dpr, dpr);
    const w = box.width;
    const h = box.height;

    ctx.fillStyle = "#d8d3c4";
    ctx.fillRect(0, 0, w, h);

    const img = ctx.createImageData(Math.ceil(w * dpr), Math.ceil(h * dpr));
    const strength = 0.35 + step * 0.105;
    const centers = [
      [0.54, 0.62, 0.22, 0.17, 1],
      [0.67, 0.70, 0.16, 0.13, 0.77],
      [0.41, 0.43, 0.17, 0.15, 0.56],
      [0.59, 0.84, 0.14, 0.1, 0.43],
    ];
    for (let py = 0; py < img.height; py++) {
      for (let px = 0; px < img.width; px++) {
        const nx = px / img.width;
        const ny = py / img.height;
        let v = 0;
        centers.forEach(([cx, cy, sx, sy, amp]) => {
          const dx = (nx - cx) / sx;
          const dy = (ny - cy) / sy;
          v += Math.exp(-(dx * dx + dy * dy) * 2.2) * amp;
        });
        const noise = Math.sin(nx * 73 + ny * 21) * 0.018 + Math.sin(ny * 89) * 0.012;
        v = Math.max(0, Math.min(1, v * strength + noise));
        const i = (py * img.width + px) * 4;
        const base = [216, 211, 196];
        let color = base;
        if (v > 0.06) {
          const t = Math.min(1, v * 1.3);
          color = t < 0.5
            ? [Math.round(232 + t * 30), Math.round(196 - t * 72), Math.round(107 - t * 28)]
            : [Math.round(245 - (t - .5) * 160), Math.round(143 - (t - .5) * 170), Math.round(87 - (t - .5) * 50)];
        }
        img.data[i] = color[0]; img.data[i + 1] = color[1]; img.data[i + 2] = color[2];
        img.data[i + 3] = quality && ((px + py * 3) % 97 < 3) ? 100 : 245;
      }
    }
    ctx.putImageData(img, 0, 0);

    ctx.strokeStyle = "rgba(255,255,255,.6)";
    ctx.lineWidth = 1;
    for (let x = -h; x < w + h; x += 55) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x + h * .4, h); ctx.stroke();
    }
    ctx.strokeStyle = "rgba(56,73,65,.23)";
    ctx.lineWidth = 2;
    [[.2,.05,.42,.95],[.72,.02,.60,.96],[.05,.55,.92,.38]].forEach(p => {
      ctx.beginPath(); ctx.moveTo(p[0]*w,p[1]*h); ctx.bezierCurveTo(p[0]*w+30,h*.38,p[2]*w-40,h*.62,p[2]*w,p[3]*h); ctx.stroke();
    });
  }, [step, quality]);

  return <canvas className="map-canvas" ref={ref} aria-label="Simulated NISAR line-of-sight displacement map" />;
}

function MiniChart({ rate, step }: { rate: number; step: number }) {
  const values = useMemo(() => dates.map((_, i) => Math.round(rate * (i / 6) * (0.82 + i * .03))), [rate]);
  return (
    <div className="chart" aria-label="Displacement trend chart">
      <div className="chart-grid"><span>0</span><span>{Math.round(rate/2)} mm</span><span>{rate} mm</span></div>
      <div className="bars">{values.map((v, i) => <div key={i} className={`bar ${i === step ? "active" : ""}`} style={{ height: `${18 + Math.abs(v/rate)*70}%` }}><i /></div>)}</div>
    </div>
  );
}

export default function Home() {
  const [step, setStep] = useState(6);
  const [selected, setSelected] = useState(0);
  const [quality, setQuality] = useState(true);
  const [about, setAbout] = useState(false);
  const spot = hotspots[selected];

  return (
    <main>
      <header>
        <div className="brand"><span className="brand-mark">↓</span><div><strong>Groundsignal</strong><small>NISAR displacement explorer</small></div></div>
        <div className="header-actions"><span className="demo-pill"><i /> DEMO DATA</span><button className="ghost" onClick={() => setAbout(true)}>Data pipeline</button></div>
      </header>

      <section className="workspace">
        <aside className="sidebar">
          <div className="eyebrow">STUDY AREA · CALIFORNIA</div>
          <h1>Where is the ground sinking?</h1>
          <p className="lede">A feasibility prototype for turning NISAR displacement products into decisions people can see.</p>

          <div className="metric-card">
            <span>FASTEST OBSERVED</span>
            <strong>{spot.rate} <small>mm</small></strong>
            <p>Line-of-sight change since Jun 17</p>
          </div>

          <div className="section-label"><span>PRIORITY HOTSPOTS</span><span>CHANGE</span></div>
          <div className="hotspot-list">
            {hotspots.map((h, i) => (
              <button key={h.name} className={selected === i ? "hotspot active" : "hotspot"} onClick={() => setSelected(i)}>
                <span className="rank">0{i+1}</span><span className="spot-copy"><strong>{h.name}</strong><small>{h.place}</small></span><b>{h.rate} mm</b>
              </button>
            ))}
          </div>

          <div className="quality-row">
            <div><strong>Quality mask</strong><small>Hide low-coherence pixels</small></div>
            <button aria-label="Toggle quality mask" aria-pressed={quality} onClick={() => setQuality(!quality)} className={`toggle ${quality ? "on" : ""}`}><i /></button>
          </div>
        </aside>

        <section className="map-panel">
          <MapCanvas step={step} quality={quality} />
          <div className="map-label north">CENTRAL VALLEY</div>
          <div className="map-label city c1">FRESNO</div><div className="map-label city c2">VISALIA</div><div className="map-label city c3">BAKERSFIELD</div>
          {hotspots.map((h, i) => <button key={h.name} onClick={() => setSelected(i)} aria-label={`Select ${h.name}`} className={`map-pin ${selected === i ? "selected" : ""}`} style={{ left: `${h.x}%`, top: `${h.y}%` }}><i /><span>{h.rate}</span></button>)}

          <div className="legend"><span>UPLIFT</span><div className="legend-bar" /><span>SUBSIDENCE</span><b>mm</b><div className="ticks"><i>+10</i><i>0</i><i>−20</i><i>−45</i></div></div>

          <div className="detail-card">
            <div className="detail-head"><div><span>SELECTED LOCATION</span><h2>{spot.name}</h2><p>{spot.place}</p></div><div className="confidence"><strong>{spot.confidence}%</strong><span>confidence</span></div></div>
            <MiniChart rate={spot.rate} step={step} />
            <div className="detail-foot"><div><span>EXPOSED ASSETS</span><strong>{spot.exposed}</strong></div><div><span>INTERPRETATION</span><strong>Persistent downward motion</strong></div></div>
          </div>

          <div className="timeline">
            <button onClick={() => setStep(step === 6 ? 0 : 6)} aria-label="Toggle first and latest acquisition">{step === 6 ? "Ⅱ" : "▶"}</button>
            <div className="time-copy"><span>ACQUISITION</span><strong>2026 · {dates[step]}</strong></div>
            <input aria-label="Acquisition date" type="range" min="0" max="6" value={step} onChange={e => setStep(Number(e.target.value))} />
            <div className="date-ends"><span>JUN 17</span><span>NOV 08</span></div>
          </div>
        </section>
      </section>

      {about && <div className="modal-backdrop" onClick={() => setAbout(false)}><section className="modal" onClick={e => e.stopPropagation()}><button className="close" onClick={() => setAbout(false)}>×</button><div className="eyebrow">PRODUCTION PATH</div><h2>From archive to map</h2><p>This prototype uses deterministic demo pixels so the interface works without credentials. The production adapter swaps in analysis-ready NISAR products.</p><ol><li><b>Discover</b><span>ASF Search · NISAR GUNW · validated</span></li><li><b>Authenticate</b><span>NASA Earthdata Login</span></li><li><b>Extract</b><span>Displacement + coherence from HDF5</span></li><li><b>Publish</b><span>Cloud-optimized GeoTIFF tiles</span></li></ol><div className="callout"><b>Earthaccess remains useful</b><span>Use it for complementary NASA datasets; use ASF Search for NISAR-specific discovery.</span></div></section></div>}
    </main>
  );
}
