<template>
  <section class="result-viewer">
    <header class="canvas-toolbar result-toolbar"><div class="result-heading"><strong>{{ result.title }}</strong><span class="muted">{{ result.source === 'upload' ? '导入方案' : '生成方案' }}</span></div>
      <div class="toolbar-actions"><a class="icon-button" :href="download('cleaned')" title="下载处理后的 PNG" aria-label="下载处理后的 PNG"><AppIcon name="download" /></a><button class="icon-button" @click="editing = !editing" :aria-expanded="editing" title="编辑方案资料" aria-label="编辑方案资料"><AppIcon name="info" /></button></div>
    </header>
    <div v-if="editing" class="result-editor"><label class="field">方案名称<input v-model="title" maxlength="120" /></label><label class="field">研究备注<textarea v-model="notes" rows="2" maxlength="5000" placeholder="记录设计判断或待验证的问题" /></label><div class="action-row"><button class="primary-button compact" @click="save" :disabled="saving || !title.trim()">{{ saving ? '保存中…' : '保存资料' }}</button><button class="text-button danger-text" @click="$emit('delete', result)">删除方案</button></div><p v-if="saveError" class="inline-alert" role="alert">{{ saveError }}</p></div>
    <div class="view-switcher" role="group" aria-label="方案显示模式"><button v-for="tab in tabs" :key="tab.key" :class="{ active: mode === tab.key }" :aria-pressed="mode === tab.key" @click="mode = tab.key"><AppIcon :name="tab.icon" />{{ tab.label }}</button></div>
    <div class="result-stage" :class="{ 'analysis-stage': mode === 'analysis' }">
      <div v-if="mode === 'plan'" class="plan-image-wrap"><img :src="assetUrl(result.image_url)" :alt="result.title + ' 二维规划图'" @error="mediaError = true" /><p v-if="mediaError" class="inline-alert">图片加载失败，请检查后端连接。</p></div>
      <ImageCompare v-else-if="mode === 'compare' && result.original_image_url" :before="result.original_image_url" :after="result.image_url" />
      <div v-else-if="mode === 'compare'" class="small-empty">这份历史方案没有保留处理前的原图。</div>
      <template v-else-if="mode === 'model'"><iframe v-if="result.html_url && result.html_exists" :src="assetUrl(result.html_url)" title="规划方案三维示意" class="model-frame" sandbox="allow-scripts allow-same-origin allow-downloads" /><div v-else class="small-empty"><AppIcon name="cube" /><h3>尚无三维示意</h3><p>导入图片时勾选“同时创建三维示意”即可生成。</p></div></template>
      <template v-else-if="mode === 'review'"><div v-if="report" class="review-split"><figure><img :src="assetUrl(result.review_mask_url)" alt="白色为待人工复核区域，黑色为其余区域" /><figcaption>白色：待人工复核区域</figcaption></figure><figure><img :src="assetUrl(result.regions_url)" alt="颜色区域分割示意，不代表实际建筑高度" /><figcaption>分色区域 · 示意色不代表高度</figcaption></figure></div><div v-else class="small-empty">{{ qualityError || '读取质量报告中…' }}</div></template>
      <section v-else class="analysis-content">
        <div class="analysis-intro"><h3>形态与环境研究</h3><p>基于栅格形态的代理分析。未标定真实尺度与高度时，不作为实际日照时长、风速或规范达标结论。</p></div>
        <div class="analysis-controls"><label class="field">季节<select v-model="analysisInputs.season_profile"><option value="spring">春季</option><option value="summer">夏季</option><option value="autumn">秋季</option><option value="winter">冬季</option></select></label><label class="field">主要风向<select v-model="analysisInputs.primary_wind_direction"><option value="west">西风</option><option value="east">东风</option><option value="north">北风</option><option value="south">南风</option></select></label><button class="primary-button compact" @click="loadAnalysis(true)" :disabled="analysisBusy">{{ analysisBusy ? '计算中…' : '重新分析' }}</button></div>
        <p v-if="analysisError" class="inline-alert" role="alert">{{ analysisError }}</p><p v-if="analysisBusy" class="muted" role="status">正在计算形态代理指标…</p>
        <template v-if="analysis"><div class="analysis-metrics"><div><span>日照暴露指数</span><strong>{{ ratio(analysis.sunlight?.metrics?.mean_exposure) }}</strong></div><div><span>通风代理指数</span><strong>{{ ratio(analysis.wind?.metrics?.mean_speed) }}</strong></div><div><span>相对最佳风向</span><strong>{{ analysis.wind_comparison?.best_label || '—' }}</strong></div></div><div class="review-split"><figure v-if="analysis.sunlight?.image_url"><img :src="assetUrl(analysis.sunlight.image_url)" alt="日照暴露代理分析图" /><figcaption>日照暴露代理图</figcaption></figure><figure v-if="analysis.wind?.image_url"><img :src="assetUrl(analysis.wind.image_url)" alt="通风代理分析图" /><figcaption>通风代理图</figcaption></figure></div></template>
      </section>
    </div>
    <footer class="quality-footer"><div v-if="report" class="quality-metrics"><div><span>轮廓分量</span><strong>{{ number(report.counts.components_after) }}</strong></div><div><span>修整轮廓</span><strong>{{ number(report.counts.footprints_regularized) }}</strong></div><div><span>移除碎片</span><strong>{{ number(report.counts.fragments_removed) }}</strong></div><div><span>待复核像素</span><strong>{{ number(report.counts.review_px) }}</strong></div></div><p class="micro-copy">{{ mode === 'model' ? '三维形态为示意；无高度标定时采用统一示意高度。' : '轮廓分量不等于建筑栋数；多色区域保留供高度关系复核。' }}</p><div class="report-links"><a v-if="report" :href="download('report')">下载质量报告 ↗</a><a v-if="result.original_image_url" :href="download('original')">下载原图 ↗</a><a v-if="mode === 'model' && result.html_exists" :href="download('model')">下载三维 HTML ↗</a><span v-if="qualityError" class="muted">{{ qualityError }}</span></div></footer>
  </section>
