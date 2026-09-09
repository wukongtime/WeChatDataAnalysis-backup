<template>
  <div class="ai-settings" :inert="dialogStep ? true : undefined">
    <header class="ais-heading">
      <div class="ais-heading-icon"><i class="fa-solid fa-wand-magic-sparkles" aria-hidden="true"></i></div>
      <div><h3>AI 服务</h3><p>管理 AI 模型、本地搜索与对话体验。</p></div>
      <span class="ais-local"><i class="fa-solid fa-lock" aria-hidden="true"></i> {{ activeTab==='local' ? '搜索在本机运行' : '密钥本机保存' }}</span>
    </header>

    <div class="ais-tabs" role="tablist" aria-label="AI 服务页面">
      <button v-for="tab in settingsTabs" :key="tab.id" :id="`ais-${tab.id}-tab`" type="button" role="tab"
        :aria-selected="activeTab === tab.id" :aria-controls="`ais-${tab.id}`" :tabindex="activeTab===tab.id ? 0 : -1"
        @click="activeTab=tab.id" @keydown="navigateTabs($event,tab.id)">
        <i class="fa-solid" :class="tab.icon" aria-hidden="true"></i><span class="ais-tab-copy"><strong>{{ tab.label }}</strong><small>{{ tab.hint }}</small></span>
      </button>
    </div>
    <AgentSettings v-if="activeTab === 'agent'" id="ais-agent" role="tabpanel" aria-labelledby="ais-agent-tab" />
    <LocalSearchSettings v-if="activeTab === 'local'" id="ais-local" role="tabpanel" aria-labelledby="ais-local-tab" />
    <p v-if="error" role="alert" class="ais-feedback is-error">{{ error }}</p>
    <p v-if="notice" role="status" class="ais-feedback is-success"><i class="fa-solid fa-circle-check" aria-hidden="true"></i>{{ notice }}</p>

    <div id="ais-config" v-show="activeTab === 'config'" role="tabpanel" aria-labelledby="ais-config-tab">
      <div class="ais-defaults">
        <label><span><i class="fa-regular fa-file-lines" aria-hidden="true"></i>默认文本模型</span><UiSelect v-model="defaults.text" label="默认文本模型" plain :options="profileOptions(false)" placeholder="选择配置" @change="saveDefaults" /></label>
        <label><span><i class="fa-regular fa-image" aria-hidden="true"></i>默认视觉模型</span><UiSelect v-model="defaults.vision" label="默认视觉模型" plain :options="profileOptions(true)" placeholder="选择配置" @change="saveDefaults" /></label>
      </div>

      <div class="ais-profilebar">
        <div><h4>已连接的服务</h4><p class="ais-muted">统一管理聊天总结与关注提醒使用的模型。</p></div>
        <button type="button" class="ais-add" :disabled="busy" @click="startNew"><i class="fa-solid fa-plus" aria-hidden="true"></i>新增服务</button>
      </div>
      <div class="ais-service-list">
        <button v-for="p in profiles" :key="p.id" type="button" class="ais-service-card" :disabled="busy" :aria-label="`编辑 ${p.name}`" @click="edit(p)">
          <AiProviderIcon :provider="p.provider" />
          <span class="ais-service-copy"><strong>{{ p.name }}</strong><small>{{ p.model }}</small></span>
          <span v-if="p.vision" class="ais-tag">支持图片</span><i class="fa-solid fa-chevron-right" aria-hidden="true"></i>
        </button>
        <div v-if="!profiles.length" class="ais-empty"><i class="fa-solid fa-plug" aria-hidden="true"></i><h4>连接你的第一个 AI 服务</h4><p>选择服务商，填写密钥，即可获取可用模型。</p></div>
      </div>
      <p class="ais-footnote">密钥仅保存在本机。分析内容将发送至你选择的服务。</p>

      <Teleport to="body">
      <div v-if="dialogStep" class="ais-dialog-overlay" @click.self="closeDialog" @keydown.stop="onDialogKeydown">
      <section ref="dialogPanel" class="ai-settings ais-dialog" :class="{ 'ais-provider-picker': dialogStep === 'providers' }" role="dialog" aria-modal="true" aria-labelledby="ais-dialog-title" tabindex="-1">
        <header class="ais-dialog-heading"><div><h3 id="ais-dialog-title">{{ dialogStep === 'providers' ? '选择 AI 服务' : editId ? '编辑 AI 服务' : '添加 AI 服务' }}</h3><p>{{ dialogStep === 'providers' ? '选择服务商，也可以连接兼容接口的自定义服务。' : '连接服务后，从上游获取并选择可用模型。' }}</p></div><button type="button" class="ais-icon-button" aria-label="关闭服务弹窗" :disabled="busy" @click="closeDialog"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button></header>
        <template v-if="dialogStep === 'providers'">
          <label class="ais-provider-search"><span class="ais-sr-only">搜索 AI 服务</span><i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i><input v-model="providerSearch" type="search" placeholder="搜索服务名称，例如：谷歌、千问、火山" /></label>
          <div class="ais-provider-grid">
            <button v-for="p in filteredPresets" :key="p.provider" type="button" class="ais-provider-choice" @click="chooseProvider(p.provider)"><AiProviderIcon :provider="p.provider" /><span><strong>{{ providerInfo(p.provider)?.label || p.name }}</strong><small>{{ providerInfo(p.provider)?.caption || providerHint(p.provider) }}</small></span><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button>
          </div>
          <div v-if="!filteredPresets.length" class="ais-empty" role="status"><p>没有匹配的 AI 服务，试试其他名称。</p><button type="button" @click="providerSearch = ''">清空搜索</button></div>
        </template>
        <template v-else>
        <p v-if="error" role="alert" class="ais-feedback is-error">{{ error }}</p>
        <p v-if="notice" role="status" class="ais-feedback is-success">{{ notice }}</p>
      <form class="ais-editor" @submit.prevent="save">
        <div class="ais-editor-heading">
          <div class="ais-selected-provider"><AiProviderIcon :provider="form.provider" /><div><h4>{{ presets.find(p => p.provider === form.provider)?.name || form.provider }}</h4><span>{{ providerHint(form.provider) }}</span></div></div>
          <button type="button" class="ais-change-provider" :disabled="busy" @click="showProviders">更换服务商</button>
        </div>
        <div class="ais-form-body">
          <div class="ais-connection">
          <div class="ais-fields">
            <label>配置名称<input v-model.trim="form.name" required maxlength="80" placeholder="例如：日常总结" /></label>
            <label>接口协议<UiSelect v-model="form.protocol" label="接口协议" :options="protocolOptions" /></label>
          </div>
          <div class="ais-fields ais-address-row">
            <label>API 地址<input v-model.trim="form.base_url" class="ais-mono" required type="url" placeholder="https://…" @blur="autoFetchModels" /></label>
          </div>
          <label class="ais-key-label"><span>API 密钥 <span v-if="editId && form.has_key && !key" class="ais-tag">已保存</span></span><input v-model="key" type="password" autocomplete="new-password" :placeholder="editId && !credentialsReset ? '留空保留已有密钥' : '输入 API 密钥，本地服务可留空'" @blur="autoFetchModels" /></label>
          <p v-if="isLocalService" class="ais-muted">请先启动本地服务并准备好模型；未启用鉴权时，API 密钥可留空。</p>

          </div>
          <div class="ais-model-config">
          <div class="ais-model-section">
            <div class="ais-section-heading">
              <div><h5>使用模型</h5><span v-if="models.length && !modelError">已从上游获取 {{ models.length }} 个模型</span><span v-else>模型列表直接来自你的服务商</span></div>
              <button type="button" class="ais-refresh" :disabled="busy || modelsLoading || !form.base_url" @click="getModels"><i class="fa-solid fa-arrows-rotate" :class="{ 'fa-spin': modelsLoading }" aria-hidden="true"></i>{{ modelsLoading ? '获取中…' : '从上游获取' }}</button>
            </div>
            <p v-if="modelError" role="alert" class="ais-feedback is-error">{{ modelError }}</p>
            <template v-if="!manualModel">
              <div class="ais-model-controls">
                <UiSelect v-model="form.model" label="选择模型" mono :disabled="modelsLoading || !models.length" :options="modelOptions" :placeholder="modelsLoading ? '正在加载模型…' : isLocalService ? '启动本地服务后，从上游获取模型' : '填写密钥后，从上游获取模型'" @change="selectModel" />
                <label v-if="models.length" class="ais-model-search"><span class="ais-sr-only">搜索模型</span><i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i><input v-model="modelSearch" type="search" placeholder="搜索上游返回的模型" /></label>
              </div>
              <p v-if="modelSearch && !filteredModels.length" class="ais-muted">没有匹配的模型，试试其他名称。</p>
            </template>
            <label v-else>模型名称<input v-model.trim="form.model" class="ais-mono" required placeholder="上游不支持获取列表时手动填写" /></label>
            <label class="ais-manual"><input v-model="manualModel" type="checkbox" />手动输入（备用）</label>
            <label>模型上下文窗口（可选）<input v-model.number="form.context_window" type="number" min="4096" max="10000000" placeholder="已知时填写 Token 数，留空不猜测" /></label>
          </div>

          <label class="ais-vision">
            <span class="ais-vision-icon"><i class="fa-regular fa-image" aria-hidden="true"></i></span>
            <span class="ais-vision-copy"><strong>此模型支持图片理解</strong><small>用于图片与扫描文档；请确认所选模型支持视觉输入。</small></span>
            <input v-model="form.vision" class="ais-switch" type="checkbox" role="switch" />
          </label>
          </div>
        </div>
        <footer class="ais-editor-footer">
          <button v-if="editId" type="button" class="ais-icon-button ais-delete" :disabled="busy" title="删除配置" aria-label="删除配置" @click="remove"><i class="fa-regular fa-trash-can" aria-hidden="true"></i></button><span v-else>密钥仅保存在本机</span>
          <div><button type="button" :disabled="busy || !editId" title="检查已保存的服务能否正常响应；修改配置后请先保存" @click="test">{{ testing ? '测试中…' : '测试连接' }}</button><button class="ais-primary" :disabled="busy || modelsLoading || !form.model || (!manualModel && !models.includes(form.model))"><i class="fa-solid fa-check" aria-hidden="true"></i>保存配置</button></div>
        </footer>
      </form>
      <p class="ais-footnote">测试使用已保存的配置，修改后请先保存。测试会产生少量用量，可在「使用量审计」查看。</p>
        </template>
      </section>
      </div>
      </Teleport>
    </div>

    <div id="ais-usage" v-show="activeTab === 'usage'" role="tabpanel" aria-labelledby="ais-usage-tab">
      <div class="ais-metrics">
        <div><span>累计调用</span><strong>{{ formatNumber(usage?.calls) }}<small>次</small></strong></div>
        <div><span>输入 tokens</span><strong>{{ formatNumber(usage?.input_tokens) }}</strong></div>
        <div><span>输出 tokens</span><strong>{{ formatNumber(usage?.output_tokens) }}</strong></div>
      </div>
      <div class="ais-audit-toolbar"><div><h4>调用明细</h4><p>失败 {{ usage?.failed_calls || 0 }} 次 · 用量未知 {{ usage?.unknown_usage_calls || 0 }} 次</p></div><div><button type="button" :disabled="busy" @click="action(() => loadAudit(true))"><i class="fa-solid fa-arrows-rotate" aria-hidden="true"></i>刷新</button><button type="button" :disabled="!audit.length" @click="exportAudit"><i class="fa-solid fa-download" aria-hidden="true"></i>导出已加载记录</button></div></div>
      <div class="ais-table-wrap">
        <table v-if="audit.length" class="ais-audit-table"><thead><tr><th>模型 / 时间</th><th>状态</th><th>用量</th><th>详情</th></tr></thead>
          <tbody><tr v-for="r in audit" :key="r.id">
            <td><strong :title="r.model">{{ r.model || r.profile_name || r.profile_id }}</strong><small>{{ r.started_at ? new Date(r.started_at * 1000).toLocaleString() : '历史记录' }}</small></td>
            <td><span class="ais-status" :class="'status-' + (r.status || 'success')">{{ statusLabel(r.status) }}</span><small v-if="r.http_status">HTTP {{ r.http_status }}</small></td>
            <td class="ais-token-cell"><span>输入 {{ r.usage_known === false ? '未知' : (r.usage?.input_tokens ?? '未知') }}</span><span>输出 {{ r.usage_known === false ? '未知' : (r.usage?.output_tokens ?? '未知') }}</span></td>
            <td><details><summary>查看</summary><div class="ais-audit-detail">{{ r.profile_name || r.profile_id }}<br />第 {{ r.attempt || 1 }} 次尝试 · 图片 {{ r.image_count || 0 }} 张<br />{{ r.account ? '账号 ' + r.account : '' }}<br v-if="r.account" />{{ r.task_id ? '任务 ' + r.task_id : '独立调用 / 连接测试' }}</div></details></td>
          </tr></tbody></table>
        <div v-else class="ais-empty"><i class="fa-regular fa-chart-bar" aria-hidden="true"></i><h4>还没有调用记录</h4><p>完成第一次总结或连接测试后，用量会显示在这里。</p></div>
      </div>
      <button v-if="hasMoreAudit" type="button" class="ais-load-more" :disabled="busy" @click="action(() => loadAudit(false))">加载更多</button>
      <p class="ais-footnote">每次重试单独记录，费用以服务商账单为准。审计不包含密钥和聊天正文。</p>
    </div>
  </div>
