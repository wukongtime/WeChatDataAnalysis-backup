<template>
  <section class="agent-reply agent-run">
    <ChainOfThought v-model="open" class="agent-process-panel" :class="{ 'is-open': open, 'is-running': running }" aria-label="执行过程">
    <button class="agent-process-toggle" type="button" :aria-expanded="open" :aria-controls="`process-${run.id}`" :title="open ? '收起执行过程' : '展开执行过程与用量'" @click="toggle">
      <span class="agent-process-title">{{ running ? '执行中' : '执行过程' }}</span>
      <small class="agent-process-meta">{{ Math.floor(Math.max(0, elapsed || 0) / 60) }}分{{ Math.floor(Math.max(0, elapsed || 0)) % 60 }}秒</small>
      <i :class="open ? 'fa-solid fa-chevron-down' : 'fa-solid fa-chevron-right'" aria-hidden="true" />
    </button>
    <div v-show="open || running" class="agent-process-body" :class="{'is-collapsed':!open}">
    <div :id="`process-${run.id}`" v-show="open" class="agent-process" :class="{ 'is-live': running }">
      <AgentSubtasks v-if="(run.subtasks?.total || run.subtasks?.scanning || run.subtasks?.planned) && !firstTaskRecord" :run="run" :now="now" @locate="$emit('locate', $event)" />
      <template v-for="item in groupedRecords" :key="item.id">
        <AgentSubtasks v-if="(run.subtasks?.total || run.subtasks?.scanning || run.subtasks?.planned) && item.id === firstTaskRecord" :run="run" :now="now" @locate="$emit('locate', $event)" />
        <AgentToolCall v-else-if="item.kind === 'tool' && !(item.action === 'task' && run.subtasks?.total)" :items="item.calls" :now="now" :name-for="nameFor" :view-state="viewState" />
        <div v-else-if="item.kind === 'progress'" class="agent-progress-note" :class="{'is-superseded':item.status === 'superseded'}" role="group" aria-label="阶段性回复"><AgentAnswer :text="item.text" :citations="run.citations" :references="run.references" :streaming="item.status === 'running'" @locate="$emit('locate', $event)" /><small v-if="item.status === 'superseded'">已根据补充要求调整</small></div>
        <div v-else-if="item.kind === 'supplement'" class="agent-supplement"><p>{{ item.text }}</p><small>{{ item.status === 'applied' ? '补充要求已应用' : '已收到补充要求' }}</small></div>
        <template v-else-if="isCompaction(item)"><AgentContextCompaction v-if="open" :item="item" :run="run" :view-state="viewState" /></template>
        <p v-else-if="item.kind === 'notice'" class="agent-process-notice" role="status">{{ item.text }}<small v-if="item.attempt"> · 第 {{ item.attempt }} 次尝试</small></p>
        <div v-else-if="item.kind === 'answer' && item.status === 'superseded'" class="agent-progress-note is-superseded"><small>旧答案已根据补充要求调整</small></div>
        <div v-else-if="item.kind === 'status'" class="agent-stage-row" :class="`is-${item.status}`">
          <i v-if="item.status !== 'running'" :class="item.status === 'completed' ? 'fa-solid fa-check' : 'fa-regular fa-circle-pause'" aria-hidden="true" />
          <span :class="{ 'agent-shimmer': item.status === 'running' }">{{ item.text.replace(/^正在/, '') }}</span>
          <small><span class="sr-only">{{ stageOutcome(item.status) }} · </span>{{ duration((item.finished_at ?? now / 1000) - item.started_at) }}</small>
        </div>
      </template>
    </div>
      <div v-if="running && !(open && compacting) && !(open && run.subtasks?.running && run.stage === '执行独立子任务')" class="agent-live-step" role="status" aria-live="polite" aria-atomic="true">
        <div><span class="agent-live-caption">AI 助手</span><span class="agent-stream-status agent-shimmer">{{ run.stage || (run.status === 'queued' ? '等待开始处理' : '正在查找与分析') }}</span><p v-if="liveHint" class="agent-live-hint">{{ liveHint }}</p><p v-if="stageElapsed >= 30" class="agent-wait-note">这一步仍在处理中，可随时补充要求或停止。</p></div>
        <time aria-hidden="true">{{ duration(stageElapsed) }}</time>
      </div>
      <div v-show="open" class="agent-run-metadata">
        <p v-if="!running && run.analysis?.known && run.coverage_state !== 'not_applicable'" class="agent-coverage-summary">已读取 {{ run.read_count || 0 }} 条<template v-if="run.analysis.tracked !== false"> · 已提交分析 {{ run.analysis.analyzed || 0 }} 条 · {{ run.analysis.complete ? '范围处理完成' : '范围尚未处理完成' }}</template><template v-else> · 按需检索</template></p>
        <p v-else-if="!running && run.coverage_state !== 'not_applicable'" class="agent-coverage">此轮未记录完整遍历进度，范围覆盖情况未知。</p>
        <p v-if="run.usage" class="agent-usage" :title="run.usage.unknown ? '部分调用未返回完整用量，当前显示已知部分。' : undefined">输入 {{ usagePending ? '待汇总' : (run.usage.input_tokens ?? '未知') }} · 输出 {{ usagePending ? '待汇总' : (run.usage.output_tokens ?? '未知') }} Token</p>
        <div v-if="run.coverage_state !== 'not_applicable' && (run.source_count || run.analysis?.known)" class="agent-metadata-actions">
          <button type="button" class="agent-materials-link" :aria-expanded="materialsOpen" :aria-controls="`materials-${run.id}`" @click="materialsOpen = !materialsOpen">{{ materialsOpen ? '收起来源与结果' : '来源与结果' }}<i :class="materialsOpen ? 'fa-solid fa-chevron-down' : 'fa-solid fa-chevron-right'" aria-hidden="true" /></button>
        </div>
      </div>
    <AgentMaterials v-if="materialsOpen" v-show="open" :id="`materials-${run.id}`" :run="run" :name-for="nameFor" @close="materialsOpen = false" @locate="$emit('locate', $event)" />
    </div>
    </ChainOfThought>
    <div v-if="run.error" class="agent-error" role="alert">{{ run.error }}<details v-if="run.error_info?.diagnostic_id"><summary>诊断信息</summary><small>{{ run.error_info.category }} · {{ run.error_info.diagnostic_id }}</small></details></div>
    <div v-if="run.answer" class="agent-final-answer"><h3 class="agent-answer-heading">{{ run.status === 'completed' ? '最终回答' : running ? '正在回答' : '未完成的回答' }}</h3><AgentAnswer :text="run.answer" :citations="run.citations" :references="run.references" :streaming="running" @locate="$emit('locate', $event)" /></div>

    <div v-if="run.choices?.length" class="agent-choices"><button v-for="choice in run.choices" :key="choice.username" type="button" @click="$emit('choose', choice)">{{ choice.name }}<small>{{ choice.username }}</small></button></div>
    <div v-if="!running || (run.answer && run.coverage_warnings?.length)" class="agent-result-actions">
      <AgentCopyAction v-if="!running && run.answer" :text="run.answer" :citations="run.citations" :references="run.references" />
      <button v-if="!running && run.coverage_state !== 'not_applicable' && (run.citations?.length || run.answer)" type="button" :aria-label="evidenceOpen ? '收起出处' : '查看出处'" :aria-expanded="evidenceOpen" @click="evidenceOpen = !evidenceOpen"><i class="fa-solid fa-quote-left" aria-hidden="true" />出处</button>
      <button v-if="run.answer && run.coverage_warnings?.length" type="button" class="agent-coverage-action" :aria-expanded="coverageOpen" :aria-controls="`coverage-${run.id}`" title="部分资料未读取，点击查看说明" @click="coverageOpen = !coverageOpen"><i class="fa-regular fa-circle-question" aria-hidden="true" />部分资料未读</button>
      <button v-if="!running && latest && run.error_info?.action === 'settings'" type="button" @click="$emit('settings')">检查 AI 服务</button>
      <button v-else-if="!running && run.restart_required" type="button" @click="$emit('restart')"><i class="fa-solid fa-arrow-rotate-right" aria-hidden="true" />使用新引擎重新运行</button>
      <button v-else-if="!running && latest && run.can_resume !== false && ['budget','failed','cancelled','interrupted'].includes(run.status)" type="button" @click="$emit('continue')"><i class="fa-solid fa-arrow-rotate-right" aria-hidden="true" />{{ run.status === 'failed' ? '重试这一步' : '继续查找' }}</button>
    </div>
    <div v-if="coverageOpen && run.answer && run.coverage_warnings?.length" :id="`coverage-${run.id}`" class="agent-coverage-explanation" role="region" aria-label="资料读取说明"><p v-for="warning in run.coverage_warnings" :key="warning">{{ warning }}</p></div>

    <AgentEvidence v-if="evidenceOpen && (run.citations?.length || run.answer)" :run="run" @locate="$emit('locate', $event)" />



  </section>
