<template>
  <div class="planner-shell">
    <aside class="sidebar panel-surface">
      <section class="map-panel panel-inset">
        <div class="panel-heading">
          <div>
            <p class="section-label">范围选择</p>
            <h2>Cesium 范围圈选</h2>
          </div>
          <button class="ghost-button compact" @click="openMapPanel">
            打开地图
          </button>
        </div>

        <p class="status-text">{{ mapStatus }}</p>

        <div v-if="currentRangeSummary" class="range-summary panel-soft">
          <div class="range-summary-header">
            <strong>待发送范围</strong>
            <div class="range-summary-actions">
              <span>{{ currentRangeSummary.pointsCount }} 个点</span>
              <button class="ghost-button compact subtle-button" @click="cancelSelectionRange">
                取消范围
              </button>
            </div>
          </div>
          <p>
            BBox:
            {{ formatCoord(currentRangeSummary.bbox.west) }},
            {{ formatCoord(currentRangeSummary.bbox.south) }}
            /
            {{ formatCoord(currentRangeSummary.bbox.east) }},
            {{ formatCoord(currentRangeSummary.bbox.north) }}
          </p>
        </div>

        <div class="map-panel-actions">
          <button class="ghost-button compact" @click="openMapPanel">进入范围选择</button>
          <button
            class="ghost-button compact subtle-button"
            @click="clearSelectionRange"
            :disabled="!drawingPoints.length && !selectionRange"
          >
            清空范围
          </button>
        </div>

        <p class="helper-text">点击后会弹出独立地图窗口，左键添加点，右键结束绘制。</p>
      </section>

      <section class="current-panel panel-inset">
        <div class="panel-heading">
          <div>
            <p class="section-label">当前结果</p>
            <h2>{{ activeResult?.title || "等待生成结果" }}</h2>
          </div>
          <button
            v-if="activeResult"
            class="accent-button compact"
            @click="openFullscreenPreview()"
          >
            打开结果详情
          </button>
        </div>

        <div v-if="!activeResult" class="current-panel-body">
          <div class="preview-empty standalone">
            生成结果后，这里会展示当前结果摘要，并可在独立弹窗中查看完整结果。
          </div>
        </div>
      </section>

      <section class="results-panel panel-inset">
        <div class="panel-heading">
          <div>
            <p class="section-label">结果列表</p>
            <h2>{{ results.length }} 条记录</h2>
          </div>
        </div>

        <div class="results-panel-body">
          <div v-if="results.length" class="result-list">
            <div
              v-for="item in results"
              :key="item.id"
              class="result-item"
              :class="{ active: item.id === activeResultId }"
            >
              <button type="button" class="result-select" @click="selectResult(item.id)">
                <span class="result-item-title">{{ item.title }}</span>
                <span class="result-item-meta">
                  {{ areaMeta(item.area_type).label }} · {{ formatDate(item.created_at) }}
                </span>
              </button>
              <button
                type="button"
                class="result-delete-button"
                title="删除结果"
                @click.stop="deleteResult(item)"
              >
                删除
              </button>
            </div>
          </div>
          <div v-else class="status-text">还没有可查看的结果。</div>
        </div>
      </section>
    </aside>

    <main class="workspace panel-surface">
      <header class="workspace-header">
        <div>
          <p class="eyebrow">Conversation</p>
          <h2>生成对话</h2>
        </div>
      </header>

      <div ref="messageStreamRef" class="message-stream" @scroll="handleMessageStreamScroll">
        <article
          v-for="message in chatMessages"
          :key="message.id"
          class="message-card"
          :class="[message.role, { 'text-only': message.type === 'text' }]"
        >
          <div class="message-meta">
            <span>{{ message.role === "user" ? "你" : "系统" }}</span>
            <time>{{ message.time }}</time>
          </div>

          <p v-if="message.type === 'text'" class="message-copy">{{ message.content }}</p>

          <div v-else class="message-result">
            <div class="result-summary">
              <div>
                <p class="result-title">{{ message.result.title }}</p>
                <p class="result-subtitle">
                  {{ areaMeta(message.result.area_type).label }} / FLAG {{ message.result.area_flag }}
                </p>
                <p v-if="message.result.selection_range" class="result-range-tag">已附带圈定范围</p>
              </div>
              <div class="message-actions">
                <button class="ghost-button compact" @click="selectResult(message.result.id)">设为当前</button>
                <button class="accent-button compact" @click="openFullscreenPreview(message.result)">
                  预览 3D
                </button>
              </div>
            </div>

            <div class="result-media">
              <img
                v-if="message.result.image_url"
                :src="assetUrl(message.result.image_url)"
                :alt="message.result.title"
                class="result-image"
              />
              <div class="result-payload">
                <p><strong>标准 Prompt</strong></p>
                <p>{{ message.result.rewritten_prompt || message.result.prompt }}</p>
                <p><strong>Negative Prompt</strong></p>
                <p>{{ message.result.negative_prompt }}</p>
              </div>
            </div>
          </div>
        </article>

        <article v-if="isLoading" class="message-card assistant loading-card">
          <div class="message-meta">
            <span>系统</span>
            <time>处理中</time>
          </div>
          <p class="message-copy">
            正在执行 Qwen 路由、文生图、2D 转 3D 和分析流程，请稍候。
          </p>
        </article>
      </div>

      <div class="composer-panel panel-inset">
        <div v-if="currentRangeSummary" class="composer-range-chip">
          已附带范围：{{ currentRangeSummary.pointsCount }} 点 /
          {{ formatCoord(currentRangeSummary.bbox.west) }},
          {{ formatCoord(currentRangeSummary.bbox.south) }}
          -
          {{ formatCoord(currentRangeSummary.bbox.east) }},
          {{ formatCoord(currentRangeSummary.bbox.north) }}
          <button class="ghost-button compact chip-button" @click="cancelSelectionRange">取消</button>
        </div>

        <textarea
          v-model="composer"
          class="composer-input"
          rows="3"
          placeholder="例如：生成一个高密住宅区规划图，评估冬季低太阳高度角的日照暴露和多风向差异。"
          @keydown.enter.exact.prevent="handleSubmit"
        ></textarea>

        <div class="composer-footer">
          <p class="helper-text">
            发送时会把当前圈定范围一并传给后端，后续可直接接入“仅在该区域内生图”。
          </p>
          <button class="accent-button large" @click="handleSubmit" :disabled="isLoading">
            {{ isLoading ? "生成中..." : "发送任务" }}
          </button>
        </div>
      </div>
    </main>

    <div
      v-if="isPreviewFullscreen && activeResult"
      class="fullscreen-overlay"
      @click.self="closeFullscreenPreview"
    >
      <div class="fullscreen-shell">
        <div class="fullscreen-header">
          <div>
            <p class="eyebrow">Result Detail</p>
            <h2>{{ activeResult.title }}</h2>
          </div>
          <div class="fullscreen-actions">
            <button class="ghost-button" @click="loadAnalysis(true)" :disabled="isAnalysisLoading">
              {{ isAnalysisLoading ? "分析中..." : "刷新分析" }}
            </button>
            <button class="ghost-button" @click="saveActiveResult" :disabled="isSaving">
              {{ isSaving ? "保存中..." : "保存修改" }}
            </button>
            <button class="danger-button" @click="deleteActiveResult">删除结果</button>
            <button class="ghost-button" @click="closeFullscreenPreview">关闭</button>
          </div>
        </div>

        <div class="fullscreen-body">
          <div class="result-detail-modal">
            <div class="result-detail-sidebar">
              <div class="meta-grid result-detail-meta">
                <div class="meta-card">
                  <span class="meta-label">分区类型</span>
                  <strong>{{ areaMeta(activeResult.area_type).label }}</strong>
                </div>
                <div class="meta-card">
                  <span class="meta-label">状态标识</span>
                  <strong>FLAG {{ activeResult.area_flag }}</strong>
                </div>
                <div class="meta-card">
                  <span class="meta-label">模型路由</span>
                  <strong>{{ activeResult.model_key }}</strong>
                </div>
                <div class="meta-card">
                  <span class="meta-label">创建时间</span>
                  <strong>{{ formatDate(activeResult.created_at) }}</strong>
                </div>
              </div>

              <div v-if="activeResultRangeSummary" class="range-summary panel-soft">
                <div class="range-summary-header">
                  <strong>本结果已记录范围</strong>
                  <span>{{ activeResultRangeSummary.pointsCount }} 个点</span>
                </div>
                <p>
                  BBox:
                  {{ formatCoord(activeResultRangeSummary.bbox.west) }},
                  {{ formatCoord(activeResultRangeSummary.bbox.south) }}
                  /
                  {{ formatCoord(activeResultRangeSummary.bbox.east) }},
                  {{ formatCoord(activeResultRangeSummary.bbox.north) }}
                </p>
              </div>

              <div class="analysis-summary panel-soft">
                <div class="panel-heading compact-heading">
                  <div>
                    <p class="section-label">分析摘要</p>
                    <h3>自动加载当前结果分析</h3>
                  </div>
                </div>

                <div v-if="analysis" class="analysis-grid">
                  <div class="analysis-card">
                    <span class="meta-label">日照暴露</span>
                    <strong>{{ formatRatio(analysis.sunlight?.metrics?.mean_exposure) }}</strong>
                  </div>
                  <div class="analysis-card">
                    <span class="meta-label">通风效率</span>
                    <strong>{{ formatRatio(analysis.wind?.metrics?.mean_speed) }}</strong>
                  </div>
                  <div class="analysis-card">
                    <span class="meta-label">最佳风向</span>
                    <strong>{{ analysis.wind_comparison?.best_label || "--" }}</strong>
                  </div>
                  <div class="analysis-card">
                    <span class="meta-label">最弱风向</span>
                    <strong>{{ analysis.wind_comparison?.worst_label || "--" }}</strong>
                  </div>
                </div>
                <p v-else-if="analysisError" class="status-text error-text">{{ analysisError }}</p>
                <p v-else class="status-text">{{ isAnalysisLoading ? "正在计算分析结果..." : "等待分析结果" }}</p>
              </div>

              <div class="editor-block">
                <label class="form-field">
                  <span>标题</span>
                  <input v-model="editor.title" type="text" />
                </label>

                <label class="form-field">
                  <span>备注</span>
                  <textarea v-model="editor.notes" rows="4"></textarea>
                </label>
              </div>
            </div>

            <div class="result-detail-preview">
              <iframe
                v-if="activeResult.html_url"
                :src="assetUrl(activeResult.html_url)"
                class="fullscreen-frame"
                title="Result detail preview"
              ></iframe>
              <div v-else class="preview-empty fullscreen-empty">当前结果暂无可预览的 3D 内容。</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="isMapPanelOpen" class="map-overlay" @click.self="closeMapPanel">
      <div class="map-modal-shell">
        <div class="fullscreen-header">
          <div>
            <p class="eyebrow">Range Selection</p>
            <h2>Cesium 2D 范围圈选</h2>
            <p class="map-modal-copy">左键添加点，右键完成圈选。关闭窗口不会清空当前范围。</p>
          </div>
          <div class="fullscreen-actions">
            <button
              class="ghost-button"
              @click="clearSelectionRange"
              :disabled="!drawingPoints.length && !selectionRange"
            >
              清空范围
            </button>
            <button
              class="ghost-button subtle-button"
              @click="cancelSelectionRange"
              :disabled="!drawingPoints.length && !selectionRange"
            >
              取消范围
            </button>
            <button class="ghost-button" @click="closeMapPanel">关闭</button>
          </div>
        </div>

        <div v-if="currentRangeSummary" class="range-summary panel-soft map-modal-summary">
          <div class="range-summary-header">
            <strong>当前待发送范围</strong>
            <span>{{ currentRangeSummary.pointsCount }} 个点</span>
          </div>
          <p>
            BBox:
            {{ formatCoord(currentRangeSummary.bbox.west) }},
            {{ formatCoord(currentRangeSummary.bbox.south) }}
            /
            {{ formatCoord(currentRangeSummary.bbox.east) }},
            {{ formatCoord(currentRangeSummary.bbox.north) }}
          </p>
        </div>

        <div class="map-shell map-shell-modal">
          <div ref="mapContainerRef" class="map-container map-container-modal"></div>

          <div class="map-toolbar">
            <p class="helper-text">当前阶段会把圈定范围随请求发送给后端，暂不直接约束生图范围。</p>
            <button class="accent-button compact" @click="closeMapPanel">完成并返回</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from "vue";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { API_BASE, assetUrl as buildAssetUrl } from "./config";

