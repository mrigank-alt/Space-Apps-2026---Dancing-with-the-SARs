import test from 'node:test';
import assert from 'node:assert/strict';
import {EXAMPLE,REGION,PEAK_CM,validatePolygon,pointInPolygon,buildHeatmap,waterBudget,boundaryGeoJSON,isoAtDay,areaHectares} from '../public/demo-model.mjs';

test('rejects outside-window and crossing polygons',()=>{
  assert.match(validatePolygon([[55,30.4],[56,30.5],[56,30.3]]),/window/);
  assert.match(validatePolygon([[55.8,30.3],[56.1,30.5],[55.8,30.5],[56.1,30.3]]),/cross/);
  assert.match(validatePolygon([[55.8,30.3],[55.9,30.4]]),/three/);
  assert.equal(validatePolygon(EXAMPLE),null);
});
test('rejects malformed coordinates and nonfinite inputs',()=>{
  assert.ok(validatePolygon(null));
  assert.ok(validatePolygon([[NaN,30.4],[56,30.4],[56,30.5]]));
  assert.ok(validatePolygon([[56,30.4],[56,30.4],[56.1,30.5]]));
});
test('region boundary is inclusive and polygon area is meaningful',()=>{
  const ring=[[REGION.west,REGION.south],[REGION.east,REGION.south],[REGION.east,REGION.north],[REGION.west,REGION.north]];
  assert.equal(validatePolygon(ring),null);
  assert.ok(areaHectares(EXAMPLE)>0);
  assert.ok(pointInPolygon(EXAMPLE[0],EXAMPLE));
});
test('synthetic grid is deterministic, inside selection, and normalized to 4.2',()=>{
  const cells=buildHeatmap(EXAMPLE);
  assert.ok(cells.length>100);
  assert.ok(cells.every(c=>pointInPolygon([c.lon,c.lat],EXAMPLE)&&c.simulation&&c.cm>0&&c.cm<=PEAK_CM+1e-12));
  assert.ok(Math.abs(Math.max(...cells.map(c=>c.cm))-4.2)<1e-12);
  assert.deepEqual(cells,buildHeatmap(EXAMPLE));
});
test('concave polygons do not include samples in their missing region',()=>{
  const p=[[55.8,30.3],[56,30.3],[56,30.4],[55.9,30.4],[55.9,30.5],[55.8,30.5]];
  assert.equal(validatePolygon(p),null);
  assert.ok(buildHeatmap(p).every(c=>pointInPolygon([c.lon,c.lat],p)));
  assert.equal(pointInPolygon([55.95,30.45],p),false);
});
test('exports a closed polygon with unmistakable simulation provenance',()=>{
  const f=boundaryGeoJSON(EXAMPLE);
  assert.deepEqual(f.geometry.coordinates[0][0],f.geometry.coordinates[0].at(-1));
  assert.equal(f.properties.simulation,true);
  assert.match(f.properties.displacement_data,/NOT SATELLITE/);
  assert.equal(f.properties.groundwater_depletion_prediction,null);
  assert.equal(f.properties.full_subsidence_date,null);
});
test('hypothetical water budget supports net loss and balanced replenishment',()=>{
  assert.ok(Math.abs(waterBudget(12,2.4,.6).years-6.6666666667)<1e-8);
  assert.ok(waterBudget(12,2.4,.6,20).years>waterBudget(12,2.4,.6).years);
  assert.equal(waterBudget(12,.6,.6).years,null);
  assert.equal(waterBudget(12,0,.6).years,null);
  assert.ok(waterBudget(0,2,.5).error);
  assert.ok(waterBudget(12,NaN,.5).error);
  assert.ok(waterBudget(12,2,.5,101).error);
});
test('timeline spans June 23 to October 21 without timezone drift',()=>{
  assert.equal(isoAtDay(0),'2026-06-23');
  assert.equal(isoAtDay(120),'2026-10-21');
  assert.equal(isoAtDay(-2),'2026-06-23');
  assert.equal(isoAtDay(200),'2026-10-21');
});
