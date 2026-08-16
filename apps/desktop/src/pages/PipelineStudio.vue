<script setup lang="ts">
// 管线工作室（八.）：节点库 | 画布 | 属性面板，底部实时状态条。
import { onMounted, ref } from "vue";
import { api } from "../api";
import NodeEditor from "../components/NodeEditor.vue";
import SchemaForm from "../components/SchemaForm.vue";

const specs = ref<any[]>([]);
const nodes = ref<any[]>([]);
const edges = ref<any[]>([]);
const selected = ref<string | null>(null);
const editor = ref<InstanceType<typeof NodeEditor> | null>(null);
const issues = ref<any[]>([]);
const pipelines = ref<any[]>([]);
const graphName = ref("未命名管线");
const running = ref(false);
const statusLine = ref("");
const search = ref("");

const categories = ref<[string, any[]][]>([]);
onMounted(async () => {
  await reloadAll();
  // 自动加载默认管线（若有）
  const def = pipelines.value.find((p: any) => p.is_default) ?? pipelines.value[0];
  if (def) await load(def.id);
});

async function reloadAll() {
  specs.value = await api.nodeRegistry();
  const byCat = new Map<string, any[]>();
  for (const s of specs.value) {
    if (!byCat.has(s.category)) byCat.set(s.category, []);
    byCat.get(s.category)!.push(s);
  }
  categories.value = [...byCat.entries()];
  pipelines.value = await api.listPipelines();
}

const specOf = (t: string) => specs.value.find(s => s.node_type === t);
const selNode = () => nodes.value.find(n => n.id === selected.value);
const selSpec = () => specOf(selNode()?.node_type ?? "");

function dropNode(type: string) {
  const cx = 120 + Math.random() * 60, cy = 90 + nodes.value.length * 30;
  editor.value?.addNode(type, cx, cy);
}

function graphJson() {
  return JSON.stringify({
    format_version: 1,
    id: currentId.value || `pl_${Date.now().toString(36)}`,
    name: graphName.value,
    nodes: nodes.value,
    edges: edges.value,
    description: "",
    tags: [],
  });
}
const currentId = ref("");

async function validate() {
  try {
    issues.value = await api.validatePipeline(graphJson());
  } catch (e: any) { issues.value = [{ level: "Error", message: String(e) }]; }
}

async function save(asDefault: boolean) {
  try {
    currentId.value = await api.savePipeline(graphJson(), graphName.value, asDefault);
    pipelines.value = await api.listPipelines();
    statusLine.value = `已保存：${graphName.value}`;
  } catch (e: any) { statusLine.value = `保存失败：${e}`; }
}

async function load(id: string) {
  const row = pipelines.value.find(p => p.id === id);
  if (!row) return;
  const g = JSON.parse(row.graph_json);
  nodes.value = g.nodes;
  edges.value = g.edges;
  graphName.value = row.name;
  currentId.value = row.id;
  selected.value = null;
}