</template>

<script setup>
import AgentSettings from './AgentSettings.vue'
import LocalSearchSettings from './LocalSearchSettings.vue'
import AiProviderIcon from './AiProviderIcon.vue'
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import UiSelect from './UiSelect.vue'
import '~/assets/css/ai-settings.css'
const activeTab = ref('config')
const settingsTabs = [
  {id:'config',label:'模型服务',hint:'连接与默认模型',icon:'fa-plug'},
  {id:'local',label:'本地检索',hint:'按意思查找聊天',icon:'fa-magnifying-glass'},
  {id:'agent',label:'Agent',hint:'对话与查找偏好',icon:'fa-comment-dots'},
  {id:'usage',label:'用量记录',hint:'调用明细与消耗',icon:'fa-chart-simple'},
]
function navigateTabs(event,id){
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return
  event.preventDefault()
  const index=settingsTabs.findIndex(tab=>tab.id===id)
  const next=event.key==='Home'?0:event.key==='End'?settingsTabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+settingsTabs.length)%settingsTabs.length
  activeTab.value=settingsTabs[next].id
  nextTick(()=>document.getElementById(`ais-${activeTab.value}-tab`)?.focus())
}
const localSettingsTarget = useSettingsDialog().focusTarget || ref('')
// 服务连接结果不带入本地检索、Agent 或审计页面。
watch(activeTab, () => { error.value = ''; notice.value = '' })
watch(localSettingsTarget, target => { if (target === 'local-search') activeTab.value = 'local' }, { immediate: true })
const formatNumber = (value) => Number(value || 0).toLocaleString('zh-CN')
const profileOptions = vision => [{ value: '', label: '不设置默认模型' }, ...profiles.value.filter(p => !vision || p.vision).map(p => ({ value: p.id, label: p.name, description: p.model }))]
const protocolOptions = [{ value: 'openai', label: 'OpenAI 兼容' }, { value: 'anthropic', label: 'Claude Messages' }]
const providerPresentation = {
  deepseek: { hint: 'DeepSeek 官方接口', aliases: '深度求索' },
  claude: { hint: 'Claude Messages 接口', aliases: 'Anthropic' },
  kimi: { hint: 'Moonshot 兼容接口', aliases: '月之暗面' },
  openai: { hint: 'OpenAI 官方接口', aliases: 'ChatGPT GPT' },
  gemini: { label: 'Gemini', caption: 'Google AI Studio', hint: 'Google AI Studio 兼容接口', aliases: '谷歌' },
  qwen: { label: '通义千问', caption: '阿里云百炼', hint: '阿里云百炼 · 国内通用接口', aliases: '通义 千问 阿里 DashScope' },
  zhipu: { caption: '智谱开放平台', hint: '智谱开放平台 · 国内通用接口', aliases: '智谱 GLM BigModel' },
  doubao: { label: '豆包', caption: '火山方舟', hint: '火山方舟 · 国内通用接口', aliases: '字节 火山引擎 Volcengine Ark' },
  siliconflow: { caption: 'SiliconCloud', hint: '硅基流动 · 国内模型服务', aliases: 'SiliconCloud' },
  openrouter: { caption: '多模型聚合服务', hint: '聚合多个服务商的模型', aliases: '' },
  groq: { hint: 'Groq 官方兼容接口', aliases: '' },
  ollama: { caption: '本地模型服务', hint: '本地模型 · 默认端口 11434', aliases: '本机 local' },
  lmstudio: { caption: '本地模型服务', hint: '本地模型 · 默认端口 1234', aliases: '本机 local' },
  custom: { hint: '自定义地址与接口协议', aliases: '兼容' },
}
const providerInfo = provider => providerPresentation[provider === 'anthropic' ? 'claude' : provider]
const providerHint = provider => providerInfo(provider)?.hint || '连接模型服务'
const providerSearch = ref('')
const filteredPresets = computed(() => {
  const query = providerSearch.value.trim().toLowerCase()
  return presets.value.filter(p => `${p.name} ${p.provider} ${providerHint(p.provider)} ${providerInfo(p.provider)?.aliases || ''}`.toLowerCase().includes(query))
    .sort((a, b) => Number(a.provider === 'custom') - Number(b.provider === 'custom'))
})
const dialogStep = ref(''), dialogPanel = ref(null)
let returnFocus = null
const focusDialog = () => nextTick(() => dialogPanel.value?.focus())
const closeDialog = () => {
  if (busy.value) return
  dialogStep.value = ''; key.value = ''; error.value = ''
  invalidateModels()
  nextTick(() => { if (returnFocus?.isConnected) returnFocus.focus() })
}
const showProviders = () => { providerSearch.value = ''; dialogStep.value = 'providers'; focusDialog() }
const startNew = () => { returnFocus = document.activeElement; reset(); error.value = ''; notice.value = ''; showProviders() }
const chooseProvider = provider => {
  form.provider = provider; applyPreset(); dialogStep.value = 'edit'; focusDialog()
  if (isLocalService.value) autoFetchModels()
}
const onDialogKeydown = event => {
  if (event.key === 'Escape') { event.preventDefault(); closeDialog() }
  if (event.key !== 'Tab') return
  const nodes = [...dialogPanel.value.querySelectorAll('button:not(:disabled), input:not(:disabled), [tabindex="0"]')]
  const first = nodes[0], last = nodes.at(-1)
  if (!first) { event.preventDefault(); return }
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogPanel.value)) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialogPanel.value)) { event.preventDefault(); first.focus() }
}
const api = useAiApi()
const profiles = ref([]), presets = ref([]), models = ref([]), editId = ref(''), key = ref('')
const busy = ref(false), error = ref(''), notice = ref(''), usage = ref(null)
const testing = ref(false)
const audit = ref([]), hasMoreAudit = ref(false)
const statusLabel = (status) => ({ success: '成功', failed: '失败', cancelled: '已取消', interrupted: '已中断', running: '执行中' }[status] || (status ? '未知状态' : '历史成功调用'))
const loadAudit = async (reset = true) => {
  const rows = await api.request(`/usage/records?limit=50&offset=${reset ? 0 : audit.value.length}`)
  audit.value = reset ? rows : [...audit.value, ...rows]; hasMoreAudit.value = rows.length === 50
  usage.value = await api.request('/usage')
}
const exportAudit = () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(audit.value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = 'ai-usage-audit.json'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
const defaults = reactive({ text: '', vision: '' })
const blank = () => ({ provider: 'deepseek', name: 'DeepSeek', protocol: 'openai', base_url: 'https://api.deepseek.com/v1', model: '', vision: false, context_window: null })
const form = reactive(blank())
// 切换预设后明确清空凭据，不让后端复用原配置的密钥。
const credentialsReset = ref(false)
const isLocalService = computed(() => {
  if (!['ollama', 'lmstudio'].includes(form.provider)) return false
  try { return ['localhost', '127.0.0.1', '[::1]'].includes(new URL(form.base_url).hostname) } catch { return false }
})
const manualModel = ref(false), modelSearch = ref(''), modelDetails = ref([]), modelError = ref(''), modelsLoading = ref(false)
const filteredModels = computed(() => models.value.filter(m => m.toLowerCase().includes(modelSearch.value.trim().toLowerCase())))
const modelOptions = computed(() => {
  const options = filteredModels.value.map(model => ({ value: model, label: model, description: modelDetails.value.find(x => x.id === model)?.vision === true ? '支持图片理解' : '' }))
  if (form.model && !options.some(option => option.value === form.model)) options.unshift({ value: form.model, label: form.model, description: models.value.includes(form.model) ? '当前选择' : '未在上游列表中确认', disabled: true })
  return options
})
let modelRequest = 0, fetchedSignature = ''
const discoverySignature = () => JSON.stringify([editId.value, form.base_url, form.protocol, key.value])
const invalidateModels = () => {
  modelRequest++; modelsLoading.value = false; models.value = []; modelDetails.value = []
  modelError.value = ''; modelSearch.value = ''; fetchedSignature = ''
}
watch([editId, () => form.base_url, () => form.protocol, key], () => {
  invalidateModels(); form.model = ''; form.vision = false
}, { flush: 'sync' })
onBeforeUnmount(() => { modelRequest++; key.value = '' })
const action = async (fn) => {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await fn() } catch (e) { error.value = e.message } finally { busy.value = false }
}
const load = async () => {
  const data = await api.request('/settings')
  profiles.value = data.profiles; presets.value = data.presets; Object.assign(defaults, data.defaults)
  await loadAudit()
}
const reset = () => { invalidateModels(); editId.value = ''; key.value = ''; credentialsReset.value = false; manualModel.value = false; Object.assign(form, blank()) }
const edit = (p) => {
  if (!dialogStep.value) returnFocus = document.activeElement
  dialogStep.value = 'edit'; error.value = ''; notice.value = ''; focusDialog()
  invalidateModels(); editId.value = p.id; key.value = ''; credentialsReset.value = false; manualModel.value = false
  Object.assign(form, p); form.model = p.model; form.vision = p.vision
  void getModels()
}
const applyPreset = () => {
  const p = presets.value.find(x => x.provider === form.provider)
  key.value = ''; credentialsReset.value = true; form.has_key = false; manualModel.value = false
  if (p) Object.assign(form, { provider: p.provider, name: p.name, protocol: p.protocol, base_url: p.base_url })
  invalidateModels(); form.model = ''; form.vision = false
}
const save = () => action(async () => {
  const body = { ...form, context_window: form.context_window || null, api_key: key.value.trim() || (editId.value && !credentialsReset.value ? null : '') }
  await api.request(editId.value ? `/profiles/${editId.value}` : '/profiles', { method: editId.value ? 'PUT' : 'POST', body })
  await load(); key.value = ''; dialogStep.value = ''; invalidateModels(); notice.value = '配置已保存'
  nextTick(() => returnFocus?.isConnected && returnFocus.focus())
})
const saveDefaults = () => action(async () => { await api.request('/defaults', { method: 'PUT', body: defaults }); notice.value = '默认模型已保存' })
const selectModel = () => {
  const detail = modelDetails.value.find(x => x.id === form.model)
  const saved = profiles.value.find(x => x.id === editId.value)
  form.vision = typeof detail?.vision === 'boolean' ? detail.vision : (saved?.model === form.model ? saved.vision : false)
}
const getModels = async () => {
  if (busy.value || modelsLoading.value) return
  const request = ++modelRequest, signature = discoverySignature()
  modelsLoading.value = true; modelError.value = ''
  try {
    const data = await api.request('/models', { method: 'POST', body: { base_url: form.base_url, protocol: form.protocol, api_key: key.value.trim() || (credentialsReset.value ? '' : null), profile_id: editId.value } })
    // 切换配置或修改凭据后，迟到的响应不能覆盖当前模型列表。
    if (request !== modelRequest) return
    models.value = data.models || []; modelDetails.value = data.model_details || []; fetchedSignature = signature
    if (!models.value.length) { modelError.value = '上游没有返回可用模型，可重试或使用手动输入。'; return }
    if (!form.model) {
      form.model = modelDetails.value.find(x => x.vision === true)?.id || models.value[0]
      selectModel()
    } else if (!models.value.includes(form.model)) {
      modelError.value = '已保存模型未出现在上游列表中，请重新选择，或启用手动输入保留。'
    }
  } catch (e) {
    if (request === modelRequest) modelError.value = isLocalService.value ? `${e.message}。请检查本地服务是否已启动、地址和端口是否正确；启用鉴权时请填写密钥，也可使用手动输入。` : e.message
  } finally {
    if (request === modelRequest) modelsLoading.value = false
  }
}
const autoFetchModels = () => {
  if (!form.base_url || modelsLoading.value || fetchedSignature === discoverySignature()) return
  if (!key.value.trim() && !(editId.value && !credentialsReset.value) && form.provider !== 'custom' && !isLocalService.value) return
  void getModels()
}
const test = () => action(async () => {
  testing.value = true
  try {
    const result = await api.request(`/profiles/${editId.value}/test`, { method: 'POST' })
    // 兼容旧后端也不直接展示模型自由生成的测试回答。
    notice.value = '连接成功，模型已正常响应。' + (result.test_type === 'image' ? '本次也测试了图片输入。' : '')
    await load()
  } finally { testing.value = false }
})
const remove = () => action(async () => { await api.request(`/profiles/${editId.value}`, { method: 'DELETE' }); reset(); await load(); dialogStep.value = ''; notice.value = '配置已删除，引用它的规则已暂停'; nextTick(() => document.querySelector('.ais-add')?.focus()) })
onMounted(() => action(load))
</script>
