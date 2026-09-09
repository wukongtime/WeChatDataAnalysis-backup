<template>
  <section class="agent-reply agent-run">
    <section class="agent-process-panel" :class="{ 'is-open': open, 'is-running': running }" aria-label="执行过程">
    <button class="agent-process-toggle" type="button" :aria-expanded="open" :aria-controls="`process-${run.id} usage-${run.id}`" :title="open ? '收起执行过程，仅显示回答' : '展开执行过程与用量'" @click="toggle">
      <i :class="statusIcon" aria-hidden="true" />
      <span class="agent-process-title">执行过程</span>
      <small v-if="running" class="agent-process-meta">执行中 · {{ duration(elapsed) }}</small>
      <small v-else class="agent-process-meta">{{ statusLabel }} · {{ duration(elapsed) }}<span v-if="toolCount"> · {{ toolCount }} 项操作</span></small>
      <span class="agent-process-disclosure">{{ open ? '收起' : running ? '过程' : '展开' }}</span>
      <i :class="open ? 'fa-solid fa-chevron-down' : 'fa-solid fa-chevron-right'" aria-hidden="true" />
    </button>
    <div v-show="open || running" class="agent-process-body" :class="{'is-collapsed':!open}">
    <div :id="`process-${run.id}`" v-show="open" class="agent-process" :class="{ 'is-live': running }">
      <template v-for="item in groupedRecords" :key="item.id">
        <AgentToolCall v-if="item.kind === 'tool'" :items="item.calls" :now="now" :name-for="nameFor" />
        <div v-else-if="item.kind === 'progress'" class="agent-progress-note" :class="{'is-superseded':item.status === 'superseded'}"><span class="agent-progress-caption">阶段小结</span><AgentAnswer :text="item.text" :citations="run.citations" :streaming="running" @locate="$emit('locate', $event)" /><small v-if="item.status === 'superseded'">已根据补充要求调整</small></div>
        <div v-else-if="item.kind === 'supplement'" class="agent-supplement"><p>{{ item.text }}</p><small>{{ item.status === 'applied' ? '补充要求已应用' : '已收到补充要求' }}</small></div>
        <p v-else-if="item.kind === 'notice'" class="agent-process-notice" role="status">{{ item.text }}<small v-if="item.attempt"> · 第 {{ item.attempt }} 次尝试</small></p>
        <div v-else-if="item.kind === 'answer' && item.status === 'superseded'" class="agent-progress-note is-superseded"><small>旧答案已根据补充要求调整</small></div>
        <div v-else-if="item.kind === 'status'" class="agent-stage-row" :class="`is-${item.status}`">
          <i :class="item.status === 'running' ? 'fa-solid fa-spinner fa-spin' : item.status === 'completed' ? 'fa-solid fa-check' : 'fa-regular fa-circle-pause'" aria-hidden="true" />
          <span>{{ item.text.replace(/^正在/, '') }}</span>
          <small><span class="sr-only">{{ stageOutcome(item.status) }} · </span>{{ duration((item.finished_at ?? now / 1000) - item.started_at) }}</small>
        </div>
      </template>
    </div>
      <div v-if="running" class="agent-live-step" role="status" aria-live="polite" aria-atomic="true">
        <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
        <div><span class="agent-live-caption">AI 助手</span><span class="agent-stream-status">{{ run.stage || (run.status === 'queued' ? '等待开始处理' : '正在查找与分析') }}</span><p v-if="liveHint" class="agent-live-hint">{{ liveHint }}</p><p v-if="stageElapsed >= 30" class="agent-wait-note">这一步仍在处理中，可随时补充要求或停止。</p></div>
        <time aria-hidden="true">{{ duration(stageElapsed) }}</time>
      </div>
      <details :id="`usage-${run.id}`" v-show="open" class="agent-run-metadata"><summary><i class="fa-solid fa-caret-right" aria-hidden="true" /><span>用量与读取范围<span v-if="run.usage?.calls != null"> · {{ run.usage.calls }} 次模型调用</span></span><i class="fa-solid fa-chevron-right" aria-hidden="true" /></summary><p>{{ toolCount }} 项操作<span v-if="run.usage"> · {{ run.usage.calls }} 次模型调用</span></p>
        <p v-if="running">当前步骤 {{ duration(stageElapsed) }} · 已读取 {{ run.read_count || 0 }} 条消息 · 媒体 {{ run.used?.media || 0 }}</p>
        <div v-if="run.time_range?.start != null" class="agent-query-range"><small>查询范围：{{ date(run.time_range.start) }} — {{ date(run.time_range.end) }}</small></div>
        <p v-if="run.intent?.message_count">在上述范围内，每个会话读取最近 {{ run.intent.message_count }} 条消息；不足时按实际数量。</p>
        <div v-if="run.analysis?.known" class="agent-coverage-note"><p>已读取 {{ run.read_count || 0 }} 条 · 已分析 {{ run.analysis.analyzed || 0 }} 条 · {{ run.analysis.complete ? '范围处理完成' : '范围尚未处理完成' }}</p><p v-for="c in run.analysis.coverage" :key="c.username">{{ nameFor(c.username) }}：读取 {{ c.read }} 条，分析 {{ c.analyzed }} 条 · {{ c.complete ? '已处理完成' : '待继续' }}<span v-if="c.warning"> · {{ c.warning }}</span></p><p>已生成 {{ run.analysis.segments }} 个分段结果，{{ run.analysis.findings }} 条分析发现。</p></div>
        <p v-else-if="!running" class="agent-coverage">此轮未记录完整遍历进度，范围覆盖情况未知。</p>
        <div v-if="run.usage" class="agent-usage"><p>输入 {{ run.usage.input_tokens }} · 输出 {{ run.usage.output_tokens }} Token</p><p v-if="run.usage.unknown">{{ run.usage.unknown }} 次调用未返回完整用量，以上为已知部分。</p><button type="button" @click="$emit('settings')">查看用量审计</button></div>
        <button v-if="run.source_count || run.analysis?.known" type="button" class="agent-materials-link" :aria-expanded="materialsOpen" @click="materialsOpen = !materialsOpen">{{ materialsOpen ? '收起详细结果' : '查看全部来源与详细结果' }}</button>
      </details>
    <AgentMaterials v-if="materialsOpen" v-show="open" :run="run" :name-for="nameFor" @close="materialsOpen = false" @locate="$emit('locate', $event)" />
    </div>
    </section>
    <div v-if="run.error" class="agent-error" role="alert">{{ run.error }}<details v-if="run.error_info?.diagnostic_id"><summary>诊断信息</summary><small>{{ run.error_info.category }} · {{ run.error_info.diagnostic_id }}</small></details></div>
    <div v-if="run.answer" class="agent-final-answer"><h3 class="agent-answer-heading">{{ run.status === 'completed' ? '最终回答' : running ? '正在回答' : '未完成的回答' }}</h3><AgentAnswer :text="run.answer" :citations="run.citations" :streaming="running" @locate="$emit('locate', $event)" /></div>

    <div v-if="run.choices?.length" class="agent-choices"><button v-for="choice in run.choices" :key="choice.username" type="button" @click="$emit('choose', choice)">{{ choice.name }}<small>{{ choice.username }}</small></button></div>
    <div v-if="!running || (run.answer && run.coverage_warnings?.length)" class="agent-result-actions">
      <button v-if="!running && run.answer" type="button" class="agent-copy-action" :aria-label="copied ? '已复制回答' : '复制回答'" :title="copied ? '已复制回答' : '复制回答'" @click="copy"><i :class="copied ? 'fa-solid fa-check' : 'fa-regular fa-copy'" aria-hidden="true" /></button>
      <button v-if="!running && (run.citations?.length || run.answer)" type="button" :aria-label="evidenceOpen ? '收起出处' : '查看出处'" :aria-expanded="evidenceOpen" @click="evidenceOpen = !evidenceOpen"><i class="fa-solid fa-quote-left" aria-hidden="true" />出处</button>
      <button v-if="run.answer && run.coverage_warnings?.length" type="button" class="agent-coverage-action" :aria-expanded="coverageOpen" :aria-controls="`coverage-${run.id}`" title="部分资料未读取，点击查看说明" @click="coverageOpen = !coverageOpen"><i class="fa-regular fa-circle-question" aria-hidden="true" />部分资料未读</button>
      <button v-if="!running && latest && run.error_info?.action === 'settings'" type="button" @click="$emit('settings')">检查 AI 服务</button>
      <button v-else-if="!running && latest && ['budget','failed','cancelled','interrupted'].includes(run.status)" type="button" @click="$emit('continue')"><i class="fa-solid fa-arrow-rotate-right" aria-hidden="true" />{{ run.status === 'failed' ? '重试这一步' : '继续查找' }}</button>
    </div>
    <div v-if="coverageOpen && run.answer && run.coverage_warnings?.length" :id="`coverage-${run.id}`" class="agent-coverage-explanation" role="region" aria-label="资料读取说明"><p v-for="warning in run.coverage_warnings" :key="warning">{{ warning }}</p></div>

    <AgentEvidence v-if="evidenceOpen && (run.citations?.length || run.answer)" :run="run" @locate="$emit('locate', $event)" />



  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import AgentToolCall from './AgentToolCall.vue'
