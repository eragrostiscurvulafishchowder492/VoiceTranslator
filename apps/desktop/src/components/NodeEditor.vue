<script setup lang="ts">
// 节点图编辑器：SVG 画布。支持拖入、拖线、删除、多选、复制粘贴、
// 撤销重做、缩放平移、按端口类型校验连线。
import { computed, reactive, ref, watch } from "vue";

export interface EditorNode {
  id: string; node_type: string; label: string;
  params: any; position: [number, number];
  bypassed?: boolean; notes?: string; group?: string;
}
export interface EditorEdge {
  id: string; from_node: string; from_port: string;
  to_node: string; to_port: string;
  backpressure?: string; capacity?: number;
}
export interface NodeSpecLite {
  node_type: string; display_name: string; category: string;
  inputs: { name: string; port_type: string; required?: boolean }[];
  outputs: { name: string; port_type: string }[];
  default_params?: any;
}

const props = defineProps<{
  nodes: EditorNode[]; edges: EditorEdge[]; specs: NodeSpecLite[];
}>();
const emit = defineEmits<{
  (e: "change"): void
  (e: "select", id: string | null): void
}>();

const sel = ref<Set<string>>(new Set());
const clipboard = ref<EditorNode[]>([]);
const undoStack = ref<string[]>([]);
const redoStack = ref<string[]>([]);
const view = reactive({ x: 0, y: 0, k: 1 });
const W = 190, H_HEADER = 30, PORT_GAP = 22;

const specOf = (t: string) => props.specs.find(s => s.node_type === t);
const inCount = (t: string) => specOf(t)?.inputs.length ?? 1;
const nodeH = (t: string) => H_HEADER + Math.max(inCount(t), specOf(t)?.outputs.length ?? 1) * PORT_GAP + 12;

interface DragState { mode: "none" | "pan" | "node" | "wire"; x0: number; y0: number; node?: string; port?: string; isOut?: boolean }
const drag = reactive<DragState>({ mode: "none", x0: 0, y0: 0 });
const wireEnd = ref<{ x: number; y: number } | null>(null);

function snapshot() {
  undoStack.value.push(JSON.stringify({ nodes: props.nodes, edges: props.edges }));
  if (undoStack.value.length > 100) undoStack.value.shift();
  redoStack.value = [];
}
function undo() {
  const s = undoStack.value.pop();
  if (!s) return;
  redoStack.value.push(JSON.stringify({ nodes: props.nodes, edges: props.edges }));
  apply(s);
}
function redo() {
  const s = redoStack.value.pop();
  if (!s) return;
  undoStack.value.push(JSON.stringify({ nodes: props.nodes, edges: props.edges }));
  apply(s);
}
function apply(s: string) {
  const o = JSON.parse(s);
  props.nodes.splice(0, props.nodes.length, ...o.nodes);
  props.edges.splice(0, props.edges.length, ...o.edges);
  emit("change");
}

let uidc = 0;
const nid = () => `n${Date.now().toString(36)}${(uidc++).toString(36)}`;

function addNode(type: string, x: number, y: number) {
  snapshot();
  const spec = specOf(type);
  props.nodes.push({
    id: nid(), node_type: type,
    label: spec?.display_name ?? type,
    params: JSON.parse(JSON.stringify(spec?.default_params ?? {})),
    position: [x, y],
  });
  emit("change");
}

function deleteSelection() {
  if (!sel.value.size) return;
  snapshot();
  const ids = new Set(sel.value);
  for (let i = props.edges.length - 1; i >= 0; i--) {
    if (ids.has(props.edges[i].from_node) || ids.has(props.edges[i].to_node)) props.edges.splice(i, 1);
  }
  for (let i = props.nodes.length - 1; i >= 0; i--) {
    if (ids.has(props.nodes[i].id)) props.nodes.splice(i, 1);
  }
  sel.value = new Set();
  emit("select", null);
  emit("change");
}

