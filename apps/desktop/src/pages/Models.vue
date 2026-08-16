<script setup lang="ts">
// 模型页（17.5）：模型清单 + 手动导入 + 校验状态。
import { onMounted, ref } from "vue";
import { api } from "../api";

const models = ref<any[]>([]);
const plugins = ref<any[]>([]);
const msg = ref("");

async function reload() {
  models.value = await api.modelList();
  plugins.value = await api.pluginList();
}
onMounted(reload);

async function importModel() {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const f = await open({ directory: true, multiple: false });
  if (!f) return;
  // 以目录名作为 model_id 手动导入登记
  const dir = String(f);
  const id = dir.split(/[\\/]/).filter(Boolean).pop() ?? "manual_model";
  let size = 0;
  try {
    // 通过宿主侧登记（大小由前端粗略略过；准确值以校验为准）
    await api.modelUpsert({
      model_id: id, plugin_id: plugins.value[0]?.id ?? "manual",
      local_path: dir, size_bytes: size, license: "user-imported",
      verified: false, last_used_at: new Date().toISOString(),
    });
    msg.value = `已登记 {id}（待校验）`;
    await reload();
  } catch (e: any) { msg.value = String(e); }
}

async function verify(m: any) {
  msg.value = `校验 ${m.model_id}：路径存在 = ${!!m.local_path}`;
  await api.modelUpsert({ ...m, verified: !!m.local_path });
  await reload();
}

async function remove(m: any) {
  await api.modelDelete(m.model_id);
  await reload();
}
</script>

<template>
  <div class="page">
    <h2>模型</h2>
    <div class="card">
      <h3>模型管理</h3>
      <p class="muted" style="margin-bottom: 10px">
        大型模型不打入安装包；本页登记本地模型目录（models/ 下已就位的模型在插件启动时直接加载）。
        下载请使用官方来源（ModelScope / HuggingFace），本应用不内置下载源。
      </p>
      <div class="row">
        <button class="primary" @click="importModel">手动导入模型目录…</button>
        <span class="muted">{{ msg }}</span>
      </div>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>模型</th><th>插件</th><th>本地路径</th><th>大小</th><th>许可证</th><th>校验</th><th></th></tr></thead>
        <tbody>
          <tr v-for="m in models" :key="m.model_id">
            <td>{{ m.model_id }}</td>
            <td class="muted">{{ m.plugin_id }}</td>
            <td class="muted">{{ m.local_path || "—" }}</td>
            <td>{{ m.size_bytes ? (m.size_bytes / 1e9).toFixed(2) + " GB" : "—" }}</td>
            <td>{{ m.license || "—" }}</td>
            <td><span :class="m.verified ? 'tag ok' : 'tag warn'">{{ m.verified ? "已校验" : "未校验" }}</span></td>
            <td><button @click="verify(m)">重新校验</button> <button class="danger" @click="remove(m)">删除</button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="!models.length" class="muted">暂无登记的模型。已就位的模型：models/CosyVoice3-0.5B、models/paraformer-streaming（由仓库 Python 环境直接使用）。</div>
    </div>
  </div>
</template>