// Vite 会把 VITE_ 变量写入浏览器产物，因此这里只接受受域名限制的公开 Cesium Token。
const CESIUM_ION_TOKEN = (import.meta.env.VITE_CESIUM_ION_TOKEN || "").trim();
if (CESIUM_ION_TOKEN) {
  Cesium.Ion.defaultAccessToken = CESIUM_ION_TOKEN;
}

const routeCards = [
  { key: "commercial", label: "商业区" },
  { key: "residential", label: "居住区" },
  { key: "industrial", label: "工业区" },
  { key: "public", label: "公共区" },
];

const composer = ref("");
const isLoading = ref(false);
const isSaving = ref(false);
const isAnalysisLoading = ref(false);
const isPreviewFullscreen = ref(false);
const isMapPanelOpen = ref(false);
const results = ref([]);
const activeResultId = ref("");
const analysis = ref(null);
const analysisError = ref("");
const selectionRange = ref(null);
const drawingPoints = ref([]);
const mapStatus = ref("展开地图后，可左键落点、右键完成圈选。");
const analysisInputs = reactive({
  season_profile: "spring",
  sun_altitude_deg: 44,
  primary_wind_direction: "west",
  wind_directions: ["north", "east", "south", "west"],
});
const messageStreamRef = ref(null);
const mapContainerRef = ref(null);
const viewerRef = shallowRef(null);
const shouldAutoScroll = ref(true);

