<template>
  <section
    ref="rootRef"
    class="city-intro"
    :class="{ 'is-entering': isEntering }"
    @pointermove="handlePointerMove"
    @pointerdown="handlePointerDown"
    @pointerleave="handlePointerLeave"
    @pointercancel="handlePointerLeave"
  >
    <canvas ref="canvasRef" class="city-canvas" aria-hidden="true"></canvas>
    <div class="atmosphere atmosphere-grain" aria-hidden="true"></div>
    <div class="atmosphere atmosphere-vignette" aria-hidden="true"></div>

    <header class="intro-header">
      <div class="brand" aria-label="城市扩散智能规划平台">
        <span class="brand-mark" aria-hidden="true">
          <i></i><i></i><i></i>
        </span>
        <span class="brand-copy">
          <strong>URBAN DIFFUSION</strong>
          <small>城市规划生成与空间分析平台</small>
        </span>
      </div>
    </header>

    <main class="intro-content">
      <h1>
        <span class="headline-line">让城市从</span>
        <span class="headline-line headline-line-accent"><strong>扩散</strong><span>中生长</span></span>
      </h1>
      <p class="intro-description">
        <span>以扩散模型生成城市规划方案，</span>
        <span>联动空间形态与环境分析。</span>
      </p>

      <button class="enter-button" type="button" :disabled="isEntering" @click="requestEnter">
        <span class="button-label">{{ isEntering ? "正在进入" : "进入规划工作台" }}</span>
        <span class="button-arrow" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M5 12h13M13 7l5 5-5 5" />
          </svg>
        </span>
      </button>
    </main>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import { createCyberGlobeScene } from "./cyberGlobeScene";

const emit = defineEmits(["enter"]);
const rootRef = ref(null);
const canvasRef = ref(null);
const isEntering = ref(false);

let scene = null;
let enterTimer = 0;
let motionPreference = null;

function handlePointerMove(event) {
  scene?.handlePointerMove(event);
}

function handlePointerLeave() {
  scene?.handlePointerLeave();
}

function handlePointerDown(event) {
  scene?.handlePointerDown(event);
}

function handleMotionChange(event) {
  scene?.setReducedMotion(event.matches);
}

function requestEnter() {
  if (isEntering.value) return;
  isEntering.value = true;
  scene?.excite();
  enterTimer = window.setTimeout(() => emit("enter"), motionPreference?.matches ? 0 : 520);
}

onMounted(() => {
  motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
  scene = createCyberGlobeScene({
    root: rootRef.value,
    canvas: canvasRef.value,
    reducedMotion: motionPreference.matches,
  });
  motionPreference.addEventListener("change", handleMotionChange);
});

onBeforeUnmount(() => {
  window.clearTimeout(enterTimer);
  motionPreference?.removeEventListener("change", handleMotionChange);
  scene?.destroy();
  scene = null;
});
</script>

