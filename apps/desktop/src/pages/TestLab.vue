<script setup lang="ts">
// 测试实验室（17.7）：TTS A/B、设备测试、结果回放。
import { onMounted, ref } from "vue";
import { convertFileSrc } from "@tauri-apps/api/core";
import { api } from "../api";

const text = ref("你们先过去，我拿一下东西，马上回来。");
const plugins = ref<any[]>([]);
const aPlugin = ref("org.voicestudio.cosyvoice");
const bPlugin = ref("org.voicestudio.cosyvoice");
const results = ref<any[]>({});
const busy = ref<string | null>(null);
const devices = ref<any[]>([]);

onMounted(async () => {
  plugins.value = await api.pluginList();
  devices.value = await api.listDevices();
});

async function run(slot: "A" | "B") {
  const pid = slot === "A" ? aPlugin.value : bPlugin.value;
  if (!pid) return;
  busy.value = slot;
  try {
    results.value[slot] = await api.testTts(text.value, pid, `lab_${slot}`);
  } catch (e: any) {
    results.value[slot] = { error: String(e) };
  }
  busy.value = null;
}

async function testDevices() {
  // 简单回环：列出可打开设备（采集测试用麦克风节点在管线中验证）
  results.value["devices"] = { ok: true, count: devices.value.length };
}

function convertSrc(p: string) {
  // 经 Tauri asset 协议访问本地 WAV（file:// 在 WebView 中被禁）
  return convertFileSrc(p);
}
</script>

<template>
  <div class="page">
    <h2>测试实验室</h2>
    <div class="card">
      <h3>Voice A/B</h3>
      <p class="muted" style="margin-bottom: 8px">同一文本 + 不同 TTS 插件生成对比（真实推理，结果为 WAV）</p>
      <div class="row">
        <textarea v-model="text" rows="2" style="width: 520px"></textarea>
      </div>
      <div class="row">
        <span class="lb">A 引擎</span>
        <select v-model="aPlugin" style="width: 240px">
          <option v-for="p in plugins" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <button class="primary" :disabled="busy === 'A'" @click="run('A')">{{ busy === "A" ? "生成中…" : "生成 A" }}</button>
      </div>
      <div class="row">
        <span class="lb">B 引擎</span>
        <select v-model="bPlugin" style="width: 240px">
          <option v-for="p in plugins" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <button class="primary" :disabled="busy === 'B'" @click="run('B')">{{ busy === "B" ? "生成中…" : "生成 B" }}</button>
      </div>
      <div class="ab">
        <div v-for="s in ['A', 'B']" :key="s" class="rescard">
          <b>{{ s }}</b>
          <template v-if="results[s]">
            <div v-if="results[s].error" class="muted" style="color: var(--danger)">{{ results[s].error }}</div>
            <template v-else>
              <div class="muted">TTFA {{ results[s].ttfa_ms }}ms · 总 {{ results[s].total_ms }}ms · 音频 {{ results[s].audio_dur_s }}s</div>
              <audio v-if="results[s].wav" :src="convertSrc(results[s].wav)" controls style="width: 100%; margin-top: 6px" />
              <div class="muted">{{ results[s].wav }}</div>
            </template>
          </template>
          <div v-else class="muted">（未生成）</div>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>Device Test</h3>
      <div class="row">
        <button @click="testDevices">检测全部设备</button>
        <span class="muted" v-if="results.devices">{{ results.devices.count }} 个设备可用。采集/播放回环请在「管线工作室」用「原声监听」预置实测。</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lb { width: 60px; color: var(--muted); }
.ab { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px; }
.rescard { background: var(--panel2); border: 1px solid var(--border); border-radius: 8px; padding: 10px; }
</style>
