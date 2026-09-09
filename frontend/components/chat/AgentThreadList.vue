<template>
  <nav class="agent-thread-list" aria-label="AI 会话列表">
    <header><strong><i class="fa-regular fa-comment-dots" aria-hidden="true" />AI 助手</strong><button type="button" aria-label="收起会话列表" @click="$emit('close')"><i class="fa-solid fa-columns" aria-hidden="true" /></button></header>
    <button type="button" class="agent-thread-new" @click="$emit('new')"><i class="fa-regular fa-pen-to-square" aria-hidden="true" />新对话</button>
    <label class="agent-thread-search"><i class="fa-solid fa-magnifying-glass" aria-hidden="true" /><input v-model="query" aria-label="搜索 AI 会话" placeholder="搜索会话" /></label>
    <div class="agent-thread-list-heading"><span>最近的会话</span><button type="button" aria-label="刷新会话列表" :disabled="loading" @click="$emit('refresh')"><i :class="loading ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-rotate-right'" aria-hidden="true" /></button></div>
    <p v-if="error" class="agent-thread-error" role="alert">{{ error }}</p>
    <div class="agent-thread-items" :aria-busy="loading">
      <p v-if="loading && !items.length" class="agent-thread-empty" role="status">正在加载会话…</p>
      <p v-else-if="!filtered.length" class="agent-thread-empty">{{ query ? '没有匹配的会话' : '还没有对话，点击上方开始。' }}</p>
      <article v-for="item in filtered" :key="item.id" class="agent-thread-item" :class="{ 'is-current': item.id === current }">
        <button type="button" class="agent-thread-select" :aria-current="item.id === current ? 'page' : undefined" :title="item.title || '新的对话'" @click="$emit('select', item)"><span>{{ item.title || '新的对话' }}</span><small>{{ nameFor(item.username) }}<i v-if="item.id === runningId" class="fa-solid fa-spinner fa-spin" aria-label="正在处理" /></small></button>
        <button type="button" class="agent-thread-more" :aria-label="`管理会话：${item.title || '新的对话'}`" :aria-expanded="menu === item.id" @click="menu = menu === item.id ? '' : item.id; editing = ''; deleting = ''"><i class="fa-solid fa-ellipsis" aria-hidden="true" /></button>
        <div v-if="menu === item.id" class="agent-thread-management" @keydown.esc.stop="menu = ''">
          <form v-if="editing === item.id" @submit.prevent="$emit('rename', item, title.trim())"><input v-model="title" aria-label="对话新名称" maxlength="100" /><button type="submit" :disabled="busy || !title.trim()">保存名称</button></form>
          <template v-else-if="deleting === item.id"><p>删除后无法恢复{{ item.id === runningId ? '，正在运行的任务也会停止' : '' }}。</p><button type="button" :disabled="busy" @click="$emit('delete', item)">确认删除对话</button><button type="button" @click="deleting = ''">取消</button></template>
          <template v-else><button type="button" @click="editing = item.id; title = item.title">重命名</button><button type="button" @click="deleting = item.id">删除对话</button></template>
        </div>
      </article>
    </div>
    <footer><button type="button" @click="$emit('settings')"><i class="fa-solid fa-sliders" aria-hidden="true" />模型与服务</button><span>对话保存在本机</span></footer>
  </nav>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
const props = defineProps({ items: { type: Array, default: () => [] }, current: String, runningId: String, loading: Boolean, busy: Boolean, error: String, nameFor: { type: Function, default: value => value } })
defineEmits(['new', 'select', 'rename', 'delete', 'refresh', 'close', 'settings'])
const query = ref(''), menu = ref(''), editing = ref(''), deleting = ref(''), title = ref('')
const filtered = computed(() => props.items.filter(item => `${item.title} ${props.nameFor(item.username)}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))
watch(() => props.busy, (busy, wasBusy) => { if (wasBusy && !busy && !props.error) menu.value = '' })
watch(() => props.current, () => { menu.value = '' })
</script>
