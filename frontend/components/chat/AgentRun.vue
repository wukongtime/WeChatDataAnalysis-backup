<template>
  <section class="agent-reply agent-run">
    <div v-if="run.time_range?.start != null" class="agent-query-range"><small>查询范围：{{ date(run.time_range.start) }} — {{ date(run.time_range.end) }}</small></div>
    <details v-if="run.analysis?.known" class="agent-coverage-note"><summary>已读取 {{ run.read_count || 0 }} 条 · 已分析 {{ run.analysis.analyzed || 0 }} 条 · {{ run.analysis.complete ? '范围处理完成' : '范围尚未处理完成' }}</summary><p v-for="c in run.analysis.coverage" :key="c.username">{{ nameFor(c.username) }}：读取 {{ c.read }} 条，分析 {{ c.analyzed }} 条 · {{ c.complete ? '已处理完成' : '待继续' }}<span v-if="c.warning"> · {{ c.warning }}</span></p><p>已生成 {{ run.analysis.segments }} 个分段结果，{{ run.analysis.findings }} 条分析发现。</p></details>
    <p v-else-if="!running" class="agent-coverage">此轮未记录完整遍历进度，范围覆盖情况未知。</p>
    <button class="agent-process-toggle" type="button" :aria-expanded="open" @click="toggle">
      <i :class="running ? 'fa-solid fa-spinner fa-spin' : run.status === 'completed' ? 'fa-solid fa-circle-check' : 'fa-solid fa-circle-info'" aria-hidden="true"></i>
      <span>{{ running ? '正在查找与分析' : statusLabel }} · {{ open ? '收起过程' : '查看过程' }}</span>
      <i :class="open ? 'fa-solid fa-chevron-up' : 'fa-solid fa-chevron-down'" aria-hidden="true"></i>
      <small :title="`${duration(elapsed)} · ${toolCount} 次工具调用`">{{ run.usage ? `${run.usage.calls} 次调用` : duration(elapsed) }}</small>
    </button>
    <div v-show="open" class="agent-process">
    <details v-if="run.usage" class="agent-usage"><summary>本次用量 · {{ run.usage.calls }} 次模型调用</summary><p>输入 {{ run.usage.input_tokens }} · 输出 {{ run.usage.output_tokens }} Token</p><p v-if="run.usage.unknown">{{ run.usage.unknown }} 次调用未返回完整用量，以上为已知部分。</p><button type="button" @click="$emit('settings')">查看用量审计</button></details>
      <template v-for="item in records" :key="item.id">
        <details v-if="item.kind === 'tool'" class="agent-tool" :class="`is-${item.status}`">
          <summary><i :class="icon(item.status)" aria-hidden="true"></i><span>{{ item.text }}<small v-if="item.result">{{ item.cached ? '复用已读结果 · ' : '' }}{{ item.result.returned || 0 }} 条{{ item.result.has_more ? ' · 还有更多' : '' }}</small><small v-if="item.action === 'search_messages'" class="agent-retrieval-label">{{ retrievalLabel(item) }}</small></span><time>{{ duration((item.finished_at || now / 1000) - item.started_at) }}</time></summary>
          <div class="agent-tool-detail"><p v-if="item.username">会话：{{ nameFor(item.username) }}</p><p v-if="item.query">搜索：{{ item.query }}</p><p v-if="item.start || item.end">范围：{{ date(item.start) }} — {{ date(item.end) }}</p><p v-if="item.offset">分页位置：{{ item.offset }}</p><p v-if="item.detail && item.status === 'running'">{{ item.detail }}</p><p v-if="item.result?.match_counts">本页关键词命中 {{ item.result.match_counts.keyword }} 条 · 语义命中 {{ item.result.match_counts.semantic }} 条（同一消息可同时命中）</p><p v-if="item.result?.source_ids?.length">来源明细见下方“回答依据”，可查看原消息。</p><p v-if="item.result?.warning" class="agent-coverage">{{ item.result.warning }}</p><p v-if="item.result?.note">{{ item.result.note }}</p><p v-if="['failed','paused','superseded'].includes(item.status)">{{ item.status === 'failed' ? '这一步未完成，已读取资料会保留。' : item.status === 'superseded' ? '已根据补充要求调整。' : '这一步已暂停。' }}</p></div>
        </details>
        <div v-else-if="item.kind === 'progress'" class="agent-progress-note" :class="{'is-superseded':item.status === 'superseded'}"><p>{{ item.text }}</p><small v-if="item.status === 'superseded'">已根据补充要求调整</small></div>
        <div v-else-if="item.kind === 'supplement'" class="agent-supplement"><p>{{ item.text }}</p><small>{{ item.status === 'applied' ? '补充要求已应用' : '已收到补充要求' }}</small></div>
        <p v-else-if="item.kind === 'notice'" class="agent-process-notice" role="status">{{ item.text }}<small v-if="item.attempt"> · 第 {{ item.attempt }} 次尝试</small></p>
        <div v-else-if="item.kind === 'answer' && item.status === 'superseded'" class="agent-progress-note is-superseded"><small>旧答案已根据补充要求调整</small></div>
        <p v-else-if="item.kind === 'status' && item.status === 'running'" class="agent-process-notice">{{ item.text }}</p>
        <p v-else-if="!run.timeline?.length" class="agent-process-notice">{{ item.text }} · {{ duration((item.finished_at || now / 1000) - item.started_at) }}</p>
      </template>
    </div>
    <div v-if="running" class="agent-live"><strong>{{ run.stage }}</strong><small>当前步骤 {{ duration(stageElapsed) }} · 已读取 {{ run.read_count || 0 }} 条消息 · 媒体 {{ run.used?.media || 0 }}</small><p v-if="stageElapsed >= 15">这一步仍在处理中，可以补充要求或切换聊天。</p></div>
    <div v-if="run.error" class="agent-error" role="alert">{{ run.error }}<details v-if="run.error_info?.diagnostic_id"><summary>诊断信息</summary><small>{{ run.error_info.category }} · {{ run.error_info.diagnostic_id }}</small></details></div>
    <div v-if="run.answer" class="agent-final-answer"><small v-if="!running && run.status !== 'completed'">回答尚未完成</small><AgentAnswer :text="run.answer" :citations="run.citations" @locate="$emit('locate', $event)" /><details v-if="run.coverage_warnings?.length" class="agent-coverage-note"><summary><i class="fa-regular fa-circle-question" aria-hidden="true"></i>部分资料未读取 · 查看说明</summary><p v-for="warning in run.coverage_warnings" :key="warning">{{ warning }}</p></details></div>
    <div v-if="run.choices?.length" class="agent-choices"><button v-for="choice in run.choices" :key="choice.username" type="button" @click="$emit('choose', choice)">{{ choice.name }}<small>{{ choice.username }}</small></button></div>
    <div v-if="!running" class="agent-result-actions"><button v-if="run.answer" type="button" @click="copy"><i class="fa-regular fa-copy" aria-hidden="true"></i>{{ copied ? '已复制' : '复制回答' }}</button><button v-if="run.citations?.length || run.answer" type="button" :aria-expanded="evidenceOpen" @click="evidenceOpen = !evidenceOpen"><i class="fa-solid fa-quote-left" aria-hidden="true"></i>{{ evidenceOpen ? '收起出处' : '查看出处' }}</button><button v-if="latest && run.error_info?.action === 'settings'" type="button" @click="$emit('settings')">检查 AI 服务</button><button v-else-if="latest && ['budget','failed','cancelled','interrupted'].includes(run.status)" type="button" @click="$emit('continue')"><i class="fa-solid fa-arrow-rotate-right" aria-hidden="true"></i>{{ run.status === 'failed' ? '重试这一步' : '继续查找' }}</button></div>
    <AgentEvidence v-if="evidenceOpen && (run.citations?.length || run.answer)" :run="run" @locate="$emit('locate', $event)" />
    <button v-if="run.source_count || run.analysis?.known" type="button" class="agent-process-toggle" :aria-expanded="materialsOpen" @click="materialsOpen = !materialsOpen">{{ materialsOpen ? '收起详细结果' : '查看全部来源与详细结果' }}</button>
    <AgentMaterials v-if="materialsOpen" :run="run" :name-for="nameFor" @close="materialsOpen = false" @locate="$emit('locate', $event)" />

  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import AgentAnswer from './AgentAnswer.vue'
