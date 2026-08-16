<script setup lang="ts">
import { onMounted, ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { api } from "./api";
import Home from "./pages/Home.vue";
import LiveVoice from "./pages/LiveVoice.vue";
import PipelineStudio from "./pages/PipelineStudio.vue";
import VoiceProfiles from "./pages/VoiceProfiles.vue";
import Models from "./pages/Models.vue";
import Plugins from "./pages/Plugins.vue";
import AudioDevices from "./pages/AudioDevices.vue";
import TestLab from "./pages/TestLab.vue";
import Performance from "./pages/Performance.vue";
import Settings from "./pages/Settings.vue";

const pages = [
  { id: "home", label: "首页", icon: "⌂", comp: Home },
  { id: "live", label: "实时语音", icon: "◉", comp: LiveVoice },
  { id: "studio", label: "管线工作室", icon: "⛭", comp: PipelineStudio },
  { id: "voice", label: "声音档案", icon: "♪", comp: VoiceProfiles },
  { id: "models", label: "模型", icon: "▤", comp: Models },
  { id: "plugins", label: "插件", icon: "⬢", comp: Plugins },
  { id: "devices", label: "音频设备", icon: "⏵", comp: AudioDevices },
  { id: "lab", label: "测试实验室", icon: "⚗", comp: TestLab },
  { id: "perf", label: "性能与日志", icon: "∿", comp: Performance },
  { id: "settings", label: "设置", icon: "⚙", comp: Settings },
];
const active = ref("home");
const init = ref<any>({});
const showRecovery = ref(false);
const lastKnownGood = ref<string | null>(null);

onMounted(async () => {
  try {
    init.value = await api.appInit();
    // 启动参数 --page=<id> 深链接（如 --page=studio）
    try {
      const page = await invoke<string | null>("get_startup_page");
      if (page && pages.some(p => p.id === page)) active.value = page;
    } catch {}
    if (init.value.abnormal_exit) {
      lastKnownGood.value = init.value.last_known_good;
      showRecovery.value = true;
    }
  } catch (e) {
    console.error("app_init failed", e);
  }
});

function useSafeMode() { showRecovery.value = false; }
async function useLastKnown() {
  if (lastKnownGood.value) {
    try {
      const g = JSON.parse(lastKnownGood.value);
      await api.savePipeline(lastKnownGood.value, g.name + " (恢复)", false);
    } catch (e) { console.error(e); }
  }
  showRecovery.value = false;
}
</script>

<template>
  <div class="shell">
    <nav class="nav">
      <div class="brand">
        <div class="logo">VS</div>
        <div>
          <div class="name">Voice Studio</div>
          <div class="sub">可插拔实时语音平台</div>
        </div>
      </div>
      <button v-for="p in pages" :key="p.id" :class="{ item: true, on: active === p.id }"
              @click="active = p.id">
        <span class="ic">{{ p.icon }}</span>{{ p.label }}
      </button>
      <div class="navfoot muted">v0.1.0 · 本地优先</div>
    </nav>
    <main class="main">
      <component :is="pages.find(p => p.id === active)!.comp" :init="init" />
    </main>

    <div v-if="showRecovery" class="modal-mask">
      <div class="modal card">
        <h3>检测到上次异常退出</h3>
        <p class="muted" style="margin: 8px 0 14px">
          为安全起见，本次启动不会自动加载任何模型或启动管线。
        </p>
        <div class="row">
          <button class="primary" @click="useSafeMode">安全模式进入（推荐）</button>
          <button v-if="lastKnownGood" @click="useLastKnown">恢复上次可用管线</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shell { display: flex; height: 100vh; }
.nav {
  width: 190px; background: var(--panel); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; padding: 12px 8px; gap: 2px; flex-shrink: 0;
}
.brand { display: flex; gap: 10px; align-items: center; padding: 6px 8px 14px; }
.logo {
  width: 36px; height: 36px; border-radius: 9px; background: linear-gradient(135deg, #1c4a63, #2c6e52);
  display: flex; align-items: center; justify-content: center; font-weight: 700; color: var(--accent);
}
.name { font-weight: 600; font-size: 14px; }
.sub { font-size: 10px; color: var(--muted); }
.item {
  text-align: left; background: transparent; border: none; border-radius: 8px;
  padding: 9px 10px; color: var(--muted); display: flex; gap: 9px; align-items: center; font-size: 13px;
}
.item:hover { background: var(--panel2); color: var(--text); }
.item.on { background: #1c2633; color: var(--accent); }
.ic { width: 18px; text-align: center; }
.navfoot { margin-top: auto; padding: 8px 10px; font-size: 11px; }
.main { flex: 1; min-width: 0; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center; z-index: 99;
}
.modal { width: 460px; }
</style>
