<template>
  <div ref="answer" class="agent-answer">
    <div class="agent-markdown" v-html="rendered" @click="onCitation" />
    <div v-if="selected" :key="selected.source" :id="previewId" ref="preview" popover="auto" class="agent-citation-preview" role="dialog" aria-label="消息来源预览" @toggle="onToggle" @keydown.esc.stop.prevent="closePreview(true)">
      <header><div><small>来源 {{ selectedNumber }}</small><strong>{{ selected.name || selected.username }}</strong></div><button type="button" aria-label="关闭来源预览" @click="closePreview(true)"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button></header>
      <small>{{ selected.sender }} · {{ new Date(selected.time * 1000).toLocaleString() }}</small>
      <p class="agent-citation-text">{{ selected.text }}</p>
      <p v-if="locateError" class="agent-citation-error" role="alert">{{ locateError }}</p>
      <button type="button" class="agent-citation-locate" :disabled="locating" :aria-busy="locating" :aria-label="locating ? '正在定位原消息' : locateError ? '重试定位原消息' : '定位原消息'" @click="locateSelected">
        <i :class="locating ? 'fa-solid fa-spinner fa-spin' : located ? 'fa-solid fa-check' : 'fa-solid fa-arrow-up-right-from-square'" aria-hidden="true"></i>
        <span role="status">{{ locating ? '正在定位…' : located ? '已定位原消息' : locateError ? '重试定位' : '定位原消息' }}</span>
      </button>
    </div>
  </div>
</template>
<script setup>
import { computed, inject, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { renderAgentMarkdown } from '~/utils/agentMarkdown'
const props = defineProps({ text: { type: String, default: '' }, citations: { type: Array, default: () => [] }, streaming: Boolean })
const emit = defineEmits(['locate'])
const navigation = inject('agentSourceNavigation', null)
const answer = ref(null), preview = ref(null), selected = ref(null)
const previewId = `agent-source-${useId()}`
const selectedNumber = ref(0), locating = ref(false), located = ref(false), locateError = ref('')
let trigger = null, observer = null, revision = 0
// 原始 HTML、远程图片和自动链接均禁用；只渲染本地已核验的来源按钮。
const rendered = computed(() => renderAgentMarkdown(props.text, props.citations, props.streaming))
const closePreview = (restoreFocus = false) => {
  ++revision
  observer?.disconnect(); observer = null
  window.removeEventListener('scroll', positionPreview, true)
  window.removeEventListener('resize', positionPreview)
  trigger?.setAttribute('aria-expanded', 'false')
  trigger?.removeAttribute('aria-controls')
  if (restoreFocus && trigger?.isConnected) trigger.focus({ preventScroll: true })
  selected.value = null
  trigger = null
}
const positionPreview = () => {
  const el = preview.value
  if (!el || !trigger) return
  if (!trigger.isConnected) { closePreview(); return }
  const rect = trigger.getBoundingClientRect()
  const container = answer.value.closest('.agent-conversation')?.getBoundingClientRect()
  const top = Math.max(8, container?.top ?? 8), bottom = Math.min(window.innerHeight - 8, container?.bottom ?? window.innerHeight - 8)
  const left = Math.max(8, container?.left ?? 8), right = Math.min(window.innerWidth - 8, container?.right ?? window.innerWidth - 8)
  if (rect.bottom < top || rect.top > bottom || rect.right < left || rect.left > right) { closePreview(); return }
  // 浏览器顶层浮层不受表格、滚动容器裁切；根据编号附近的空间向上或向下展开。
  el.style.width = `${Math.min(320, right - left)}px`
  const below = bottom - rect.bottom - 8, above = rect.top - top - 8
  const text = el.querySelector('.agent-citation-text')
  const naturalHeight = el.scrollHeight + Math.max(0, (text?.scrollHeight || 0) - (text?.clientHeight || 0))
  const showBelow = below >= Math.min(naturalHeight, 320) || below >= above
  el.style.maxHeight = `${Math.max(0, showBelow ? below : above)}px`
  el.style.left = `${Math.max(left, Math.min(rect.left, right - el.offsetWidth))}px`
  el.style.top = `${showBelow ? rect.bottom + 8 : Math.max(top, rect.top - el.offsetHeight - 8)}px`
}
const onToggle = event => { if (event.newState === 'closed' && event.target === preview.value) closePreview() }
const onCitation = async event => {
  const button = event.target.closest('button[data-source]')
  const source = props.citations.find(c => c.source === button?.dataset.source)
  if (!source) return
  // 大视图使用统一的出处栏，窄侧栏继续使用编号旁的浮层。
  if (navigation?.inspect?.(source, Number(button.textContent), button)) {
    closePreview()
    return
  }
  if (trigger === button && selected.value) { closePreview(true); return }
  closePreview()
  trigger = button
  selected.value = source; selectedNumber.value = Number(button.textContent)
  locating.value = false; located.value = false; locateError.value = ''
  const current = revision
  // 只在用户展开来源时预读，失败由实际定位时重试，不打断阅读。
  Promise.resolve().then(() => navigation?.prepare?.(source)).catch(() => {})
  await nextTick()
  if (current !== revision || !preview.value) return
  button.setAttribute('aria-expanded', 'true'); button.setAttribute('aria-controls', previewId)
  preview.value.showPopover?.()
  positionPreview()
  if (!selected.value) return
  window.addEventListener('scroll', positionPreview, true)
  window.addEventListener('resize', positionPreview)
  observer = new ResizeObserver(positionPreview)
  observer.observe(preview.value)
  const container = answer.value.closest('.agent-conversation')
  if (container) observer.observe(container)
  preview.value.querySelector('button')?.focus({ preventScroll: true })
}
const locateSelected = async () => {
  if (locating.value || !selected.value) return
  const current = revision, source = selected.value
  locating.value = true; locateError.value = ''
  try {
    if (navigation?.locate) {
      const result = await navigation.locate(source)
      if (result === false) throw new Error('定位未完成，请重试')
      if (current === revision) located.value = true
    } else emit('locate', source)
  } catch (error) {
    if (current === revision) locateError.value = error?.message || '暂时无法定位，请重试'
  } finally {
    if (current === revision) { locating.value = false; await nextTick(); positionPreview() }
  }
}
watch(() => props.text, () => { if (selected.value) closePreview() })
onBeforeUnmount(() => closePreview())
</script>