import AgentEvidence from './AgentEvidence.vue'
import AgentMaterials from './AgentMaterials.vue'
const props = defineProps({run:{type:Object,required:true},now:Number,nearBottom:Boolean,latest:Boolean,nameFor:{type:Function,default:()=>''},viewState:{type:Object,required:true}})
defineEmits(['locate','choose','continue','settings'])
const copied = ref(false), pendingCollapse = ref(false), evidenceOpen = ref(false)
const materialsOpen = ref(false)
const running = computed(() => ['queued','running'].includes(props.run.status))
const open = computed({get:()=>props.viewState[props.run.id] ?? props.run.status !== 'completed',set:v=>{props.viewState[props.run.id]=v}})
const records = computed(() => (props.run.timeline?.length ? props.run.timeline : (props.run.activity || []).map(x=>({...x,kind:'status'}))).filter(x=>x.kind !== 'answer' || x.status === 'superseded').sort((a,b)=>(a.seq||0)-(b.seq||0)))
const retrievalLabel = item => item.result?.retrieval_mode === 'hybrid' ? '智能检索：关键词＋语义（按意思查找）' : item.result?.retrieval_mode === 'keyword' ? '已退回关键词检索 · 展开查看原因' : item.status === 'running' ? '正在确认检索方式' : '此步骤未记录实际检索方式'
const toolCount = computed(() => records.value.filter(x=>x.kind==='tool').length)
const elapsed = computed(() => (props.run.elapsed_seconds || 0) + (running.value ? Math.max(0,props.now / 1000 - props.run.segment_started) : 0))
const stageElapsed = computed(() => Math.max(0,props.now / 1000 - (props.run.stage_started_at || props.now / 1000)))
const duration = value => { const n=Math.max(0,Math.floor(value || 0)); return n>=60 ? `${Math.floor(n/60)}分${n%60}秒` : `${n}秒` }
const date = value => value ? new Date(value*1000).toLocaleString() : '不限'
const statusLabel = computed(()=>({completed:'已完成',failed:'本次处理未完成',budget:'本轮查找已暂停',cancelled:'已停止',interrupted:'可继续处理',needs_input:'需要补充信息'}[props.run.status] || '正在处理'))
const icon = status => status==='running' ? 'fa-solid fa-spinner fa-spin' : status==='completed' ? 'fa-solid fa-check' : status==='failed' ? 'fa-solid fa-circle-exclamation' : 'fa-regular fa-circle-pause'
const toggle = () => { open.value=!open.value; pendingCollapse.value=false }
const copy = async () => { try { await navigator.clipboard.writeText(props.run.answer); copied.value=true } catch { copied.value=false } }
watch(()=>props.run.status,(status,old)=>{
  if (status==='completed' && ['queued','running'].includes(old)) {
    if (props.nearBottom) open.value=false
    else { open.value=true; pendingCollapse.value=true }
  } else if (status!=='completed') open.value=true
})
watch(()=>props.nearBottom,bottom=>{if(bottom && pendingCollapse.value){open.value=false;pendingCollapse.value=false}})
</script>