</template>

<script setup>
import { computed } from 'vue'
import AgentToolCall from './AgentToolCall.vue'
import AgentSubtasks from './AgentSubtasks.vue'
import ChainOfThought from '../ai-elements/chain-of-thought/ChainOfThought.vue'
import AgentCopyAction from './AgentCopyAction.vue'
import { groupTimelineTools } from '~/utils/agentTimeline'
import AgentAnswer from './AgentAnswer.vue'
import AgentEvidence from './AgentEvidence.vue'
import AgentMaterials from './AgentMaterials.vue'
import AgentContextCompaction from './AgentContextCompaction.vue'
const props = defineProps({run:{type:Object,required:true},now:Number,nearBottom:Boolean,latest:Boolean,nameFor:{type:Function,default:()=>''},viewState:{type:Object,required:true}})
defineEmits(['locate','choose','continue','restart','settings'])
// 阅读页在切回窗口或重新挂载时复用同一份展开状态。
const disclosure = name => computed({get:()=>!!props.viewState[`${props.run.id}:${name}`],set:value=>{props.viewState[`${props.run.id}:${name}`]=value}})
const evidenceOpen = disclosure('evidence'), materialsOpen = disclosure('materials'), coverageOpen = disclosure('coverage')
const running = computed(() => ['queued','running'].includes(props.run.status))
// 有过程就默认展开，完成后不自动收起；仍保留用户手动收起的选择。
const open = computed({get:()=>props.viewState[props.run.id] ?? !(running.value && !records.value.length),set:v=>{props.viewState[props.run.id]=v}})
// 仅去掉与入口重复的当前阶段，保留已完成的同名阶段及阶段小结。
const records = computed(() => (props.run.timeline?.length ? props.run.timeline : (props.run.activity || []).map(x=>({...x,kind:'status'}))).filter(x=>(x.kind !== 'answer' || x.status === 'superseded') && !(running.value && x.kind === 'status' && x.status === 'running' && x.text === props.run.stage)).sort((a,b)=>(a.seq||0)-(b.seq||0)))
const groupedRecords = computed(() => groupTimelineTools(records.value))
const isCompaction = item => item.kind === 'notice' && item.context_job?.id && Number.isFinite(item.context_job.before)
const compactions = computed(() => records.value.filter(isCompaction))
const compacting = computed(() => compactions.value.some(item => item.context_job.status === 'running' && (item.input_version ?? props.run.version) === props.run.version))
const firstTaskRecord = computed(() => groupedRecords.value.find(item => item.kind === 'tool' && item.action === 'task')?.id)
// 尚未汇总的模型调用不显示成零 Token。
const modelCalls = computed(() => Math.max(props.run.used?.models || 0, props.run.usage?.calls || 0))
const usagePending = computed(() => running.value && modelCalls.value > (props.run.usage?.calls || 0))
const elapsed = computed(() => (props.run.elapsed_seconds || 0) + (running.value ? Math.max(0,props.now / 1000 - props.run.segment_started) : 0))
const stageElapsed = computed(() => Math.max(0,props.now / 1000 - (props.run.stage_started_at ?? props.run.segment_started ?? props.now / 1000)))
// 提示只来自已返回的进度，不编造模型思考或尚未完成的动作。
const liveHint = computed(() => {
  if (props.run.subtasks?.running) return `正在执行 ${props.run.subtasks.running} 个子任务，已完成 ${props.run.subtasks.completed || 0}/${props.run.subtasks.total}；展开子任务可查看各自进度。`
  const scan = [...(props.run.timeline || [])].reverse().find(item => item.input_version === props.run.version && item.result?.realtime_coverage)?.result.realtime_coverage
  if (scan && props.run.stage?.includes('搜索')) return `实时回查已检查 ${scan.scanned} 条，匹配 ${scan.matched} 条。`
  const analysis=props.run.analysis
  if(analysis?.known && analysis.tracked === false) return `已读取 ${props.run.read_count || 0} 条，按需检索。`
  if(analysis?.known) return `已读取 ${props.run.read_count || 0} 条，已提交分析 ${analysis.analyzed || 0} 条${analysis.complete ? '，范围处理完成。' : '。'}`
  return props.run.read_count ? `已读取 ${props.run.read_count} 条消息。` : ''
})
const duration = value => { const n=Math.max(0,Math.floor(value || 0)); return n>=60 ? `${Math.floor(n/60)}分${n%60}秒` : `${n}秒` }
const stageOutcome = status => ({running:'进行中',completed:'已完成',failed:'未完成',superseded:'已调整',cancelled:'已停止',paused:'已暂停',incomplete:'未完成'}[status] || '已结束')
const toggle = () => { open.value = !open.value }
</script>