function copySelection() {
  clipboard.value = props.nodes.filter(n => sel.value.has(n.id)).map(n => JSON.parse(JSON.stringify(n)));
}
function paste() {
  if (!clipboard.value.length) return;
  snapshot();
  for (const n of clipboard.value) {
    n.id = nid();
    n.position = [n.position[0] + 40, n.position[1] + 40];
    props.nodes.push(n);
  }
  emit("change");
}

// ---------- 坐标换算 ----------
const svgEl = ref<SVGSVGElement | null>(null);
function toWorld(cx: number, cy: number): [number, number] {
  return [(cx - view.x) / view.k, (cy - view.y) / view.k];
}

function portPos(nodeId: string, port: string, isOut: boolean): [number, number] {
  const n = props.nodes.find(x => x.id === nodeId)!;
  const spec = specOf(n.node_type);
  const list = isOut ? spec?.outputs ?? [] : spec?.inputs ?? [];
  const idx = Math.max(0, list.findIndex(p => p.name === port));
  return [n.position[0] + (isOut ? W : 0), n.position[1] + H_HEADER + 10 + idx * PORT_GAP];
}

const edgePath = (e: EditorEdge) => {
  const [x1, y1] = portPos(e.from_node, e.from_port, true);
  const [x2, y2] = portPos(e.to_node, e.to_port, false);
  const dx = Math.max(40, Math.abs(x2 - x1) * 0.5);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
};

const portColor = (t: string) => ({
  "audio.pcm": "#5ac8fa", "audio.encoded": "#3d7fa0", "speech.vad_event": "#b48dfa",
  "text.partial": "#fac464", "text.final": "#64fab4", "text.segment": "#8ce064",
  "tts.request": "#fa9664", "control.signal": "#999999", "system.event": "#777777",
  "metrics.sample": "#c1c1d1",
}[t] ?? "#888");

// ---------- 鼠标 ----------
function onMouseDown(ev: MouseEvent) {
  const target = ev.target as HTMLElement;
  const svg = svgEl.value!;
  const rect = svg.getBoundingClientRect();
  const [wx, wy] = toWorld(ev.clientX - rect.left, ev.clientY - rect.top);
  const nd = target.closest("[data-node]") as HTMLElement | null;
  const pd = target.closest("[data-port]") as HTMLElement | null;

  if (pd) {
    const nodeId = pd.dataset.node!, port = pd.dataset.port!;
    const isOut = pd.dataset.dir === "out";
    drag.mode = "wire"; drag.node = nodeId; drag.port = port; drag.isOut = isOut;
    wireEnd.value = [wx, wy] as any;
    return;
  }
  if (nd) {
    const id = nd.dataset.node!;
    if (ev.ctrlKey || ev.metaKey) {
      sel.value.has(id) ? sel.value.delete(id) : sel.value.add(id);
      sel.value = new Set(sel.value);
    } else if (!sel.value.has(id)) {
      sel.value = new Set([id]);
    }
    emit("select", [...sel.value][0] ?? null);
    drag.mode = "node"; drag.x0 = wx; drag.y0 = wy;
    return;
  }
  drag.mode = "pan"; drag.x0 = ev.clientX; drag.y0 = ev.clientY;
  sel.value = new Set();
  emit("select", null);
}

function onMouseMove(ev: MouseEvent) {
  const svg = svgEl.value;
  if (!svg) return;
  const rect = svg.getBoundingClientRect();
  if (drag.mode === "wire") {
    wireEnd.value = toWorld(ev.clientX - rect.left, ev.clientY - rect.top) as any;
  } else if (drag.mode === "node" && sel.value.size) {
    const wx = (ev.clientX - rect.left - view.x) / view.k;
    const wy = (ev.clientY - rect.top - view.y) / view.k;
    const dx = wx - drag.x0, dy = wy - drag.y0;
    for (const n of props.nodes) {
      if (sel.value.has(n.id)) { n.position[0] += dx; n.position[1] += dy; }
    }
    drag.x0 = wx; drag.y0 = wy;
  } else if (drag.mode === "pan") {
    view.x += ev.clientX - drag.x0; view.y += ev.clientY - drag.y0;
    drag.x0 = ev.clientX; drag.y0 = ev.clientY;
  }
}

