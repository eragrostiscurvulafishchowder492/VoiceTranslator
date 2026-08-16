<script setup lang="ts">
// 设置：热键、音频块、PTT 模式、外观。设置持久化到 SQLite。
import { onMounted, ref } from "vue";
import { api } from "../api";

const s = ref<any>({
  hotkeys: { ptt: "F8", mute: "F9", clear_queue: "F10", interrupt: "F11" },
  listen_mode: "ptt", theme: "dark", auto_start_default: false,
});
const msg = ref("");

onMounted(async () => {
  const saved = await api.settingsGet();
  if (saved && Object.keys(saved).length) s.value = { ...s.value, ...saved };
});

async function save() {
  await api.settingsSet(s.value);
  msg.value = "已保存（热键重启应用后生效）";
}
</script>

<template>
  <div class="page">
    <h2>设置</h2>
    <div class="card">
      <h3>全局热键</h3>
      <div class="row"><span class="lb">Push-to-talk</span><input v-model="s.hotkeys.ptt" style="width: 100px" /></div>
      <div class="row"><span class="lb">静音</span><input v-model="s.hotkeys.mute" style="width: 100px" /></div>
      <div class="row"><span class="lb">清空队列</span><input v-model="s.hotkeys.clear_queue" style="width: 100px" /></div>
      <div class="row"><span class="lb">中断输出</span><input v-model="s.hotkeys.interrupt" style="width: 100px" /></div>
      <p class="muted">默认 F8/F9/F10/F11。热键冲突时 Windows 可能注册失败，重启后查看日志。</p>
    </div>
    <div class="card">
      <h3>聆听模式</h3>
      <div class="row">
        <select v-model="s.listen_mode" style="width: 200px">
          <option value="ptt">按键说话（PTT）</option>
          <option value="auto">VAD 自动</option>
        </select>
      </div>
    </div>
    <div class="card">
      <h3>启动</h3>
      <label class="row"><input type="checkbox" style="width: auto" v-model="s.auto_start_default" /> 启动时自动打开默认管线（安全模式下不生效）</label>
    </div>
    <div class="row"><button class="primary" @click="save">保存设置</button><span class="muted">{{ msg }}</span></div>
  </div>
</template>

<style scoped>
.lb { width: 100px; color: var(--muted); }
</style>
