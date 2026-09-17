<template>
  <div class="postprocess-layout">
    <aside class="tool-panel">
      <p class="eyebrow">IMAGE LAB / 图像实验室</p><h2>让规划图更清晰。</h2>
      <p class="muted intro-copy">上传已有规划图，修复颜色噪声与细小轮廓缺陷。原图独立保留，修改可随时对比。</p>
      <label class="upload-zone" :class="{ 'is-dragging': dragging }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="onDrop">
        <AppIcon name="upload" /><strong>{{ file ? file.name : '选择或拖入规划图' }}</strong>
        <span>{{ file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · 点击重新选择` : 'PNG · 最大 12 MB / 419 万像素' }}</span>
        <input ref="fileInput" type="file" accept="image/png,.png" aria-label="选择 PNG 规划图" :disabled="pending || submitting" @change="choose($event.target.files?.[0])" />
      </label>
      <label class="field">方案名称<input v-model="title" maxlength="120" placeholder="例如：住宅街区 · 方案 A" :disabled="pending" /></label>
      <label class="field">处理策略<select v-model="preset" :disabled="pending"><option value="balanced">标准修复 · 推荐</option><option value="conservative">保守修复 · 保留复杂轮廓</option><option value="color_only">仅清理颜色 · 保留原轮廓</option></select></label>
      <p class="micro-copy">{{ presetCopy }}</p>
      <label class="check-field"><input type="checkbox" v-model="make3d" :disabled="pending" /> 同时创建三维示意</label>
      <button class="primary-button full-width" :disabled="!file || pending || submitting || !online" @click="submit"><AppIcon :name="pending ? 'refresh' : 'spark'" />{{ submitting ? '正在上传…' : pending ? '正在处理…' : '开始后处理' }}</button>
      <div v-if="job && pending" class="job-status" role="status"><span class="status-dot working"></span><div><strong>{{ job.stage }}</strong><small>任务已保存，可以切换分区。</small></div></div>
      <div v-if="error || uploadError" class="inline-alert" role="alert">{{ error || uploadError }}<button v-if="job && job.status !== 'failed' && !pending && error" class="text-button" @click="resume">恢复查询</button></div>
      <p v-if="!online" class="micro-copy">后端连接恢复后即可处理，文件选择可先完成。</p>
      <div class="tool-footnote"><AppIcon name="info" /><p>自动识别图中颜色，不绑定住宅区色板。稳定的分色可能代表不同高度，将保留供复核。</p></div>
    </aside>
    <section class="lab-preview">
      <ResultViewer v-if="output" :key="output.id" :result="output" initial-mode="compare" @updated="updateOutput" @delete="$emit('delete', $event)" />
      <template v-else>
        <div class="canvas-toolbar"><strong>图像检查</strong><span class="muted">{{ file ? '原始图像' : '等待导入' }}</span></div>
        <div class="upload-preview-body">
          <img v-if="preview" :src="preview" alt="待处理的原始规划图" class="uploaded-preview" />
          <div v-else class="lab-empty"><div class="layer-illustration" aria-hidden="true"><i></i><i></i><i></i></div><h3>每一次修复，都有迹可循。</h3><p>在这里查看原图与处理结果，<br />检查轮廓、分色及需要人工复核的区域。</p><div class="quiet-tags"><span>原图保留</span><span>颜色自适应</span><span>质量报告</span></div></div>
        </div>
        <div class="canvas-caption"><span>01 导入图片</span><span>02 修复与检查</span><span>03 保存到方案库</span></div>
      </template>
    </section>
  </div>
</template>
<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
import ResultViewer from './ResultViewer.vue';
import { request, readLocal, writeLocal } from '../api';
import { useJob } from '../composables/useJob';
const props = defineProps({ online: Boolean, removedId: String });
const emit = defineEmits(['saved', 'delete']);
const file = ref(null), preview = ref(''), title = ref(''), preset = ref('balanced'), make3d = ref(true);
const dragging = ref(false), submitting = ref(false), uploadError = ref(''), output = ref(null), fileInput = ref(null);
const { job, pending, error, track, resume } = useJob('ud:upload-job', async data => {
  output.value = data.result; uploadError.value = data.warning || ''; writeLocal('ud:last-upload', data.result.id); emit('saved', data.result);
});
const presetCopy = computed(() => ({balanced:'修整直线轮廓与零碎色块，同时保留可信曲线和稳定分色。',conservative:'仅做小范围局部修补，适合曲线较多或存在细小构筑物的图。',color_only:'仅处理颜色噪声，不改建筑外轮廓与间距。'})[preset.value]);
function choose(value) {
  if (!value || pending.value || submitting.value) return;
  uploadError.value = '';
  if (!/\.png$/i.test(value.name) || value.size > 12 * 1024 * 1024) { uploadError.value = '请选择不超过 12 MB 的 PNG 图片。'; return; }
  if (preview.value) URL.revokeObjectURL(preview.value);
  file.value = value; preview.value = URL.createObjectURL(value); title.value = value.name.replace(/\.png$/i, '').slice(0,120); output.value = null;
  writeLocal('ud:last-upload', null);
}
function onDrop(e) { dragging.value = false; choose(e.dataTransfer.files?.[0]); }
async function submit() {
  if (!file.value || submitting.value || pending.value) return;
  submitting.value = true; uploadError.value = ''; error.value = '';
  const data = new FormData(); data.append('file', file.value); data.append('title', title.value); data.append('preset', preset.value); data.append('make_3d', String(make3d.value));
  try { track(await request('/jobs/postprocess', { method: 'POST', body: data, timeout: 60000 })); }
  catch (e) { uploadError.value = e.message; }
  finally { submitting.value = false; }
}
function updateOutput(value) { output.value = value; emit('saved', value); }
watch(() => props.removedId, id => { if (id === output.value?.id) { output.value = null; writeLocal('ud:last-upload', null); } });
onMounted(async () => { if (!resume()) { const id = readLocal('ud:last-upload'); if (id) { try { output.value = await request(`/results/${id}`); } catch { writeLocal('ud:last-upload', null); } } } });
onBeforeUnmount(() => { if (preview.value) URL.revokeObjectURL(preview.value); });
</script>
