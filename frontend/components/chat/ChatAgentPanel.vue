<template>
  <aside ref="panelView" class="agent-panel" :class="{ 'is-expanded': expanded }" :role="expanded ? 'dialog' : undefined" :aria-modal="expanded ? true : undefined" aria-label="AI 助手" @keydown.esc="onEscape" @keydown.tab="expanded && trapFocus($event, panelView)">
    <header class="agent-header">
      <span class="agent-brand"><i class="fa-solid fa-wand-magic-sparkles" aria-hidden="true"></i></span><strong>AI 助手</strong>
      <button type="button" aria-label="新建 AI 对话" title="新建对话" @click="mode = 'agent'; newThread()"><i class="fa-regular fa-pen-to-square" aria-hidden="true"></i></button>
      <button type="button" aria-label="AI 对话历史" title="对话历史" @click="openHistory"><i class="fa-regular fa-clock" aria-hidden="true"></i></button>
      <button type="button" :aria-label="expanded ? '收起大视图' : '展开大视图'" :title="expanded ? '收起大视图' : '展开大视图'" @click="expanded = !expanded"><i :class="expanded ? 'fa-solid fa-compress' : 'fa-solid fa-expand'" aria-hidden="true"></i></button>
      <div class="agent-menu-anchor" ref="menuAnchor">
        <button ref="menuTrigger" type="button" aria-label="更多 AI 功能" :aria-expanded="menuOpen" aria-controls="agent-more-menu" @click="menuOpen = !menuOpen"><i class="fa-solid fa-ellipsis" aria-hidden="true"></i></button>
        <div v-if="menuOpen" id="agent-more-menu" class="agent-menu">
          <button type="button" @click="mode = 'agent'; menuOpen = false"><i class="fa-regular fa-comment-dots" aria-hidden="true"></i>对话<i v-if="mode === 'agent'" class="fa-solid fa-check" aria-hidden="true"></i></button>
          <button type="button" @click="mode = 'tools'; menuOpen = false"><i class="fa-solid fa-toolbox" aria-hidden="true"></i>工具与任务<i v-if="mode === 'tools'" class="fa-solid fa-check" aria-hidden="true"></i></button>
          <button type="button" @click="menuOpen = false; settings.openDialog('ai')"><i class="fa-solid fa-sliders" aria-hidden="true"></i>AI 服务设置</button>
        </div>
      </div>
      <button type="button" aria-label="关闭 AI 助手" title="关闭 AI 助手" @click="$emit('close')"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>
    </header>
    <div v-if="mode === 'tools'" class="agent-tools-heading"><button type="button" @click="mode = 'agent'"><i class="fa-solid fa-arrow-left" aria-hidden="true"></i>返回对话</button><strong>工具与任务</strong></div>
    <AiSidebar v-show="mode === 'tools'" class="agent-tools" :account="account" :contact="contact" :contacts="contacts" :focus-task-id="focusTaskId" @locate="locate" />
    <template v-if="mode === 'agent'">
      <div class="agent-context">
        <i class="fa-regular fa-comment-dots" aria-hidden="true"></i>
        <button type="button" class="agent-scope" :title="scopeLabel" aria-label="修改读取范围" @click="openScope"><span>{{ scopeLabel }}</span><i class="fa-solid fa-chevron-down" aria-hidden="true"></i></button>
        <button type="button" class="agent-follow" :aria-pressed="pinned" :title="pinned ? '取消固定，跟随当前聊天' : '固定此对话'" aria-label="固定此对话" @click="togglePin">{{ pinned ? '已固定' : '跟随聊天' }}<i class="fa-solid fa-thumbtack" aria-hidden="true"></i></button>
      </div>
      <div class="agent-workspace" :class="{ 'has-source': inspectedSource }">
      <div class="agent-reading">
      <p v-if="error" class="agent-error" role="alert">{{ error }}</p>
      <div ref="scrollView" class="agent-conversation" @scroll="onScroll">
        <div v-if="!thread?.messages?.length" class="agent-welcome"><span class="agent-brand"><i class="fa-solid fa-wand-magic-sparkles" aria-hidden="true"></i></span><h3>想从聊天里了解什么？</h3><p>可以找消息、梳理进展，也可以接着追问。<br>我会先查看{{ contactName }}，回答附上原文出处。</p><button v-for="q in suggestions" :key="q" type="button" @click="draft = q">{{ q }}<i class="fa-solid fa-arrow-up" aria-hidden="true"></i></button></div>
        <template v-for="turn in turns" :key="turn.id">
          <div class="agent-user"><p>{{ turn.question }}</p></div>
          <AgentRun v-if="turn.detail" :run="turn.detail" :now="now" :near-bottom="nearBottom" :latest="turn.id === run?.id" :name-for="nameFor" :view-state="processView" @locate="locate" @choose="chooseContact" @continue="runAction('continue')" @settings="settings.openDialog('ai')" />
          <section v-else class="agent-reply"><button type="button" class="agent-process-toggle" @click="loadPastRun(turn.id)">查看这轮处理过程</button><AgentAnswer v-if="turn.answer" :text="turn.answer.text" :citations="turn.answer.citations" @locate="locate" /></section>
        </template>
      </div>
      <button v-if="newContent" type="button" class="agent-new-content" @click="toBottom">有新内容 <i class="fa-solid fa-arrow-down" aria-hidden="true"></i></button>
      <footer class="agent-composer">
        <div class="agent-input-box">
          <textarea ref="draftInput" v-model="draft" aria-label="给 AI 助手的消息" :placeholder="running ? '可以补充要求，例如：只看上周的…' : '继续追问这段聊天…'" rows="1" @input="resizeDraft" @keydown.enter.exact="sendOnEnter" @compositionstart="composing = true" @compositionend="composing = false" />
          <div class="agent-input-actions">
            <UiSelect v-model="profileId" plain class="agent-model-select" label="Agent 文本模型" :options="profileOptions" :loading="profilesLoading" :load-error="profilesError" @open="loadProfiles" />
            <UiSelect v-model="effort" plain class="agent-effort-select" label="查找深度" :options="[{ value:'moderate',label:'适中' },{value:'deep',label:'深入查找'}]" />
            <button type="button" aria-label="对话设置" title="对话设置" :aria-expanded="composerSettings" @click="composerSettings = !composerSettings"><i class="fa-solid fa-sliders" aria-hidden="true"></i></button>
            <button v-if="running" type="button" class="agent-stop" aria-label="停止处理" title="停止处理" @click="runAction('stop')"><i class="fa-solid fa-stop" aria-hidden="true"></i></button>
            <button type="button" class="agent-send" :disabled="sending || !draft.trim() || !account || (!thread && !contact?.username)" :aria-label="running ? '发送补充要求' : '发送问题'" @click="send"><i :class="sending ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-arrow-up'" aria-hidden="true"></i></button>
          </div>
        </div>
        <div v-if="composerSettings" class="agent-composer-settings"><header><strong>对话设置</strong><button type="button" aria-label="关闭对话设置" @click="composerSettings = false"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button></header><label>视觉模型<UiSelect v-model="visionId" label="Agent 视觉模型" :options="visionOptions" :loading="profilesLoading" :load-error="profilesError" @open="loadProfiles" /></label><button type="button" @click="settings.openDialog('ai')">管理模型与服务<i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></button></div>
        <small class="agent-disclaimer" role="status">{{ running ? '补充要求会在下一步生效' : '回答附原文出处，点击可核对' }}</small>
      </footer>
      </div>
      <AgentSourceInspector v-if="inspectedSource" :source="inspectedSource.source" :number="inspectedSource.number" :prepare="prepareSource" :locate="locateSource" @close="closeInspector(true)" />
      </div>
    </template>
    <Teleport to="body"><div v-if="dialog" class="agent-dialog-overlay" @click.self="dialog = ''" @keydown.esc.stop="dialog = ''"><section class="agent-dialog" role="dialog" aria-modal="true" :aria-label="dialog === 'scope' ? '读取范围' : 'AI 对话历史'"><header><h3>{{ dialog === 'scope' ? '读取范围' : 'AI 对话历史' }}</h3><button type="button" aria-label="关闭弹窗" @click="dialog = ''">×</button></header>
      <template v-if="dialog === 'scope'"><p>仅在你指定的会话内查找。也可以直接在对话中说出要查的群或好友。</p><input v-model="scopeQuery" aria-label="搜索读取范围" placeholder="搜索群聊或好友" /><div class="agent-scope-list"><label v-for="item in scopeContacts" :key="item.username"><input v-model="scopeDraft" type="checkbox" :value="item.username" />{{ item.name }}<small>{{ item.username }}</small></label></div><footer><button type="button" @click="scopeDraft = [thread?.username || contact?.username]">仅当前会话</button><button type="button" :disabled="!scopeDraft.length" @click="saveScope">应用范围（{{ scopeDraft.length }}）</button></footer></template>
      <template v-else><p v-if="!history.length">还没有保存的对话。</p><article v-for="item in history" :key="item.id" class="agent-history-item"><button type="button" @click="selectHistory(item)">{{ item.title }}<small>{{ nameFor(item.username) }}</small></button><input v-if="renameId === item.id" v-model="renameTitle" aria-label="对话新名称" @keydown.enter="rename(item)" /><button type="button" @click="renameId === item.id ? rename(item) : (renameId = item.id, renameTitle = item.title)">{{ renameId === item.id ? '保存' : '重命名' }}</button><button type="button" @click="deleteHistory(item)">{{ deleteId === item.id ? '确认删除' : '删除' }}</button></article></template>
      <p v-if="dialogError" class="agent-error">{{ dialogError }}</p>
    </section></div></Teleport>
  </aside>
