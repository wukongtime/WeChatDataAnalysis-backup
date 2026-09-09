<template>
  <section class="ais-agent-settings">
    <h4>Agent 查找额度</h4><p>每轮达到任一上限会暂停，保留资料并允许继续。继续查找会开始一轮新的额度。</p>
    <form @submit.prevent="save"><div class="ais-agent-limit-grid"><fieldset v-for="mode in modes" :key="mode.key"><legend>{{ mode.label }}</legend><label v-for="field in fields" :key="field.key">{{ field.label }}<input v-model.number="limits[mode.key][field.key]" type="number" :min="field.min" :max="field.max" required /></label></fieldset></div>
    <label>单次输入预算<input v-model.number="limits.input_budget" type="number" min="2048" max="1000000" required /></label><p>未知分词器时按 UTF-8 字节保守计量，默认 12,000；实际 Token 以上游返回为准。资料超出预算会分段处理，不是截取前几条。图片、扫描页和文档嵌入图片分别计数，重试计入模型请求。</p><button type="submit" class="ais-primary" :disabled="busy">{{ busy ? '保存中…' : '保存 Agent 设置' }}</button><span v-if="notice" role="status">{{ notice }}</span><p v-if="error" role="alert" class="ais-feedback is-error">{{ error }}</p></form>
  </section>
</template>
<script setup>
import { ref, onMounted } from 'vue'
const api = useAiApi(), busy = ref(false), error = ref(''), notice = ref('')
const modes = [{key:'moderate',label:'适中'},{key:'deep',label:'深入查找'}]
const fields = [{key:'tools',label:'工具调用次数',min:1,max:200},{key:'models',label:'模型请求次数',min:1,max:400},{key:'media',label:'媒体分析单元',min:1,max:200},{key:'seconds',label:'运行时间（秒）',min:30,max:3600}]
const limits = ref({moderate:{tools:12,models:24,media:8,seconds:300},deep:{tools:36,models:72,media:24,seconds:900},input_budget:12000})
const save = async () => { busy.value = true; error.value = ''; try { await api.request('/agent/settings',{method:'PUT',body:limits.value}); notice.value = 'Agent 设置已保存，新一轮提问生效。' } catch(e) { error.value = e.message } finally { busy.value = false } }
onMounted(async () => { try { limits.value = await api.request('/agent/settings') } catch(e) { error.value = e.message } })
</script>
<style scoped>
.ais-agent-settings { padding-top:20px; }
.ais-agent-settings h4 { font-size:16px; font-weight:600; }
.ais-agent-settings p { color:var(--app-text-secondary,#79828e); font-size:12px; margin:10px 0 18px; }
.ais-agent-limit-grid { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
fieldset { border:1px solid var(--app-border,#e7e9ed); border-radius:10px; padding:16px; }
legend { padding:0 7px; font-weight:600; }
label { display:flex; align-items:center; justify-content:space-between; gap:10px; font-size:12px; margin:12px 0; }
input { width:100px; border:1px solid var(--app-border,#e7e9ed); border-radius:6px; padding:7px; color:inherit; background:transparent; }
button { background:#079b57; color:white; border:0; border-radius:7px; padding:9px 14px; }
span { margin-left:12px; font-size:12px; color:#079b57; }
@media(max-width:600px) { .ais-agent-limit-grid { grid-template-columns:1fr; } }
</style>
