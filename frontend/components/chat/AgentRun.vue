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
          <i :class="item.status === 'running' ? 'fa-solid fa-spinner fa-spin' : item.status === 'completed' ? 'fa-solid fa-check' : 'fa-regular fa-circle-pause'" aria-hidden="true" />
          <span>{{ item.text.replace(/^正在/, '') }}</span>
          <small><span class="sr-only">{{ stageOutcome(item.status) }} · </span>{{ duration((item.finished_at ?? now / 1000) - item.started_at) }}</small>
        </div>
      </template>
    </div>
      <div v-if="running && !(open && compacting) && !(open && run.subtasks?.running && run.stage === '执行独立子任务')" class="agent-live-step" role="status" aria-live="polite" aria-atomic="true">
        <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
        <div><span class="agent-live-caption">AI 助手</span><span class="agent-stream-status">{{ run.stage || (run.status === 'queued' ? '等待开始处理' : '正在查找与分析') }}</span><p v-if="liveHint" class="agent-live-hint">{{ liveHint }}</p><p v-if="stageElapsed >= 30" class="agent-wait-note">这一步仍在处理中，可随时补充要求或停止。</p></div>
        <time aria-hidden="true">{{ duration(stageElapsed) }}</time>
      </div>
      <div v-show="open" class="agent-run-metadata">
        <p v-if="!running && run.analysis?.known && run.coverage_state !== 'not_applicable'" class="agent-coverage-summary">已读取 {{ run.read_count || 0 }} 条<template v-if="run.analysis.tracked !== false"> · 已提交分析 {{ run.analysis.analyzed || 0 }} 条 · {{ run.analysis.complete ? '范围处理完成' : '范围尚未处理完成' }}</template><template v-else> · 按需检索</template></p>
        <p v-else-if="!running && run.coverage_state !== 'not_applicable'" class="agent-coverage">此轮未记录完整遍历进度，范围覆盖情况未知。</p>
        <div class="agent-metadata-actions">
          <button type="button" :aria-expanded="detailsOpen" :aria-controls="`run-details-${run.id}`" @click="detailsOpen = !detailsOpen"><i :class="detailsOpen ? 'fa-solid fa-chevron-down' : 'fa-solid fa-chevron-right'" aria-hidden="true" />运行详情</button>
          <button v-if="run.coverage_state !== 'not_applicable' && (run.source_count || run.analysis?.known)" type="button" class="agent-materials-link" :aria-expanded="materialsOpen" :aria-controls="`materials-${run.id}`" @click="materialsOpen = !materialsOpen">{{ materialsOpen ? '收起来源与结果' : '来源与结果' }}<i :class="materialsOpen ? 'fa-solid fa-chevron-down' : 'fa-solid fa-chevron-right'" aria-hidden="true" /></button>
        </div>
        <div v-show="detailsOpen" :id="`run-details-${run.id}`" class="agent-run-details" role="region" aria-label="运行详情">
        <dl class="agent-detail-facts">
          <div><dt>执行统计</dt><dd>{{ toolCount }} 项操作<span v-if="run.usage || modelCalls"> · {{ modelCalls }} 次模型调用</span><span v-if="run.used?.media"> · {{ run.used.media }} 个媒体</span></dd></div>
          <div v-if="run.query_filters"><dt>聊天范围</dt><dd>{{ run.query_filters.conversations?.length || 0 }} 个聊天<span v-if="run.query_filters.sender"> · 发言人 {{ nameFor(run.query_filters.sender) }}</span></dd></div>
          <div v-if="run.time_range && (run.time_range.start != null || run.time_range.end != null)"><dt>查询时间</dt><dd>{{ date(run.time_range.start) }} — {{ date(run.time_range.end) }}</dd></div>
          <div v-if="run.intent?.message_count"><dt>读取范围</dt><dd>最近 {{ run.intent.message_count }} 条消息；不足时按实际数量。</dd></div>
          <div v-if="running && run.analysis?.known && run.coverage_state !== 'not_applicable'"><dt>范围进度</dt><dd>{{ run.analysis.tracked === false ? '按需检索' : run.analysis.complete ? '范围处理完成' : '范围尚未处理完成' }}</dd></div>
          <div v-if="run.analysis?.segments || run.analysis?.findings"><dt>分析产出</dt><dd>{{ run.analysis.segments || 0 }} 个分段结果 · {{ run.analysis.findings || 0 }} 条分析发现</dd></div>
        </dl>
        <div v-if="run.analysis?.known && run.coverage_state !== 'not_applicable'" class="agent-coverage-note">
          <button v-if="readingCoverage.length" type="button" :aria-expanded="readingCoverageOpen" :aria-controls="`reading-coverage-${run.id}`" @click="readingCoverageOpen = !readingCoverageOpen">{{ readingCoverageOpen ? '收起逐聊天覆盖' : '查看逐聊天覆盖' }}（{{ readingCoverage.length }} 个聊天）</button>
          <div v-if="readingCoverageOpen" :id="`reading-coverage-${run.id}`" role="region" aria-label="逐聊天读取覆盖">
            <p v-for="c in visibleCoverage" :key="c.username">{{ nameFor(c.username) }}：读取 {{ c.read }} 条<template v-if="run.analysis.tracked !== false">，分析 {{ c.analyzed }} 条 · {{ c.complete ? '已处理完成' : '待继续' }}</template><template v-else> · 按需检索</template><span v-if="c.warning"> · {{ c.warning }}</span></p>
            <div v-if="coveragePages > 1"><button type="button" :disabled="coveragePage === 0" @click="coveragePage--">上一页覆盖</button><span>第 {{ coveragePage + 1 }} / {{ coveragePages }} 页</span><button type="button" :disabled="coveragePage + 1 >= coveragePages" @click="coveragePage++">下一页覆盖</button></div>
          </div>
        </div>
        <p v-if="run.index_status && run.coverage_state !== 'not_applicable'" class="agent-index-note">{{ run.index_status.message }}<button v-if="!run.index_status.enabled" type="button" @click="$emit('settings')">启用本地模型</button></p>
        <div v-if="run.usage" class="agent-usage"><p v-if="running && modelCalls > run.usage.calls">Token 用量将在本轮结束后汇总。</p><p v-else>输入 {{ run.usage.input_tokens }} · 输出 {{ run.usage.output_tokens }} Token</p><p v-if="run.usage.unknown">{{ run.usage.unknown }} 次调用未返回完整用量，以上为已知部分。</p><button type="button" @click="$emit('settings')">查看用量审计</button></div>
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
const readingCoverageOpen = disclosure('readingCoverage')
// 运行详情默认折叠，并在进度刷新或切回对话时保留用户选择。
const detailsOpen = disclosure('details')
const readingCoverage = computed(() => props.run.analysis?.coverage || [])
const coveragePages = computed(() => Math.max(1, Math.ceil(readingCoverage.value.length / 20)))
// 分页和展开状态随原有对话视图保存，刷新进度不重置用户的阅读页。
const coveragePage = computed({
  get: () => Math.max(0, Math.min(coveragePages.value - 1, props.viewState[`${props.run.id}:coveragePage`] || 0)),
  set: value => { props.viewState[`${props.run.id}:coveragePage`] = value },
})
const visibleCoverage = computed(() => readingCoverage.value.slice(coveragePage.value * 20, (coveragePage.value + 1) * 20))
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
const toolCount = computed(() => records.value.filter(x=>x.kind==='tool').length)
// SSE 已推送实际调用次数，不能继续显示首次快照里尚未汇总的零值。
const modelCalls = computed(() => Math.max(props.run.used?.models || 0, props.run.usage?.calls || 0))
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
const date = value => value ? new Date(value*1000).toLocaleString() : '不限'
const toggle = () => { open.value = !open.value }
</script>
