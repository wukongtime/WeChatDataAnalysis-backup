<template>
  <details class="agent-tool" :class="`is-${status}`">
    <summary>
      <i :class="icon" aria-hidden="true" />
      <span class="agent-tool-title"><span class="agent-tool-label">{{ first.text || toolLabel(first.action) }}</span><small v-if="first.query" class="agent-tool-query">{{ first.query }}</small><small v-if="items.length > 1" class="agent-tool-count">· {{ items.length }} 次</small></span>
      <span v-if="status !== 'completed'" class="agent-tool-outcome">{{ outcome(status) }}</span>
      <i class="fa-solid fa-chevron-right agent-tool-chevron" aria-hidden="true" />
    </summary>
    <div class="agent-tool-detail">
      <section v-for="(item, index) in items" :key="item.id" class="agent-tool-attempt">
        <header><strong>{{ items.length > 1 ? `第 ${index + 1} 次 · ` : '' }}{{ item.cached ? '复用已读结果' : toolLabel(item.action) }}</strong><span>{{ outcome(item.status) }} · {{ duration((item.finished_at || now / 1000) - item.started_at) }}</span></header>
        <p v-if="item.username">会话：{{ nameFor(item.username) }}</p>
        <p v-if="item.query">搜索：{{ item.query }}</p>
        <p v-if="item.start || item.end">范围：{{ date(item.start) }} — {{ date(item.end) }}</p>
        <p v-if="item.offset">分页位置：{{ item.offset }}</p>
        <p v-if="item.detail && item.status === 'running'">{{ item.detail }}</p>
        <p v-if="item.result">{{ item.cached ? '复用已读结果 · ' : '' }}{{ item.result.returned ?? 0 }} 条结果{{ item.result.has_more ? ' · 还有更多' : '' }}</p>
        <p v-if="item.action === 'search_messages'" class="agent-retrieval-label">{{ retrievalLabel(item) }}</p>
        <p v-if="item.result?.match_counts">本页关键词命中 {{ item.result.match_counts.keyword }} 条 · 语义命中 {{ item.result.match_counts.semantic }} 条（同一消息可同时命中）</p>
        <p v-if="item.result?.source_ids?.length">来源明细可在“查看出处”中核对原消息。</p>
        <p v-if="item.result?.warning" class="agent-coverage">{{ item.result.warning }}</p>
        <p v-if="item.result?.note">{{ item.result.note }}</p>
        <p v-if="['failed','paused','superseded'].includes(item.status)">{{ item.status === 'failed' ? '这一步未完成，已读取资料会保留。' : item.status === 'superseded' ? '已根据补充要求调整。' : '这一步已暂停。' }}</p>
      </section>
    </div>
  </details>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ items: { type: Array, required: true }, now: Number, nameFor: { type: Function, default: () => '' } })
const first = computed(() => props.items[0])
// 合并记录仍显露失败、运行或暂停状态，不能把部分完成显示为全部成功。
const status = computed(() => ['failed', 'running', 'paused', 'cancelled', 'interrupted', 'superseded'].find(status => props.items.some(item => item.status === status)) || first.value.status)
const icon = computed(() => status.value === 'running' ? 'fa-solid fa-spinner fa-spin' : status.value === 'failed' ? 'fa-solid fa-circle-exclamation' : status.value !== 'completed' ? 'fa-regular fa-circle-pause' : first.value.action?.includes('search') ? 'fa-solid fa-magnifying-glass' : first.value.action === 'analyze_media' ? 'fa-regular fa-images' : 'fa-regular fa-file-lines')
const toolLabel = action => ({ search_messages: '搜索聊天记录', read_messages: '读取消息', read_context: '读取上下文', analyze_media: '分析媒体', find_conversations: '查找会话', search_material: '搜索附件内容', read_material: '读取附件', read_results: '读取分析结果' }[action] || '工具调用')
const outcome = status => ({ completed: '已完成', running: '进行中', failed: '失败', paused: '已暂停', cancelled: '已停止', interrupted: '已中断', superseded: '已调整' }[status] || '')
const duration = value => { const n = Math.max(0, Math.floor(value || 0)); return n >= 60 ? `${Math.floor(n / 60)}分${n % 60}秒` : `${n}秒` }
const date = value => value ? new Date(value * 1000).toLocaleString() : '不限'
const retrievalLabel = item => item.result?.retrieval_mode === 'hybrid' ? '智能检索：关键词＋语义（按意思查找）' : item.result?.retrieval_mode === 'keyword' ? '已退回关键词检索 · 展开查看原因' : item.status === 'running' ? '正在确认检索方式' : '此步骤未记录实际检索方式'
</script>
