<template>
  <div class="studio-shell">
    <a class="skip-link" href="#studio-main">跳至工作区</a>
    <header class="studio-header"><button class="studio-brand" @click="$emit('intro')" title="返回城市开场"><span class="brand-bars" aria-hidden="true"><i></i><i></i><i></i></span><span>URBAN DIFFUSION<small>城市规划与空间研究</small></span></button><div class="header-breadcrumb">工作空间 <span>/</span> {{ pages.find(p=>p.key===page)?.label }}</div><div class="header-status"><span class="connection-pill" :class="{online}"><i></i>{{ checking ? '检查连接' : online ? '后端已连接' : '后端未连接' }}</span><button class="icon-button" @click="refresh" :disabled="checking" aria-label="刷新服务与方案" title="刷新服务与方案"><AppIcon name="refresh" /></button></div></header>
    <nav class="app-rail" aria-label="主要功能"><button v-for="item in pages" :key="item.key" :class="{active:page===item.key}" :aria-current="page===item.key?'page':undefined" @click="page=item.key"><AppIcon :name="item.icon"/><span>{{ item.short }}</span></button><button class="rail-home" @click="$emit('intro')"><AppIcon name="home"/><span>开场</span></button></nav>
    <aside class="project-sidebar"><div class="project-head"><p class="eyebrow">URBAN RESEARCH</p><h1>我的规划研究</h1><p class="muted">从空间意图，到可比较的方案。</p></div>
      <button class="new-study secondary-button" @click="newStudy"><AppIcon name="plus"/>新建规划草稿</button>
      <section class="scope-section"><div class="section-title"><h2>研究范围</h2><button class="icon-button" @click="mapOpen=true" aria-label="编辑研究范围"><AppIcon name="map"/></button></div><button class="scope-preview" @click="mapOpen=true" :aria-label="range ? '编辑已记录范围':'选择研究范围'"><svg v-if="range" viewBox="0 0 220 92" aria-hidden="true"><path d="M0 23h220M0 46h220M0 69h220M44 0v92M88 0v92M132 0v92M176 0v92" stroke="#3d43514d"/><polygon :points="rangePolygon" fill="#aa91ef25" stroke="#ac95ec" stroke-width="1.5"/></svg><span v-else class="scope-placeholder"><AppIcon name="map"/><span>圈选地图或录入坐标</span></span><span v-if="range" class="scope-count">{{range.points.length}} 个边界点</span></button><div v-if="range" class="scope-coords"><span>{{ range.bbox.west.toFixed(4) }}° — {{ range.bbox.east.toFixed(4) }}° E</span><button class="text-button" @click="range=null">清除</button></div><p v-else class="micro-copy">可选。记录范围后会附在生成任务中。</p></section>
      <section class="recent-section"><div class="section-title"><h2>最近方案</h2><span class="count-badge">{{results.length}}</span></div><div v-if="results.length" class="recent-list"><button v-for="item in results.slice(0,7)" :key="item.id" class="recent-result" :class="{selected:item.id===activeId}" @click="openResult(item)"><img v-if="item.image_url" :src="assetUrl(item.image_url)" alt="" loading="lazy"/><span><strong>{{item.title}}</strong><small>{{sourceName(item)}} · {{date(item.created_at)}}</small></span></button></div><div v-else class="sidebar-empty"><AppIcon name="layers"/><p>{{ online ? '还没有保存的方案' : '连接后读取已保存方案' }}</p><span>导入或生成后，会在这里归档。</span></div><button v-if="results.length" class="text-button see-all" @click="page='library'">查看全部方案 <AppIcon name="arrow"/></button></section>
      <div class="sidebar-system"><span class="status-dot" :class="capabilities?.generation?.mode==='demo'?'warning':capabilities?.generation?.configured?'online':''"></span><div><strong>{{modelLabel}}</strong><small>{{online ? '图像后处理可独立使用' : '草稿在此浏览器中保留'}}</small></div></div>
    </aside>
    <main id="studio-main" class="studio-main" tabindex="-1">
      <div v-if="!online && !checking" class="connection-banner" role="status"><AppIcon name="info"/><div><strong>后端暂未连接</strong><span>请启动后端后重试；你仍可编辑规划草稿和研究范围。</span></div><button class="text-button" @click="refresh">重新连接</button></div>
      <div v-else-if="resultsError" class="connection-banner" role="alert"><AppIcon name="info"/><span>{{resultsError}}</span><button class="text-button" @click="refresh">重新读取</button></div>
      <div v-if="toast" class="toast" role="status"><AppIcon name="check"/>{{toast}}</div>
      <section v-show="page==='planning'" class="planning-page">
        <div class="page-heading"><div><p class="eyebrow">DESIGN WORKSPACE</p><h2>{{activeResult ? '探索当前方案' : '开始一项新的空间研究'}}</h2></div><button class="secondary-button compact" @click="mapOpen=true"><AppIcon name="map"/>{{range ? "已记录范围" : "研究范围"}}</button></div>
        <div class="planning-layout"><section class="design-canvas"><ResultViewer v-if="activeResult" :key="activeResult.id" :result="activeResult" @updated="upsert" @delete="deleteResult"/><template v-else><div class="canvas-toolbar"><strong>方案画布</strong><span class="canvas-label"><i></i>等待规划方案</span></div><div class="welcome-canvas"><PlanningIllustration/><p class="eyebrow">FROM INTENT TO FORM</p><h3>让下一个方案，有据可循。</h3><p>从已有规划图开始，或描述你的设计目标。<br/>在同一处完成形态修复、方案检查与空间推演。</p><div class="welcome-actions"><button class="primary-button" @click="page='postprocess'"><AppIcon name="upload"/>导入已有规划图</button><button class="text-button" @click="focusPrompt">描述生成目标 <AppIcon name="arrow"/></button></div></div><div class="workflow-strip"><div><span>01</span><strong>定义范围</strong><small>记录研究边界</small></div><div><span>02</span><strong>生成 / 导入</strong><small>建立方案底图</small></div><div><span>03</span><strong>检查与推演</strong><small>比较修复与形态</small></div></div></template></section>
          <aside class="intent-panel"><header class="intent-header"><span class="intent-icon"><AppIcon name="spark"/></span><div><h3>规划助手</h3><p>将设计意图转化为方案</p></div></header><div class="conversation" ref="conversation" aria-live="polite" role="log"><div v-if="!messages.length" class="assistant-welcome"><span class="micro-label">先从一个方向开始</span><p>描述建筑布局、密度和空间关系，让目标更清晰。</p><button v-for="example in examples" :key="example.title" class="prompt-suggestion" @click="applyExample(example.text)"><span>{{example.title}}</span><AppIcon name="plus"/></button><div class="model-note"><AppIcon name="info"/><p>{{capabilities?.generation?.message || '尚未连接后端。可以先编辑你的规划目标。'}}</p></div></div><article v-for="(message,index) in messages" :key="index" class="chat-message" :class="message.role"><span>{{message.role==='user'?'你的目标':'规划助手'}}</span><p>{{message.text}}</p><button v-if="message.resultId" class="text-button" @click="activeId=message.resultId">查看方案 <AppIcon name="arrow"/></button></article></div>
            <div v-if="generationPending" class="generation-status" role="status"><div class="loader small"></div><span>{{generationJob?.stage || '等待处理'}}</span></div><div v-if="generationError || submitError" class="inline-alert" role="alert">{{generationError || submitError}}<button v-if="generationError && generationJob?.status !== 'failed' && !generationPending" class="text-button" @click="resumeGeneration">恢复查询</button></div>
            <form class="composer" @submit.prevent="submit"><label class="sr-only" for="planning-prompt">规划目标</label><textarea id="planning-prompt" ref="promptInput" v-model="prompt" maxlength="6000" rows="4" placeholder="例如：设计一处围合式住宅街区，沿街布置中低层建筑，中心保留开敞空间…" :disabled="generationPending || sending" @keydown="promptKeydown"/><div class="composer-bottom"><span>{{range ? `附带 ${range.points.length} 点范围` : '草稿自动保存'}}</span><button class="primary-button compact" type="submit" :disabled="!prompt.trim() || !canGenerate || generationPending || sending" :title="!canGenerate?'生成模型未配置，可先导入图片':'发送规划目标'"><AppIcon name="arrow"/>{{sending?'提交中':'发送'}}</button></div><small>Enter 发送 · Shift + Enter 换行</small></form>
          </aside>
        </div>
      </section>
      <section v-show="page==='postprocess'" class="postprocess-page"><div class="page-heading"><div><p class="eyebrow">REFINE & REVIEW</p><h2>图像后处理</h2></div><span class="small-label">已有 PNG 可直接使用 · 无需生成模型</span></div><PostprocessWorkbench :online="online" :removed-id="removedId" @saved="onUploaded" @delete="deleteResult"/></section>
      <section v-show="page==='library'" class="library-page"><div class="page-heading"><div><p class="eyebrow">SCENARIO LIBRARY</p><h2>方案库 <span class="heading-count">{{results.length}}</span></h2></div><button class="primary-button compact" @click="page='postprocess'"><AppIcon name="upload"/>导入方案</button></div><div class="library-toolbar"><label class="search-field"><AppIcon name="search"/><input v-model="query" type="search" placeholder="搜索名称、类型或备注" aria-label="搜索方案"/></label><label class="sr-only" for="source-filter">来源筛选</label><select id="source-filter" v-model="sourceFilter"><option value="all">所有来源</option><option value="upload">导入图片</option><option value="generated">模型生成</option></select><label class="sr-only" for="sort-order">排序</label><select id="sort-order" v-model="sortOrder"><option value="newest">最近创建</option><option value="oldest">最早创建</option><option value="name">按名称</option></select></div><div v-if="filteredResults.length" class="scenario-grid"><article v-for="item in filteredResults" :key="item.id" class="scenario-card"><button class="scenario-thumbnail" @click="openResult(item)"><img :src="assetUrl(item.image_url)" :alt="item.title" loading="lazy"/><span>{{item.html_exists?'2D + 3D':'2D 图像'}}</span></button><div class="scenario-copy"><div class="scenario-meta"><span>{{sourceName(item)}}</span><time>{{date(item.created_at)}}</time></div><button class="scenario-title" @click="openResult(item)">{{item.title}}</button><p>{{item.notes || (item.source==='upload'?'原图、处理结果与质量报告已归档。':'生成方案已归档，可继续检查与研究。')}}</p><div class="scenario-actions"><button class="text-button" @click="openResult(item)">打开方案 <AppIcon name="arrow"/></button><a :href="`${API_BASE}/results/${item.id}/download/cleaned`" class="icon-button" aria-label="下载方案 PNG"><AppIcon name="download"/></a><button class="icon-button danger-text" aria-label="删除方案" @click="deleteResult(item)"><AppIcon name="trash"/></button></div></div></article></div><div v-else class="library-empty"><AppIcon name="layers"/><h3>{{query || sourceFilter!=='all'?'没有匹配的方案':'为你的研究建立第一份档案'}}</h3><p>{{query || sourceFilter!=='all'?'试试其他关键词，或调整来源筛选。':'导入现有规划图，修复完成后会自动保存到这里。'}}</p><button class="secondary-button" @click="query || sourceFilter!=='all' ? resetFilters() : page='postprocess'">{{query || sourceFilter!=='all'?'清除筛选':'导入规划图'}}</button></div></section>
    </main>
    <MapPicker v-if="mapOpen" :range="range" @update:range="range=$event" @close="mapOpen=false"/>
  </div>