let mapHandler = null;
let mapContextMenuBlocker = null;

const editor = reactive({
  title: "",
  notes: "",
});

const chatMessages = ref([
  {
    id: "welcome",
    role: "assistant",
    type: "text",
    content: "你好，现在可以直接输入规划提示词；如果先在左侧地图上圈定范围，发送时会把该范围一并交给后端。",
    time: nowTime(),
  },
]);

const activeResult = computed(() => {
  if (!results.value.length) return null;
  return results.value.find((item) => item.id === activeResultId.value) || results.value[0];
});

const currentRangeSummary = computed(() => summarizeRange(selectionRange.value));
const activeResultRangeSummary = computed(() => summarizeRange(activeResult.value?.selection_range));

watch(
  activeResult,
  (value) => {
    editor.title = value?.title || "";
    editor.notes = value?.notes || "";
  },
  { immediate: true }
);

watch(
  () => activeResult.value?.id,
  async (resultId) => {
    analysis.value = null;
    analysisError.value = "";
    if (!resultId) return;
    await loadAnalysis(false);
  }
);

watch(isMapPanelOpen, async (open) => {
  if (open) {
    await nextTick();
    initMap();
    syncMapEntities();
    if (selectionRange.value) {
      focusMapOnRange(selectionRange.value);
    }
    return;
  }

  destroyMap();
});

function nowTime() {
  return new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function formatDate(value) {
  if (!value) return "--";
  return new Date(value.replace(" ", "T")).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRatio(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Math.round(Number(value) * 100)}%`;
}

function formatCoord(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(4);
}

function areaMeta(areaType) {
  return routeCards.find((item) => item.key === areaType) || routeCards[1];
}

function assetUrl(path) {
  return buildAssetUrl(path);
}

function selectResult(id) {
  activeResultId.value = id;
}

function openMapPanel() {
  isMapPanelOpen.value = true;
}

function closeMapPanel() {
  isMapPanelOpen.value = false;
}

function isNearMessageBottom() {
  const element = messageStreamRef.value;
  if (!element) return true;
  return element.scrollHeight - element.clientHeight - element.scrollTop < 72;
}

function handleMessageStreamScroll() {
  shouldAutoScroll.value = isNearMessageBottom();
}

function scrollMessageStreamToBottom(options = {}) {
  const { force = false, behavior = "smooth" } = options;

  nextTick(() => {
    const element = messageStreamRef.value;
    if (!element) return;
    if (!force && !shouldAutoScroll.value) return;

    element.scrollTo({
      top: element.scrollHeight,
      behavior,
    });
    shouldAutoScroll.value = true;
  });
}

function pushTextMessage(role, content) {
  chatMessages.value.push({
    id: `${role}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role,
    type: "text",
    content,
    time: nowTime(),
  });
  scrollMessageStreamToBottom({
    force: role === "user",
    behavior: role === "user" ? "smooth" : "auto",
  });
}

function pushGenerateMessage(result) {
  chatMessages.value.push({
    id: `result-${result.id}`,
    role: "assistant",
    type: "generate",
    result,
    time: nowTime(),
  });
  scrollMessageStreamToBottom({ behavior: "smooth" });
}

function upsertResult(result) {
  const index = results.value.findIndex((item) => item.id === result.id);
  if (index === -1) {
    results.value.unshift(result);
  } else {
    results.value.splice(index, 1, result);
  }
}

function syncAnalysisControls(payload) {
  const inputs = payload?.inputs || {};
  analysisInputs.season_profile = inputs.season_profile || "spring";
  analysisInputs.sun_altitude_deg = Number(inputs.sun_altitude_deg || 44);
  analysisInputs.primary_wind_direction = inputs.primary_wind_direction || "west";
  analysisInputs.wind_directions = [...(inputs.wind_directions || ["north", "east", "south", "west"])];
}

function summarizeRange(range) {
  if (!range?.bbox || !Array.isArray(range.points) || !range.points.length) return null;
  return {
    pointsCount: range.points.length,
    bbox: range.bbox,
  };
}

function cloneRange(range) {
  return range ? JSON.parse(JSON.stringify(range)) : null;
}

function roundCoord(value) {
  return Number(value.toFixed(6));
}

function buildSelectionRange(points) {
  const normalizedPoints = points.map((point, index) => ({
    lng: roundCoord(point.lng),
    lat: roundCoord(point.lat),
    order: index,
  }));

  const lngs = normalizedPoints.map((point) => point.lng);
  const lats = normalizedPoints.map((point) => point.lat);

  return {
    points: normalizedPoints,
    bbox: {
      west: Math.min(...lngs),
      south: Math.min(...lats),
      east: Math.max(...lngs),
      north: Math.max(...lats),
    },
    closed: true,
  };
}

function toCartesian(point) {
  return Cesium.Cartesian3.fromDegrees(point.lng, point.lat);
}

function getMapPoint(screenPosition) {
  const viewer = viewerRef.value;
  if (!viewer) return null;

  const cartesian = viewer.camera.pickEllipsoid(screenPosition, viewer.scene.globe.ellipsoid);
  if (!cartesian) return null;

  const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
  return {
    lng: roundCoord(Cesium.Math.toDegrees(cartographic.longitude)),
    lat: roundCoord(Cesium.Math.toDegrees(cartographic.latitude)),
  };
}

