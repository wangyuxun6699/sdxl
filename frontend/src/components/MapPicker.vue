<template>
  <dialog ref="dialog" class="map-dialog" @cancel.prevent="$emit('close')" @click="backdrop">
    <header class="dialog-heading"><div><p class="eyebrow">STUDY AREA</p><h2>定义研究范围</h2></div><button class="icon-button" aria-label="关闭范围选择" @click="$emit('close')"><AppIcon name="close" /></button></header>
    <div class="map-dialog-body"><aside class="map-settings"><h3>在地图上圈选</h3><p class="muted">点击添加边界点，再点击完成。可拖动地图、滚轮缩放。</p><div class="action-row"><button class="secondary-button compact" @click="undo" :disabled="!points.length || closed">撤销点</button><button class="primary-button compact" @click="finish" :disabled="points.length < 3 || closed">完成圈选</button></div><p class="map-selection-status" role="status">{{ closed ? `已记录 ${points.length} 个边界点` : points.length ? `已添加 ${points.length} 点` : '尚未设置范围' }}</p><button class="text-button" @click="clear" :disabled="!points.length">清空并重绘</button>
      <div class="section-divider"></div><h3>或输入坐标范围</h3><p class="micro-copy">底图不可用时，也可用经纬度矩形记录范围。</p><form @submit.prevent="applyBounds"><div class="bbox-fields"><label v-for="field in bboxFields" :key="field.key" class="field">{{ field.label }}<input v-model="bounds[field.key]" type="number" step="any" :min="field.lat ? -85 : -180" :max="field.lat ? 85 : 180" required :placeholder="field.lat ? '纬度' : '经度'" /></label></div><button class="secondary-button full-width compact" type="submit">应用坐标</button></form><p v-if="coordinateError" class="inline-alert" role="alert">{{ coordinateError }}</p>
      <div class="tool-footnote"><AppIcon name="info" /><p>范围会随生成任务保存。目前仅记录研究边界，尚不约束模型生成的建筑位置。</p></div>
    </aside><section class="map-viewport"><div ref="container" class="map-container"></div><div v-if="loading" class="map-state" role="status"><div class="loader"></div><strong>正在载入底图</strong><span>地图模块按需加载</span></div><div v-if="mapError" class="map-error-note" role="alert"><strong>底图暂不可用</strong><p>{{ mapError }}</p><button class="secondary-button compact" @click="retry" :disabled="loading">重试底图</button></div><div class="map-overlay-label">WGS 84 · 研究范围</div></section></div>
    <footer class="dialog-footer"><span>{{ closed ? '边界已保存在本次研究草稿中' : '可关闭后继续，已录入坐标会保留' }}</span><button class="primary-button" @click="$emit('close')">返回工作台<AppIcon name="arrow" /></button></footer>
  </dialog>
