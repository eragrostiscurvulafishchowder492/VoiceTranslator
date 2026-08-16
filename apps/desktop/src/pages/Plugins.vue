<script setup lang="ts">
// 插件页（17.6）：安装本地 ZIP、启停、启用禁用、权限、日志、卸载。
import { onMounted, ref } from "vue";
import { api } from "../api";

const plugins = ref<any[]>([]);
const logsOf = ref<Record<string, string[]>>({});
const msg = ref("");
const selected = ref<string | null>(null);

async function reload() { plugins.value = await api.pluginList(); }
onMounted(reload);

async function install() {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const f = await open({ filters: [{ name: "插件包", extensions: ["zip"] }] });
  if (!f) return;
  try {
    const id = await api.pluginInstall(String(f));
    msg.value = `已安装 ${id}。请检查权限声明。`;
    await reload();
  } catch (e: any) { msg.value = String(e); }
}

async function start(id: string) {
  msg.value = "启动中（大模型插件可能需要 10~60 秒）…";
  try { await api.pluginStart(id); msg.value = "已启动"; } catch (e: any) { msg.value = String(e); }
  await reload();
}
async function stop(id: string) { await api.pluginStop(id); await reload(); }
async function toggle(p: any) { await api.pluginEnable(p.id, !p.enabled); await reload(); }
async function uninstall(id: string) {
  if (!confirm(`确定卸载插件 ${id}？`)) return;
  try { await api.pluginUninstall(id); } catch (e: any) { msg.value = String(e); }
  await reload();
}
async function showLogs(id: string) {
  logsOf.value[id] = await api.pluginLogs(id, 80);
  selected.value = id;
}

async function repairEnv(p: any) {
  msg.value = `创建独立环境 ${p.id} …`;
  try {
    const r = await api.pluginPrepareEnv(p.id);
    msg.value = `独立环境创建完成（${r.ms}ms），可以启动插件了`;
  } catch (e: any) { msg.value = `环境创建失败：${e}`; }
}
</script>

<template>
  <div class="page">
    <h2>插件</h2>
    <div class="row">
      <button class="primary" @click="install">安装本地插件 ZIP…</button>
      <span class="muted">{{ msg }}</span>
    </div>
    <div class="card">
      <p class="muted" style="margin-bottom: 8px">
        注意：插件运行在独立进程，但进程隔离 ≠ 完整安全沙箱。安装第三方插件前请核对来源、哈希与权限。
      </p>
      <table>
        <thead><tr><th>插件</th><th>版本</th><th>状态</th><th>权限</th><th>环境</th><th>节点</th><th></th></tr></thead>
        <tbody>
          <tr v-for="p in plugins" :key="p.id">
            <td>{{ p.name }}<div class="muted">{{ p.id }}</div></td>
            <td>{{ p.version }}</td>
            <td><span :class="p.state === 'running' ? 'tag ok' : p.state === 'error' ? 'tag err' : 'tag'">{{ p.state }}</span>
              <div v-if="p.detail" class="muted">{{ p.detail }}</div></td>
            <td><span v-for="pm in p.permissions" :key="pm" class="tag" :class="{ warn: pm === 'network' || pm === 'process_spawn' }">{{ pm }}</span></td>
            <td>{{ p.python_env }}</td>
            <td class="muted">{{ p.node_types.join(", ") || "—" }}</td>
            <td style="white-space: nowrap">
              <button v-if="p.state !== 'running'" @click="start(p.id)">启动</button>
              <button v-else @click="stop(p.id)">停止</button>
              <button @click="toggle(p)">{{ p.enabled ? "禁用" : "启用" }}</button>
              <button v-if="p.python_env === 'isolated'" @click="repairEnv(p)">修复环境</button>
              <button @click="showLogs(p.id)">日志</button>
              <button class="danger" @click="uninstall(p.id)">卸载</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!plugins.length" class="muted">无插件。将 plugins/examples 下的插件目录复制到 app-data/plugins 后刷新，或安装 ZIP。</div>
    </div>
    <div v-if="selected" class="card">
      <h3>插件日志：{{ selected }}</h3>
      <pre class="logs">{{ (logsOf[selected] ?? []).join("\n") || "（无日志）" }}</pre>
    </div>
  </div>
</template>

<style scoped>
.logs {
  max-height: 300px; overflow: auto; background: #0d0d11; border: 1px solid var(--border);
  border-radius: 8px; padding: 10px; font-size: 11px; white-space: pre-wrap;
}
</style>
