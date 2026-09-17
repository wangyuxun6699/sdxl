import { buildCity, spherePoint, projectVertex, polygonArea, containsPoint,
  createFrameClock, smoothstep, clamp, CITY_EXTENT_X, CITY_BACK, CITY_DEPTH } from "./cityGeometry.js";
const TWO_PI = Math.PI * 2;
const SURFACE_LATITUDE_MIN = -1.42;
const SURFACE_LATITUDE_MAX = 1.42;
const RIPPLE_COLOR = "190, 151, 246";
const RIPPLE_HIGHLIGHT = "205, 181, 252";
const INITIAL_ROTATION = 0.48;
const PALETTE = Array.from({ length: 96 }, (_, i) => {
  const e = i / 95;
  return { top: `hsl(266 ${29+e*12}% ${31+e*22}%)`,
    side: `hsl(${249+e*12} ${30+e*5}% ${12.5+e*15}%)` };
});
const easeOutCubic = value => 1 - (1 - clamp(value, 0, 1)) ** 3;
const createTangentPoint = spherePoint;
function createSpherePoint(longitude, latitude) {
  const c = Math.cos(latitude);
  return {longitude,latitude,x:c*Math.sin(longitude),y:Math.sin(latitude),z:c*Math.cos(longitude)};
}
export function createCyberGlobeScene({ root, canvas, reducedMotion = false }) {
  let context, outputContext, frameId = 0, resizeFrame = 0, resizeObserver;
  let sceneWidth = 1, sceneHeight = 1, pixelRatio = 1, gridColumns = 72, gridRows = 52;
  let buildings = [], roads = [], surfaceLines = [], stars = [], horizonDust = [];
  let ripples = [], activeRippleFronts = [], visibleBuildings = [], visibleFaces = [];
  let seed = 20260905, currentTime = 0, globeRotation = INITIAL_ROTATION;
  let nextRandomRippleAt = 4, nextAmbientRippleAt = 10, lastPointerRippleAt = -10;
  let lastPointerRippleX = -1000, lastPointerRippleY = -1000;
  let bloomFrame = 0, frameDelta = 1 / 60, layeredDof = true;
  let cachedRotation = NaN, cachedCosRotation = 1, cachedSinRotation = 0;
  let destroyed = false, qualityTier = 0, renderAverage = 0, renderCount = 0, slowFrames = 0;
  let compactScene = null, touchReleaseAt = 0, lastHitId = null, contentBottom = 0;
  const lowPower = (navigator.hardwareConcurrency || 4) <= 4 || (navigator.deviceMemory || 4) <= 4;
  let targetFps = lowPower ? 30 : 60;
  const clock = createFrameClock(targetFps);
  const layers = {
    base: {canvas:document.createElement('canvas'),scale:1},
    scene: {canvas:document.createElement('canvas'),scale:1},
    dof: {canvas:document.createElement('canvas'),scale:.32},
    bloom: {canvas:document.createElement('canvas'),scale:lowPower?.32:.4},
    bloomSoft: {canvas:document.createElement('canvas'),scale:lowPower?.32:.4},
  };
  const pointer = {x:0,y:0,targetX:0,targetY:0,strength:0,targetStrength:0,source:null};
  const pathProjection = {}, worldVertex = {};
  const bearings = Array.from({length:57},(_,i)=>({c:Math.cos(i/56*TWO_PI),s:Math.sin(i/56*TWO_PI)}));
  function random() { seed = (Math.imul(seed,1664525)+1013904223)>>>0; return seed/4294967296; }
  function createGeographicLine(points) {
    return points.map(({ longitude, latitude }) => createSpherePoint(longitude, latitude));
  }

  function createLatitudeLine(latitude, samples = 100) {
    const points = [];
    for (let index = 0; index <= samples; index += 1) {
      points.push({ longitude: -Math.PI + (index / samples) * TWO_PI, latitude });
    }
    return createGeographicLine(points);
  }

  function createLongitudeLine(longitude, samples = 58) {
    const points = [];
    for (let index = 0; index <= samples; index += 1) {
      points.push({
        longitude,
        latitude:
          SURFACE_LATITUDE_MIN +
          (index / samples) * (SURFACE_LATITUDE_MAX - SURFACE_LATITUDE_MIN),
      });
    }
    return createGeographicLine(points);
  }

  function createTangentLine(axis, value, samples = 84) {
    const points = [];
    for (let index = 0; index <= samples; index += 1) {
      const progress = index / samples;
      const east = axis === "east" ? value : -CITY_EXTENT_X + progress * CITY_EXTENT_X * 2;
      const depth = axis === "depth" ? value : CITY_BACK + progress * CITY_DEPTH;
      points.push(createTangentPoint(east, depth));
    }
    return points;
  }

  function addRipple(longitude, latitude, type = 'auto', delay = 0, strength = 1) {
    if (reducedMotion || ripples.length >= (lowPower ? 7 : 10)) return;
    const duration = type==='pointer'?4.2:type==='ambient'?6.2:5.2;
    const start = currentTime + delay;
    // Reserve visual slots for the whole lifetime, so rings never swap by brightness.
    const overlaps = ripples.filter(r=>r.drawRing && r.start<start+duration && r.start+r.duration>start).length;
    const source = createSpherePoint(longitude,latitude);
    const east = {x:Math.cos(longitude),y:0,z:-Math.sin(longitude)};
    const north = {x:-Math.sin(latitude)*Math.sin(longitude),y:Math.cos(latitude),z:-Math.sin(latitude)*Math.cos(longitude)};
    ripples.push({longitude,latitude,source,east,north,start,duration,
      maximumAngle:type==='pointer'?.51:type==='ambient'?.73:.61,strength,type,
      drawRing:overlaps<(lowPower?2:3),angle:0,fade:0,
      ring:bearings.map(()=>({x:0,y:0,z:0})),chordRadius:0,chordSpeed:0});
  }
  function addVisibleTangentRipple(east, depth, type='auto', delay=0, strength=1) {
    const metrics = sceneMetrics();
    const desired = projectPoint(spherePoint(east,depth),metrics,INITIAL_ROTATION);
    let closest = null, distance = Infinity;
    for(const b of buildings) {
      const p = projectPoint(b,metrics,globeRotation);
      const d = (p.x-desired.x)**2+(p.y-desired.y)**2;
      if(p.facing>.06 && d<distance) {distance=d;closest=b;}
    }
    if(closest) addRipple(closest.longitude,closest.latitude,type,delay,strength);
  }
  function createScene() {
    seed=20260905;roads=[];surfaceLines=[];stars=[];horizonDust=[];ripples=[];
    const compact = sceneWidth<720;
    gridColumns=compact?44:lowPower?62:72;
    gridRows=compact?36:lowPower?46:52;
    const city = buildCity(gridColumns,gridRows);
    buildings=city.buildings;
    for (const row of city.streetRows) roads.push({kind:city.primaryRows.has(row)?'primary':'secondary',
      points:createTangentLine('depth',CITY_BACK+(row+.5)*city.cellZ,compact?48:84)});
    for (const col of city.streetColumns) roads.push({kind:city.primaryColumns.has(col)?'primary':'secondary',
      points:createTangentLine('east',-CITY_EXTENT_X+(col+.5)*city.cellX,compact?48:84)});
    [0.2, 0.42, 0.64, 0.84, 1.02, 1.18, 1.32, 1.43].forEach((latitude) => {
      surfaceLines.push(createLatitudeLine(latitude, compact ? 64 : 104));
    });
    const longitudeLineCount = compact ? 12 : 16;
    for (let index = 0; index < longitudeLineCount; index += 1) {
      surfaceLines.push(
        createLongitudeLine(-Math.PI + (index / longitudeLineCount) * TWO_PI, compact ? 38 : 58)
      );
    }

    const starCount = compact ? 54 : lowPower ? 76 : 106;
    for (let index = 0; index < starCount; index += 1) {
      stars.push({
        x: random(),
        y: random() * 0.78,
        size: 0.35 + random() * 1.35,
        alpha: 0.16 + random() * 0.62,
        phase: random() * TWO_PI,
        speed: 0.18 + random() * 0.42,
      });
    }

    const dustCount = compact ? 22 : 44;
    for (let index = 0; index < dustCount; index += 1) {
      horizonDust.push({
        x: random(),
        offset: (random() - 0.5) * 0.14,
        size: 0.6 + random() * 1.8,
        alpha: 0.08 + random() * 0.24,
        phase: random() * TWO_PI,
      });
    }

    nextRandomRippleAt = currentTime+5.6; nextAmbientRippleAt=currentTime+12;
    addVisibleTangentRipple(-.38,.24,'auto',.3,.86);
    addVisibleTangentRipple(.36,.62,'ambient',1.6,.8);
  }
  function configureLayer(layer) {
    layer.canvas.width=Math.max(1,Math.round(sceneWidth*pixelRatio*layer.scale));
    layer.canvas.height=Math.max(1,Math.round(sceneHeight*pixelRatio*layer.scale));
    layer.context=layer.canvas.getContext('2d',{alpha:true,desynchronized:true});
    layer.context.setTransform(pixelRatio*layer.scale,0,0,pixelRatio*layer.scale,0,0);
    layer.context.imageSmoothingEnabled=true;
  }
  function clearLayer(layer) {
    const c=layer.context;
    c.setTransform(1,0,0,1,0,0);c.clearRect(0,0,layer.canvas.width,layer.canvas.height);
    c.setTransform(pixelRatio*layer.scale,0,0,pixelRatio*layer.scale,0,0);
    c.globalAlpha=1;c.globalCompositeOperation='source-over';c.filter='none';c.setLineDash([]);
  }
  function blit(target,layer,blur=0,alpha=1,operation='source-over') {
    target.save();target.globalAlpha=alpha;target.globalCompositeOperation=operation;
    target.filter=blur?`blur(${blur}px)`:'none';
    target.drawImage(layer.canvas,0,0,layer.canvas.width,layer.canvas.height,0,0,sceneWidth,sceneHeight);
    target.restore();
  }
  function resizeCanvas(force=false) {
    if(destroyed) return;
    const rect=root.getBoundingClientRect();
    const content=root.querySelector?.('.intro-content');
    const nextBottom=content?content.getBoundingClientRect().bottom-rect.top:0;
    const w=Math.max(1,Math.round(rect.width)),h=Math.max(1,Math.round(rect.height));
    if(!force && w===sceneWidth && h===sceneHeight && nextBottom===contentBottom && outputContext) return;
    contentBottom=nextBottom;
    sceneWidth=w;sceneHeight=h;
    const caps=lowPower?[1,.85,.75]:[1.2,1,.85];
    const pixelBudget=lowPower?800000:1800000;
    pixelRatio=Math.min(window.devicePixelRatio||1,caps[qualityTier],Math.sqrt(pixelBudget/(w*h)));
    canvas.width=Math.round(w*pixelRatio);canvas.height=Math.round(h*pixelRatio);
    canvas.style.width=`${w}px`;canvas.style.height=`${h}px`;
    outputContext=canvas.getContext('2d',{alpha:true,desynchronized:true});
    outputContext.setTransform(pixelRatio,0,0,pixelRatio,0,0);
    for(const layer of Object.values(layers)) configureLayer(layer);
    context=layers.scene.context;
    layeredDof=w>=720 && h>=600;
    pointer.x=pointer.targetX=w*.5;pointer.y=pointer.targetY=h*.7;
    pointer.source=null;pointer.targetStrength=pointer.strength=0;
    bloomFrame=0;
    const compact=w<720;
    if(compactScene!==compact) {compactScene=compact;createScene();}
    renderBackground();
    clock.reset();renderScene();requestFrame();
  }
  function scheduleResize() {
    window.cancelAnimationFrame(resizeFrame);
    resizeFrame=window.requestAnimationFrame(()=>resizeCanvas());
  }
  function sceneMetrics() {
    const compact=sceneWidth<720;
    const radius=compact?Math.min(sceneWidth*1.45,sceneHeight*1.38):Math.min(sceneWidth*.88,sceneHeight*1.62);
    let horizonY=sceneHeight*(compact?.6:sceneHeight<700?.64:sceneHeight<900?.565:.515);
    if(contentBottom) horizonY=Math.max(horizonY,contentBottom+Math.min(66,sceneHeight*.065));
    return {centerX:sceneWidth*.5,centerY:radius+horizonY,radius,unit:radius*CITY_EXTENT_X*2/gridColumns,horizonY};
  }
  function projectPoint(point,metrics,rotation) {
    if(rotation!==cachedRotation) {
      cachedRotation=rotation;cachedCosRotation=Math.cos(rotation);cachedSinRotation=Math.sin(rotation);
    }
    return projectVertex(point,metrics,cachedCosRotation,cachedSinRotation);
  }
  function drawSpace(time, metrics) {
    const celestialGlow = context.createRadialGradient(
      metrics.centerX,
      sceneHeight * 0.05,
      0,
      metrics.centerX,
      sceneHeight * 0.18,
      sceneWidth * 0.38
    );
    celestialGlow.addColorStop(0, "rgba(190, 163, 255, 0.11)");
    celestialGlow.addColorStop(0.24, "rgba(104, 91, 210, 0.06)");
    celestialGlow.addColorStop(1, "rgba(26, 18, 72, 0)");
    context.fillStyle = celestialGlow;
    context.fillRect(0, 0, sceneWidth, sceneHeight);

    context.save();
    context.globalCompositeOperation = "screen";
    stars.forEach((star) => {
      const flicker = 0.68 + Math.sin(time * star.speed + star.phase) * 0.26;
      context.beginPath();
      context.fillStyle = `rgba(211, 203, 232, ${star.alpha * flicker})`;
      context.arc(star.x * sceneWidth, star.y * sceneHeight, star.size, 0, TWO_PI);
      context.fill();
    });
    context.restore();
  }

  function drawGlobe(metrics) {
    context.save();
    context.beginPath();
    context.arc(metrics.centerX, metrics.centerY, metrics.radius, 0, TWO_PI);
    context.shadowColor = "rgba(180, 153, 226, 0.32)";
    context.shadowBlur = 28;
    context.lineWidth = 10;
    context.strokeStyle = "rgba(158, 132, 202, 0.08)";
    context.stroke();
    context.shadowBlur = 0;

    const globeFill = context.createRadialGradient(
      metrics.centerX - metrics.radius * 0.16,
      metrics.centerY - metrics.radius * 0.74,
      metrics.radius * 0.04,
      metrics.centerX + metrics.radius * 0.12,
      metrics.centerY - metrics.radius * 0.12,
      metrics.radius * 1.02
    );
    globeFill.addColorStop(0, "rgba(61, 53, 128, 0.72)");
    globeFill.addColorStop(0.28, "rgba(42, 35, 102, 0.88)");
    globeFill.addColorStop(0.62, "rgba(19, 17, 58, 0.98)");
    globeFill.addColorStop(1, "rgba(4, 7, 26, 1)");
    context.fillStyle = globeFill;
    context.fill();
    context.clip();

    const surfaceLight = context.createLinearGradient(0, metrics.centerY - metrics.radius, 0, sceneHeight);
    surfaceLight.addColorStop(0, "rgba(203, 185, 230, 0.13)");
    surfaceLight.addColorStop(0.16, "rgba(155, 124, 198, 0.07)");
    surfaceLight.addColorStop(0.62, "rgba(31, 24, 86, 0.04)");
    surfaceLight.addColorStop(1, "rgba(1, 3, 15, 0.46)");
    context.fillStyle = surfaceLight;
    context.fillRect(0, 0, sceneWidth, sceneHeight);

    const nightSide = context.createLinearGradient(0, 0, sceneWidth, 0);
    nightSide.addColorStop(0, "rgba(3, 5, 22, 0.22)");
    nightSide.addColorStop(0.43, "rgba(20, 12, 57, 0)");
    nightSide.addColorStop(1, "rgba(1, 3, 17, 0.44)");
    context.fillStyle = nightSide;
    context.fillRect(0, metrics.horizonY, sceneWidth, sceneHeight - metrics.horizonY);
    context.restore();

    context.save();
    context.beginPath();context.arc(metrics.centerX,metrics.centerY,metrics.radius,Math.PI*1.04,Math.PI*1.96);
    context.strokeStyle='rgba(152,122,198,0.08)';context.lineWidth=3;
    context.shadowColor='rgba(157,122,202,0.14)';context.shadowBlur=22;context.stroke();context.restore();
  }

  function traceProjectedPath(points,metrics,rotation,threshold=.002) {
    context.beginPath();let active=false;
    const cos=Math.cos(rotation),sin=Math.sin(rotation);
    for(const point of points) {
      projectVertex(point,metrics,cos,sin,pathProjection);
      if(pathProjection.facing<=threshold) {active=false;continue;}
      if(active) context.lineTo(pathProjection.x,pathProjection.y);
      else context.moveTo(pathProjection.x,pathProjection.y);
      active=true;
    }
  }
  function drawSurfaceGrid(metrics, rotation) {
    context.save();
    context.globalCompositeOperation = "screen";
    context.strokeStyle = "rgba(125, 108, 157, 0.07)";
    context.lineWidth = 0.62;
    surfaceLines.forEach((line) => {
      traceProjectedPath(line, metrics, rotation, 0.005);
      context.stroke();
    });
    context.restore();
  }

  function drawRoads(time, metrics, rotation) {
    context.save();
    context.globalCompositeOperation = "screen";
    context.lineCap = "round";
    context.lineJoin = "round";

    roads.forEach((road, index) => {
      const primary = road.kind === "primary";
      const pulse = 0.86 + Math.sin(time * 0.5 + index * 0.63) * 0.09;

      traceProjectedPath(road.points, metrics, rotation, 0.008);
      context.setLineDash([]);
      context.shadowBlur = 0;
      context.strokeStyle = primary
        ? `rgba(118, 89, 157, ${0.18 * pulse})`
        : `rgba(96, 82, 124, ${0.1 * pulse})`;
      context.lineWidth = primary ? 2.8 : 1.5;
      context.stroke();

      context.strokeStyle = primary
        ? `rgba(178, 153, 207, ${0.55 * pulse})`
        : `rgba(126, 109, 153, ${0.28 * pulse})`;
      context.lineWidth = primary ? 0.7 : 0.42;
      context.stroke();

      if (primary) {
        context.setLineDash([2.5, 21]);
        context.lineDashOffset = -time * 17 - index * 9;
        context.strokeStyle = `rgba(216, 198, 237, ${0.72 * pulse})`;
        context.lineWidth = 0.92;
        context.stroke();
        context.setLineDash([]);
      }
    });
    context.restore();
  }

  function updateRipples(time) {
    ripples=ripples.filter(r=>time<=r.start+r.duration);
    if(!reducedMotion && time>=nextRandomRippleAt) {
      const mirror=random()>.5?1:-1;
      addVisibleTangentRipple(mirror*(-.45+random()*.12),.15+random()*.24,'auto',0,.8+random()*.12);
      addVisibleTangentRipple(mirror*(.38+random()*.12),.5+random()*.18,'auto',.85,.76);
      nextRandomRippleAt=time+7.2+random()*1.8;
    }
    if(!reducedMotion && time>=nextAmbientRippleAt) {
      addVisibleTangentRipple(0,.36,'ambient',0,.72);nextAmbientRippleAt=time+13.5;
    }
    activeRippleFronts.length=0;
    for(const r of ripples) {
      const raw=(time-r.start)/r.duration;
      r.fade=raw<0?0:Math.pow(Math.max(0,1-raw),.75)*smoothstep(0,.095,raw)*r.strength;
      if(r.fade<=.0001) continue;
      r.angle=.012+Math.max(0,raw)*r.maximumAngle;
      r.chordRadius=2*Math.sin(r.angle*.5);
      r.chordSpeed=Math.cos(r.angle*.5)*r.maximumAngle/r.duration;
      r.width=r.type==='pointer'?.032:.037;
      activeRippleFronts.push(r);
    }
  }
  function drawRipples(time,metrics,rotation) {
    context.save();context.globalCompositeOperation='screen';context.lineCap='round';
    for(const r of activeRippleFronts) {
      if(!r.drawRing) continue;
      const cos=Math.cos(r.angle),sin=Math.sin(r.angle);
      for(let i=0;i<r.ring.length;i++) {
        const b=bearings[i],p=r.ring[i];
        p.x=r.source.x*cos+(r.east.x*b.c+r.north.x*b.s)*sin;
        p.y=r.source.y*cos+(r.east.y*b.c+r.north.y*b.s)*sin;
        p.z=r.source.z*cos+(r.east.z*b.c+r.north.z*b.s)*sin;
      }
      traceProjectedPath(r.ring,metrics,rotation);
      context.lineWidth=3.4;context.strokeStyle=`rgba(${RIPPLE_COLOR},${r.fade*.085})`;context.stroke();
      context.lineWidth=.86;context.strokeStyle=`rgba(${RIPPLE_HIGHLIGHT},${r.fade*.62})`;context.stroke();
    }
    context.restore();
  }
  function rippleEnergyAt(building) {
    let energy=0;
    for(const r of activeRippleFronts) {
      const dot=clamp(building.x*r.source.x+building.y*r.source.y+building.z*r.source.z,-1,1);
      const distance=Math.sqrt(Math.max(0,2-2*dot));
      const passed=r.chordRadius-building.responseDelay*r.chordSpeed-distance;
      if(passed < -r.width*3 || passed>r.chordSpeed*building.responseRelease*5) continue;
      const ridge=Math.exp(-((passed/r.width)**2));
      const tail=passed>0?Math.exp(-passed/(r.chordSpeed*building.responseRelease))*smoothstep(0,r.width,passed):0;
      energy+=(ridge*.9+tail*.3)*r.fade;
    }
    return 1.15*(1-Math.exp(-energy*1.7));
  }
  function tracePolygon(c,points) {
    c.beginPath();c.moveTo(points[0].x,points[0].y);
    for(let i=1;i<points.length;i++) c.lineTo(points[i].x,points[i].y);
    c.closePath();
  }
  function prepareBuildings(metrics) {
    visibleBuildings.length=0;visibleFaces.length=0;
    const cos=Math.cos(globeRotation),sin=Math.sin(globeRotation);
    for(const b of buildings) {
      projectVertex(b,metrics,cos,sin,b.projected);
      b.visible=false;
      if(b.projected.facing<=.003 || b.projected.x < -150 || b.projected.x>sceneWidth+150 || b.projected.y>sceneHeight+260) {
        b.response*=Math.exp(-frameDelta);continue;
      }
      const growth=reducedMotion?1:easeOutCubic((currentTime-b.delay)/1.5);
      if(growth===0) continue;
      const target=rippleEnergyAt(b);
      b.response+=(target-b.response)*(1-Math.exp(-frameDelta*(target>b.response?11:1/b.responseRelease)));
      let hover=0;
      if(pointer.source && pointer.strength>.001) {
        const dot=b.x*pointer.source.x+b.y*pointer.source.y+b.z*pointer.source.z;
        hover=Math.exp(-Math.max(0,2-2*dot)/.014)*pointer.strength;
      }
      b.rise=clamp(b.response*.16+hover*.04,0,.21);
      const height=b.height*growth*(1+b.rise);
      const dx=(b.projected.x-metrics.centerX)/(sceneWidth*.35);
      const dy=(b.projected.y-sceneHeight*.73)/(sceneHeight*.27);
      const focal=Math.exp(-(dx*dx+dy*dy)*1.6);
      b.illumination=clamp(b.response*.82+hover*.12,0,1);
      b.alpha=smoothstep(.003,.19,b.projected.facing)*growth;
      b.visible=true;visibleBuildings.push(b);
      for(const v of b.vertices) {
        worldVertex.x=v.x+b.x*height*v.level;
        worldVertex.y=v.y+b.y*height*v.level;
        worldVertex.z=v.z+b.z*height*v.level;
        projectVertex(worldVertex,metrics,cos,sin,v.projected);
      }
      for(const v of b.shadow) projectVertex(v,metrics,cos,sin,v.projected);
      for(const face of b.faces) {
        if(polygonArea(face.points)>=-.03) continue;
        let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity,depth=0;
        for(const p of face.points) {
          minX=Math.min(minX,p.x);minY=Math.min(minY,p.y);maxX=Math.max(maxX,p.x);maxY=Math.max(maxY,p.y);depth+=p.facing;
        }
        if(maxX<0 || minX>sceneWidth || maxY<0 || minY>sceneHeight) continue;
        face.minX=minX;face.minY=minY;face.maxX=maxX;face.maxY=maxY;face.depth=depth/face.points.length;
        const n=face.normal,nx=n.x*cos+n.z*sin,nz=n.z*cos-n.x*sin;
        const light=clamp(nx*(-.38)+n.y*.86+nz*.34,0,1);
        const energy=face.roof
          ?.12+light*.22+focal*.19+b.illumination*.35+b.tone
          :.06+light*.5+focal*.065+b.illumination*.11;
        face.color=PALETTE[Math.round(clamp(energy,0,1)*95)][face.roof?'top':'side'];
        face.alpha=b.alpha;visibleFaces.push(face);
      }
    }
    // Faces, including separate podium/courtyard parts, share one camera-depth order.
    visibleFaces.sort((a,b)=>a.depth-b.depth || a.building.id-b.building.id);
  }
  function drawBuildings() {
    for(const b of visibleBuildings) {
      context.globalAlpha=b.alpha*.16;context.fillStyle='#070b23';
      tracePolygon(context,b.shadowPoints);context.fill();
    }
    const updateBloom=bloomFrame%(qualityTier>0?3:2)===0 || bloomFrame===1;
    if(updateBloom) clearLayer(layers.bloom);
    const glow=layers.bloom.context;
    for(const face of visibleFaces) {
      context.globalAlpha=face.alpha;context.fillStyle=face.color;
      tracePolygon(context,face.points);context.fill();
      if(face.roof && face.building.illumination>.13) {
        context.strokeStyle=`rgba(${RIPPLE_COLOR},${face.building.illumination*.16})`;
        context.lineWidth=.48;context.stroke();
      }
      if(updateBloom) {
        // Opaque dark faces occlude farther emissive roofs in the bloom buffer.
        glow.globalAlpha=1;glow.fillStyle='#000';tracePolygon(glow,face.points);glow.fill();
        if(face.roof && face.building.illumination>.13) {
          glow.strokeStyle=`rgba(${RIPPLE_COLOR},${face.alpha*face.building.illumination*.48})`;
          glow.lineWidth=1.05;glow.stroke();
        }
      }
    }
    context.globalAlpha=1;
    if(updateBloom) {
      clearLayer(layers.bloomSoft);
      blit(layers.bloomSoft.context,layers.bloom,qualityTier>0?1:1.5);
    }
    blit(context,layers.bloomSoft,0,.42,'screen');
  }
  function drawHorizonAtmosphere(metrics) {
    context.save();context.globalCompositeOperation='screen';
    context.translate(metrics.centerX,metrics.horizonY+sceneHeight*.035);
    context.scale(1,.32);
    const radius=Math.max(sceneWidth*.63,500);
    const fog=context.createRadialGradient(0,0,0,0,0,radius);
    fog.addColorStop(0,'rgba(145,111,193,0.033)');fog.addColorStop(.45,'rgba(122,96,168,0.012)');fog.addColorStop(1,'rgba(80,60,130,0)');
    context.fillStyle=fog;context.beginPath();context.arc(0,0,radius,0,TWO_PI);context.fill();context.restore();
  }
  function drawFocalPool(metrics) {
    context.save();
    context.beginPath();
    context.arc(metrics.centerX, metrics.centerY, metrics.radius, 0, TWO_PI);
    context.clip();
    context.globalCompositeOperation = "screen";
    context.translate(metrics.centerX, sceneHeight * 0.72);
    context.scale(1, 0.46);
    const radius = Math.max(sceneWidth * 0.3, 320);
    const pool = context.createRadialGradient(0, 0, 0, 0, 0, radius);
    pool.addColorStop(0, "rgba(161, 124, 214, 0.052)");
    pool.addColorStop(0.44, "rgba(127, 92, 183, 0.024)");
    pool.addColorStop(1, "rgba(82, 50, 139, 0)");
    context.fillStyle = pool;
    context.beginPath();
    context.arc(0, 0, radius, 0, TWO_PI);
    context.fill();
    context.restore();
  }

  function drawHorizonDust(time, metrics) {
    const horizonTop = metrics.centerY - metrics.radius;
    context.save();
    context.globalCompositeOperation = "screen";
    horizonDust.forEach((dust) => {
      const normalizedX = dust.x * 2 - 1;
      const arcOffset = metrics.radius - Math.sqrt(
        Math.max(0, metrics.radius * metrics.radius - normalizedX * normalizedX * sceneWidth * sceneWidth * 0.24)
      );
      const x = dust.x * sceneWidth + Math.sin(time * 0.16 + dust.phase) * 8;
      const y = horizonTop + arcOffset + dust.offset * sceneHeight;
      const flicker = 0.65 + Math.sin(time * 0.72 + dust.phase) * 0.25;
      context.beginPath();
      context.fillStyle = `rgba(184, 164, 212, ${dust.alpha * flicker})`;
      context.arc(x, y, dust.size, 0, TWO_PI);
      context.fill();
    });
    context.restore();
  }

  function drawForegroundShade() {
    const shade = context.createLinearGradient(0, sceneHeight * 0.68, 0, sceneHeight);
    shade.addColorStop(0, "rgba(5, 8, 28, 0)");
    shade.addColorStop(1, "rgba(4, 8, 27, 0.27)");
    context.fillStyle = shade;
    context.fillRect(0, sceneHeight * 0.64, sceneWidth, sceneHeight * 0.36);
  }

  function applyDepthOfField(metrics) {
    outputContext.clearRect(0,0,sceneWidth,sceneHeight);
    blit(outputContext,layers.scene);
    if(!layeredDof || qualityTier>=2) return;
    // A single downsampled image is the low-pass lens layer. Its continuous mask
    // leaves the middle sharp without classifying buildings into abrupt bands.
    const layer=layers.dof;clearLayer(layer);const c=layer.context;
    blit(c,layers.scene);
    c.globalCompositeOperation='destination-in';
    const horizon=clamp(metrics.horizonY/sceneHeight,0,.7);
    const mask=c.createLinearGradient(0,0,0,sceneHeight);
    mask.addColorStop(0,'rgba(0,0,0,0)');
    mask.addColorStop(Math.max(0,horizon-.075),'rgba(0,0,0,0)');
    mask.addColorStop(horizon+.015,qualityTier===0?'rgba(0,0,0,.5)':'rgba(0,0,0,0)');
    mask.addColorStop(Math.min(.855,horizon+.14),'rgba(0,0,0,0)');
    mask.addColorStop(.87,'rgba(0,0,0,0)');
    mask.addColorStop(.94,'rgba(0,0,0,.2)');
    mask.addColorStop(1,'rgba(0,0,0,.62)');
    c.fillStyle=mask;c.fillRect(0,0,sceneWidth,sceneHeight);
    c.globalCompositeOperation='source-over';
    blit(outputContext,layer);
  }
  function renderBackground() {
    clearLayer(layers.base);context=layers.base.context;
    const metrics=sceneMetrics();
    drawSpace(0,metrics);drawGlobe(metrics);drawHorizonAtmosphere(metrics);
    drawHorizonDust(0,metrics);drawFocalPool(metrics);
    context=layers.scene.context;
  }
  function renderScene() {
    if(!outputContext || destroyed) return;
    const begin=performance.now();
    if(reducedMotion) globeRotation=INITIAL_ROTATION;
    else globeRotation=INITIAL_ROTATION+currentTime*.018;
    updateRipples(currentTime);
    const metrics=sceneMetrics();
    clearLayer(layers.scene);context=layers.scene.context;bloomFrame++;
    blit(context,layers.base);
    drawSurfaceGrid(metrics,globeRotation);drawRoads(currentTime,metrics,globeRotation);
    prepareBuildings(metrics);drawRipples(currentTime,metrics,globeRotation);drawBuildings();
    drawForegroundShade();applyDepthOfField(metrics);
    const duration=performance.now()-begin;
    renderAverage=renderAverage?renderAverage*.96+duration*.04:duration;
    renderCount++;
    if(!reducedMotion && renderCount>30) {
      slowFrames=renderAverage>1000/targetFps*.86?slowFrames+1:Math.max(0,slowFrames-2);
      if(slowFrames>45) {
        slowFrames=0;
        if(qualityTier<2) {qualityTier++;resizeCanvas(true);}
        else if(targetFps>30) {targetFps=30;clock.setFps(30);}
      }
    }
  }
  function requestFrame() {
    if(!frameId && !reducedMotion && !document.hidden && !destroyed) frameId=window.requestAnimationFrame(drawFrame);
  }
  function drawFrame(timestamp) {
    frameId=0;
    if(destroyed || document.hidden || reducedMotion) return;
    const dt=clock.tick(timestamp);
    if(dt!==null) {
      frameDelta=dt;currentTime+=dt;
      if(touchReleaseAt && currentTime>touchReleaseAt) {pointer.targetStrength=0;touchReleaseAt=0;}
      const follow=1-Math.exp(-dt*4);
      pointer.x+=(pointer.targetX-pointer.x)*follow;pointer.y+=(pointer.targetY-pointer.y)*follow;
      pointer.strength+=(pointer.targetStrength-pointer.strength)*(1-Math.exp(-dt*4.4));
      renderScene();
    }
    requestFrame();
  }
  function hitTest(x,y) {
    for(let i=visibleFaces.length-1;i>=0;i--) {
      const f=visibleFaces[i];
      if(f.alpha<.3 || x<f.minX || x>f.maxX || y<f.minY || y>f.maxY) continue;
      if(containsPoint(f.points,x,y)) return f.building;
    }
    return null;
  }
  function pointFromEvent(event) {
    if(event.target?.closest?.('button, a') || reducedMotion) return null;
    const rect=root.getBoundingClientRect();
    pointer.targetX=event.clientX-rect.left;pointer.targetY=event.clientY-rect.top;
    return hitTest(pointer.targetX,pointer.targetY);
  }
  function activate(source,touch=false) {
    if(!source) {pointer.targetStrength=0;return;}
    pointer.source=source;pointer.targetStrength=1;lastHitId=source.id;
    const travel=Math.hypot(pointer.targetX-lastPointerRippleX,pointer.targetY-lastPointerRippleY);
    if(currentTime-lastPointerRippleAt>.65 && (travel>48 || touch)) {
      addRipple(source.longitude,source.latitude,'pointer',0,1.02);
      lastPointerRippleAt=currentTime;lastPointerRippleX=pointer.targetX;lastPointerRippleY=pointer.targetY;
    }
    if(touch) touchReleaseAt=currentTime+.75;
  }
  function handlePointerMove(event) { if(event.pointerType!=='touch') activate(pointFromEvent(event)); }
  function handlePointerDown(event) { if(event.pointerType==='touch') activate(pointFromEvent(event),true); }
  function handlePointerLeave() {pointer.targetStrength=0;}
  function excite() {if(!reducedMotion) addVisibleTangentRipple(0,.36,'pointer',0,1);}
  function handleVisibility() {
    window.cancelAnimationFrame(frameId);frameId=0;clock.reset();
    pointer.targetStrength=pointer.strength=0;
    requestFrame();
  }
  function setReducedMotion(value) {
    reducedMotion=value;window.cancelAnimationFrame(frameId);frameId=0;clock.reset();
    if(value) {ripples=[];for(const b of buildings) b.response=0;pointer.strength=pointer.targetStrength=0;}
    renderScene();requestFrame();
  }
  function destroy() {
    destroyed=true;window.cancelAnimationFrame(frameId);window.cancelAnimationFrame(resizeFrame);
    resizeObserver?.disconnect();window.removeEventListener('resize',scheduleResize);
    document.removeEventListener('visibilitychange',handleVisibility);
    for(const layer of Object.values(layers)) {layer.canvas.width=1;layer.canvas.height=1;}
  }
  function getDiagnostics() {
    return {buildings:buildings.length,visibleBuildings:visibleBuildings.length,visibleFaces:visibleFaces.length,
      types:buildings.reduce((all,b)=>(all[b.type]=(all[b.type]||0)+1,all),{}),
      targetFps,renderAverageMs:Number(renderAverage.toFixed(2)),renderCount,pixelRatio,qualityTier,
      currentTime,activeRipples:activeRippleFronts.length,visibleRings:activeRippleFronts.filter(r=>r.drawRing).length,
      maxRise:Math.max(0,...visibleBuildings.map(b=>b.rise)),lastHitId,
      sampleRoofs:visibleFaces.filter(f=>f.roof && f.alpha>.9).slice(-60).map(f=>({
        id:f.building.id,x:f.points.reduce((v,p)=>v+p.x,0)/4,y:f.points.reduce((v,p)=>v+p.y,0)/4}))};
  }
  resizeCanvas();
  if('ResizeObserver' in window) {
    resizeObserver=new ResizeObserver(scheduleResize);resizeObserver.observe(root);
    const content=root.querySelector?.('.intro-content');
    if(content) resizeObserver.observe(content);
  }
  else window.addEventListener('resize',scheduleResize,{passive:true});
  document.addEventListener('visibilitychange',handleVisibility);
  return {handlePointerMove,handlePointerDown,handlePointerLeave,excite,setReducedMotion,destroy,getDiagnostics};
}