</template>

<script setup>
import { computed, ref, watch, onMounted, onUnmounted, nextTick, provide } from 'vue'
import AiSidebar from './AiSidebar.vue'
import UiSelect from '../UiSelect.vue'
import AgentAnswer from './AgentAnswer.vue'
import AgentRun from './AgentRun.vue'
import AgentSourceInspector from './AgentSourceInspector.vue'
import { mergeTimeline } from '~/utils/agentTimeline'
import '~/assets/css/agent.css'
const props = defineProps({ account: String, contact: Object, contacts: Array, focusTaskId: String, locateSource: Function, prepareSource: Function })
const emit = defineEmits(['close', 'locate', 'expanded'])
const api = useAiApi(), settings = useSettingsDialog()
const saved = useState('chat-agent-ui', () => ({ selected: {}, drafts: {}, pinned: {} }))
const mode = ref(props.focusTaskId ? 'tools' : 'agent'), expanded = ref(false), thread = ref(null), run = ref(null)
const pastRuns = ref({})
saved.value.process ||= {}
const processView = computed(() => saved.value.process)
const error = ref(''), sending = ref(false), now = ref(Date.now()), composing = ref(false)
const profileId = ref(''), visionId = ref(''), profiles = ref([]), effort = ref('moderate')
const profilesLoading = ref(false), profilesError = ref('')
let profilesRequest = null
const history = ref([]), directory = ref([]), dialog = ref(''), dialogError = ref(''), scopeQuery = ref(''), scopeDraft = ref([])
const renameId = ref(''), renameTitle = ref(''), deleteId = ref('')
const menuOpen = ref(false), menuAnchor = ref(null), menuTrigger = ref(null), composerSettings = ref(false), draftInput = ref(null)
const inspectedSource = ref(null), canInspect = ref(false)
let panelObserver, sourceTrigger = null
const closeInspector = (restoreFocus = false) => {
  sourceTrigger?.setAttribute('aria-expanded', 'false')
  sourceTrigger?.removeAttribute('aria-controls')
  if (restoreFocus && sourceTrigger?.isConnected) sourceTrigger.focus({ preventScroll: true })
  sourceTrigger = null; inspectedSource.value = null
}
const inspectSource = (source, number, button) => {
  if (!expanded.value || !canInspect.value) return false
  if (sourceTrigger === button) { closeInspector(true); return true }
  closeInspector()
  sourceTrigger = button
  button.setAttribute('aria-expanded', 'true'); button.setAttribute('aria-controls', 'agent-source-inspector')
  inspectedSource.value = { source, number }
  return true
}
const resizeDraft = () => {
  const input = draftInput.value
  if (!input) return
  input.style.height = 'auto'
  input.style.height = `${Math.min(144, Math.max(28, input.scrollHeight))}px`
}
const onOutside = event => { if (!menuAnchor.value?.contains(event.target)) menuOpen.value = false }
const panelView = ref(null), scrollView = ref(null), nearBottom = ref(true), newContent = ref(false)
const trapFocus = (event, root) => {
  if (!root) return
  const elements = [...root.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]')].filter(el => el.getClientRects().length)
  const first = elements[0], last = elements.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
const pinned = computed(() => !!saved.value.pinned[props.account])
const selectionKey = computed(() => `${props.account}:${props.contact?.username || ''}`)
const draftKey = computed(() => `${props.account}:${thread.value?.id || props.contact?.username || ''}`)
const draft = computed({ get: () => saved.value.drafts[draftKey.value] || '', set: value => { saved.value.drafts[draftKey.value] = value } })
const nameFor = id => [props.contact, ...(props.contacts || []), ...directory.value].find(c => c?.username === id)?.name || id
const contactName = computed(() => nameFor(thread.value?.username || props.contact?.username) || '当前聊天')
const scopeLabel = computed(() => !thread.value ? contactName.value : thread.value.scope.length === 1 ? nameFor(thread.value.scope[0]) : `${thread.value.scope.length} 个会话`)
const scopeContacts = computed(() => directory.value.filter(c => `${c.name} ${c.username}`.toLowerCase().includes(scopeQuery.value.toLowerCase())))
const running = computed(() => ['queued', 'running'].includes(run.value?.status))
const profileOptions = computed(() => [{ value:'',label:'默认模型',description:'使用全局默认文本模型' }, ...profiles.value.map(p => ({value:p.id,label:p.name,description:p.model}))])
const visionOptions = computed(() => [{ value:'',label:'全局默认视觉模型' }, ...profiles.value.filter(p => p.vision).map(p => ({value:p.id,label:p.name,description:p.model}))])
const suggestions = ['最近讨论了哪些重要的事？', '帮我找一下之前提过的报价', '有哪些事情还没确认？']
const turns = computed(() => (thread.value?.messages || []).filter(m => m.role === 'user' && !m.supplement).map(m => ({id:m.run_id,question:m.text,detail:m.run_id === run.value?.id ? run.value : pastRuns.value[m.run_id],answer:thread.value.messages.find(a=>a.role==='assistant' && a.run_id===m.run_id)})))
const loadPastRun = id => guardAction(async () => { const account=props.account; const result=await api.request(`/agent/runs/${id}`,{query:{account}}); if(!disposed && account===props.account) pastRuns.value[id]=result })

let disposed = false, version = 0, timer, events, refreshing = false, eventTimer
// 首次无缓存也主动读取；挂载、打开下拉框和设置关闭时共用正在进行的请求。
const loadProfiles = () => {
  if (disposed) return Promise.resolve()
  if (profilesRequest) return profilesRequest
  profilesLoading.value = true; profilesError.value = ''
  profilesRequest = Promise.resolve().then(() => api.request('/settings', { timeout: 12000 })).then(data => {
    if (disposed) return
    if (!Array.isArray(data?.profiles)) throw new Error('模型配置返回格式异常')
    profiles.value = data.profiles
    if (profileId.value && !data.profiles.some(profile => profile.id === profileId.value)) profileId.value = ''
    if (visionId.value && !data.profiles.some(profile => profile.id === visionId.value && profile.vision)) visionId.value = ''
  }).catch(() => {
    if (!disposed) profilesError.value = '模型列表加载失败'
  }).finally(() => {
    profilesRequest = null
    if (!disposed) profilesLoading.value = false
  })
  return profilesRequest
}
const params = () => ({ account: props.account })
const guardAction = async fn => { const account = props.account; error.value = ''; try { await fn() } catch (e) { if (!disposed && account === props.account) error.value = e.message } }
const readThread = async id => {
  closeInspector()
  const account = props.account, current = ++version
  const detail = await api.request(`/agent/threads/${id}`, { query:{account} })
  const task = detail.latest_run ? await api.request(`/agent/runs/${detail.latest_run}`, { query:{account} }) : null
  if (!disposed && account === props.account && current === version) { thread.value = detail; run.value = task; nearBottom.value = true; await toBottom() }
}
const loadSelection = async () => {
  ++version; closeInspector(); thread.value = null; run.value = null; dialog.value = ''; pastRuns.value = {}
  if (!props.account || !props.contact?.username) return
  const account = props.account, key = selectionKey.value
  const chosen = saved.value.pinned[account] || saved.value.selected[key]
  if (chosen) { try { await readThread(chosen); return } catch { delete saved.value.pinned[account]; delete saved.value.selected[key] } }
  const list = await api.request('/agent/threads', { query:{ account, username: props.contact.username } })
  if (disposed || props.account !== account || selectionKey.value !== key) return
  if (list[0]) { saved.value.selected[key] = list[0].id; await readThread(list[0].id) }
}
const refresh = async () => {
  if (!thread.value || refreshing || disposed) return
  const account = props.account, id = thread.value.id, current = version
  refreshing = true
  try {
    const detail = await api.request(`/agent/threads/${id}`, { query:{account}, timeout:12000 })
    const task = detail.latest_run ? await api.request(`/agent/runs/${detail.latest_run}`, { query:{account}, timeout:12000 }) : null
    if (!disposed && account === props.account && id === thread.value?.id && current === version && (!task || !run.value || task.id !== run.value.id || (task.updated_at || 0) >= (run.value.updated_at || 0))) {
      if (task?.id === run.value?.id) task.timeline = mergeTimeline(run.value.timeline, task.timeline)
      const streamed = task?.timeline?.find(item => item.id === `answer:${task.id}`)
      if (streamed && streamed.status !== 'superseded') task.answer = streamed.text
      thread.value = detail; run.value = task; error.value = ''
    } else api.diagnostic?.('response.stale', { thread_id: id, run_id: task?.id, component: 'agent' })
  } catch { if (!disposed && id === thread.value?.id && account === props.account) error.value = '进度连接暂时中断，正在自动重连。请勿重复提交。' }
  finally { refreshing = false }
}
const ensureThread = async () => {
  if (thread.value) return thread.value
  const account = props.account, key = selectionKey.value, oldDraft = draft.value
  const created = await api.request('/agent/threads', {method:'POST',body:{account,username:props.contact.username}})
  if (account !== props.account || key !== selectionKey.value) throw new Error('聊天已切换，请在当前对话重新发送')
  saved.value.selected[key] = created.id; thread.value = created; saved.value.drafts[draftKey.value] = oldDraft; return created
}
const send = async () => {
  if (sending.value || !draft.value.trim()) return
  if (new TextEncoder().encode(draft.value.trim()).length > 1048576) { error.value = '输入超过 1 MiB，请分次发送。'; return }
  const text = draft.value.trim(), oldKey = draftKey.value
  sending.value = true
  await guardAction(async () => {
    const t = await ensureThread(), account = props.account
    // 同一份草稿失败重试时沿用请求 ID，避免网络超时造成重复调用。
    const pendingKey = `pending:${account}:${t.id}:${text}`
    const requestId = saved.value.drafts[pendingKey] ||= crypto.randomUUID()
    const result = await api.request(`/agent/threads/${t.id}/messages`, {method:'POST',query:{account},body:{text,request_id:requestId,effort:effort.value,profile_id:profileId.value,vision_profile_id:visionId.value}})
    delete saved.value.drafts[pendingKey]; saved.value.drafts[oldKey] = ''
    if (account === props.account && thread.value?.id === t.id) { draft.value = ''; run.value = result; await refresh(); await toBottom() }
  })
  sending.value = false
}
const sendOnEnter = event => { if (event.isComposing || composing.value) return; event.preventDefault(); void send() }
const newThread = () => guardAction(async () => { closeInspector(); delete saved.value.pinned[props.account]; delete saved.value.selected[selectionKey.value]; ++version; thread.value = null; run.value = null; await toBottom() })
const togglePin = () => guardAction(async () => { if (pinned.value) { delete saved.value.pinned[props.account]; await loadSelection() } else { const t = await ensureThread(); saved.value.pinned[props.account] = t.id } })
const locateSource = async source => {
  if (thread.value) saved.value.pinned[props.account] = thread.value.id
  const result = props.locateSource ? await props.locateSource(source) : emit('locate', source)
  if (result === false) return false
  closeInspector()
  expanded.value = false
  return result
}
// 提供可等待的定位回调，让每条引用能准确显示进行中、成功与失败状态。
provide('agentSourceNavigation', { locate: locateSource, prepare: source => props.prepareSource?.(source), inspect: inspectSource })
const locate = source => guardAction(() => locateSource(source))
const runAction = action => guardAction(async () => { const id = run.value.id, account = props.account; const result = await api.request(`/agent/runs/${id}/${action}`, {method:'POST',query:{account}}); if (run.value?.id === id && props.account === account) run.value = result })
const openScope = () => guardAction(async () => {
  const account = props.account, current = version
  const items = await api.request('/conversations', {query:{account}})
  // 切换账号或对话后，丢弃旧请求，避免弹窗显示上一会话的数据。
  if (disposed || account !== props.account || current !== version) return
  directory.value = items; scopeDraft.value = [...(thread.value?.scope || [props.contact?.username])]; scopeQuery.value = ''; dialogError.value = ''; dialog.value = 'scope'
})
const saveScope = async () => {
  const account = props.account
  try {
    const t = await ensureThread()
    const result = await api.request(`/agent/threads/${t.id}`, {method:'PATCH',query:{account},body:{scope:[...scopeDraft.value]}})
    if (disposed || account !== props.account || thread.value?.id !== t.id) return
    thread.value = result; dialog.value = ''; await refresh()
  } catch (e) { if (!disposed && account === props.account) dialogError.value = e.message }
}
const openHistory = () => guardAction(async () => {
  const account = props.account, current = version
  const items = await api.request('/agent/threads', {query:{account}})
  if (disposed || account !== props.account || current !== version) return
  history.value = items; dialogError.value = ''; deleteId.value = ''; dialog.value = 'history'
})
const selectHistory = item => guardAction(async () => { saved.value.selected[`${props.account}:${item.username}`] = item.id; if (item.username !== props.contact?.username || pinned.value) saved.value.pinned[props.account] = item.id; dialog.value = ''; await readThread(item.id) })
const rename = async item => { try { await api.request(`/agent/threads/${item.id}`, {method:'PATCH',query:params(),body:{title:renameTitle.value}}); item.title = renameTitle.value; renameId.value = '' } catch(e) { dialogError.value = e.message } }
const deleteHistory = async item => { if (deleteId.value !== item.id) { deleteId.value = item.id; return }; try { await api.request(`/agent/threads/${item.id}`, {method:'DELETE',query:params()}); history.value = history.value.filter(t => t.id !== item.id); for (const [key,id] of Object.entries(saved.value.selected)) if (id === item.id) delete saved.value.selected[key]; if (saved.value.pinned[props.account] === item.id) delete saved.value.pinned[props.account]; if (thread.value?.id === item.id) { ++version; thread.value = null; run.value = null } } catch(e) { dialogError.value = e.message } }
const chooseContact = choice => guardAction(async () => { thread.value = await api.request(`/agent/threads/${thread.value.id}`, {method:'PATCH',query:params(),body:{scope:[...new Set([...thread.value.scope,choice.username])]}}); draft.value = `选择会话 ${choice.username}，请继续刚才的问题`; await send() })
const onScroll = () => { const el = scrollView.value; if (el) { nearBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 70; if (nearBottom.value) newContent.value = false } }
const toBottom = async () => { await nextTick(); const el = scrollView.value; if (el) el.scrollTop = el.scrollHeight; nearBottom.value = true; newContent.value = false }
const onEscape = () => { if (dialog.value) dialog.value = ''; else if (menuOpen.value) { menuOpen.value = false; menuTrigger.value?.focus() } else if (composerSettings.value) composerSettings.value = false; else if (inspectedSource.value) closeInspector(true); else if (expanded.value) expanded.value = false }
const connect = () => {
  events?.()
  const account=props.account
  if (account && api.agentEvents) events=api.agentEvents(account, event=>{
    if (disposed || account!==props.account) return
    if (event?.run_id === run.value?.id && event.timeline_item) {
      run.value={...run.value,timeline:mergeTimeline(run.value.timeline,[event.timeline_item])}
      const accepted = run.value.timeline.find(item=>item.id===event.timeline_item.id)
      if (accepted?.kind === 'answer' && accepted.status !== 'superseded') run.value.answer=accepted.text
    }
    clearTimeout(eventTimer); eventTimer=setTimeout(refresh,180)
  })
}
watch(() => [props.account, props.contact?.username], ([account],[oldAccount]) => { if (account !== oldAccount) { expanded.value = false; directory.value = []; connect() }; if (!pinned.value || account !== oldAccount) void guardAction(loadSelection) })
watch(() => props.focusTaskId, id => { if (id) mode.value = 'tools' })
watch(() => settings.open?.value, (open, previous) => { if (previous && !open) void loadProfiles() })
watch(expanded, value => { closeInspector(); emit('expanded', value) })
// 切换对话或调整授权范围后，不保留上一范围的出处内容。
watch([() => thread.value?.id, () => thread.value?.scope?.join('\0')], () => closeInspector())
watch(mode, () => { closeInspector(); composerSettings.value = false; nextTick(resizeDraft) })
watch(draft, () => nextTick(resizeDraft))
watch(() => [run.value?.answer, run.value?.stage, run.value?.timeline, thread.value?.messages?.length], () => { if (nearBottom.value) void toBottom(); else newContent.value = true })
onMounted(() => {
  document.addEventListener('pointerdown', onOutside)
  panelObserver = new ResizeObserver(entries => {
    canInspect.value = entries[0].contentRect.width >= 860
    if (!canInspect.value) closeInspector()
    resizeDraft()
  })
  panelObserver.observe(panelView.value)
  resizeDraft()
  connect(); void guardAction(loadSelection); void loadProfiles(); timer = setInterval(() => { now.value = Date.now(); if (running.value) void refresh() }, 1500) })
onUnmounted(() => { panelObserver?.disconnect(); document.removeEventListener('pointerdown', onOutside); closeInspector(); disposed = true; ++version; clearInterval(timer); clearTimeout(eventTimer); events?.(); emit('expanded', false) })
</script>
