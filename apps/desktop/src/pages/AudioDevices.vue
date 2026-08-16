<script setup lang="ts">
// 音频设备（17 + 十六.）：输入/监听/虚拟输出选择 + VB-CABLE 指引。
import { onMounted, ref } from "vue";
import { api } from "../api";
import { listen } from "@tauri-apps/api/event";

const devices = ref<any[]>([]);
const settings = ref<any>({ input: "", monitor: "", virtual: "" });
const msg = ref("");

async function reload() { devices.value = await api.listDevices(); }
onMounted(async () => {
  await reload();
  settings.value = await api.settingsGet();
  await listen("devices-changed", async (e) => {
    msg.value = `设备变更：${JSON.stringify(e.payload)}`;
    await reload();
  });
});

async function save() {
  await api.settingsSet(settings.value);
  msg.value = "已保存设备选择";
}
const ins = () => devices.value.filter(d => d.is_input);
const outs = () => devices.value.filter(d => d.is_output);
const vb = () => outs().find(d => d.name.toLowerCase().includes("cable input"));
</script>

<template>
  <div class="page">
    <h2>音频设备</h2>
    <div class="card">
      <h3>设备选择</h3>
      <div class="row"><span class="lb">输入设备</span>
        <select v-model="settings.input" style="width: 340px">
          <option v-for="d in ins()" :key="d.key" :value="d.key">
            {{ d.name }}{{ d.default_input ? "（默认）" : "" }} — {{ d.default_sample_rate }}Hz
          </option>
        </select></div>
      <div class="row"><span class="lb">监听设备</span>
        <select v-model="settings.monitor" style="width: 340px">
          <option value="">（不监听）</option>
          <option v-for="d in outs()" :key="d.key" :value="d.key">{{ d.name }}</option>
        </select></div>
      <div class="row"><span class="lb">虚拟输出</span>
        <select v-model="settings.virtual" style="width: 340px">
          <option value="">（自动检测 VB-CABLE）</option>
          <option v-for="d in outs()" :key="d.key" :value="d.key">{{ d.name }}</option>
        </select>
        <span :class="vb() ? 'tag ok' : 'tag warn'">{{ vb() ? "已检测到 CABLE Input" : "未检测到 VB-CABLE" }}</span></div>
      <div class="row"><button class="primary" @click="save">保存</button><span class="muted">{{ msg }}</span></div>
    </div>
    <div class="card">
      <h3>VB-CABLE 使用指引</h3>
      <ol class="muted" style="padding-left: 18px; line-height: 1.9">
        <li>从 vb-audio.com 下载并安装 VB-CABLE（需要管理员权限，本应用绝不自动安装驱动）</li>
        <li>本应用「虚拟输出」选择 <b>CABLE Input</b></li>
        <li>在 Discord / QQ / VRChat / 游戏语音设置中，麦克风选择 <b>CABLE Output</b></li>
        <li>检测不到虚拟设备时仍可使用普通扬声器输出，不影响其他功能</li>
      </ol>
    </div>
    <div class="card">
      <h3>全部设备（{{ devices.length }}）</h3>
      <table>
        <thead><tr><th>名称</th><th>方向</th><th>声道</th><th>采样率</th><th>默认</th></tr></thead>
        <tbody>
          <tr v-for="d in devices" :key="d.key">
            <td>{{ d.name }}</td><td>{{ d.is_input ? "输入" : "输出" }}</td>
            <td>{{ d.is_input ? d.max_input_channels : d.max_output_channels }}</td>
            <td>{{ d.default_sample_rate }} Hz</td>
            <td>{{ d.default_input || d.default_output ? "✔" : "" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.lb { width: 76px; color: var(--muted); }
</style>
