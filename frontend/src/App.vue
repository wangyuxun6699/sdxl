<template><Transition name="entry" mode="out-in"><CityIntro v-if="!entered" @enter="enter" /><Workspace v-else @intro="leave" /></Transition></template>
<script setup>
import { defineAsyncComponent, ref } from 'vue';
import CityIntro from './components/CityIntro.vue';
import { readLocal, writeLocal } from './api';
const Workspace = defineAsyncComponent(()=>import('./Workspace.vue'));
const entered = ref(readLocal('ud:entered',false));
function enter(){entered.value=true;writeLocal('ud:entered',true);}
function leave(){entered.value=false;writeLocal('ud:entered',false);}
</script>
<style>.entry-enter-active,.entry-leave-active{transition:opacity .35s ease}.entry-enter-from,.entry-leave-to{opacity:0}.app-starting{display:grid;place-items:center;min-height:100dvh;color:#c7bddc}@media(prefers-reduced-motion:reduce){.entry-enter-active,.entry-leave-active{transition:none}}</style>