function syncMapEntities() {
  const viewer = viewerRef.value;
  if (!viewer || viewer.isDestroyed()) return;

  viewer.entities.removeAll();

  const points = selectionRange.value?.closed ? selectionRange.value.points : drawingPoints.value;
  if (!points.length) {
    viewer.scene.requestRender();
    return;
  }

  points.forEach((point, index) => {
    viewer.entities.add({
      position: toCartesian(point),
      point: {
        pixelSize: 10,
        color: Cesium.Color.fromCssColorString("#2b7fff"),
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2,
      },
      label: {
        text: `${index + 1}`,
        font: "12px sans-serif",
        pixelOffset: new Cesium.Cartesian2(0, -18),
        fillColor: Cesium.Color.fromCssColorString("#1f2937"),
        showBackground: true,
        backgroundColor: Cesium.Color.fromCssColorString("rgba(255,255,255,0.75)"),
      },
    });
  });

  const cartesianPositions = points.map(toCartesian);

  if (cartesianPositions.length >= 2) {
    const polylinePositions = [...cartesianPositions];
    if (selectionRange.value?.closed && cartesianPositions.length >= 3) {
      polylinePositions.push(cartesianPositions[0]);
    }
    viewer.entities.add({
      polyline: {
        positions: polylinePositions,
        width: 3,
        material: Cesium.Color.fromCssColorString("#2b7fff"),
      },
    });
  }

  if (cartesianPositions.length >= 3) {
    viewer.entities.add({
      polygon: {
        hierarchy: cartesianPositions,
        material: Cesium.Color.fromCssColorString("rgba(43,127,255,0.22)"),
        outline: false,
      },
    });
  }

  viewer.scene.requestRender();
}

function expandedRectangle(bbox) {
  const lngPadding = Math.max((bbox.east - bbox.west) * 0.2, 0.01);
  const latPadding = Math.max((bbox.north - bbox.south) * 0.2, 0.01);

  return Cesium.Rectangle.fromDegrees(
    bbox.west - lngPadding,
    bbox.south - latPadding,
    bbox.east + lngPadding,
    bbox.north + latPadding
  );
}

function focusMapOnRange(range) {
  const viewer = viewerRef.value;
  if (!viewer || !range?.bbox) return;

  viewer.camera.flyTo({
    destination: expandedRectangle(range.bbox),
    duration: 0.8,
  });
}

function clearSelectionRange() {
  drawingPoints.value = [];
  selectionRange.value = null;
  mapStatus.value = "范围已清空，可以重新圈选。";
  syncMapEntities();
}

function cancelSelectionRange() {
  clearSelectionRange();
  mapStatus.value = "当前范围已取消，不会随本次请求发送。";
}

function finishDrawing() {
  if (selectionRange.value?.closed) {
    mapStatus.value = "当前范围已完成，可直接发送，或清空后重新绘制。";
    return;
  }

  if (drawingPoints.value.length < 3) {
    mapStatus.value = "至少需要 3 个点才能完成多边形圈选。";
    syncMapEntities();
    return;
  }

  selectionRange.value = buildSelectionRange(drawingPoints.value);
  mapStatus.value = `已完成范围圈选，共 ${selectionRange.value.points.length} 个点。`;
  syncMapEntities();
  focusMapOnRange(selectionRange.value);
}

function handleMapLeftClick(movement) {
  if (selectionRange.value?.closed) {
    mapStatus.value = "当前范围已完成，请先清空范围再重新绘制。";
    return;
  }

  const point = getMapPoint(movement.position);
  if (!point) {
    mapStatus.value = "请在地图平面范围内点击以添加点。";
    return;
  }

  drawingPoints.value = [
    ...drawingPoints.value,
    {
      lng: point.lng,
      lat: point.lat,
      order: drawingPoints.value.length,
    },
  ];
  mapStatus.value = `已添加 ${drawingPoints.value.length} 个点，右键可结束绘制。`;
  syncMapEntities();
}

function handleMapRightClick() {
  finishDrawing();
}

function initMap() {
  if (viewerRef.value || !mapContainerRef.value) return;

  const viewer = new Cesium.Viewer(mapContainerRef.value, {
    sceneMode: Cesium.SceneMode.SCENE2D,
    animation: false,
    baseLayerPicker: true,
    fullscreenButton: false,
    geocoder: false,
    homeButton: true,
    infoBox: false,
    navigationHelpButton: false,
    sceneModePicker: false,
    selectionIndicator: false,
    timeline: false,
    requestRenderMode: true,
  });

  viewer.scene.screenSpaceCameraController.enableRotate = false;
  viewer.scene.screenSpaceCameraController.enableTilt = false;
  viewer.scene.screenSpaceCameraController.enableLook = false;
  viewer.scene.globe.depthTestAgainstTerrain = false;
  viewer.camera.setView({
    destination: Cesium.Rectangle.fromDegrees(73, 18, 136, 54),
  });

  mapHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  mapHandler.setInputAction(handleMapLeftClick, Cesium.ScreenSpaceEventType.LEFT_CLICK);
  mapHandler.setInputAction(handleMapRightClick, Cesium.ScreenSpaceEventType.RIGHT_CLICK);

  mapContextMenuBlocker = (event) => event.preventDefault();
  mapContainerRef.value.addEventListener("contextmenu", mapContextMenuBlocker);

  viewerRef.value = viewer;
  mapStatus.value = "地图已就绪，左键添加点，右键结束绘制。";
}

function destroyMap() {
  if (mapHandler) {
    mapHandler.destroy();
    mapHandler = null;
  }

  if (mapContainerRef.value && mapContextMenuBlocker) {
    mapContainerRef.value.removeEventListener("contextmenu", mapContextMenuBlocker);
  }
  mapContextMenuBlocker = null;

  if (viewerRef.value && !viewerRef.value.isDestroyed()) {
    viewerRef.value.destroy();
  }
  viewerRef.value = null;
}

async function loadResults() {
  try {
    const response = await fetch(`${API_BASE}/results`);
    if (!response.ok) throw new Error("无法读取结果列表");
    const data = await response.json();
    results.value = data.items || [];
    if (!results.value.length) {
      activeResultId.value = "";
      return;
    }
    if (!activeResultId.value || !results.value.some((item) => item.id === activeResultId.value)) {
      activeResultId.value = results.value[0].id;
    }
  } catch (error) {
    pushTextMessage("assistant", `读取结果列表失败：${error.message}`);
  }
}

