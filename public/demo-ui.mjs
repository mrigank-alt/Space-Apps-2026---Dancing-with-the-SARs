import {REGION,PERIOD,PEAK_CM,EXAMPLE,inRegion,bounds,areaHectares,validatePolygon,buildHeatmap,severity,isoAtDay,boundaryGeoJSON,waterBudget} from './demo-model.mjs';
const $=id=>document.getElementById(id),stage=$('map-stage'),svg=$('overlay');
let map=null,points=[],selected=null,cells=[],drawing=false,day=120,animation=null,focus=null,pointer=null,down=null,pending=false;
const regionRing=[[REGION.west,REGION.south],[REGION.east,REGION.south],[REGION.east,REGION.north],[REGION.west,REGION.north]];
let fallbackBounds=[REGION.west-.04,REGION.south-.04,REGION.east+.04,REGION.north+.04];
function project([lon,lat]) {if(map){const p=map.project([lon,lat]);return[p.x,p.y];}const[w,s,e,n]=fallbackBounds;return[(lon-w)/(e-w)*stage.clientWidth,(n-lat)/(n-s)*stage.clientHeight];}
function unproject(x,y) {if(map){const p=map.unproject([x,y]);return[p.lng,p.lat];}const[w,s,e,n]=fallbackBounds;return[w+x/stage.clientWidth*(e-w),n-y/stage.clientHeight*(n-s)];}
const path=ps=>ps.map(p=>project(p).map(n=>n.toFixed(2)).join(',')).join(' ');
function color(value){const stops=[[242,223,139],[234,170,86],[216,113,77],[169,54,75]],u=Math.min(2.9999,Math.max(0,value/PEAK_CM*3)),i=Math.floor(u),f=u-i;return`rgb(${stops[i].map((v,k)=>Math.round(v+(stops[i+1][k]-v)*f)).join(',')})`;}
function queueRender(){if(!pending){pending=true;requestAnimationFrame(()=>{pending=false;renderMap();});}}
function renderMap(){
 const width=stage.clientWidth,height=stage.clientHeight;svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
 let html=`<polygon points="${path(regionRing)}" fill="none" stroke="#526a3b" stroke-width="1.5" stroke-dasharray="7 6" opacity=".7"/>`;
 if(!map){for(let lon=55.7;lon<56.4;lon+=.1){const[x]=project([lon,30.4]);html+=`<text x="${x}" y="${height-133}" fill="#768663" font-size="9" text-anchor="middle">${lon.toFixed(1)}° E</text>`;}for(let lat=30.2;lat<30.7;lat+=.1){const[,y]=project([56,lat]);html+=`<text x="12" y="${y}" fill="#768663" font-size="9">${lat.toFixed(1)}° N</text>`;}}
 if(selected){
  html+=`<defs><clipPath id="field-clip"><polygon points="${path(selected)}"/></clipPath></defs><g clip-path="url(#field-clip)"><polygon points="${path(selected)}" fill="#f1df8b" fill-opacity=".45"/>`;
  for(const c of cells)html+=`<polygon points="${path([[c.west,c.south],[c.east,c.south],[c.east,c.north],[c.west,c.north]])}" fill="${color(c.cm*day/120)}" fill-opacity=".76" stroke="none"/>`;
  html+=`</g><polygon points="${path(selected)}" fill="none" stroke="#f8fae7" stroke-width="4"/><polygon points="${path(selected)}" fill="none" stroke="#284c31" stroke-width="1.6"/>`;
  const peak=cells.reduce((a,b)=>a.cm>b.cm?a:b),[x,y]=project([peak.lon,peak.lat]);
  html+=`<circle cx="${x}" cy="${y}" r="18" fill="none" stroke="#fff8e4" stroke-width="1.5"/><circle cx="${x}" cy="${y}" r="4" fill="#fff8e4"/><rect x="${x+17}" y="${y-29}" rx="4" width="98" height="35" fill="#173e30"/><text x="${x+26}" y="${y-14}" font-family="system-ui" fill="#fff8e4" font-size="11">${(PEAK_CM*day/120).toFixed(1)} cm · DEMO</text><text x="${x+26}" y="${y-3}" font-family="system-ui" fill="#c7d6b2" font-size="7">SIMULATED PEAK</text>`;
 }
 if(points.length){html+=`<polyline points="${path(pointer&&drawing?[...points,pointer]:points)}" fill="none" stroke="#254b2f" stroke-width="2" stroke-dasharray="5 4"/>`;for(let i=0;i<points.length;i++){const[x,y]=project(points[i]);html+=`<circle cx="${x}" cy="${y}" r="${i===0?6:4}" fill="#fbfbeb" stroke="#254b2f" stroke-width="2"/>`;}}
 if(focus){const[x,y]=project(focus);html+=`<circle cx="${x}" cy="${y}" r="27" fill="none" stroke="#fff" stroke-width="2" stroke-dasharray="4 3"/>`;}
 svg.innerHTML=html;
}
function error(message){$('selection-error').hidden=!message;$('selection-error').textContent=message||'';}
function stopAnimation(){if(animation)clearInterval(animation);animation=null;$('play').textContent='▶ Play';}
function controls(){
 $('draw').classList.toggle('active',drawing);$('draw').textContent=drawing?'Drawing polygon…':'＋ Draw a polygon';stage.classList.toggle('drawing',drawing);
 $('undo').disabled=!drawing||!points.length;$('finish').disabled=!drawing||points.length<3;$('clear').disabled=!selected&&!points.length;
 $('export').disabled=!selected;$('analysis').hidden=!selected;$('time').disabled=!selected;$('play').disabled=!selected;$('map-placeholder').hidden=!!selected||drawing;
 $('map-mode').textContent=drawing?'CLICK CORNERS · ENTER TO FINISH · ESC TO CANCEL':'POLYGON SELECTION · RAFSANJAN ONLY';
 $('area').innerHTML=selected?`${areaHectares(selected).toLocaleString(undefined,{maximumFractionDigits:1})} <small>ha</small>`:'— <small>ha</small>';
 $('corners').innerHTML=selected?`${selected.length} <small>corners</small>`:`${points.length||'—'} <small>corners</small>`;
 if(map){if(drawing)map.dragPan.disable();else map.dragPan.enable();}queueRender();
}
function startDrawing(){stopAnimation();drawing=true;selected=null;cells=[];points=[];pointer=null;focus=null;error(null);$('selection-status').textContent='Click each field corner. Click the first corner or press Enter to finish. Escape cancels.';controls();stage.focus();}
function finish(){const message=validatePolygon(points);if(message){error(message);return;}try{cells=buildHeatmap(points);}catch(e){error(e.message);return;}selected=points.map(p=>[...p]);points=[];drawing=false;pointer=null;focus=null;error(null);$('selection-status').textContent='Boundary selected. The colored surface is simulated; download your actual boundary below.';controls();updateAnalysis();}
function clear(){stopAnimation();selected=null;cells=[];points=[];drawing=false;pointer=null;focus=null;error(null);$('selection-status').textContent='Click “Draw a polygon”, then mark each corner. Finish with Enter or the button.';controls();}
function fitSelection(){if(!selected)return;const[w,s,e,n]=bounds(selected);if(map)map.fitBounds([[w,s],[e,n]],{padding:{top:160,bottom:180,left:65,right:65},duration:650,maxZoom:15});else{const dx=(e-w)*.55,dy=(n-s)*.7;fallbackBounds=[w-dx,s-dy,e+dx,n+dy];queueRender();}}
function recenter(){fallbackBounds=[REGION.west-.04,REGION.south-.04,REGION.east+.04,REGION.north+.04];if(map)map.fitBounds([[REGION.west,REGION.south],[REGION.east,REGION.north]],{padding:70,duration:650});queueRender();}
function zoneName(c){const[w,s,e,n]=bounds(selected),x=(c.lon-w)/(e-w),y=(c.lat-s)/(n-s);return`${y>.66?'Northern':y<.33?'Southern':'Central'} ${x>.66?'east':x<.33?'west':'field'} zone`;}
function updateAnalysis(){
 $('selected-date').textContent=new Date(isoAtDay(day)+'T00:00:00Z').toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'}).toUpperCase();
 if(!selected){queueRender();return;}const ratio=day/120,mean=cells.reduce((sum,c)=>sum+c.cm*ratio,0)/cells.length;
 $('peak').textContent=(PEAK_CM*ratio).toFixed(1);$('average').textContent=mean.toFixed(1);$('high-fraction').textContent=Math.round(100*cells.filter(c=>severity(c.cm*ratio)==='high').length/cells.length)+'%';
 $('measurement-period').textContent=`23 Jun – ${new Date(isoAtDay(day)+'T00:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'})} · ${day} simulated days`;
 const[w,s,e,n]=bounds(selected),chosen=[];for(const cell of [...cells].sort((a,b)=>b.cm-a.cm)){if(chosen.every(c=>Math.hypot((c.lon-cell.lon)/(e-w),(c.lat-cell.lat)/(n-s))>.24))chosen.push(cell);if(chosen.length===3)break;}
 const messages={high:'First verification priority: inspect wells, irrigation lines and visible cracks here. Ask the local water manager to compare metered extraction and well levels before setting pumping limits.',moderate:'Review priority: check irrigation demand and avoidable water losses; compare well-level trends with nearby fields. This demo threshold is not a measured hazard level.',lower:'Routine-check priority: continue recording well levels and pumping. Lower simulated movement does not establish groundwater availability or safe extraction.'};
 $('alerts').replaceChildren();chosen.forEach(c=>{const level=severity(c.cm*ratio),article=document.createElement('article');article.className='alert '+level;const top=document.createElement('div');top.className='alert-top';const h=document.createElement('h3');h.textContent=zoneName(c);const value=document.createElement('strong');value.textContent=(c.cm*ratio).toFixed(1)+' cm';top.append(h,value);const label=document.createElement('p');label.textContent=`${level.toUpperCase()} SIMULATED MOVEMENT · ${c.lat.toFixed(4)}° N, ${c.lon.toFixed(4)}° E`;const advice=document.createElement('p');advice.textContent=messages[level];const button=document.createElement('button');button.textContent='Locate this demo zone ↗';button.addEventListener('click',()=>{focus=[c.lon,c.lat];if(map)map.easeTo({center:focus,duration:450});queueRender();});article.append(top,label,advice,button);$('alerts').append(article);});
 $('alert-count').textContent=chosen.length+' DEMO ZONES';queueRender();
}
function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);}
$('draw').addEventListener('click',startDrawing);$('finish').addEventListener('click',finish);$('clear').addEventListener('click',clear);$('recenter').addEventListener('click',recenter);
$('undo').addEventListener('click',()=>{points.pop();error(null);controls();});
$('example').addEventListener('click',()=>{stopAnimation();points=EXAMPLE.map(p=>[...p]);day=120;$('time').value='120';finish();fitSelection();});
$('export').addEventListener('click',()=>{if(selected)download('rafsanjan-boundary-demo.geojson',JSON.stringify(boundaryGeoJSON(selected),null,2),'application/geo+json');});
$('export-grid').addEventListener('click',()=>{if(!selected)return;const lines=['longitude,latitude,simulated_land_sinkage_cm,simulation,start_date,end_date,validated_satellite_measurement'];for(const c of cells)lines.push(`${c.lon.toFixed(7)},${c.lat.toFixed(7)},${(c.cm*day/120).toFixed(4)},true,${PERIOD.start},${isoAtDay(day)},false`);download('rafsanjan-SIMULATED-grid.csv',lines.join('\n'),'text/csv');});
$('time').addEventListener('input',()=>{stopAnimation();day=Number($('time').value);updateAnalysis();});
$('play').addEventListener('click',()=>{if(animation){stopAnimation();return;}if(day>=120)day=0;$('play').textContent='Ⅱ Pause';animation=setInterval(()=>{day=Math.min(120,day+2);$('time').value=String(day);updateAnalysis();if(day===120)stopAnimation();},110);});
stage.addEventListener('pointerdown',event=>{down=[event.clientX,event.clientY];});
stage.addEventListener('pointermove',event=>{if(!drawing)return;const r=stage.getBoundingClientRect();pointer=unproject(event.clientX-r.left,event.clientY-r.top);queueRender();});
stage.addEventListener('click',event=>{if(!drawing||event.target.closest('button,input,a,.timeline')||!down||Math.hypot(event.clientX-down[0],event.clientY-down[1])>6)return;const r=stage.getBoundingClientRect(),p=unproject(event.clientX-r.left,event.clientY-r.top);if(!inRegion(p)){error('Select inside the Rafsanjan demo study window.');return;}if(points.length>=3){const a=project(points[0]);if(Math.hypot(event.clientX-r.left-a[0],event.clientY-r.top-a[1])<12){finish();return;}}if(points.length){const a=project(points.at(-1));if(Math.hypot(event.clientX-r.left-a[0],event.clientY-r.top-a[1])<3)return;}if(points.length>=200){error('Maximum 200 corners. Finish the current polygon.');return;}points.push(p);error(null);controls();});
document.addEventListener('keydown',event=>{if(!drawing||event.target.closest('input,textarea,button,summary'))return;if(event.key==='Enter'){event.preventDefault();finish();}else if(event.key==='Escape'){event.preventDefault();clear();}else if(event.key==='Backspace'){event.preventDefault();points.pop();controls();}});
function updateScenario(){
 $('scenario').hidden=!$('scenario-enabled').checked;const values=['storage','pumping','recharge'].map(id=>$(id).value.trim()===''?NaN:Number($(id).value)),reduction=Number($('reduction').value);$('reduction-label').textContent=reduction+'%';const base=waterBudget(...values),reduced=waterBudget(...values,reduction);$('scenario-error').hidden=!base.error;$('scenario-error').textContent=base.error||'';const label=r=>r.error?'—':r.years===null?'No net loss':r.years.toFixed(1);$('baseline-years').textContent=label(base);$('reduced-years').textContent=label(reduced);
}
for(const id of ['scenario-enabled','storage','pumping','recharge','reduction'])$(id).addEventListener('input',updateScenario);
function mapStyle(satellite=false){return{version:8,sources:{base:{type:'raster',tiles:[satellite?'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg':'https://tile.openstreetmap.org/{z}/{x}/{y}.png'],tileSize:256,attribution:satellite?'EOxCloudless 2025 by EOX · Copernicus Sentinel data · CC BY-NC-SA (prototype only)':'© OpenStreetMap contributors'}},layers:[{id:'base',type:'raster',source:'base',paint:{'raster-saturation':-.45,'raster-opacity':.9}}]};}
function switchMap(satellite){if(!map){$('map-notification').textContent='Basemap unavailable. Selection and simulation still work on the labeled coordinate grid.';return;}map.setStyle(mapStyle(satellite));$('map-button').setAttribute('aria-pressed',String(!satellite));$('satellite-button').setAttribute('aria-pressed',String(satellite));}
$('map-button').addEventListener('click',()=>switchMap(false));$('satellite-button').addEventListener('click',()=>switchMap(true));
function loadBasemap(){
 const script=document.createElement('script');script.src='https://unpkg.com/maplibre-gl@5.15.0/dist/maplibre-gl.js';script.crossOrigin='anonymous';
 script.onerror=()=>{$('map-notification').textContent='Offline coordinate grid. Basemap imagery could not load; drawing and GeoJSON export still work.';};
 script.onload=()=>{try{map=new window.maplibregl.Map({container:'basemap',style:mapStyle(),center:[55.98714,30.40055],zoom:9.5,minZoom:8.7,maxZoom:17,maxBounds:[[REGION.west-.1,REGION.south-.1],[REGION.east+.1,REGION.north+.1]],attributionControl:{compact:true}});map.doubleClickZoom.disable();map.on('move',queueRender);map.on('resize',queueRender);map.on('load',()=>{$('map-grid').classList.add('has-map');$('map-notification').hidden=true;if(selected)fitSelection();else recenter();controls();});map.on('error',()=>{$('map-notification').hidden=false;$('map-notification').textContent='Some map tiles could not load. Boundary coordinates and the simulated overlay remain available.';});queueRender();}catch{$('map-notification').textContent='Map renderer unavailable. Use the labeled coordinate grid to select your polygon.';map=null;queueRender();}};
 document.head.append(script);
}
new ResizeObserver(queueRender).observe(stage);controls();updateScenario();loadBasemap();
