<script setup lang="ts">
// 实时语音（17.2）：日常使用页。当前管线 + 启停 + PTT + 电平 + 文本 + 延迟/显存。
import { onMounted, onUnmounted, ref } from "vue";
import { api } from "../api";

const pipelines = ref<any[]>([]);
const current = ref("");
const running = ref(false);
const snap = ref<any>({});
const logs = ref<any[]>([]);
const level = ref(0);
let timer: any = null;

onMounted(async () => {
  pipelines.value = await api.listPipelines();
  const def = pipelines.value.find(p => p.is_default) ?? pipelines.value[0];
  if (def) current.value = def.id;
  timer = setInterval(async () => {
    snap.value = await api.pipelineSnapshot();
    running.value = snap.value.running;
    try {
      const logsNew = await api.logsRecent(40);
      logs.value = logsNew;
      const lastLevel = [...logsNew].reverse().find(l => l.component === "audio" && l.message.includes("level"));
      if (lastLevel) { const m = lastLevel.message.match(/rms=([\d.]+)/); if (m) level.value = Math.min(1, parseFloat(m[1]) * 4); }
    } catch {}
  }, 1000);
});
onUnmounted(() => clearInterval(timer));

async function start() {
  const row = pipelines.value.find(p => p.id === current.value);
  if (!row) return;
  try { await api.startPipeline(row.graph_json); running.value = true; }
  catch (e: any) { alert(String(e)); }
}
async function stop() { await api.stopPipeline(); running.value = false; }
const texts = () => (logs.value ?? []).filter(l => l.component === "text").slice(-12).reverse();
</script>

<template>
  <div class="page">
    <h2>实时语音</h2>
    <div class="row">
      <select v-model="current" style="width: 260px" :disabled="running">
        <option v-for="p in pipelines" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <button class="primary" :disabled="running" @click="start">▶ 开始</button>
      <button class="danger" :disabled="!running" @click="stop">■ 停止</button>
      <button @mousedown="api.pipelineControl('ptt_down')" @mouseup="api.pipelineControl('ptt_up')">按住说话 (F8)</button>
      <button @click="api.pipelineControl(running ? 'mute_on' : 'mute_off')">静音 (F9)</button>
      <button @click="api.pipelineControl('clear')">清空队列 (F10)</button>
      <button class="danger" @click="api.pipelineControl('interrupt')">中断 (F11)</button>
    </div>

    <div class="grid2">
      <div class="card">
        <h3>识别文本</h3>
        <div v-for="(t, i) in texts()" :key="i" class="tline" :class="{ partial: t.message.includes('[partial]') }">
          {{ t.message }}
        </div>
        <div v-if="!texts().length" class="muted">（等待语音输入…）</div>
      </div>
      <div>
        <div class="card">
          <h3>麦克风电平</h3>
          <div class="meter"><div class="fill" :style="{ width: (level * 100) + '%' }" /></div>
        </div>
        <div class="card">
          <h3>运行指标</h3>
          <div class="row"><span class="lb2">状态</span><span class="tag" :class="snap.state === 'Running' ? 'ok' : ''">{{ snap.state ?? "Stopped" }}</span></div>
          <div class="row"><span class="lb2">节点</span>
            <span v-for="(st, id) in (snap.nodes ?? {})" :key="id" class="tag" style="margin-right: 4px">
              {{ String(id).slice(0, 10) }}: {{ st }}</span></div>
          <div class="row"><span class="lb2">输入/丢弃</span><span>{{ snap.total_in ?? 0 }} / {{ snap.total_dropped ?? 0 }}</span></div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid2 { display: grid; grid-template-columns: 1.4fr 1fr; gap: 12px; align-items: start; }
.tline { padding: 4px 0; border-bottom: 1px dashed var(--border); font-size: 14px; }
.tline.partial { color: var(--muted); }
.meter { height: 14px; background: #121218; border-radius: 7px; overflow: hidden; border: 1px solid var(--border); }
.fill { height: 100%; background: linear-gradient(90deg, #64fab4, #fac464, #fa6480); transition: width 0.15s; }
.lb2 { width: 70px; color: var(--muted); font-size: 12px; }
</style>