async function loadAnalysis(force = false) {
  if (!activeResult.value?.id || isAnalysisLoading.value) return;

  isAnalysisLoading.value = true;
  analysisError.value = "";
  try {
    const endpoint = `${API_BASE}/results/${activeResult.value.id}/analysis`;
    // GET 读取已有摘要；用户修改日照/风向后用 POST 强制重新计算。
    const response = await fetch(endpoint, {
      method: force ? "POST" : "GET",
      headers: force ? { "Content-Type": "application/json" } : undefined,
      body: force
        ? JSON.stringify({
            season_profile: analysisInputs.season_profile,
            sun_altitude_deg: Number(analysisInputs.sun_altitude_deg),
            primary_wind_direction: analysisInputs.primary_wind_direction,
            wind_directions: analysisInputs.wind_directions,
          })
        : undefined,
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "空间分析失败");
    analysis.value = data;
    syncAnalysisControls(data);
    upsertResult({ ...activeResult.value, analysis_ready: true });
  } catch (error) {
    analysisError.value = error.message;
  } finally {
    isAnalysisLoading.value = false;
  }
}

async function handleSubmit() {
  const prompt = composer.value.trim();
  if (!prompt || isLoading.value) return;

  pushTextMessage("user", prompt);
  composer.value = "";
  isLoading.value = true;
  scrollMessageStreamToBottom({ force: true, behavior: "smooth" });

  try {
    // 圈选范围与提示词一并持久化；当前版本尚未用它裁剪 SDXL 的生成画布。
    const response = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: prompt,
        selection_range: cloneRange(selectionRange.value),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "请求失败");

    if (data.intent === "chat") {
      pushTextMessage("assistant", data.content);
      return;
    }

    const result = {
      ...data.result,
      analysis_ready: Boolean(data.analysis) || data.result?.analysis_ready,
    };
    upsertResult(result);
    activeResultId.value = result.id;
    if (data.analysis) {
      analysis.value = data.analysis;
      analysisError.value = "";
      syncAnalysisControls(data.analysis);
    } else if (data.analysis_error) {
      analysis.value = null;
      analysisError.value = data.analysis_error;
    }
    pushGenerateMessage(result);
  } catch (error) {
    pushTextMessage("assistant", `处理失败：${error.message}`);
  } finally {
    isLoading.value = false;
  }
}

