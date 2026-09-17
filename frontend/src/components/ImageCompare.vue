<template>
  <div class="image-compare">
    <div class="compare-stage" @pointerdown="startDrag" @pointermove="drag" @pointerup="stopDrag" @pointercancel="stopDrag" :style="{ aspectRatio: ratio }">
      <img :src="assetUrl(after)" alt="后处理后的规划图" @load="loaded" @error="failed = true" />
      <img class="compare-before" :src="assetUrl(before)" alt="处理前的原始规划图" :style="{ clipPath: `inset(0 ${100-position}% 0 0)` }" @error="failed = true" />
      <div class="compare-divider" :style="{ left: `${position}%` }"><span>‹ ›</span></div>
      <span class="compare-tag before-tag">处理前</span><span class="compare-tag after-tag">处理后</span>
      <p v-if="failed" class="image-error">图片暂不可用，请刷新或检查后端连接。</p>
    </div>
    <label class="compare-control"><span>拖动对比</span><input v-model="position" type="range" min="0" max="100" aria-label="处理前后对比分隔位置" /><output>{{ position }}%</output></label>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue';
import { assetUrl } from '../config';
const props = defineProps({ before: String, after: String });
const position = ref(50), ratio = ref(1), failed = ref(false);
let dragging = false;
function updatePosition(event) { const box = event.currentTarget.getBoundingClientRect(); position.value = Math.round(Math.max(0, Math.min(100, (event.clientX - box.left) / box.width * 100))); }
function startDrag(event) { if(event.button !== 0)return; dragging = true; event.currentTarget.setPointerCapture(event.pointerId); updatePosition(event); }
function drag(event) { if(dragging)updatePosition(event); }
function stopDrag() { dragging = false; }
function loaded(e) { ratio.value = e.target.naturalWidth / e.target.naturalHeight; }
watch(() => [props.before, props.after], () => { failed.value = false; position.value = 50; });
</script>
<style scoped>
.image-compare{width:100%;max-width:900px;margin:auto}.compare-stage{position:relative;touch-action:pan-y;cursor:ew-resize;background:#f5f5f3;overflow:hidden;border-radius:8px;max-height:60vh;margin:auto}.compare-stage img{user-select:none;-webkit-user-drag:none;width:100%;height:100%;object-fit:contain;display:block}.compare-before{position:absolute;inset:0}.compare-divider{position:absolute;top:0;bottom:0;width:2px;background:#8b6eda;pointer-events:none}.compare-divider span{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:#fff;color:#503a85;box-shadow:0 2px 12px #0003;border-radius:24px;padding:9px;white-space:nowrap;font-weight:700}.compare-tag{position:absolute;top:12px;background:#171b27de;color:#fff;padding:5px 10px;font-size:11px;border-radius:4px}.before-tag{left:12px}.after-tag{right:12px}.compare-control{display:flex;align-items:center;gap:16px;color:var(--muted);font-size:12px;padding:18px 0 4px}.compare-control input{flex:1;min-width:0;accent-color:#ab94e8}.compare-control output{width:40px;text-align:right;font-variant-numeric:tabular-nums}.image-error{position:absolute;inset:35% 10%;color:#783029;background:#fff;padding:20px;}
</style>
