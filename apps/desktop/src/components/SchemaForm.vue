<script setup lang="ts">
// Schema 驱动参数面板（十八.）：插件/内置节点声明 JSON Schema + ui:widget，
// 宿主自动生成控件。插件加参数不需要改前端代码。
import { computed } from "vue";

const props = defineProps<{
  schema: any;          // JSON Schema（properties 内含 ui:widget / unit / description / enum）
  modelValue: any;      // params 对象
}>();
const emit = defineEmits<{ (e: "update:modelValue", v: any): void }>();

const fields = computed(() => {
  const props_ = props.schema?.properties ?? {};
  return Object.entries(props_).map(([key, def]: [string, any]) => ({
    key,
    type: def.type ?? "string",
    widget: def["ui:widget"] ?? (def.type === "number" || def.type === "integer" ? "number"
      : def.type === "boolean" ? "checkbox" : def.enum ? "select" : "text"),
    min: def.minimum, max: def.maximum, step: def.type === "integer" ? 1 : 0.01,
    def: def.default, enum_: def.enum, unit: def.unit,
    desc: def.description, group: def["ui:group"] ?? "参数",
    runtime: def.runtime_modifiable,
    reload: def.requires_model_reload,
  }));
});
const groups = computed(() => {
  const m = new Map<string, any[]>();
  for (const f of fields.value) {
    if (!m.has(f.group)) m.set(f.group, []);
    m.get(f.group)!.push(f);
  }
  return [...m.entries()];
});

function set(key: string, v: any) {
  emit("update:modelValue", { ...props.modelValue, [key]: v });
}
</script>

<template>
  <div v-if="fields.length" class="sf">
    <section v-for="[g, fs] in groups" :key="g" class="grp">
      <div v-if="groups.length > 1" class="gtitle">{{ g }}</div>
      <div v-for="f in fs" :key="f.key" class="fld">
        <label class="flabel">
          {{ f.key }}
          <span v-if="f.unit" class="muted">({{ f.unit }})</span>
          <span v-if="f.reload" class="tag warn">需重载</span>
          <span v-else-if="f.runtime === false" class="tag">重启生效</span>
        </label>
        <div class="fctl">
          <template v-if="f.widget === 'slider'">
            <input type="range" :min="f.min ?? 0" :max="f.max ?? 1" :step="f.step"
                   :value="modelValue[f.key] ?? f.def ?? 0"
                   @input="set(f.key, Number(($event.target as HTMLInputElement).value))" />
            <span class="fval">{{ modelValue[f.key] ?? f.def ?? 0 }}</span>
          </template>
          <select v-else-if="f.widget === 'select' || f.enum_"
                  :value="modelValue[f.key] ?? f.def ?? ''"
                  @change="set(f.key, ($event.target as HTMLSelectElement).value)">
            <option v-for="o in (f.enum_ ?? [])" :key="String(o)" :value="o">{{ o }}</option>
          </select>
          <textarea v-else-if="f.widget === 'textarea'" rows="3"
                    :value="modelValue[f.key] ?? f.def ?? ''"
                    @input="set(f.key, ($event.target as HTMLTextAreaElement).value)" />
          <label v-else-if="f.widget === 'checkbox' || f.type === 'boolean'" class="chk">
            <input type="checkbox" style="width: auto"
                   :checked="Boolean(modelValue[f.key] ?? f.def)"
                   @change="set(f.key, ($event.target as HTMLInputElement).checked)" />
          </label>
          <input v-else-if="f.widget === 'number'"
                 type="number" :min="f.min" :max="f.max" :step="f.step"
                 :value="modelValue[f.key] ?? f.def ?? 0"
                 @input="set(f.key, Number(($event.target as HTMLInputElement).value))" />
          <input v-else :value="modelValue[f.key] ?? f.def ?? ''"
                 @input="set(f.key, ($event.target as HTMLInputElement).value)" />
        </div>
        <div v-if="f.desc" class="fdesc muted">{{ f.desc }}</div>
      </div>
    </section>
  </div>
  <div v-else class="muted" style="padding: 8px 0">该节点无可配置参数</div>
</template>

<style scoped>
.sf { display: flex; flex-direction: column; gap: 10px; }
.gtitle { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
.fld { margin-bottom: 8px; }
.flabel { display: flex; gap: 6px; align-items: center; font-size: 12px; margin-bottom: 3px; }
.fctl { display: flex; gap: 8px; align-items: center; }
.fval { min-width: 42px; text-align: right; font-size: 12px; color: var(--accent); }
.fdesc { font-size: 11px; margin-top: 2px; }
.chk input { width: auto; }
</style>