async function saveActiveResult() {
  if (!activeResult.value || isSaving.value) return;
  isSaving.value = true;

  try {
    const response = await fetch(`${API_BASE}/results/${activeResult.value.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: editor.title,
        notes: editor.notes,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "保存失败");
    upsertResult(data);
    activeResultId.value = data.id;
    pushTextMessage("assistant", `已更新《${data.title}》的标题与备注。`);
  } catch (error) {
    pushTextMessage("assistant", `保存失败：${error.message}`);
  } finally {
    isSaving.value = false;
  }
}

async function deleteActiveResult() {
  await deleteResult(activeResult.value);
}

async function deleteResult(target) {
  if (!target) return;
  const shouldDelete = window.confirm(`确认删除《${target.title}》吗？`);
  if (!shouldDelete) return;

  try {
    const wasActive = target.id === activeResultId.value;
    const response = await fetch(`${API_BASE}/results/${target.id}`, {
      method: "DELETE",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "删除失败");

    results.value = results.value.filter((item) => item.id !== target.id);
    if (wasActive) {
      activeResultId.value = results.value[0]?.id || "";
      analysis.value = null;
    }
    if (wasActive && isPreviewFullscreen.value) {
      closeFullscreenPreview();
    }
    pushTextMessage("assistant", `已删除《${target.title}》。`);
  } catch (error) {
    pushTextMessage("assistant", `删除失败：${error.message}`);
  }
}

function openFullscreenPreview(result = activeResult.value) {
  if (result?.id) {
    activeResultId.value = result.id;
  }
  if (!result?.html_url) return;
  isPreviewFullscreen.value = true;
}

function closeFullscreenPreview() {
  isPreviewFullscreen.value = false;
}

function handleKeydown(event) {
  if (event.key !== "Escape") return;

  if (isMapPanelOpen.value) {
    closeMapPanel();
    return;
  }

  if (isPreviewFullscreen.value) {
    closeFullscreenPreview();
  }
}

onMounted(() => {
  loadResults();
  window.addEventListener("keydown", handleKeydown);
  scrollMessageStreamToBottom({ force: true, behavior: "auto" });
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleKeydown);
  destroyMap();
});
</script>

<style scoped>
@import url("https://api.fontshare.com/v2/css?f[]=cabinet-grotesk@400,500,700,800&display=swap");

.planner-shell {
  --bg-deep: #07111f;
  --bg-mid: #0d1d33;
  --bg-panel: rgba(10, 18, 34, 0.76);
  --bg-panel-soft: rgba(16, 28, 50, 0.72);
  --bg-panel-elevated: rgba(23, 39, 68, 0.78);
  --border-strong: rgba(152, 196, 255, 0.24);
  --border-soft: rgba(139, 166, 214, 0.12);
  --text-main: #eff5ff;
  --text-soft: rgba(221, 232, 255, 0.72);
  --text-dim: rgba(178, 198, 232, 0.56);
  --accent: #79a8ff;
  --accent-strong: #a166ff;
  --accent-warm: #6ef2d5;
  min-height: 100vh;
  height: 100dvh;
  display: grid;
  grid-template-columns: 356px minmax(0, 1fr);
  gap: 16px;
  padding: 18px;
  box-sizing: border-box;
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(circle at 12% 14%, rgba(95, 124, 255, 0.28), transparent 20%),
    radial-gradient(circle at 88% 18%, rgba(114, 53, 255, 0.22), transparent 24%),
    radial-gradient(circle at 75% 78%, rgba(27, 201, 175, 0.16), transparent 18%),
    linear-gradient(135deg, #040911 0%, #091527 44%, #101f38 100%);
  color: var(--text-main);
  font-family: "Cabinet Grotesk", "Segoe UI", sans-serif;
}

.planner-shell::before,
.planner-shell::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
}

.planner-shell::before {
  background-image:
    radial-gradient(circle at 20% 30%, rgba(255, 255, 255, 0.16) 0 1px, transparent 1.8px),
    radial-gradient(circle at 72% 42%, rgba(255, 255, 255, 0.1) 0 1px, transparent 2px),
    radial-gradient(circle at 44% 74%, rgba(255, 255, 255, 0.08) 0 1px, transparent 1.8px),
    radial-gradient(circle at 80% 76%, rgba(255, 255, 255, 0.12) 0 1px, transparent 2px);
  background-size: 280px 280px, 340px 340px, 300px 300px, 360px 360px;
  opacity: 0.65;
}

.planner-shell::after {
  background:
    linear-gradient(115deg, rgba(255, 255, 255, 0.06), transparent 28%, transparent 72%, rgba(255, 255, 255, 0.04)),
    radial-gradient(circle at top, rgba(113, 145, 255, 0.12), transparent 48%);
  mix-blend-mode: screen;
}

.sidebar,
.workspace,
.fullscreen-overlay {
  position: relative;
  z-index: 1;
}

.sidebar,
.workspace {
  min-height: 0;
  height: 100%;
}

.sidebar {
  display: grid;
  grid-template-rows: minmax(210px, auto) minmax(96px, auto) minmax(0, 1fr);
  gap: 14px;
  overflow: hidden;
  padding: 14px 0;
}

.workspace {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.panel-surface {
  background:
    linear-gradient(180deg, rgba(14, 22, 42, 0.92), rgba(10, 17, 31, 0.82)),
    radial-gradient(circle at top right, rgba(120, 151, 255, 0.12), transparent 40%);
  border: 1px solid var(--border-soft);
  box-shadow:
    0 30px 80px rgba(0, 0, 0, 0.42),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(26px);
  border-radius: 30px;
}

.panel-inset {
  position: relative;
  background:
    linear-gradient(180deg, rgba(17, 28, 48, 0.84), rgba(10, 18, 33, 0.84)),
    radial-gradient(circle at top left, rgba(122, 104, 255, 0.12), transparent 45%);
  border: 1px solid var(--border-soft);
  border-radius: 24px;
  padding: 18px;
  overflow: hidden;
}

.panel-inset::before,
.panel-soft::before,
.message-card::before,
.preview-launch-card::before {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.08), transparent 32%, transparent 68%, rgba(110, 183, 255, 0.08));
  pointer-events: none;
}

.panel-soft {
  position: relative;
  background:
    linear-gradient(180deg, rgba(20, 34, 58, 0.76), rgba(13, 23, 42, 0.76)),
    radial-gradient(circle at top right, rgba(101, 226, 255, 0.1), transparent 42%);
  border: 1px solid rgba(134, 169, 230, 0.12);
  border-radius: 20px;
  padding: 14px;
  overflow: hidden;
}

.sidebar-top {
  padding: 18px 22px 0;
  position: relative;
}



.map-panel,
.current-panel,
.results-panel {
  margin: 0 14px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.map-panel {
  overflow: hidden;
}
.current-panel {
  overflow: hidden;
}

.results-panel {
  overflow: hidden;
  min-height: 0;
}

.workspace-header {
  flex: 0 0 auto;
  padding: 24px 28px 0;
}

.message-stream {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 20px 28px 12px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-items: stretch;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.composer-panel {
  flex: 0 0 auto;
  margin: 0 24px 24px;
}

.eyebrow,
.section-label,
.meta-label {
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  font-size: 10px;
  font-weight: 700;
  color: var(--text-dim);
}

.sidebar-title,
.workspace-header h2,
.panel-heading h2,
.compact-heading h3,
.fullscreen-header h2 {
  margin: 8px 0 0;
  font-weight: 800;
  letter-spacing: -0.04em;
}

.sidebar-title {
  max-width: none;
  font-size: clamp(2rem, 2.9vw, 2.7rem);
  line-height: 1.02;
}

.workspace-header h2 {
  font-size: clamp(1.72rem, 2.4vw, 2.2rem);
}

.panel-heading h2 {
  font-size: 1.36rem;
  line-height: 1.14;
}

.compact-heading h3,
.fullscreen-header h2 {
  font-size: 1.3rem;
}

.sidebar-copy,
.status-text,
.helper-text,
.message-copy,
.result-payload p,
.range-summary p {
  margin: 0;
  line-height: 1.6;
  font-size: 0.96rem;
  color: var(--text-soft);
}

.sidebar-copy {
  max-width: 28ch;
  font-size: 0.92rem;
  line-height: 1.55;
}

.status-text {
  color: rgba(221, 232, 255, 0.78);
}

.panel-heading,
.result-summary,
.message-actions,
.action-row,
.composer-footer,
.fullscreen-header,
.fullscreen-actions,
.range-summary-header,
.map-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-heading > div,
.result-summary > div:first-child {
  min-width: 0;
}

.compact-heading {
  align-items: flex-start;
}

.map-panel .panel-heading,
.current-panel .panel-heading {
  align-items: flex-start;
}

.map-panel .panel-heading h2 {
  max-width: 8ch;
  font-size: 1.56rem;
}

.current-panel .panel-heading h2 {
  max-width: none;
  font-size: 1.28rem;
  line-height: 1.18;
  overflow-wrap: anywhere;
}

.current-panel-body,
.results-panel-body {
  min-height: 0;
  overflow: auto;
  padding-right: 8px;
  margin-right: -8px;
  scrollbar-gutter: stable;
}

.current-panel-body {
  flex: 1 1 auto;
  margin-top: 16px;
}

.current-result-summary {
  margin-bottom: 14px;
}

.current-result-copy {
  margin: 0;
  line-height: 1.6;
  color: var(--text-soft);
}

.results-panel-body {
  flex: 1 1 auto;
  margin-top: 12px;
}

.map-shell {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.map-panel-actions {
  margin-top: 14px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.map-container {
  height: 252px;
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid rgba(137, 176, 243, 0.16);
  background:
    radial-gradient(circle at top, rgba(90, 142, 255, 0.18), transparent 40%),
    #050910;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.04),
    0 20px 45px rgba(3, 7, 18, 0.34);
}

.map-container-modal {
  height: min(68vh, 720px);
}

.map-shell-modal {
  margin-top: 0;
}

.map-modal-copy {
  margin: 10px 0 0;
  max-width: 44ch;
  color: var(--text-soft);
  font-size: 0.94rem;
  line-height: 1.55;
}

.map-modal-summary {
  margin-top: 2px;
}

.range-summary {
  margin-top: 12px;
}

.range-summary-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-launch-card {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  min-height: 112px;
  animation: card-rise 0.3s ease both;
  text-align: left;
  border: 1px solid rgba(134, 169, 230, 0.12);
  cursor: pointer;
  transition:
    transform 0.25s ease,
    border-color 0.25s ease,
    box-shadow 0.25s ease,
    opacity 0.25s ease;
}

.preview-launch-card.disabled {
  opacity: 0.78;
  cursor: not-allowed;
}

.preview-launch-card:not(:disabled):hover {
  transform: translateY(-2px);
  border-color: rgba(153, 186, 255, 0.22);
  box-shadow: 0 20px 36px rgba(4, 13, 29, 0.24);
}

.preview-launch-copy {
  min-width: 0;
}

.preview-launch-copy h3 {
  margin: 8px 0 0;
  font-size: 1.12rem;
  line-height: 1.25;
}

.preview-launch-copy p:last-child {
  margin-top: 8px;
}

.preview-launch-badge {
  flex-shrink: 0;
  padding: 9px 14px;
  border-radius: 999px;
  border: 1px solid rgba(144, 184, 255, 0.16);
  background: rgba(8, 16, 31, 0.78);
  color: #eef5ff;
  font-size: 12px;
  font-weight: 700;
  backdrop-filter: blur(14px);
}

.fullscreen-frame {
  width: 100%;
  height: 100%;
  border: 0;
  background: #02050d;
}

.preview-empty {
  min-height: 160px;
  display: grid;
  place-items: center;
  text-align: center;
  color: var(--text-soft);
  background: linear-gradient(180deg, rgba(16, 29, 52, 0.92), rgba(9, 17, 30, 0.98));
}

.standalone {
  min-height: 140px;
}

.meta-grid,
.analysis-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.meta-card,
.analysis-card {
  position: relative;
  padding: 12px 13px;
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(24, 41, 72, 0.84), rgba(15, 25, 45, 0.8)),
    radial-gradient(circle at top right, rgba(120, 178, 255, 0.12), transparent 35%);
  border: 1px solid rgba(135, 171, 230, 0.12);
  overflow: hidden;
}

.meta-card strong,
.analysis-card strong {
  display: block;
  margin-top: 8px;
  font-size: 1rem;
}

.analysis-summary,
.editor-block,
.action-row {
  margin-top: 14px;
}

.editor-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 14px;
  color: var(--text-soft);
}

.form-field input,
.form-field textarea,
.composer-input {
  width: 100%;
  border: 1px solid rgba(138, 173, 233, 0.16);
  border-radius: 16px;
  background: rgba(6, 13, 24, 0.72);
  color: var(--text-main);
  padding: 12px 14px;
  font: inherit;
  resize: vertical;
  box-sizing: border-box;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
  transition: border-color 0.25s ease, box-shadow 0.25s ease, background 0.25s ease;
}

.form-field input:focus,
.form-field textarea:focus,
.composer-input:focus {
  outline: none;
  border-color: rgba(126, 170, 255, 0.42);
  box-shadow:
    0 0 0 4px rgba(121, 169, 255, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
  background: rgba(8, 16, 29, 0.86);
}

.form-field input::placeholder,
.form-field textarea::placeholder,
.composer-input::placeholder {
  color: rgba(187, 204, 235, 0.42);
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.result-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 12px 14px;
  text-align: left;
  border-radius: 18px;
  border: 1px solid rgba(133, 165, 219, 0.12);
  background:
    linear-gradient(180deg, rgba(19, 32, 58, 0.78), rgba(11, 20, 36, 0.84)),
    radial-gradient(circle at right, rgba(126, 160, 255, 0.1), transparent 38%);
  color: var(--text-main);
  transition:
    transform 0.35s ease,
    border-color 0.35s ease,
    box-shadow 0.35s ease;
  animation: card-rise 0.3s ease both;
}

.result-item:hover {
  transform: translateY(-2px);
  border-color: rgba(154, 189, 255, 0.22);
  box-shadow: 0 18px 30px rgba(2, 10, 22, 0.22);
}

.result-item.active {
  border-color: rgba(126, 170, 255, 0.34);
  box-shadow:
    0 0 0 1px rgba(126, 170, 255, 0.18) inset,
    0 18px 34px rgba(7, 17, 37, 0.34);
  background:
    linear-gradient(180deg, rgba(31, 50, 84, 0.92), rgba(15, 27, 49, 0.92)),
    radial-gradient(circle at right, rgba(126, 160, 255, 0.16), transparent 42%);
}

.result-select {
  min-width: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.result-item-title {
  font-weight: 700;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.result-item-meta {
  font-size: 12px;
  color: var(--text-dim);
}

.result-delete-button {
  flex-shrink: 0;
  border: 1px solid rgba(255, 124, 139, 0.2);
  border-radius: 999px;
  background: rgba(97, 17, 44, 0.72);
  color: #fff2f5;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  padding: 7px 10px;
  transition:
    background 0.25s ease,
    border-color 0.25s ease,
    transform 0.25s ease;
}

.result-delete-button:hover {
  transform: translateY(-1px);
  border-color: rgba(255, 151, 162, 0.34);
  background: rgba(138, 27, 62, 0.86);
}

.message-card {
  position: relative;
  flex: 0 0 auto;
  min-width: 0;
  padding: 16px 18px;
  border-radius: 24px;
  border: 1px solid rgba(136, 168, 219, 0.12);
  background:
    linear-gradient(180deg, rgba(18, 30, 52, 0.82), rgba(9, 18, 31, 0.88)),
    radial-gradient(circle at top right, rgba(123, 183, 255, 0.12), transparent 42%);
  overflow: hidden;
  box-shadow: 0 18px 36px rgba(4, 9, 21, 0.28);
  animation: card-rise 0.34s ease both;
}

.message-card.user {
  align-self: flex-end;
  width: min(100%, 980px);
  background:
    linear-gradient(180deg, rgba(41, 62, 112, 0.86), rgba(22, 36, 71, 0.92)),
    radial-gradient(circle at right, rgba(104, 213, 255, 0.16), transparent 35%);
}

.message-card.assistant {
  align-self: flex-start;
  width: min(100%, 980px);
}

.message-card.text-only {
  width: min(100%, 980px);
  max-width: 100%;
}

.message-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--text-dim);
}

.message-copy,
.result-payload p,
.result-title,
.result-subtitle,
.result-range-tag {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.message-result,
.result-media,
.result-payload {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.result-image {
  width: 100%;
  max-height: 280px;
  object-fit: cover;
  border-radius: 18px;
  border: 1px solid rgba(142, 176, 232, 0.14);
  box-shadow: 0 20px 34px rgba(5, 10, 23, 0.25);
}

.result-title {
  margin: 0;
  font-size: 20px;
  font-weight: 800;
}

.result-subtitle,
.result-range-tag {
  margin: 4px 0 0;
  color: var(--text-soft);
}

.result-range-tag {
  font-size: 13px;
}

.composer-range-chip {
  margin-bottom: 14px;
  padding: 9px 12px;
  border-radius: 16px;
  background:
    linear-gradient(90deg, rgba(31, 56, 97, 0.92), rgba(18, 34, 68, 0.92)),
    radial-gradient(circle at left, rgba(108, 220, 255, 0.14), transparent 35%);
  color: #dff2ff;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid rgba(137, 171, 230, 0.14);
}

.composer-footer {
  margin-top: 14px;
  align-items: flex-end;
}

.composer-footer .helper-text {
  max-width: 64ch;
  padding-right: 12px;
}

.composer-input {
  min-height: 116px;
}

.fullscreen-overlay {
  position: fixed;
  inset: 0;
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(2, 7, 18, 0.72);
  backdrop-filter: blur(18px);
}

.map-overlay {
  position: fixed;
  inset: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(2, 7, 18, 0.78);
  backdrop-filter: blur(20px);
}

.fullscreen-shell {
  width: min(1440px, 100%);
  height: min(92vh, 100%);
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 22px;
  border-radius: 30px;
  background:
    linear-gradient(180deg, rgba(12, 20, 36, 0.96), rgba(6, 12, 24, 0.96)),
    radial-gradient(circle at top right, rgba(126, 170, 255, 0.12), transparent 40%);
  border: 1px solid rgba(145, 176, 229, 0.14);
  box-shadow: 0 30px 90px rgba(0, 0, 0, 0.5);
}

.map-modal-shell {
  width: min(1320px, 100%);
  height: min(90vh, 100%);
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 22px;
  border-radius: 30px;
  background:
    linear-gradient(180deg, rgba(12, 20, 36, 0.97), rgba(6, 12, 24, 0.97)),
    radial-gradient(circle at top right, rgba(114, 173, 255, 0.14), transparent 40%);
  border: 1px solid rgba(145, 176, 229, 0.14);
  box-shadow: 0 30px 90px rgba(0, 0, 0, 0.52);
}

.fullscreen-body {
  flex: 1;
  min-height: 0;
  padding: 18px;
  border-radius: 24px;
  overflow: hidden;
  border: 1px solid rgba(145, 176, 229, 0.12);
  background: #030711;
}

.result-detail-modal {
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
  gap: 18px;
}

.result-detail-sidebar,
.result-detail-preview {
  min-height: 0;
  min-width: 0;
}

.result-detail-sidebar {
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: auto;
  padding-right: 8px;
  margin-right: -8px;
  scrollbar-gutter: stable;
}

.result-detail-meta {
  margin-top: 0;
}

.result-detail-preview {
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid rgba(145, 176, 229, 0.12);
  background:
    linear-gradient(180deg, rgba(11, 19, 35, 0.96), rgba(5, 10, 21, 0.98)),
    radial-gradient(circle at top right, rgba(113, 165, 255, 0.12), transparent 42%);
}

.fullscreen-empty {
  height: 100%;
}

.accent-button,
.ghost-button,
.danger-button {
  position: relative;
  border-radius: 999px;
  padding: 10px 16px;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  transition:
    transform 0.25s ease,
    box-shadow 0.25s ease,
    border-color 0.25s ease,
    background 0.25s ease,
    filter 0.25s ease;
  overflow: hidden;
}

.accent-button::before,
.ghost-button::before,
.danger-button::before {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(115deg, transparent 20%, rgba(255, 255, 255, 0.22), transparent 80%);
  transform: translateX(-120%);
  transition: transform 0.65s ease;
}

.accent-button:hover::before,
.ghost-button:hover::before,
.danger-button:hover::before {
  transform: translateX(120%);
}

.accent-button {
  border: 0;
  color: #f8fbff;
  background:
    linear-gradient(135deg, #577fff 0%, #785eff 56%, #4ad8dc 100%);
  box-shadow:
    0 16px 30px rgba(87, 127, 255, 0.36),
    inset 0 1px 0 rgba(255, 255, 255, 0.24);
}

.ghost-button {
  border: 1px solid rgba(141, 175, 228, 0.16);
  background: rgba(12, 20, 36, 0.74);
  color: var(--text-main);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.danger-button {
  border: 1px solid rgba(255, 124, 139, 0.2);
  background:
    linear-gradient(135deg, rgba(145, 30, 71, 0.84), rgba(97, 17, 44, 0.94));
  color: #fff2f5;
  box-shadow: 0 16px 28px rgba(106, 15, 46, 0.26);
}

.accent-button:hover,
.ghost-button:hover,
.danger-button:hover {
  transform: translateY(-2px);
  filter: brightness(1.05);
}

.compact {
  padding: 8px 12px;
  font-size: 12px;
}

.large {
  padding-inline: 22px;
}

.error-text {
  color: #ff9f9f;
}

.subtle-button,
.chip-button {
  background: rgba(14, 24, 42, 0.72);
}

.chip-button {
  flex-shrink: 0;
  margin-left: auto;
}

:deep(.cesium-viewer),
:deep(.cesium-widget),
:deep(.cesium-widget canvas) {
  width: 100%;
  height: 100%;
}

:deep(.cesium-viewer-toolbar) {
  top: 12px;
  right: 12px;
}

:deep(.cesium-viewer-bottom) {
  font-family: "Cabinet Grotesk", "Segoe UI", sans-serif;
}

.current-panel-body::-webkit-scrollbar,
.results-panel-body::-webkit-scrollbar,
.message-stream::-webkit-scrollbar,
.result-detail-sidebar::-webkit-scrollbar {
  width: 8px;
}

.current-panel-body::-webkit-scrollbar-thumb,
.results-panel-body::-webkit-scrollbar-thumb,
.message-stream::-webkit-scrollbar-thumb,
.result-detail-sidebar::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(120, 154, 219, 0.18);
  border: 2px solid transparent;
  background-clip: padding-box;
}

.current-panel-body::-webkit-scrollbar-track,
.results-panel-body::-webkit-scrollbar-track,
.message-stream::-webkit-scrollbar-track,
.result-detail-sidebar::-webkit-scrollbar-track {
  background: transparent;
}

@keyframes card-rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 1180px) {
  .planner-shell {
    height: auto;
    min-height: 100vh;
    grid-template-columns: 1fr;
    overflow: visible;
  }

  .sidebar,
  .workspace {
    height: auto;
    min-height: auto;
  }

  .results-panel {
    max-height: none;
  }

  .current-panel-body,
  .results-panel-body,
  .message-stream,
  .result-detail-sidebar {
    margin-right: 0;
    padding-right: 0;
    scrollbar-gutter: auto;
  }
}

@media (max-width: 720px) {
  .planner-shell {
    padding: 14px;
    gap: 14px;
  }

  .sidebar-top,
  .workspace-header {
    padding-inline: 18px;
  }

  .message-stream,
  .composer-panel {
    padding-inline: 0;
    margin-inline: 18px;
  }

  .meta-grid,
  .analysis-grid {
    grid-template-columns: 1fr;
  }

  .result-detail-modal {
    grid-template-columns: 1fr;
  }

  .result-detail-preview {
    min-height: 320px;
  }

  .panel-heading,
  .result-summary,
  .composer-footer,
  .fullscreen-header,
  .fullscreen-actions,
  .action-row,
  .map-toolbar,
  .map-panel-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .sidebar-title {
    max-width: none;
    font-size: 2.5rem;
  }

  .message-card.user {
    width: 100%;
  }

  .fullscreen-overlay,
  .map-overlay {
    padding: 12px;
  }

  .preview-launch-card {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
