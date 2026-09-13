<template>
  <details class="agent-subtasks" :open="opened" @toggle="toggle">
    <summary>{{ run.subtasks.total > 1 ? '并行分析' : '子任务分析' }} · {{ run.subtasks.completed }}/{{ run.subtasks.total }} 已完成<span v-if="run.subtasks.failed"> · {{ run.subtasks.failed }} 未完成</span></summary>
    <p v-if="error" role="alert">{{ error }} <button type="button" @click="load()">重试</button></p>
    <p v-if="loading && !items.length" role="status">正在读取子任务…</p>
    <ul>
      <li v-for="item in items" :key="item.id">
        <div class="subtask-heading"><strong>{{ item.name }}</strong><small>{{ labels[item.status] || item.status }} · {{ elapsed(item) }}</small></div>
        <p v-if="item.status === 'running' || item.status === 'queued'" class="subtask-action"><i v-if="item.status === 'running'" class="fa-solid fa-spinner fa-spin" aria-hidden="true" />{{ item.current_action || item.stage || labels[item.status] }}<small v-if="item.action_started_at"> · {{ duration(actionSeconds(item)) }}</small></p>
        <p v-if="item.latest_progress?.text" class="subtask-progress">{{ item.latest_progress.text }}</p>
        <p v-if="item.coverage?.read != null" class="subtask-counts">已读取 {{ item.coverage.read }} 条 · 已分析 {{ item.coverage.analyzed || 0 }} 条<span v-if="item.coverage.complete"> · 范围已处理完成</span></p>
        <p v-if="item.model_running && actionSeconds(item) >= 30" class="subtask-wait">模型尚未返回本轮结果，上一条进展距今 {{ duration(sinceActivity(item)) }}。</p>
        <p v-if="item.error" role="alert">{{ item.error }}</p>
        <details>
          <summary>查看任务与最近记录</summary>
          <p v-if="item.objective">{{ item.objective }}</p>
          <ol v-if="item.activity?.length" class="subtask-history"><li v-for="entry in item.activity" :key="entry.id"><span>{{ entry.text }}</span><small v-if="entry.kind === 'tool'">{{ toolLabels[entry.status] || entry.status }}</small></li></ol>
          <p v-if="item.usage">{{ item.usage.calls }} 次模型调用 · 输入 {{ item.usage.input_tokens }} / 输出 {{ item.usage.output_tokens }} Token<span v-if="item.usage.unknown"> · {{ item.usage.unknown }} 次用量未知</span></p>
          <p v-for="(finding, index) in findings[item.id] || item.findings || []" :key="index">{{ finding.text }}
            <button v-for="source in finding.sources" :key="source" type="button" :disabled="locating" @click="locate(source)">查看来源</button>
          </p>
          <button v-if="item.result_handle && more[item.id] !== false" type="button" :disabled="loading" @click="details(item)">{{ findings[item.id] ? '更多发现' : '查看详细发现' }}</button>
        </details>
      </li>
    </ul>
    <button v-if="hasMore" type="button" :disabled="loading" @click="load(true)">更多子任务</button>
  </details>
</template>