</template>
<script setup>
import { ref, watch, onBeforeUnmount } from 'vue';
import AppIcon from './AppIcon.vue';
import ImageCompare from './ImageCompare.vue';
import { assetUrl, API_BASE } from '../config';
import { request, jsonRequest } from '../api';
const props = defineProps({ result: { type: Object, required: true }, initialMode: { type: String, default: 'plan' } });
const emit = defineEmits(['updated', 'delete']);
const mode = ref(props.initialMode), report = ref(null), qualityError = ref(''), editing = ref(false), mediaError = ref(false);
const title = ref(''), notes = ref(''), saving = ref(false), saveError = ref('');
const analysis = ref(null), analysisBusy = ref(false), analysisError = ref('');
const analysisInputs = ref({ season_profile: 'spring', primary_wind_direction: 'west', wind_directions: ['north','east','south','west'] });
const tabs = [{key:'plan',label:'二维图',icon:'image'},{key:'compare',label:'前后对比',icon:'compare'},{key:'model',label:'三维示意',icon:'cube'},{key:'review',label:'修复检查',icon:'layers'},{key:'analysis',label:'形态分析',icon:'chart'}];
let revision = 0;
watch(() => props.result.id, async () => {
  const version = ++revision; report.value = null; analysis.value = null; qualityError.value = ''; analysisError.value = ''; analysisBusy.value = false; mediaError.value = false;
  title.value = props.result.title; notes.value = props.result.notes || '';
  if (props.result.postprocess_report_url) { try { const value = await request(`/results/${props.result.id}/quality`); if (version === revision) report.value = value; } catch(e) { if(version===revision) qualityError.value = e.message; } }
  if (mode.value === 'analysis') loadAnalysis();
}, { immediate: true });
watch(() => props.result.title, value => { title.value = value; });
watch(mode, value => { if (value === 'analysis' && !analysis.value) loadAnalysis(); });
function download(kind) { return `${API_BASE}/results/${props.result.id}/download/${kind}`; }
function number(value) { return Number(value ?? 0).toLocaleString('zh-CN'); }
function ratio(value) { return value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(3); }
async function save() { saving.value = true; saveError.value = ''; try { emit('updated', await request(`/results/${props.result.id}`, jsonRequest('PATCH', { title: title.value, notes: notes.value }))); editing.value = false; } catch(e) { saveError.value = e.message; } finally { saving.value = false; } }
async function loadAnalysis(force = false) {
  if (analysisBusy.value) return;
  const version = revision; analysisBusy.value = true; analysisError.value = '';
  try { const data = await request(`/results/${props.result.id}/analysis`, { ...(force ? jsonRequest('POST', analysisInputs.value) : {}), timeout: 180000 }); if(version===revision) analysis.value = data; }
  catch(e) { if(version===revision) analysisError.value = e.message; }
  finally { if(version===revision) analysisBusy.value = false; }
}
onBeforeUnmount(() => { revision++; });
</script>