function tryConnect(fromNode: string, fromPort: string, toNode: string, toPort: string) {
  if (fromNode === toNode) return;
  // 类型校验
  const os = specOf(props.nodes.find(n => n.id === fromNode)!.node_type);
  const is = specOf(props.nodes.find(n => n.id === toNode)!.node_type);
  const po = os?.outputs.find(p => p.name === fromPort);
  const pi = is?.inputs.find(p => p.name === toPort);
  if (!po || !pi) return;
  if (po.port_type !== pi.port_type) { flashError(`端口类型不兼容：${po.port_type} → ${pi.port_type}`); return; }
  if (props.edges.some(e => e.to_node === toNode && e.to_port === toPort && pi.required)) {
    flashError(`输入端口 ${toPort} 已连接（必需端口仅接受一条）`);
    return;
  }
  // 同向连线去重
  if (props.edges.some(e => e.from_node === fromNode && e.from_port === fromPort && e.to_node === toNode && e.to_port === toPort)) return;
  snapshot();
  props.edges.push({ id: `e${Date.now().toString(36)}${(uidc++).toString(36)}`, from_node: fromNode, from_port: fromPort, to_node: toNode, to_port: toPort });
  emit("change");
}

const errToast = ref("");
let errTimer: any = 0;
function flashError(msg: string) {
  errToast.value = msg;
  clearTimeout(errTimer);
  errTimer = setTimeout(() => (errToast.value = ""), 2500);
}

function onMouseUp(ev: MouseEvent) {
  const target = ev.target as HTMLElement;
  if (drag.mode === "wire") {
    const pd = target.closest("[data-port]") as HTMLElement | null;
    if (pd) {
      const toNode = pd.dataset.node!, toPort = pd.dataset.port!;
      if (drag.isOut) tryConnect(drag.node!, drag.port!, toNode, toPort);
      else tryConnect(toNode, toPort, drag.node!, drag.port!);
    }
    wireEnd.value = null;
  }
  if (drag.mode === "node") emit("change");
  drag.mode = "none";
}

function onWheel(ev: WheelEvent) {
  const f = ev.deltaY < 0 ? 1.1 : 0.9;
  const svg = svgEl.value!;
  const rect = svg.getBoundingClientRect();
  const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
  view.x = mx - (mx - view.x) * f;
  view.y = my - (my - view.y) * f;
  view.k = Math.min(2.5, Math.max(0.25, view.k * f));
}

function onKey(ev: KeyboardEvent) {
  const t = ev.target as HTMLElement;
  if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT") return;
  if (ev.key === "Delete" || ev.key === "Backspace") deleteSelection();
  else if (ev.ctrlKey && ev.key === "c") copySelection();
  else if (ev.ctrlKey && ev.key === "v") paste();
  else if (ev.ctrlKey && ev.key === "z") { ev.preventDefault(); undo(); }
  else if (ev.ctrlKey && (ev.key === "y" || (ev.shiftKey && ev.key === "Z"))) redo();
}

const wireCursor = computed(() => {
  if (!wireEnd.value || !drag.port) return "";
  const [x1, y1] = portPos(drag.node!, drag.port!, !!drag.isOut);
  return `M ${x1} ${y1} L ${wireEnd.value[0]} ${wireEnd.value[1]}`;
});

defineExpose({ addNode, snapshot, undo, redo, deleteSelection, view });
</script>

