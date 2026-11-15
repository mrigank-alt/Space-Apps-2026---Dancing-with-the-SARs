// DEMONSTRATION DATA ONLY. This module does not process satellite observations.
export const REGION = Object.freeze({ west: 55.65, south: 30.10, east: 56.35, north: 30.70 });
export const PERIOD = Object.freeze({ start: '2026-06-23', end: '2026-10-21', days: 120 });
export const PEAK_CM = 4.2;
export const EXAMPLE = [[55.86,30.45],[55.91,30.47],[55.97,30.445],[55.98,30.40],[55.92,30.38],[55.865,30.40]];
export const inRegion = ([x,y]) => Number.isFinite(x) && Number.isFinite(y) && x >= REGION.west && x <= REGION.east && y >= REGION.south && y <= REGION.north;
const equal = (a,b) => a[0] === b[0] && a[1] === b[1];
export function openRing(points) { return points.length > 1 && equal(points[0], points.at(-1)) ? points.slice(0,-1) : points; }
export function bounds(points) { return [Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))]; }
export function areaHectares(points) {
  let sum=0;
  for(let i=0;i<points.length;i++) { const a=points[i],b=points[(i+1)%points.length]; sum+=(b[0]-a[0])*Math.PI/180*(2+Math.sin(a[1]*Math.PI/180)+Math.sin(b[1]*Math.PI/180)); }
  return Math.abs(sum)*6371008.8**2/2/10000;
}
function orientation(a,b,c) { return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]); }
function onSegment(a,b,p) { return Math.abs(orientation(a,b,p))<1e-12 && p[0]>=Math.min(a[0],b[0])-1e-12 && p[0]<=Math.max(a[0],b[0])+1e-12 && p[1]>=Math.min(a[1],b[1])-1e-12 && p[1]<=Math.max(a[1],b[1])+1e-12; }
function intersects(a,b,c,d) { const p=orientation(a,b,c),q=orientation(a,b,d),r=orientation(c,d,a),s=orientation(c,d,b); return (p*q<0 && r*s<0)||onSegment(a,b,c)||onSegment(a,b,d)||onSegment(c,d,a)||onSegment(c,d,b); }
export function validatePolygon(input) {
  if(!Array.isArray(input)||input.some(p=>!Array.isArray(p)||p.length!==2)) return 'Use longitude/latitude pairs.';
  const points=openRing(input);
  if(points.length<3) return 'Add at least three corners before finishing.';
  if(points.length>200) return 'Use no more than 200 corners for this demo.';
  if(!points.every(inRegion)) return 'Every corner must be inside the Rafsanjan demo study window.';
  if(new Set(points.map(p=>p.join(','))).size!==points.length) return 'Remove repeated corners.';
  for(let i=0;i<points.length;i++) for(let j=i+1;j<points.length;j++) {
    if(j===i+1 || (i===0 && j===points.length-1)) continue;
    if(intersects(points[i],points[(i+1)%points.length],points[j],points[(j+1)%points.length])) return 'Edges cannot cross or touch. Draw a simple polygon.';
  }
  if(areaHectares(points)<0.1) return 'Select at least 0.1 hectares so the area can be displayed.';
  return null;
}
export function pointInPolygon(point, input) {
  const p=openRing(input); let inside=false;
  for(let i=0,j=p.length-1;i<p.length;j=i++) {
    if(onSegment(p[j],p[i],point)) return true;
    if((p[i][1]>point[1])!==(p[j][1]>point[1]) && point[0]<(p[j][0]-p[i][0])*(point[1]-p[i][1])/(p[j][1]-p[i][1])+p[i][0]) inside=!inside;
  }
  return inside;
}
export function buildHeatmap(input) {
  const error=validatePolygon(input); if(error) throw new Error(error);
  const points=openRing(input),[west,south,east,north]=bounds(points);
  let cells=[];
  for(const count of [36,72,144]) {
    const dx=(east-west)/count,dy=(north-south)/count;
    cells=[];
    for(let row=0;row<count;row++) for(let col=0;col<count;col++) {
      const lon=west+(col+0.5)*dx,lat=south+(row+0.5)*dy;
      if(!pointInPolygon([lon,lat],points)) continue;
      const x=(lon-west)/(east-west),y=(lat-south)/(north-south);
      const score=0.12+0.9*Math.exp(-((x-0.70)**2/0.045+(y-0.37)**2/0.075))+0.43*Math.exp(-((x-0.24)**2/0.08+(y-0.75)**2/0.04));
      cells.push({lon,lat,west:lon-dx/2,east:lon+dx/2,south:lat-dy/2,north:lat+dy/2,score});
    }
    if(cells.length>=12) break;
  }
  if(!cells.length) throw new Error('This polygon is too narrow for the demo grid. Select a wider area.');
  const max=Math.max(...cells.map(c=>c.score));
  return cells.map(c=>({...c,cm:PEAK_CM*c.score/max,simulation:true}));
}
export function severity(cm) { return cm>=2.8?'high':cm>=1.4?'moderate':'lower'; }
export function isoAtDay(day) { return new Date(Date.parse(PERIOD.start+'T00:00:00Z')+Math.max(0,Math.min(120,day))*86400000).toISOString().slice(0,10); }
export function waterBudget(storage, pumping, recharge, reductionPercent=0) {
  if(![storage,pumping,recharge,reductionPercent].every(Number.isFinite) || storage<=0 || pumping<0 || recharge<0 || reductionPercent<0 || reductionPercent>100) return {error:'Enter positive storage, nonnegative annual flows, and a reduction from 0 to 100%.'};
  const net=pumping*(1-reductionPercent/100)-recharge;
  return {years:net>0?storage/net:null,net,simulation:true};
}
export function boundaryGeoJSON(input) {
  const error=validatePolygon(input); if(error) throw new Error(error);
  const p=openRing(input);
  return {type:'Feature',geometry:{type:'Polygon',coordinates:[[...p,p[0]]]},properties:{name:'Rafsanjan user-selected boundary',boundary_source:'user selection',study_window:'approximate demo window; not an administrative or aquifer boundary',displacement_data:'SIMULATED, NOT SATELLITE MEASUREMENTS',simulation:true,simulated_peak_cm:PEAK_CM,start:PERIOD.start,end:PERIOD.end,vertical_or_los:'illustrative land sinkage; neither validated vertical nor LOS displacement',groundwater_depletion_prediction:null,full_subsidence_date:null}};
}