</template>
<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue';
import AppIcon from './AppIcon.vue';
const props = defineProps({ range: Object });
const emit = defineEmits(['update:range', 'close']);
const dialog = ref(null), container = ref(null), loading = ref(false), mapError = ref(''), coordinateError = ref('');
const points = ref(props.range?.points ? [...props.range.points] : []), closed = ref(Boolean(props.range?.closed));
const bounds = reactive({ west: props.range?.bbox?.west ?? '', south: props.range?.bbox?.south ?? '', east: props.range?.bbox?.east ?? '', north: props.range?.bbox?.north ?? '' });
const bboxFields = [{key:'west',label:'西侧经度'},{key:'east',label:'东侧经度'},{key:'south',label:'南侧纬度',lat:true},{key:'north',label:'北侧纬度',lat:true}];
let C, viewer, handler, disposed = false, tileTimer, removeTileError, removeProgress, removeRenderError;
function backdrop(e) { if(e.target === dialog.value) emit('close'); }
function rangeOf(list) { const lngs = list.map(p=>p.lng), lats = list.map(p=>p.lat); return { points: list.map((p,i)=>({...p,order:i})), closed:true, bbox:{west:Math.min(...lngs),east:Math.max(...lngs),south:Math.min(...lats),north:Math.max(...lats)} }; }
function clear() { points.value = []; closed.value = false; emit('update:range',null); draw(); }
function undo() { points.value.pop(); draw(); }
function finish() { if(points.value.length < 3) return; const range = rangeOf(points.value); closed.value = true; Object.assign(bounds,range.bbox); emit('update:range',range); draw(); }
function applyBounds() {
  coordinateError.value = '';
  const {west:w,east:e,south:s,north:n} = Object.fromEntries(Object.entries(bounds).map(([k,v])=>[k,v===''?NaN:Number(v)]));
  if(![w,e,s,n].every(Number.isFinite) || w < -180 || e > 180 || s < -85 || n > 85 || w >= e || s >= n) { coordinateError.value = '请填写有效坐标：西经度小于东经度，南纬度小于北纬度。'; return; }
  points.value = [{lng:w,lat:s},{lng:e,lat:s},{lng:e,lat:n},{lng:w,lat:n}]; finish(); focus(rangeOf(points.value).bbox);
}
function focus(b) { if(viewer && !viewer.isDestroyed()) viewer.camera.setView({ destination:C.Rectangle.fromDegrees(b.west-.005,b.south-.005,b.east+.005,b.north+.005) }); }
function draw() {
  if(!viewer || viewer.isDestroyed()) return;
  viewer.entities.removeAll(); const positions = points.value.map(p=>C.Cartesian3.fromDegrees(p.lng,p.lat));
  positions.forEach((position,i)=>viewer.entities.add({position,point:{pixelSize:8,color:C.Color.fromCssColorString('#a991f2'),outlineColor:C.Color.WHITE,outlineWidth:2},label:{text:String(i+1),font:'12px sans-serif',pixelOffset:new C.Cartesian2(0,-17),showBackground:true}}));
  if(positions.length>1) viewer.entities.add({polyline:{positions:closed.value?[...positions,positions[0]]:positions,width:2,material:C.Color.fromCssColorString('#ac95f4')}});
  if(positions.length>2) viewer.entities.add({polygon:{hierarchy:positions,material:C.Color.fromCssColorString('#a991f2').withAlpha(.18)}});
  viewer.scene.requestRender();
}
function destroy() { clearTimeout(tileTimer); removeTileError?.();removeProgress?.();removeRenderError?.();removeTileError=removeProgress=removeRenderError=null; handler?.destroy();handler=null;if(viewer && !viewer.isDestroyed()) viewer.destroy();viewer=null; }
async function init() {
  if(loading.value || disposed) return;
  loading.value = true; mapError.value = '';
  try {
    const [module] = await Promise.all([import('cesium'), import('cesium/Build/Cesium/Widgets/widgets.css')]); C = module;
    if(disposed) return;
    const tileUrl = import.meta.env.VITE_MAP_TILE_URL;
    const provider = tileUrl ? new C.UrlTemplateImageryProvider({url:tileUrl,credit:import.meta.env.VITE_MAP_ATTRIBUTION || '配置的地图服务'}) : new C.OpenStreetMapImageryProvider({url:'https://tile.openstreetmap.org/'});
    viewer = new C.Viewer(container.value,{sceneMode:C.SceneMode.SCENE2D,baseLayer:new C.ImageryLayer(provider),baseLayerPicker:false,animation:false,timeline:false,homeButton:false,geocoder:false,fullscreenButton:false,infoBox:false,navigationHelpButton:false,sceneModePicker:false,selectionIndicator:false,requestRenderMode:true});
    viewer.scene.globe.baseColor = C.Color.fromCssColorString('#202a35');
    viewer.scene.backgroundColor = C.Color.fromCssColorString('#202a35');
    viewer.camera.setView({destination:C.Rectangle.fromDegrees(73,18,136,54)});
    const fail = () => { if(!disposed) mapError.value='地图服务可能无法连接。可重试，或在左侧输入研究区坐标。'; };
    removeTileError = provider.errorEvent.addEventListener(fail);
    removeRenderError = viewer.scene.renderError.addEventListener(()=>{ if(!disposed) mapError.value='当前图形环境无法渲染地图，可在左侧输入坐标。'; });
    tileTimer = setTimeout(fail,20000);
    removeProgress = viewer.scene.globe.tileLoadProgressEvent.addEventListener(count=>{ if(count === 0 && viewer?.imageryLayers.get(0)?.show) clearTimeout(tileTimer); });
    handler = new C.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction(e=>{if(closed.value)return;const v=viewer.camera.pickEllipsoid(e.position,viewer.scene.globe.ellipsoid);if(!v)return;const p=C.Cartographic.fromCartesian(v);points.value.push({lng:Number(C.Math.toDegrees(p.longitude).toFixed(6)),lat:Number(C.Math.toDegrees(p.latitude).toFixed(6))});draw();},C.ScreenSpaceEventType.LEFT_CLICK);
    handler.setInputAction(finish,C.ScreenSpaceEventType.RIGHT_CLICK);
    draw(); if(props.range?.bbox) focus(props.range.bbox);
  } catch { if(!disposed) mapError.value='地图组件或图形环境初始化失败。可输入坐标继续记录范围。'; destroy(); }
  finally { loading.value = false; }
}
function retry() { destroy(); init(); }
onMounted(()=>{dialog.value.showModal();init();});
onBeforeUnmount(()=>{disposed=true;destroy();});
</script>