<template>
  <div class="wrap" tabindex="0" @keydown="onKey">
    <svg ref="svgEl" class="svg" @mousedown="onMouseDown" @mousemove="onMouseMove"
         @mouseup="onMouseUp" @wheel.prevent="onWheel">
      <defs>
        <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
          <path d="M 28 0 L 0 0 0 28" fill="none" stroke="#1b1b23" stroke-width="1"/>
        </pattern>
      </defs>
      <rect x="-5000" y="-5000" width="12000" height="12000" fill="url(#grid)" />
      <g :transform="`translate(${view.x},${view.y}) scale(${view.k})`">
        <!-- 边 -->
        <path v-for="e in edges" :key="e.id" :d="edgePath(e)" fill="none"
              stroke="#5a5a72" stroke-width="2" class="edge"/>
        <!-- 拖线预览 -->
        <path v-if="wireCursor" :d="wireCursor" fill="none" stroke="#5ac8fa"
              stroke-width="2" stroke-dasharray="6 4"/>
        <!-- 节点 -->
        <g v-for="n in nodes" :key="n.id" :data-node="n.id"
           :transform="`translate(${n.position[0]},${n.position[1]})`"
           :class="{ seln: sel.has(n.id), byp: n.bypassed }">
          <rect :width="W" :height="nodeH(n.node_type)" rx="9" class="nbox"/>
          <rect :width="W" :height="H_HEADER" rx="9" class="nhead"/>
          <text x="10" y="20" class="ntitle">{{ n.label }}</text>
          <text v-if="n.bypassed" :x="W - 12" y="20" class="nby">旁路</text>
          <!-- 输入端口 -->
          <g v-for="(p, i) in (specOf(n.node_type)?.inputs ?? [])" :key="'i' + p.name"
             :data-port="p.name" :data-node="n.id" data-dir="in" class="port">
            <circle :cx="0" :cy="H_HEADER + 10 + i * PORT_GAP" r="5" :fill="portColor(p.port_type)" />
            <text :x="12" :y="H_HEADER + 14 + i * PORT_GAP" class="plabel">{{ p.name }}</text>
          </g>
          <!-- 输出端口 -->
          <g v-for="(p, i) in (specOf(n.node_type)?.outputs ?? [])" :key="'o' + p.name"
             :data-port="p.name" :data-node="n.id" data-dir="out" class="port">
            <circle :cx="W" :cy="H_HEADER + 10 + i * PORT_GAP" r="5" :fill="portColor(p.port_type)" />
            <text :x="W - 10" :y="H_HEADER + 14 + i * PORT_GAP" text-anchor="end" class="plabel">{{ p.name }}</text>
          </g>
        </g>
      </g>
    </svg>
    <div v-if="errToast" class="toast">{{ errToast }}</div>
    <div class="hint muted">拖线连接 · Delete 删除 · Ctrl+C/V 复制粘贴 · Ctrl+Z/Y 撤销重做 · 滚轮缩放</div>
  </div>
</template>

<style scoped>
.wrap { position: relative; height: 100%; outline: none; }
.svg { width: 100%; height: 100%; display: block; cursor: default; }
.nbox { fill: var(--panel); stroke: var(--border); }
.nhead { fill: #20202b; stroke: var(--border); }
.nbox, .nhead { stroke-width: 1; }
.g.sel .nbox, g.seln .nbox { stroke: var(--accent); stroke-width: 2; }
g.byp .nhead { fill: #2b2b22; }
.ntitle { fill: var(--text); font-size: 12px; font-weight: 600; }
.nby { fill: var(--warn); font-size: 10px; text-anchor: end; }
.plabel { fill: var(--muted); font-size: 10px; }
.port { cursor: crosshair; }
.port:hover circle { r: 7; }
.edge:hover { stroke: var(--accent); }
.toast {
  position: absolute; top: 12px; left: 50%; transform: translateX(-50%);
  background: #42222c; color: var(--danger); border: 1px solid #6e2c3a;
  padding: 7px 16px; border-radius: 8px; font-size: 12px;
}
.hint { position: absolute; bottom: 8px; right: 12px; }
</style>
