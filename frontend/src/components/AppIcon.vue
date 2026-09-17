<template><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] || paths.grid" /></svg></template>
<script setup>
defineProps({ name: String });
const paths = {
 grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
 spark: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z M20 2v4 M18 4h4',
 layers: 'm12 3 10 5-10 5L2 8Z M2 12l10 5 10-5 M2 16l10 5 10-5',
 map: 'm3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2Z M9 3v16 M15 5v16',
 arrow: 'M4 12h16 M14 6l6 6-6 6',
 upload: 'M12 16V3 M7 8l5-5 5 5 M4 15v5h16v-5',
 download: 'M12 3v13 M7 11l5 5 5-5 M4 17v4h16v-4',
 search: 'M10.5 18a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15Z M16 16l5 5',
 close: 'm6 6 12 12 M18 6 6 18',
 check: 'm5 12 4 4L19 6',
 refresh: 'M20 8a8 8 0 1 0 0 8 M20 3v5h-5',
 cube: 'm12 2 9 5v10l-9 5-9-5V7Z M3 7l9 5 9-5 M12 12v10 M8 4l9 5',
 image: 'M3 3h18v18H3Z m0 14 6-6 5 5 3-3 4 4 M16 7h.01',
 compare: 'M12 2v20 M8 4H3v16h5 M16 4h5v16h-5 M7 12h10',
 chart: 'M3 3v18h18 M7 16v-4 M12 16V7 M17 16v-7',
 info: 'M12 8h.01 M12 11v6 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
 plus: 'M12 5v14 M5 12h14',
 home: 'm3 10 9-7 9 7 M5 9v12h14V9 M9 21v-8h6v8',
 trash: 'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7',
};
</script>
<style scoped>svg{width:20px;height:20px;flex-shrink:0;vertical-align:middle}</style>