</template>
<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue';
import AppIcon from './components/AppIcon.vue';
import PlanningIllustration from './components/PlanningIllustration.vue';
import MapPicker from './components/MapPicker.vue';
import PostprocessWorkbench from './components/PostprocessWorkbench.vue';
import ResultViewer from './components/ResultViewer.vue';
import { API_BASE, assetUrl } from './config';
import { request, jsonRequest, readLocal, writeLocal } from './api';
import { useJob } from './composables/useJob';
import './styles/workspace.css';
defineEmits(['intro']);
const pages = [{key:'planning',label:'规划生成',short:'规划',icon:'spark'},{key:'postprocess',label:'图像后处理',short:'修复',icon:'layers'},{key:'library',label:'方案库',short:'方案',icon:'grid'}];
const storedPage = readLocal('ud:page','planning');
const page = ref(pages.some(p=>p.key===storedPage)?storedPage:'planning'), capabilities = ref(null), online = ref(false), checking = ref(false), results = ref([]), resultsError = ref('');
const range = ref(readLocal('ud:range')), prompt = ref(readLocal('ud:prompt','')), activeId = ref(''), mapOpen = ref(false), messages = ref(readLocal('ud:messages',[]));
const query = ref(''), sourceFilter = ref('all'), sortOrder = ref('newest'), sending = ref(false), submitError = ref(''), toast = ref(''), removedId = ref('');
const promptInput = ref(null), conversation = ref(null);
let refreshTimer, toastTimer, disposed = false;
const canGenerate = computed(()=>online.value && capabilities.value?.generation?.configured);
const activeResult = computed(()=>results.value.find(r=>r.id===activeId.value) || null);
const modelLabel = computed(()=>!online.value?'服务未连接':({demo:'演示模式 · 示意生图',local:'本地生成 · 配置已检测',unconfigured:'生成模型待配置'})[capabilities.value?.generation?.mode] || '读取服务状态');
const examples = [{title:'围合式住宅街区',text:'生成一处围合式住宅街区规划图，沿街中低层建筑，中心留出开敞空间，建筑间距清晰。'},{title:'多层与高层组团',text:'生成住宅片区规划图，形成多层住宅与少量高层组团，高度分区明确，建筑轮廓简洁。'},{title:'低密度庭院社区',text:'生成低密度住宅区规划图，以庭院组团组织空间，保留清晰的公共空间与连续建筑边界。'}];
const filteredResults = computed(()=>results.value.filter(r=>(sourceFilter.value==='all'||(r.source||'generated')===sourceFilter.value) && `${r.title} ${r.notes||''} ${r.area_label||''}`.toLowerCase().includes(query.value.trim().toLowerCase())).sort((a,b)=>sortOrder.value==='name'?a.title.localeCompare(b.title,'zh-CN'):(sortOrder.value==='oldest'?1:-1)*String(a.created_at).localeCompare(String(b.created_at))));
const rangePolygon = computed(()=>{if(!range.value)return '';const b=range.value.bbox;const w=Math.max(b.east-b.west,1e-8),h=Math.max(b.north-b.south,1e-8);return range.value.points.map(p=>`${20+(p.lng-b.west)/w*180},${76-(p.lat-b.south)/h*60}`).join(' ');});
const {job:generationJob,pending:generationPending,error:generationError,track:trackGeneration,resume:resumeGeneration} = useJob('ud:generation-job', async data=>{
  if(data.result){upsert(data.result);activeId.value=data.result.id;messages.value.push({role:'assistant',text:'方案已生成并保存，可检查二维图、修复记录与三维示意。',resultId:data.result.id});}
  else messages.value.push({role:'assistant',text:data.content || '任务已完成。'});
});
watch(page,v=>writeLocal('ud:page',v));watch(range,v=>writeLocal('ud:range',v),{deep:true});watch(prompt,v=>writeLocal('ud:prompt',v));watch(messages,async v=>{writeLocal('ud:messages',v.slice(-50));await nextTick();if(conversation.value)conversation.value.scrollTop=conversation.value.scrollHeight;},{deep:true});
async function refresh(){
 if(checking.value)return;checking.value=true;
 const responses=await Promise.allSettled([request('/health',{timeout:7000}),request('/results',{timeout:7000})]);
 if(disposed)return;
 online.value=responses[0].status==='fulfilled';if(online.value)capabilities.value=responses[0].value;
 if(responses[1].status==='fulfilled'){results.value=responses[1].value.items||[];resultsError.value='';}else resultsError.value='方案列表读取失败，请稍后重试。';
 checking.value=false;
}
function upsert(item){const at=results.value.findIndex(r=>r.id===item.id);if(at>=0)results.value.splice(at,1,item);else results.value.unshift(item);}
function notify(text){toast.value=text;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.value='',3500);}
function onUploaded(result){upsert(result);notify('处理完成，方案已自动保存。');}
function openResult(item){activeId.value=item.id;page.value='planning';}
function resetFilters(){query.value='';sourceFilter.value='all';}
function date(v){return v?new Date(v.replace(' ','T')).toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'}):'—';}
function sourceName(item){return item.source==='upload'?'图片导入':item.area_label||'模型生成';}
function focusPrompt(){nextTick(()=>promptInput.value?.focus());}
function applyExample(value){prompt.value=value;focusPrompt();}
function newStudy(){if((prompt.value.trim()||range.value) && !window.confirm('开始新的规划草稿？当前未提交的目标和范围会清空，已保存方案保留。'))return;activeId.value='';prompt.value='';range.value=null;messages.value=[];page.value='planning';focusPrompt();}
function promptKeydown(e){if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();submit();}}
async function submit(){
 if(!prompt.value.trim() || !canGenerate.value || generationPending.value || sending.value)return;
 sending.value=true;submitError.value='';const text=prompt.value.trim();
 try{const job=await request('/jobs/generate',jsonRequest('POST',{message:text,selection_range:range.value}));messages.value.push({role:'user',text});prompt.value='';trackGeneration(job);}
 catch(e){submitError.value=e.message;}finally{sending.value=false;}
}
async function deleteResult(item){
 if(!window.confirm(`删除“${item.title}”及其图片、三维结果和报告？此操作无法撤销。`))return;
 try{await request(`/results/${item.id}`,{method:'DELETE'});results.value=results.value.filter(r=>r.id!==item.id);if(activeId.value===item.id)activeId.value='';removedId.value=item.id;messages.value=messages.value.filter(m=>m.resultId!==item.id);notify('方案已删除。');}
 catch(e){notify(e.message);}
}
onMounted(()=>{refresh();resumeGeneration();refreshTimer=setInterval(()=>{if(!document.hidden)refresh();},30000);});
onBeforeUnmount(()=>{disposed=true;clearInterval(refreshTimer);clearTimeout(toastTimer);});
</script>
