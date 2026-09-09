<template>
  <section class="agent-reply agent-run">
    <button class="agent-process-toggle" type="button" :aria-expanded="open" :aria-controls="`process-${run.id} usage-${run.id}`" :title="open ? '收起执行过程，仅显示回答' : '展开执行过程与用量'" @click="toggle">
      <i :class="statusIcon" aria-hidden="true" />
      <span>{{ open ? (running ? '执行中' : statusLabel) : '查看执行过程' }} · {{ duration(elapsed) }}</span>
      <small v-if="open && toolCount">{{ toolCount }} 项操作</small>
      <i :class="open ? 'fa-solid fa-chevron-down' : 'fa-solid fa-chevron-right'" aria-hidden="true" />
    </button>
    <div :id="`process-${run.id}`" v-show="open" class="agent-process" :class="{ 'is-live': running }">
      <template v-for="item in groupedRecords" :key="item.id">
        <AgentToolCall v-if="item.kind === 'tool'" :items="item.calls" :now="now" :name-for="nameFor" />
        <div v-else-if="item.kind === 'progress'" class="agent-progress-note" :class="{'is-superseded':item.status === 'superseded'}"><AgentAnswer :text="item.text" :citations="run.citations" :streaming="running" @locate="$emit('locate', $event)" /><small v-if="item.status === 'superseded'">已根据补充要求调整</small></div>
        <div v-else-if="item.kind === 'supplement'" class="agent-supplement"><p>{{ item.text }}</p><small>{{ item.status === 'applied' ? '补充要求已应用' : '已收到补充要求' }}</small></div>
        <p v-else-if="item.kind === 'notice'" class="agent-process-notice" role="status">{{ item.text }}<small v-if="item.attempt"> · 第 {{ item.attempt }} 次尝试</small></p>
        <div v-else-if="item.kind === 'answer' && item.status === 'superseded'" class="agent-progress-note is-superseded"><small>旧答案已根据补充要求调整</small></div>
        <p v-else-if="item.kind === 'status' && item.status === 'running'" class="agent-process-notice">{{ item.text }}</p>
        <p v-else-if="!run.timeline?.length" class="agent-process-notice">{{ item.text }} · {{ duration((item.finished_at || now / 1000) - item.started_at) }}</p>
      </template>
    </div>
    <div v-if="run.error" class="agent-error" role="alert">{{ run.error }}<details v-if="run.error_info?.diagnostic_id"><summary>诊断信息</summary><small>{{ run.error_info.category }} · {{ run.error_info.diagnostic_id }}</small></details></div>
      <details :id="`usage-${run.id}`" v-show="open" class="agent-run-metadata"><summary><i class="fa-solid fa-caret-right" aria-hidden="true" /><span>用量与读取范围<span v-if="run.usage?.calls != null"> · {{ run.usage.calls }} 次模型调用</span></span><i class="fa-solid fa-chevron-right" aria-hidden="true" /></summary><p>{{ toolCount }} 项操作<span v-if="run.usage"> · {{ run.usage.calls }} 次模型调用</span></p>
        <p v-if="running">当前步骤 {{ duration(stageElapsed) }} · 已读取 {{ run.read_count || 0 }} 条消息 · 媒体 {{ run.used?.media || 0 }}</p>
        <div v-if="run.time_range?.start != null" class="agent-query-range"><small>查询范围：{{ date(run.time_range.start) }} — {{ date(run.time_range.end) }}</small></div>
        <div v-if="run.analysis?.known" class="agent-coverage-note"><p>已读取 {{ run.read_count || 0 }} 条 · 已分析 {{ run.analysis.analyzed || 0 }} 条 · {{ run.analysis.complete ? '范围处理完成' : '范围尚未处理完成' }}</p><p v-for="c in run.analysis.coverage" :key="c.username">{{ nameFor(c.username) }}：读取 {{ c.read }} 条，分析 {{ c.analyzed }} 条 · {{ c.complete ? '已处理完成' : '待继续' }}<span v-if="c.warning"> · {{ c.warning }}</span></p><p>已生成 {{ run.analysis.segments }} 个分段结果，{{ run.analysis.findings }} 条分析发现。</p></div>
        <p v-else-if="!running" class="agent-coverage">此轮未记录完整遍历进度，范围覆盖情况未知。</p>
        <div v-if="run.usage" class="agent-usage"><p>输入 {{ run.usage.input_tokens }} · 输出 {{ run.usage.output_tokens }} Token</p><p v-if="run.usage.unknown">{{ run.usage.unknown }} 次调用未返回完整用量，以上为已知部分。</p><button type="button" @click="$emit('settings')">查看用量审计</button></div>
        <button v-if="run.source_count || run.analysis?.known" type="button" class="agent-materials-link" :aria-expanded="materialsOpen" @click="materialsOpen = !materialsOpen">{{ materialsOpen ? '收起详细结果' : '查看全部来源与详细结果' }}</button>
      </details>
    <div v-if="run.answer" class="agent-final-answer"><small v-if="!running && run.status !== 'completed'">回答尚未完成</small><AgentAnswer :text="run.answer" :citations="run.citations" :streaming="running" @locate="$emit('locate', $event)" /><details v-if="run.coverage_warnings?.length" class="agent-coverage-note"><summary><i class="fa-regular fa-circle-question" aria-hidden="true"></i>部分资料未读取 · 查看说明</summary><p v-for="warning in run.coverage_warnings" :key="warning">{{ warning }}</p></details></div>
    <div v-if="running" class="agent-stream-status" role="status"><span class="agent-status-dot" aria-hidden="true"></span><span class="agent-shimmer">{{ run.stage || '正在查找与分析' }}</span><time>{{ duration(stageElapsed) }}</time></div>
    <p v-if="running && stageElapsed >= 30" class="agent-wait-note">这一步仍在处理中，可随时补充要求或停止。</p>
    <div v-if="run.choices?.length" class="agent-choices"><button v-for="choice in run.choices" :key="choice.username" type="button" @click="$emit('choose', choice)">{{ choice.name }}<small>{{ choice.username }}</small></button></div>
    <div v-if="!running" class="agent-result-actions"><button v-if="run.answer" type="button" @click="copy"><i class="fa-regular fa-copy" aria-hidden="true"></i>{{ copied ? '已复制' : '复制回答' }}</button><button v-if="run.citations?.length || run.answer" type="button" :aria-expanded="evidenceOpen" @click="evidenceOpen = !evidenceOpen"><i class="fa-solid fa-quote-left" aria-hidden="true"></i>{{ evidenceOpen ? '收起出处' : '查看出处' }}</button><button v-if="latest && run.error_info?.action === 'settings'" type="button" @click="$emit('settings')">检查 AI 服务</button><button v-else-if="latest && ['budget','failed','cancelled','interrupted'].includes(run.status)" type="button" @click="$emit('continue')"><i class="fa-solid fa-arrow-rotate-right" aria-hidden="true"></i>{{ run.status === 'failed' ? '重试这一步' : '继续查找' }}</button></div>

    <AgentEvidence v-if="evidenceOpen && (run.citations?.length || run.answer)" :run="run" @locate="$emit('locate', $event)" />

    <AgentMaterials v-if="materialsOpen" v-show="open" :run="run" :name-for="nameFor" @close="materialsOpen = false" @locate="$emit('locate', $event)" />

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
const materialsOpen = ref(false)
const running = computed(() => ['queued','running'].includes(props.run.status))
// 成功且已有回答时默认聚焦结果；显式展开或收起的选择优先于默认状态。
const open = computed({get:()=>props.viewState[props.run.id] ?? !(props.run.status === 'completed' && props.run.answer?.trim()),set:v=>{props.viewState[props.run.id]=v}})
const records = computed(() => (props.run.timeline?.length ? props.run.timeline : (props.run.activity || []).map(x=>({...x,kind:'status'}))).filter(x=>(x.kind !== 'answer' || x.status === 'superseded') && !(running.value && ['status','progress'].includes(x.kind) && x.text === props.run.stage)).sort((a,b)=>(a.seq||0)-(b.seq||0)))
const groupedRecords = computed(() => groupTimelineTools(records.value))
const toolCount = computed(() => records.value.filter(x=>x.kind==='tool').length)
const elapsed = computed(() => (props.run.elapsed_seconds || 0) + (running.value ? Math.max(0,props.now / 1000 - props.run.segment_started) : 0))
const stageElapsed = computed(() => Math.max(0,props.now / 1000 - (props.run.stage_started_at || props.now / 1000)))
const duration = value => { const n=Math.max(0,Math.floor(value || 0)); return n>=60 ? `${Math.floor(n/60)}分${n%60}秒` : `${n}秒` }
const date = value => value ? new Date(value*1000).toLocaleString() : '不限'
const statusLabel = computed(()=>({completed:'已完成',failed:'本次处理未完成',budget:'本轮查找已暂停',cancelled:'已停止',interrupted:'可继续处理',needs_input:'需要补充信息'}[props.run.status] || '正在处理'))
const statusIcon = computed(() => running.value ? 'fa-solid fa-spinner fa-spin' : props.run.status === 'completed' ? 'fa-solid fa-circle-check' : props.run.status === 'failed' ? 'fa-solid fa-circle-exclamation' : 'fa-regular fa-circle-pause')
const toggle = () => { open.value = !open.value }
const copy = async () => { try { await navigator.clipboard.writeText(props.run.answer); copied.value=true } catch { copied.value=false } }
</script>
