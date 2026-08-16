<script setup lang="ts">
// 声音档案（17.4）：用户参考音频管理。绝不随程序分发角色语音。
import { onMounted, ref } from "vue";
import { api } from "../api";

const profiles = ref<any[]>([]);
const form = ref({ id: "", name: "", ref_path: "", ref_text: "", style_json: "{}", tags: "", created_at: "" });
const msg = ref("");

async function reload() { profiles.value = await api.referenceList(); }
onMounted(reload);

async function pick() {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const f = await open({ filters: [{ name: "WAV 音频", extensions: ["wav"] }] });
  if (f) form.value.ref_path = String(f);
}

async function save() {
  if (!form.value.name || !form.value.ref_path) { msg.value = "名称与参考 WAV 必填"; return; }
  form.value.id = form.value.id || `vp_${Date.now().toString(36)}`;
  form.value.created_at = form.value.created_at || new Date().toISOString();
  try {
    await api.referenceSave({ ...form.value });
    msg.value = "已保存";
    form.value = { id: "", name: "", ref_path: "", ref_text: "", style_json: "{}", tags: "", created_at: "" };
    await reload();
  } catch (e: any) { msg.value = String(e); }
}

async function remove(id: string) { await api.referenceDelete(id); await reload(); }
function edit(p: any) { form.value = { ...p }; }
</script>

<template>
  <div class="page">
    <h2>声音档案</h2>
    <div class="card">
      <h3>导入参考音频</h3>
      <p class="muted" style="margin-bottom: 10px">
        参考音频（你自己录制或拥有授权的 WAV，5~15 秒清晰语音）仅保存在本机 app-data/references。
        程序不附带任何角色语音素材。
      </p>
      <div class="row"><span class="lb">名称</span><input v-model="form.name" placeholder="例：我的音色 A" style="width: 220px" /></div>
      <div class="row"><span class="lb">参考 WAV</span>
        <input :value="form.ref_path" readonly placeholder="选择文件…" style="width: 320px" @click="pick" />
        <button @click="pick">浏览…</button></div>
      <div class="row"><span class="lb">参考文本</span>
        <input v-model="form.ref_text" placeholder="（可选）参考音频的文字转写，留空走跨语言模式" style="width: 380px" /></div>
      <div class="row"><span class="lb">标签</span><input v-model="form.tags" placeholder="逗号分隔" style="width: 220px" /></div>
      <div class="row"><button class="primary" @click="save">保存档案</button><span class="muted">{{ msg }}</span></div>
    </div>

    <div class="card">
      <h3>已有档案</h3>
      <table>
        <thead><tr><th>名称</th><th>参考文本</th><th>标签</th><th>创建时间</th><th></th></tr></thead>
        <tbody>
          <tr v-for="p in profiles" :key="p.id">
            <td>{{ p.name }}</td>
            <td class="muted">{{ p.ref_text?.slice(0, 30) || "（跨语言）" }}</td>
            <td>{{ p.tags }}</td>
            <td class="muted">{{ p.created_at?.slice(0, 10) }}</td>
            <td><button @click="edit(p)">编辑</button> <button class="danger" @click="remove(p.id)">删除</button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="!profiles.length" class="muted">暂无档案</div>
    </div>
  </div>
</template>

<style scoped>
.lb { width: 64px; flex-shrink: 0; font-size: 13px; color: var(--muted); }
</style>