function exportJson() {
  // 导出安全化：本地路径占位（宿主命令侧同样处理）
  const blob = new Blob([JSON.stringify({ nodes: nodes.value, edges: edges.value }, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${graphName.value}.voicepipeline.json`;
  a.click();
}

async function start() {
  await validate();
  const errs = issues.value.filter(i => i.level === "Error");
  if (errs.length) { statusLine.value = "存在校验错误，无法启动"; return; }
  try {
    await api.startPipeline(graphJson());
    running.value = true;
    statusLine.value = "管线运行中";
  } catch (e: any) { statusLine.value = `启动失败：${e}`; }
}
async function stop() {
  await api.stopPipeline();
  running.value = false;
  statusLine.value = "已停止";
}

const filteredCats = () => categories.value.map(([c, list]) => [c,
  list.filter(s => !search.value || s.display_name.includes(search.value) || s.node_type.includes(search.value))]);
</script>

<template>
  <div class="studio">
    <!-- 节点库 -->
    <aside class="lib">
      <input v-model="search" placeholder="搜索节点…" />
      <div v-for="[cat, list] in filteredCats().filter(([, l]) => l.length)" :key="cat" class="cat">
        <div class="ct">{{ cat }}</div>
        <div v-for="s in list" :key="s.node_type" class="ni" draggable="true"
             @dragstart="$event.dataTransfer?.setData('text/node-type', s.node_type)"
             @dblclick="dropNode(s.node_type)" :title="s.node_type">
          {{ s.display_name }}
          <span v-if="s.estimated_vram_mb" class="muted">{{ s.estimated_vram_mb }}MB</span>
        </div>
      </div>
    </aside>

    <!-- 画布 -->
    <div class="canvas" @dragover.prevent @drop="dropNode($event.dataTransfer?.getData('text/node-type') ?? '')">
      <NodeEditor ref="editor" :nodes="nodes" :edges="edges" :specs="specs"
                  @select="selected = $event" @change="() => {}" />
      <div class="toolbar">
        <button class="primary" :disabled="running" @click="start">▶ 启动</button>
        <button class="danger" :disabled="!running" @click="stop">■ 停止</button>
        <button @click="validate">✓ 校验</button>
        <button @click="save(false)">保存</button>
        <button @click="save(true)">设为默认</button>
        <button @click="exportJson">导出</button>
        <select :value="currentId" class="plsel" @change="load(($event.target as HTMLSelectElement).value)">
          <option value="" disabled>加载管线…</option>
          <option v-for="p in pipelines" :key="p.id" :value="p.id">{{ p.name }}{{ p.is_default ? " ★" : "" }}</option>
        </select>
        <input v-model="graphName" class="pname" />
      </div>
    </div>

    <!-- 属性面板 -->
    <aside class="props">
      <template v-if="selNode()">
        <h3>{{ selSpec()?.display_name }}</h3>
        <div class="muted" style="margin-bottom: 8px">{{ selNode().node_type }}</div>
        <label class="row"><span class="lb">标签</span>
          <input :value="selNode().label" @input="selNode().label = ($event.target as HTMLInputElement).value" /></label>
        <label class="row"><span class="lb">备注</span>
          <input :value="selNode().notes ?? ''" @input="selNode().notes = ($event.target as HTMLInputElement).value" /></label>
        <label class="row chk"><input type="checkbox" style="width: auto" v-model="selNode().bypassed" /> 旁路该节点</label>
        <div class="sec">节点参数</div>
        <SchemaForm :schema="selSpec()?.params_schema ?? { properties: {} }" v-model="selNode().params" />
        <div class="sec">端口信息</div>
        <div v-for="p in selSpec()?.inputs ?? []" :key="'i' + p.name" class="portrow">
          <span class="dot" />入 {{ p.name }} <span class="muted">{{ p.port_type }}{{ p.required ? " *" : "" }}</span>
        </div>
        <div v-for="p in selSpec()?.outputs ?? []" :key="'o' + p.name" class="portrow">
          <span class="dot out" />出 {{ p.name }} <span class="muted">{{ p.port_type }}</span>
        </div>
      </template>
      <template v-else>
        <h3>管线属性</h3>
        <div class="muted">未选中节点。双击左侧节点或拖入画布。</div>
        <div v-if="issues.length" class="sec" style="margin-top: 10px">校验结果</div>
        <div v-for="(i, k) in issues" :key="k" class="issue" :class="i.level.toLowerCase()">
          [{{ i.level }}] {{ i.message }}
        </div>
      </template>
    </aside>
  </div>
  <div class="statusbar">{{ statusLine }} <span v-if="issues.length" class="muted">{{ issues.filter(i => i.level === 'Error').length }} 错误 / {{ issues.length }} 项</span></div>
</template>

<style scoped>
.studio { display: flex; height: calc(100vh - 34px); }
.lib {
  width: 200px; background: var(--panel); border-right: 1px solid var(--border);
  overflow-y: auto; padding: 10px; flex-shrink: 0;
}
.ct { font-size: 11px; color: var(--muted); margin: 12px 0 5px; text-transform: uppercase; letter-spacing: 1px; }
.ni {
  background: var(--panel2); border: 1px solid var(--border); border-radius: 7px;
  padding: 6px 9px; margin-bottom: 4px; font-size: 12px; cursor: grab; display: flex;
  justify-content: space-between; align-items: center;
}
.ni:hover { border-color: var(--accent); }
.canvas { flex: 1; position: relative; min-width: 0; }
.toolbar {
  position: absolute; top: 10px; left: 10px; display: flex; gap: 6px; z-index: 5;
  background: rgba(16, 16, 20, 0.85); padding: 8px; border-radius: 9px; border: 1px solid var(--border);
}
.toolbar button { padding: 5px 11px; }
.plsel { width: 150px; }
.pname { width: 120px; }
.props {
  width: 270px; background: var(--panel); border-left: 1px solid var(--border);
  overflow-y: auto; padding: 14px; flex-shrink: 0;
}
.props h3 { color: var(--accent); font-size: 14px; margin-bottom: 6px; }
.lb { width: 36px; flex-shrink: 0; font-size: 12px; }
.sec { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px;
  margin: 14px 0 6px; border-top: 1px solid var(--border); padding-top: 10px; }
.portrow { font-size: 12px; margin: 3px 0; display: flex; gap: 6px; align-items: center; }
.dot { width: 8px; height: 8px; border-radius: 4px; background: #fac464; display: inline-block; }
.dot.out { background: #5ac8fa; }
.issue { font-size: 12px; padding: 5px 8px; border-radius: 6px; margin-bottom: 4px; background: var(--panel2); }
.issue.error { border-left: 3px solid var(--danger); }
.issue.warning { border-left: 3px solid var(--warn); }
.issue.info { border-left: 3px solid var(--accent); }
.statusbar {
  height: 34px; border-top: 1px solid var(--border); background: var(--panel);
  display: flex; align-items: center; gap: 14px; padding: 0 16px; font-size: 12px;
}
.chk { gap: 6px; font-size: 12px; }
</style>
