<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api";

const props = defineProps<{ init: any }>();
const pipelines = ref<any[]>([]);
const plugins = ref<any[]>([]);
const gpu = ref<any>({});
const recent = ref<any[]>([]);

onMounted(async () => {
  pipelines.value = await api.listPipelines();
  plugins.value = props.init?.plugins ?? await api.pluginList();
  gpu.value = props.init?.gpu ?? await api.resourceSnapshot();
  try { recent.value = (await api.logsRecent(8)).slice(-8).reverse(); } catch {}
});
</script>

<template>
  <div class="page">
    <h2>首页</h2>
    <div class="grid">
      <div class="card">
        <h3>最近使用管线 · 一键启动</h3>
        <div v-for="p in pipelines.slice(0, 6)" :key="p.id" class="row" style="justify-content: space-between">
          <span>{{ p.name }} <span v-if="p.is_default" class="tag ok">默认</span></span>
          <span class="muted">{{ p.updated_at.slice(0, 16).replace("T", " ") }}</span>
        </div>
        <div v-if="!pipelines.length" class="muted">暂无管线</div>
      </div>
      <div class="card">
        <h3>系统状态</h3>
        <div class="row"><span class="lb2">GPU</span><span>{{ gpu.gpu_name || "未检测到" }}</span></div>
        <div class="row"><span class="lb2">显存</span>
          <span>{{ gpu.vram_used_mb ?? 0 }} / {{ gpu.vram_total_mb ?? 0 }} MB</span></div>
        <div class="row"><span class="lb2">内存</span><span>{{ (gpu.mem_used_gb ?? 0).toFixed(1) }} / {{ (gpu.mem_total_gb ?? 0).toFixed(1) }} GB</span></div>
        <div class="row"><span class="lb2">虚拟麦克风</span>
          <span :class="init?.vb_cable ? 'tag ok' : 'tag warn'">
            {{ init?.vb_cable ? "VB-CABLE 已检测" : "未检测到 VB-CABLE（可用扬声器输出）" }}</span></div>
        <div class="row"><span class="lb2">CPU</span><span>{{ (gpu.cpu_percent ?? 0).toFixed(0) }}%</span></div>
      </div>
      <div class="card">
        <h3>已安装插件</h3>
        <div v-for="p in plugins" :key="p.id" class="row" style="justify-content: space-between">
          <span>{{ p.name }} <span class="muted">v{{ p.version }}</span></span>
          <span :class="p.state === 'running' ? 'tag ok' : p.state === 'error' ? 'tag err' : 'tag'">{{ p.state }}</span>
        </div>
        <div v-if="!plugins.length" class="muted">无插件（前往「插件」页安装）</div>
      </div>
      <div class="card">
        <h3>最近事件</h3>
        <div v-for="(l, i) in recent" :key="i" class="muted ev">
          [{{ l.ts }}] {{ l.component }}: {{ l.message }}
        </div>
      </div>
    </div>
    <div class="card">
      <h3>快速开始</h3>
      <div class="muted">
        1. 「音频设备」确认输入/输出 → 2. 「声音档案」导入参考音频 →
        3. 「管线工作室」加载预置「中文语音转目标音色」→ 4. ▶ 启动 →
        5. 在 Discord/游戏中选择 CABLE Output 作为麦克风
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.lb2 { width: 90px; color: var(--muted); font-size: 12px; }
.ev { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
