<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
const props = defineProps({ modelValue: { type: Object, default: () => ({}) }, profiles: { type: Array, default: () => [] }, defaultId: String, profilesLoading: Boolean, profilesError: String })
const emit = defineEmits(['update:modelValue', 'refresh'])
const api = useAiApi()
const menu = ref(null), catalogs = ref({}), errors = ref({}), loading = ref({}), manual = ref(''), manualProfile = ref('')
const profile = computed(() => props.profiles.find(p => p.id === (props.modelValue.profile_id || props.defaultId)))
const modelName = computed(() => props.modelValue.model_id || profile.value?.model || '选择模型')
// 当前配置已合并手动能力；获取上游列表不能用缺少能力的条目覆盖它。
const metadata = computed(() => modelName.value === profile.value?.model ? profile.value?.model_metadata || {} : catalogs.value[profile.value?.id]?.find(m => m.id === modelName.value) || {})
const levels = computed(() => metadata.value.reasoning_efforts || [])
const labels = { none: '无', minimal: '极低', low: '低', medium: '中', high: '高', xhigh: '极高', max: '最高' }
const choices = p => [{ id: p.model, ...p.model_metadata }, ...(catalogs.value[p.id] || []).filter(m => m.id !== p.model)]
const fetchModels = async p => {
  if (loading.value[p.id]) return
  loading.value[p.id] = true; errors.value[p.id] = ''
  try { const data = await api.request(`/profiles/${p.id}/models`); catalogs.value[p.id] = data.model_details || (data.models || []).map(id => ({ id })) }
  catch { errors.value[p.id] = '列表加载失败，仍可使用已保存模型或手动输入' }
  finally { loading.value[p.id] = false }
}
const select = (p, model) => { emit('update:modelValue', { profile_id: p.id, model_id: model, reasoning_effort: null }); menu.value.open = false }
const submitManual = () => { const p = props.profiles.find(p => p.id === manualProfile.value) || profile.value || props.profiles[0]; if (p && manual.value.trim()) select(p, manual.value.trim()) }
const closeOutside = event => {
  if (menu.value?.open && !menu.value.contains(event.target)) menu.value.open = false
}
const closeOnEscape = event => {
  if (event.key !== 'Escape' || !menu.value?.open) return
  const focusInside = menu.value.contains(document.activeElement)
  menu.value.open = false
  // 先关闭模型菜单，避免同一次 Esc 又折叠整个 AI 视图。
  event.preventDefault(); event.stopPropagation()
  if (focusInside) menu.value.querySelector('summary')?.focus()
}
onMounted(() => {
  document.addEventListener('pointerdown', closeOutside, true)
  document.addEventListener('keydown', closeOnEscape, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', closeOutside, true)
  document.removeEventListener('keydown', closeOnEscape, true)
})
</script>
<template>
  <div class="agent-model-controls">
    <details ref="menu" class="agent-model-menu">
      <summary @click="profilesError && emit('refresh')" :title="`${profile?.name || '全局默认'} · ${modelName}`" aria-label="选择服务配置与模型"><span>{{ modelName }}</span><i class="fa-solid fa-chevron-down" aria-hidden="true" /></summary>
      <div class="agent-model-popover" :aria-busy="profilesLoading"><p v-if="profilesLoading" role="status">正在加载模型配置…</p><p v-if="profilesError" role="alert">{{ profilesError }}<button type="button" @click="emit('refresh')">重试</button></p><p v-if="!profilesLoading && !profilesError && !profiles.length">请先在 AI 设置中添加服务配置。</p>
        <button type="button" @click="emit('update:modelValue', {}); menu.open = false">使用全局默认模型</button>
        <section v-for="p in profiles" :key="p.id">
          <header><strong>{{ p.name }}</strong><button type="button" :disabled="loading[p.id]" @click="fetchModels(p)">{{ loading[p.id] ? '加载中…' : '获取模型' }}</button></header>
          <p v-if="errors[p.id]" role="status">{{ errors[p.id] }}</p>
          <button v-for="m in choices(p)" :key="m.id" type="button" :aria-pressed="profile?.id === p.id && modelName === m.id" @click="select(p, m.id)">{{ m.id }}</button>
        </section>
        <form @submit.prevent="submitManual"><select v-model="manualProfile" aria-label="手动模型的服务配置"><option value="">当前服务</option><option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select><input v-model="manual" aria-label="手动模型 ID" placeholder="输入模型 ID" maxlength="200" /><button type="submit" :disabled="!manual.trim() || !profiles.length">使用</button></form>
      </div>
    </details>
    <select v-if="levels.length" class="agent-reasoning-select" aria-label="原生思考等级" :value="modelValue.reasoning_effort || ''" @change="emit('update:modelValue', { ...modelValue, reasoning_effort: $event.target.value || null })"><option value="">默认</option><option v-for="level in levels" :key="level" :value="level">{{ labels[level] || level }}</option></select>
  </div>
</template>