<script setup>
import { ref, watch, onUnmounted } from 'vue'
import { useAiApi } from '~/composables/useAiApi'
const props = defineProps({ run: { type: Object, required: true }, now: Number })
const emit = defineEmits(['locate'])
const api = useAiApi(), items = ref([]), findings = ref({}), more = ref({})
const loading = ref(false), error = ref(''), hasMore = ref(false), opened = ref(['queued', 'running'].includes(props.run.status)), locating = ref(false)
const labels = { queued:'等待执行', running:'分析中', completed:'已完成', failed:'未完成', interrupted:'已暂停', superseded:'已更新范围' }
const toolLabels = { running:'进行中', completed:'已完成', failed:'未成功', paused:'已暂停' }
let generation = 0, disposed = false, timer, refreshTimer
const scheduleRefresh = () => {
  clearTimeout(refreshTimer)
  if (!disposed && opened.value && ['queued', 'running'].includes(props.run.status)) {
    refreshTimer = setTimeout(() => load(), 3000)
  }
}
const identity = () => `${props.run.account}:${props.run.id}:${props.run.version}`
const duration = value => { const seconds = Math.max(0, Math.round(value)); return seconds < 60 ? `${seconds}秒` : `${Math.floor(seconds / 60)}分${seconds % 60}秒` }
const actionSeconds = item => Math.max(0, (props.now || Date.now()) / 1000 - (item.action_started_at || (props.now || Date.now()) / 1000))
const sinceActivity = item => Math.max(0, (props.now || Date.now()) / 1000 - (item.last_activity_at || item.started_at || (props.now || Date.now()) / 1000))
const elapsed = item => duration(item.elapsed_seconds ?? ((item.finished_at || (props.now || Date.now()) / 1000) - (item.started_at || (props.now || Date.now()) / 1000)))
const load = async (append = false) => {
  if (loading.value) return
  const key = identity(), revision = ++generation, startedStatus = props.run.status
  loading.value = true; error.value = ''
  try {
    const value = await api.request(`/agent/runs/${props.run.id}/subtasks`, { query: { account:props.run.account, version:props.run.version, offset:append ? items.value.length : 0, limit:20 } })
    if (disposed || identity() !== key || revision !== generation) return
    items.value = append ? [...items.value, ...value.items] : value.items
    hasMore.value = value.has_more
  } catch (e) { if (!disposed && identity() === key) error.value = `子任务加载失败：${e.message}` }
  finally { if (revision === generation) { loading.value = false; if (opened.value && startedStatus !== props.run.status) void load(); else scheduleRefresh() } }
}
const details = async item => {
  const key = identity()
  try {
    const result = await api.request(`/agent/runs/${props.run.id}/subtasks/${item.id}`, {query:{account:props.run.account,version:props.run.version,offset:findings.value[item.id]?.length || 0}})
    if (!disposed && identity() === key) { findings.value[item.id] = [...(findings.value[item.id] || []), ...result.items]; more.value[item.id] = result.has_more }
  } catch(e) { if (!disposed && identity() === key) error.value = e.message }
}
const locate = async source => {
  const key = identity(); locating.value = true
  try {
    const result = await api.request(`/agent/runs/${props.run.id}/materials/${source}`, {query:{account:props.run.account,version:props.run.version}})
    if (!disposed && identity() === key) emit('locate', result)
  } catch(e) { if (!disposed && identity() === key) error.value = e.message }
  finally { if (identity() === key) locating.value = false }
}
const toggle = event => { if (event.target !== event.currentTarget) return; const changed = opened.value !== event.target.open; opened.value = event.target.open; clearTimeout(refreshTimer); if (opened.value) { if (changed) void load(); else scheduleRefresh() } }
watch(identity, () => { ++generation; loading.value = false; items.value = []; findings.value = {}; more.value = {}; error.value = ''; if (opened.value) void load() }, { immediate: true })
watch(() => JSON.stringify(props.run.subtasks), () => { clearTimeout(timer); if (opened.value) timer = setTimeout(() => load(), 250) })
watch(() => props.run.status, status => { clearTimeout(refreshTimer); if (opened.value && !['queued', 'running'].includes(status)) void load(); else scheduleRefresh() })
onUnmounted(() => { disposed = true; ++generation; clearTimeout(timer); clearTimeout(refreshTimer) })
</script>

<style scoped>
.agent-subtasks { margin-block: 12px; padding-block: 8px; border-block: 1px solid var(--app-border, #ddd); font-size: 13px; line-height: 1.6; }
summary { cursor: pointer; overflow-wrap: anywhere; }
ul { list-style: none; padding: 0; margin: 8px 0; }
li { padding-block: 8px; }
small { color: var(--app-text-secondary, #666); }
.subtask-heading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; }
.subtask-heading strong { font-weight: 500; overflow-wrap: anywhere; }
.subtask-action { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px; }
.subtask-action i { color: var(--app-accent, #16854b); }
.subtask-progress { font-size: 14px; line-height: 1.75; white-space: pre-wrap; }
.subtask-counts, .subtask-wait, li > details > summary { color: var(--app-text-secondary, #666); font-size: 12px; }
li > details { margin-top: 10px; }
.subtask-history { padding-left: 20px; margin: 10px 0; }
.subtask-history li { padding-block: 4px; overflow-wrap: anywhere; }
.subtask-history small { margin-left: 8px; }
p { margin-block: 6px; overflow-wrap: anywhere; }
button { color: var(--app-text-primary, #333); text-decoration: underline; margin-inline-end: 8px; }
button:disabled { opacity: .5; cursor: wait; }
button:focus-visible, summary:focus-visible { outline: 2px solid var(--app-accent, #16854b); outline-offset: 3px; }
</style>
