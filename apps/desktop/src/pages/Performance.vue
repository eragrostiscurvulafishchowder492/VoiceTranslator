<script setup lang="ts">
// 性能与日志（二十四.）：GPU/延迟/队列 + 日志流。
import { onMounted, onUnmounted, ref } from "vue";
import { api } from "../api";

const res = ref<any>({});
const logs = ref<any[]>([]);
const snap = ref<any>({});
let timer: any = null;
const history = ref<number[]>([]);

onMounted(async () => {
  timer = setInterval(async () => {
    res.value = await api.resourceSnapshot();
    snap.value = await api.pipelineSnapshot();
    logs.value = await api.logsRecent(200);
    const pct = res.value.vram_total_mb ? (res.value.vram_used_mb / res.value.vram_total_mb) * 100 : 0;
    history.value.push(pct);
    if (history.value.length > 120) history.value.shift();
  }, 1000);
});
onUnmounted(() => clearInterval(timer));
</script>

<template>
  <div class="page">
    <h2>性能与日志</h2>
    <div class="gridp">
      <div class="card">
        <h3>资源</h3>
        <div class="row"><span class="lb">GPU</span><span>{{ res.gpu_name || "—" }}</span></div>
        <div class="row"><span class="lb">显存</span>
          <span>{{ res.vram_used_mb ?? 0 }} / {{ res.vram_total_mb ?? 0 }} MB</span></div>
        <div class="vbar"><div class="vfill" :style="{ width: (history[history.length - 1] ?? 0) + '%' }" /></div>
        <div class="row"><span class="lb">CPU</span><span>{{ (res.cpu_percent ?? 0).toFixed(0) }}%</span></div>
        <div class="row"><span class="lb">内存</span><span>{{ (res.mem_used_gb ?? 0).toFixed(1) }} GB</span></div>
        <div class="row"><span class="lb">Underrun</span><span>{{ res.underruns ?? 0 }}</span></div>
        <div class="row"><span class="lb">输入溢出</span><span>{{ res.input_overflows ?? 0 }}</span></div>
        <svg v-if="history.length" :viewBox="`0 0 ${history.length} 40`" class="spark">
          <polyline :points="history.map((v, i) => `${i},${40 - v * 0.4}`).join(' ')" fill="none" stroke="#5ac8fa" stroke-width="1.5" />
        </svg>
      </div>
      <div class="card">
        <h3>管线队列 / 节点</h3>
        <table>
          <thead><tr><th>边</th><th>队列</th><th>发送</th><th>丢弃</th></tr></thead>
          <tbody>
            <tr v-for="e in (snap.edges ?? [])" :key="e.edge">
              <td class="muted">{{ e.edge }}</td><td>{{ e.queue_depth }}</td>
              <td>{{ e.sent }}</td><td>{{ e.dropped }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!(snap.edges ?? []).length" class="muted">管线未运行</div>
        <div class="row" style="margin-top: 8px">
          <span v-for="(st, id) in (snap.nodes ?? {})" :key="id" class="tag">{{ id }}: {{ st }}</span>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>日志（最近 200 条）</h3>
      <div class="logstream">
        <div v-for="(l, i) in logs" :key="i" class="lg" :class="l.level.toLowerCase()">
          <span class="ts">{{ l.ts }}</span> <span class="cp">[{{ l.component }}]</span> {{ l.message }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gridp { display: grid; grid-template-columns: 340px 1fr; gap: 12px; align-items: start; }
.lb { width: 84px; color: var(--muted); font-size: 12px; }
.vbar { height: 8px; background: #121218; border-radius: 4px; margin: 4px 0 10px; overflow: hidden; }
.vfill { height: 100%; background: linear-gradient(90deg, #64fab4, #fac464, #fa6480); }
.spark { width: 100%; height: 40px; margin-top: 8px; }
.logstream { max-height: 320px; overflow-y: auto; font-size: 12px; font-family: Consolas, monospace; }
.lg { padding: 1px 0; }
.lg .ts { color: var(--muted); }
.lg .cp { color: var(--accent); }
.lg.error { color: var(--danger); }
.lg.warn { color: var(--warn); }
</style>
