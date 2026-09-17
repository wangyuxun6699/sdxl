import test from 'node:test';
import assert from 'node:assert/strict';
import {buildCity,projectVertex,polygonArea,containsPoint,createFrameClock} from '../src/components/cityGeometry.js';

test('all block types fit their reserved lots without occupying roads', () => {
  for(const [columns,rows] of [[72,52],[62,46],[44,36]]) {
    const city=buildCity(columns,rows),occupied=new Set(),types=new Set();
    for(const b of city.buildings) {
      types.add(b.type);
      for(let r=b.row;r<b.row+b.spanZ;r++) for(let c=b.col;c<b.col+b.spanX;c++) {
        assert(!city.streetRows.has(r) && !city.streetColumns.has(c));
        assert(r<rows && c<columns);
        const key=`${c},${r}`;assert(!occupied.has(key));occupied.add(key);
      }
      for(const v of b.vertices) {
        assert(Math.abs(Math.hypot(v.x,v.y,v.z)-1)<.005);
        assert(Math.abs(v.x*b.x+v.y*b.y+v.z*b.z-b.foundation)<1e-12);
      }
    }
    assert.equal(types.size,4);
  }
});

test('sphere rotation keeps shared roof/facade vertices and finite visible faces', () => {
  const {buildings}=buildCity(44,36);
  const metrics={centerX:720,centerY:1730,radius:1267};
  for(const angle of [0,.48,Math.PI/2,Math.PI,Math.PI*1.8]) {
    let visible=0;
    for(const b of buildings) {
      for(const v of b.vertices) {
        projectVertex({x:v.x+b.x*b.height*v.level,y:v.y+b.y*b.height*v.level,z:v.z+b.z*b.height*v.level},
          metrics,Math.cos(angle),Math.sin(angle),v.projected);
        assert(Number.isFinite(v.projected.x+v.projected.y+v.projected.facing));
      }
      for(const face of b.faces) {
        for(const p of face.points) assert(b.vertices.some(v=>v.projected===p));
        if(polygonArea(face.points)<-.03) {
          visible++;
          const x=face.points.reduce((sum,p)=>sum+p.x,0)/4;
          const y=face.points.reduce((sum,p)=>sum+p.y,0)/4;
          assert(containsPoint(face.points,x,y));
        }
      }
    }
    assert(visible>0);
  }
});

test('frame clock retains cadence on 60/120/144 Hz displays', () => {
  for(const refresh of [60,120,144]) for(const target of [30,60]) {
    const clock=createFrameClock(target);let frames=0,time=0;
    for(let i=0;i<=refresh*5;i++) {
      const dt=clock.tick(i*1000/refresh);
      if(dt!==null){frames++;time+=dt;}
    }
    assert(Math.abs(frames-(target*5+1))<=1,`${target} FPS target on ${refresh} Hz: ${frames}`);
    assert(Math.abs(time-5)<1/target);
    clock.reset();assert.equal(clock.tick(600000),0);
    assert(clock.tick(600100)<=.1);
  }
});