import { groupTimelineTools } from '~/utils/agentTimeline'
import AgentAnswer from './AgentAnswer.vue'
import AgentEvidence from './AgentEvidence.vue'
import AgentMaterials from './AgentMaterials.vue'
const props = defineProps({run:{type:Object,required:true},now:Number,nearBottom:Boolean,latest:Boolean,nameFor:{type:Function,default:()=>''},viewState:{type:Object,required:true}})
defineEmits(['locate','choose','continue','settings'])
const copied = ref(false), evidenceOpen = ref(false)
const materialsOpen = ref(false), coverageOpen = ref(false)
const running = computed(() => ['queued','running'].includes(props.run.status))
// 尚无操作时不展开空面板；成功后聚焦回答，用户显式选择始终优先。
const open = computed({get:()=>props.viewState[props.run.id] ?? !((props.run.status === 'completed' && props.run.answer?.trim()) || (running.value && !records.value.length)),set:v=>{props.viewState[props.run.id]=v}})
// 仅去掉与入口重复的当前阶段，保留已完成的同名阶段及阶段小结。
const records = computed(() => (props.run.timeline?.length ? props.run.timeline : (props.run.activity || []).map(x=>({...x,kind:'status'}))).filter(x=>(x.kind !== 'answer' || x.status === 'superseded') && !(running.value && x.kind === 'status' && x.status === 'running' && x.text === props.run.stage)).sort((a,b)=>(a.seq||0)-(b.seq||0)))
const groupedRecords = computed(() => groupTimelineTools(records.value))
const toolCount = computed(() => records.value.filter(x=>x.kind==='tool').length)
const elapsed = computed(() => (props.run.elapsed_seconds || 0) + (running.value ? Math.max(0,props.now / 1000 - props.run.segment_started) : 0))
const stageElapsed = computed(() => Math.max(0,props.now / 1000 - (props.run.stage_started_at ?? props.run.segment_started ?? props.now / 1000)))
// 提示只来自已返回的进度，不编造模型思考或尚未完成的动作。
const liveHint = computed(() => {
  const analysis=props.run.analysis
  if(analysis?.known) return `已读取 ${props.run.read_count || 0} 条，已分析 ${analysis.analyzed || 0} 条${analysis.complete ? '，范围处理完成。' : '。'}`
  return props.run.read_count ? `已读取 ${props.run.read_count} 条消息。` : ''
})
const duration = value => { const n=Math.max(0,Math.floor(value || 0)); return n>=60 ? `${Math.floor(n/60)}分${n%60}秒` : `${n}秒` }
const stageOutcome = status => ({running:'进行中',completed:'已完成',failed:'未完成',superseded:'已调整',cancelled:'已停止',paused:'已暂停',incomplete:'未完成'}[status] || '已结束')
const date = value => value ? new Date(value*1000).toLocaleString() : '不限'
const statusLabel = computed(()=>({completed:'已完成',failed:'本次处理未完成',budget:'本轮查找已暂停',cancelled:'已停止',interrupted:'可继续处理',needs_input:'需要补充信息'}[props.run.status] || '正在处理'))
const statusIcon = computed(() => running.value ? 'fa-solid fa-wand-magic-sparkles' : props.run.status === 'completed' ? 'fa-solid fa-circle-check' : props.run.status === 'failed' ? 'fa-solid fa-circle-exclamation' : 'fa-regular fa-circle-pause')
const toggle = () => { open.value = !open.value }
const copy = async () => { try { await navigator.clipboard.writeText(props.run.answer); copied.value=true } catch { copied.value=false } }
</script>