<style scoped>
.city-intro {
  --violet: #a66cff;
  --focus: #d8c5f4;
  position: fixed;
  inset: 0;
  z-index: 100;
  min-width: 320px;
  min-height: 100dvh;
  overflow: hidden;
  isolation: isolate;
  color: #f8f5ff;
  background:
    radial-gradient(circle at 50% -8%, rgba(128, 92, 215, 0.18), transparent 30%),
    radial-gradient(circle at 50% 72%, rgba(73, 37, 162, 0.2), transparent 42%),
    linear-gradient(180deg, #030610 0%, #06091a 48%, #070516 100%);
  font-family: "Segoe UI Variable", "HarmonyOS Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.city-canvas,
.atmosphere {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.city-canvas {
  z-index: 0;
  filter: none;
  transition: filter 0.75s ease, transform 1s cubic-bezier(0.2, 0.75, 0.2, 1);
}

.atmosphere {
  pointer-events: none;
}

.atmosphere-vignette {
  z-index: 2;
  background:
    linear-gradient(90deg, rgba(2, 5, 18, 0.56), transparent 20%, transparent 80%, rgba(2, 5, 18, 0.56)),
    linear-gradient(180deg, rgba(2, 5, 17, 0.1), transparent 26%, transparent 68%, rgba(3, 6, 21, 0.48)),
    radial-gradient(ellipse 70% 62% at 50% 70%, transparent 34%, rgba(2, 4, 18, 0.4) 100%);
}

.atmosphere-grain {
  z-index: 1;
  opacity: 0.032;
  background-image: url("/noise-grain.png");
  background-repeat: repeat;
  background-size: 128px 128px;
  mix-blend-mode: soft-light;
}

.intro-header,
.intro-content {
  position: absolute;
  z-index: 4;
}

.intro-header {
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  padding: clamp(24px, 3vw, 46px) clamp(24px, 4vw, 72px);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 13px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 3px;
  padding: 7px;
  border: 1px solid rgba(196, 181, 255, 0.3);
  border-radius: 10px;
  background: rgba(118, 77, 217, 0.11);
  box-shadow: inset 0 0 16px rgba(183, 123, 255, 0.08);
}

.brand-mark i {
  display: block;
  width: 4px;
  border-radius: 1px 1px 0 0;
  background: linear-gradient(to top, #7255a0, #cbb5e8);
  box-shadow: 0 0 8px rgba(183, 151, 221, 0.42);
}

.brand-mark i:nth-child(1) { height: 9px; }
.brand-mark i:nth-child(2) { height: 17px; }
.brand-mark i:nth-child(3) { height: 12px; }

.brand-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.brand-copy strong {
  font-size: 12px;
  letter-spacing: 0.2em;
}

.brand-copy small {
  color: rgba(230, 224, 249, 0.62);
  font-size: 10px;
  letter-spacing: 0.08em;
}

.intro-content {
  top: clamp(144px, 15.5vh, 188px);
  left: 50%;
  width: min(900px, calc(100% - 44px));
  transform: translateX(-50%);
  text-align: center;
  pointer-events: none;
}

.intro-content h1 {
  margin: 0;
  color: #fbf9ff;
  font-size: clamp(3.2rem, 4.65vw, 5.35rem);
  font-weight: 310;
  line-height: 0.96;
  letter-spacing: -0.035em;
  text-shadow: 0 10px 44px rgba(4, 3, 22, 0.98);
  animation: content-rise 1s 0.2s both;
}

.headline-line {
  display: block;
}

.headline-line-accent {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 0.06em;
  margin-top: 0.1em;
}

.headline-line-accent strong {
  color: #c9b8ff;
  font-weight: 610;
  text-shadow: 0 0 30px rgba(177, 116, 255, 0.32), 0 10px 42px rgba(4, 3, 22, 0.98);
}

.intro-description {
  max-width: 680px;
  margin: 22px auto 0;
  color: rgba(241, 237, 251, 0.86);
  font-size: clamp(13px, 1vw, 16px);
  line-height: 1.7;
  letter-spacing: 0.025em;
  text-shadow: 0 4px 22px #030413;
  animation: content-rise 1s 0.32s both;
}

.intro-description span {
  display: inline;
}

.enter-button {
  position: relative;
  min-width: 214px;
  margin-top: 26px;
  padding: 13px 13px 13px 20px;
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  overflow: hidden;
  border: 1px solid rgba(226, 213, 255, 0.3);
  border-radius: 14px;
  color: #fff;
  background: linear-gradient(135deg, rgba(111, 78, 174, 0.36), rgba(48, 31, 89, 0.46));
  -webkit-backdrop-filter: blur(12px) saturate(115%);
  backdrop-filter: blur(12px) saturate(115%);
  box-shadow:
    0 18px 44px rgba(18, 7, 49, 0.42),
    0 0 28px rgba(137, 92, 215, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.13),
    inset 0 -1px 0 rgba(35, 19, 68, 0.42);
  cursor: pointer;
  pointer-events: auto;
  transition: transform 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
  animation: content-rise 1s 0.45s both;
}

.enter-button:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: rgba(234, 219, 255, 0.5);
  box-shadow:
    0 21px 48px rgba(20, 7, 58, 0.48),
    0 0 34px rgba(152, 103, 227, 0.13),
    inset 0 1px 0 rgba(255, 255, 255, 0.18),
    inset 0 -1px 0 rgba(35, 19, 68, 0.34);
}

.enter-button:active:not(:disabled) {
  transform: translateY(1px) scale(0.985);
}

.enter-button:focus-visible {
  outline: 2px solid rgba(216, 197, 244, 0.88);
  outline-offset: 5px;
}

.enter-button:disabled {
  cursor: wait;
}

.button-label {
  position: relative;
  z-index: 1;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.button-arrow {
  position: relative;
  z-index: 1;
  width: 29px;
  height: 29px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(231, 217, 250, 0.28);
  border-radius: 8px;
  color: rgba(247, 241, 255, 0.9);
  background: linear-gradient(135deg, rgba(222, 205, 245, 0.22), rgba(173, 143, 215, 0.12));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.11);
  transition: transform 0.3s ease, background 0.3s ease, border-color 0.3s ease;
}

.button-arrow svg {
  width: 17px;
  height: 17px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.enter-button:hover .button-arrow {
  transform: translateX(2px);
  border-color: rgba(236, 224, 255, 0.42);
  background: linear-gradient(135deg, rgba(228, 213, 249, 0.28), rgba(182, 151, 224, 0.16));
}

.is-entering .city-canvas {
  transform: scale(1.075);
  filter: saturate(1.02) brightness(1.12) blur(1px);
}

.is-entering .intro-content,
.is-entering .intro-header {
  opacity: 0;
  transition: opacity 0.46s ease;
}

@keyframes content-rise {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 720px) {
  .intro-header {
    padding: 22px 20px;
  }

  .brand-copy small {
    display: none;
  }

  .intro-content {
    top: clamp(132px, 15vh, 166px);
  }

  .intro-content h1 {
    font-size: clamp(3rem, 13vw, 4rem);
    line-height: 0.98;
  }

  .intro-description {
    max-width: 34ch;
    font-size: 13px;
  }

  .intro-description span {
    display: block;
  }
}

@media (max-height: 700px) and (min-width: 721px) {
  .intro-header {
    padding-top: 20px;
    padding-bottom: 20px;
  }

  .intro-content {
    top: 92px;
  }

  .intro-content h1 {
    font-size: clamp(2.9rem, 7.5vh, 3.55rem);
  }

  .intro-description {
    margin-top: 14px;
  }

  .enter-button {
    margin-top: 16px;
    padding-top: 10px;
    padding-bottom: 10px;
  }
}

@media (max-height: 560px) {
  .intro-header { padding-top: 16px; padding-bottom: 16px; }
  .intro-content { top: 80px; }
  .intro-content h1 { font-size: clamp(2rem, 7vh, 2.75rem); }
  .intro-description { margin-top: 12px; font-size: 12px; }
  .enter-button { margin-top: 14px; padding-top: 8px; padding-bottom: 8px; }
}

@media (prefers-reduced-motion: reduce) {
  .city-intro *,
  .city-intro *::before,
  .city-intro *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
