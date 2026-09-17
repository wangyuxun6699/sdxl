// All geometry lives on a unit sphere. Screen coordinates are derived only at render time.
export const CAMERA_TILT = 0.36;
const COS_TILT = Math.cos(CAMERA_TILT);
const SIN_TILT = Math.sin(CAMERA_TILT);
export const CITY_EXTENT_X = 1.38;
export const CITY_BACK = -0.92;
export const CITY_FRONT = 1.3;
export const CITY_DEPTH = CITY_FRONT - CITY_BACK;
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
export function smoothstep(lo, hi, v) {
  const t = clamp((v - lo) / (hi - lo), 0, 1);
  return t * t * (3 - 2 * t);
}
export function spherePoint(east, depth) {
  const inv = 1 / Math.hypot(east, 1, depth);
  const x = east * inv, y = inv, z = depth * inv;
  return { x, y, z, longitude: Math.atan2(x, z), latitude: Math.asin(y) };
}
export function projectVertex(point, metrics, cos, sin, out = {}) {
  const x = point.x * cos + point.z * sin;
  const z = point.z * cos - point.x * sin;
  out.facing = point.y * SIN_TILT + z * COS_TILT;
  out.vertical = point.y * COS_TILT - z * SIN_TILT;
  out.x = metrics.centerX + x * metrics.radius;
  out.y = metrics.centerY - out.vertical * metrics.radius;
  return out;
}
export function polygonArea(points) {
  let area = 0;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    area += points[j].x * points[i].y - points[i].x * points[j].y;
  }
  return area * 0.5;
}
export function containsPoint(points, x, y) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const a = points[i], b = points[j];
    if ((a.y > y) !== (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}
function normalBetween(a, b, n) {
  const x = b.x - a.x, y = b.y - a.y, z = b.z - a.z;
  const nx = y * n.z - z * n.y;
  const ny = z * n.x - x * n.z;
  const nz = x * n.y - y * n.x;
  const inv = 1 / Math.hypot(nx, ny, nz);
  return { x: nx * inv, y: ny * inv, z: nz * inv };
}
function addPrism(building, west, back, width, depth, bottom, top) {
  const start = building.vertices.length;
  const corners = [spherePoint(west, back), spherePoint(west, back + depth),
    spherePoint(west + width, back + depth), spherePoint(west + width, back)];
  // One local plane per building keeps roofs flat at grazing camera angles.
  // Its lowest spherical corner sets the foundation, preventing a floating edge.
  for(const p of corners) {
    const offset=building.foundation-(p.x*building.x+p.y*building.y+p.z*building.z);
    p.x+=building.x*offset;p.y+=building.y*offset;p.z+=building.z*offset;
  }
  for (const level of [bottom, top]) {
    for (const corner of corners) building.vertices.push({ ...corner, level, projected: {} });
  }
  function face(indices, roof, normal) {
    building.faces.push({
      building, points: indices.map(i => building.vertices[start + i].projected),
      roof, normal, depth: 0, color: '', alpha: 1,
    });
  }
  for (let i = 0; i < 4; i++) {
    const j = (i + 1) % 4;
    face([i, j, j + 4, i + 4], false, normalBetween(corners[i], corners[j], building));
  }
  face([4, 5, 6, 7], true, building);
}

export function buildCity(columns, rows, seed = 20260905) {
  let state = seed;
  const random = () => ((state = (Math.imul(state, 1664525) + 1013904223) >>> 0) / 4294967296);
  const cellX = CITY_EXTENT_X * 2 / columns, cellZ = CITY_DEPTH / rows;
  const primaryColumns = new Set([.17, .38, .65, .85].map(p => Math.round(columns * p)));
  const primaryRows = new Set([.18, .4, .65, .86].map(p => Math.round(rows * p)));
  const streetColumns = new Set([...primaryColumns, ...Array.from({length:columns},(_,i)=>i).filter(i=>i%8===3)]);
  const streetRows = new Set([...primaryRows, ...Array.from({length:rows},(_,i)=>i).filter(i=>i%8===3)]);
  const used = new Uint8Array(columns * rows);
  for (let row = 0; row < rows; row++) for (let col = 0; col < columns; col++) {
    if (streetColumns.has(col) || streetRows.has(row)) used[row * columns + col] = 1;
  }
  const centers = [
    {e:.04,d:.32,w:1,s:.36}, {e:-.63,d:.06,w:.74,s:.26},
    {e:.64,d:.55,w:.69,s:.25}, {e:.38,d:-.45,w:.49,s:.24},
  ];
  const buildings = [];
  function fits(col, row, w, h) {
    if (col + w > columns || row + h > rows) return false;
    for(let z=row;z<row+h;z++) for(let x=col;x<col+w;x++) if(used[z*columns+x]) return false;
    return true;
  }
  for (let row = 0; row < rows; row++) for (let col = 0; col < columns; col++) {
    if (used[row * columns + col]) continue;
    const east = -CITY_EXTENT_X + (col + .5) * cellX;
    const depth = CITY_BACK + (row + .5) * cellZ;
    let district = 0;
    for (const c of centers) district = Math.max(district, c.w * Math.exp(-((east-c.e)**2+(depth-c.d)**2)/(c.s*c.s)));
    const pick = random();
    let spanX = 1, spanZ = 1, type = 'block';
    if (district < .55 && pick < .085 && fits(col,row,2,2)) { spanX = spanZ = 2; type = 'court'; }
    else if (district < .62 && pick < .48) {
      if ((row + col) % 2 && fits(col,row,2,1)) { spanX=2;type='slab'; }
      else if (fits(col,row,1,2)) { spanZ=2;type='slab'; }
    } else if (district > .45 && pick > .44) type = 'podium';
    for (let z=row;z<row+spanZ;z++) for (let x=col;x<col+spanX;x++) used[z*columns+x]=1;
    const west = -CITY_EXTENT_X + (col + .15) * cellX;
    const back = CITY_BACK + (row + .15) * cellZ;
    const width = (spanX-.3)*cellX, length = (spanZ-.3)*cellZ;
    const point = spherePoint(west+width/2,back+length/2);
    const edge = clamp(1-.34*Math.max(Math.abs(east)/CITY_EXTENT_X,Math.abs(depth-.19)/(CITY_DEPTH/2))**1.7,.55,1);
    let h = (.42 + random()*.38 + district*2.15)*edge;
    if (type==='slab') h *= .72;
    if (type==='court') h = .5 + district*.6;
    if (district>.8 && random()>.96) h+=.5;
    const building = {
      ...point, id: buildings.length, col,row,spanX,spanZ,type,density:district,
      height: cellX*.86*clamp(h,.26,3.25), delay: random()*.8,
      response: 0, responseDelay: random()*.095, responseRelease:.85+random()*.3,
      tone: random()*.06-.03, vertices:[],faces:[], shadow:[], visible:false,
      projected:{}, rise:0, illumination:0, alpha:1,
    };
    building.foundation=Math.min(...[spherePoint(west,back),spherePoint(west+width,back),
      spherePoint(west,back+length),spherePoint(west+width,back+length)]
      .map(p=>p.x*building.x+p.y*building.y+p.z*building.z));
    if (type==='podium') {
      addPrism(building,west,back,width,length,0,.23);
      addPrism(building,west+width*.17,back+length*.17,width*.66,length*.66,.23,1);
    } else if(type==='court') {
      const wing=.28;
      addPrism(building,west,back,width,length*wing,0,1);
      addPrism(building,west,back+length*(1-wing),width,length*wing,0,1);
      addPrism(building,west,back+length*wing,width*wing,length*(1-2*wing),0,.94);
      addPrism(building,west+width*(1-wing),back+length*wing,width*wing,length*(1-2*wing),0,.94);
    } else addPrism(building,west,back,width,length,0,1);
    building.shadow = [spherePoint(west-.001,back-.001),spherePoint(west-.001,back+length+.003),
      spherePoint(west+width+.003,back+length+.003),spherePoint(west+width+.003,back-.001)]
      .map(p=>({...p,projected:{}}));
    building.shadowPoints=building.shadow.map(p=>p.projected);
    buildings.push(building);
  }
  return {buildings,cellX,cellZ,primaryColumns,primaryRows,streetColumns,streetRows};
}

// Retains fractional time rather than discarding it at every rAF boundary.
export function createFrameClock(fps = 60) {
  let last = null, accumulated = 0, sinceDraw = 0;
  return {
    setFps(value) { fps = value; accumulated = sinceDraw = 0; },
    reset() { last = null; accumulated = sinceDraw = 0; },
    tick(timestamp) {
      if (last === null) { last = timestamp; return 0; }
      const dt = clamp(timestamp-last,0,100);
      last = timestamp;
      accumulated += dt; sinceDraw += dt;
      const interval = 1000 / fps;
      if (accumulated + .15 < interval) return null;
      accumulated = Math.max(0, accumulated-interval);
      if(accumulated>interval) accumulated %= interval;
      const elapsed = sinceDraw/1000;
      sinceDraw=0;
      return elapsed;
    },
  };
}
