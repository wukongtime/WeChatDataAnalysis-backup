import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatAgentPanel from '../components/chat/ChatAgentPanel.vue'
import AgentAnswer from '../components/chat/AgentAnswer.vue'
import AgentSettings from '../components/AgentSettings.vue'

let state, threads, runs, request, seq
beforeEach(() => {
  state = ref({selected:{},drafts:{},pinned:{}}); threads = {}; runs = {}; seq = 0
  request = vi.fn(async (path, options = {}) => {
    if (path === '/settings') return {profiles:[]}
    if (path === '/conversations') return [{username:'first',name:'会话一'},{username:'second',name:'会话二'}]
    if (path === '/agent/settings') return {moderate:{tools:12,models:24,media:8,seconds:300},deep:{tools:36,models:72,media:24,seconds:900}}
    if (path === '/agent/threads') {
      if (options.method === 'POST') { const id = `thread${++seq}`; return threads[id] = {id, ...options.body, scope:[options.body.username], messages:[], latest_run:''} }
      return Object.values(threads).filter(t => !options.query?.username || t.username === options.query.username)
    }
    const [, , , id, action] = path.split('/')
    if (path.startsWith('/agent/threads/')) {
      if (action === 'messages') {
        const t = threads[id]
        const runId = t.latest_run || `run${seq}`
        runs[runId] = {id:runId,thread_id:id,status:'running',stage:'搜索相关消息',created:Date.now()/1000,segment_started:Date.now()/1000,updated_at:Date.now()/1000,activity:[],used:{media:0},answer:'',citations:[]}
        threads[id] = {...t,latest_run:runId,messages:[...t.messages,{id:options.body.request_id,role:'user',text:options.body.text,run_id:runId,supplement:!!t.latest_run}]}
        runs[runId].timeline = threads[id].messages.filter(m=>m.supplement).map((m,i)=>({id:m.id,seq:i+1,revision:1,kind:'supplement',text:m.text,status:'received'}))
        return {...runs[runId]}
      }
      if (options.method === 'PATCH') threads[id] = {...threads[id],...options.body}
      return {...threads[id]}
    }
    if (path.startsWith('/agent/runs/')) return {...runs[id]}
    return []
  })
  vi.stubGlobal('useAiApi', () => ({request,events:()=>()=>{},agentEvents:()=>()=>{}}))
  vi.stubGlobal('useSettingsDialog', () => ({openDialog:vi.fn()}))
  vi.stubGlobal('useState', () => state)
})
const mountPanel = () => mount(ChatAgentPanel, {attachTo:document.body,props:{account:'acc',contact:{username:'first',name:'会话一'},contacts:[{username:'first',name:'会话一'},{username:'second',name:'会话二'}]},global:{stubs:{AiSidebar:true,Teleport:true}}})
const send = async (wrapper,text) => { await wrapper.find('textarea').setValue(text); await wrapper.find('[aria-label="发送问题"], [aria-label="发送补充要求"]').trigger('click'); await flushPromises() }

describe('聊天 Agent', () => {
  it('无缓存首次展开模型菜单时等待请求，返回后直接显示选项且菜单保持打开', async () => {
    let resolveSettings
    const pending = new Promise(resolve => { resolveSettings = resolve })
    const original = request.getMockImplementation()
    request.mockImplementation((path, options) => path === '/settings' ? pending : original(path, options))
    const wrapper = mountPanel(); await flushPromises()
    await wrapper.find('[aria-label="Agent 文本模型"]').trigger('click')
    expect(wrapper.find('[role="listbox"]').attributes('aria-busy')).toBe('true')
    expect(wrapper.find('[role="listbox"]').text()).toContain('正在加载')
    expect(request.mock.calls.filter(([path]) => path === '/settings')).toHaveLength(1)
    resolveSettings({profiles:[{id:'text',name:'首次返回的文本模型'},{id:'vision',name:'首次返回的视觉模型',vision:true}]})
    await flushPromises()
    expect(wrapper.find('[aria-label="Agent 文本模型"]').attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[role="listbox"]').text()).toContain('首次返回的文本模型')
    await wrapper.find('[aria-label="Agent 文本模型"]').trigger('keydown', {key:'Escape'})
    await wrapper.find('[aria-label="对话设置"]').trigger('click')
    await wrapper.find('[aria-label="Agent 视觉模型"]').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="listbox"]').text()).toContain('首次返回的视觉模型')
    expect(wrapper.find('[role="listbox"]').text()).not.toContain('首次返回的文本模型')
    wrapper.unmount()
  })
  it('首次读取模型失败后，打开下拉框会重试；失败提示可见且重试成功后清除', async () => {
    let attempts = 0
    const original = request.getMockImplementation()
    request.mockImplementation((path, options) => {
      if (path !== '/settings') return original(path, options)
      if (++attempts <= 2) return Promise.reject(new Error('后端尚未就绪'))
      return Promise.resolve({profiles:[{id:'ready',name:'已恢复的模型'}]})
    })
    const wrapper=mountPanel(); await flushPromises()
    await wrapper.find('[aria-label="Agent 文本模型"]').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="listbox"]').text()).toContain('模型列表加载失败')
    await wrapper.find('[aria-label="Agent 文本模型"]').trigger('click')
    await wrapper.find('[aria-label="Agent 文本模型"]').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="listbox"]').text()).toContain('已恢复的模型')
    expect(wrapper.find('[role="listbox"]').text()).not.toContain('加载失败')
    expect(attempts).toBe(3)
    wrapper.unmount()
  })
  it('关闭服务设置后刷新模型，不必关闭并重开助手', async () => {
    const settingsOpen=ref(false)
    vi.stubGlobal('useSettingsDialog',()=>({open:settingsOpen,openDialog:vi.fn()}))
    const original=request.getMockImplementation()
    let profiles=[]
    request.mockImplementation((path,options)=>path==='/settings'?Promise.resolve({profiles}):original(path,options))
    const wrapper=mountPanel();await flushPromises()
    settingsOpen.value=true;await flushPromises()
    profiles=[{id:'new',name:'刚添加的模型'}]
    settingsOpen.value=false;await flushPromises()
    expect(wrapper.vm.profileOptions.some(option=>option.label==='刚添加的模型')).toBe(true)
    wrapper.unmount()
  })
  it('从更多菜单切换工具再返回时保留草稿，输入区设置可独立开关', async () => {
    const wrapper = mountPanel(); await flushPromises()
    await wrapper.find('textarea').setValue('保留这份草稿')
    await wrapper.find('[aria-label="更多 AI 功能"]').trigger('click')
    await wrapper.findAll('.agent-menu button')[1].trigger('click')
    expect(wrapper.find('textarea').exists()).toBe(false)
    await wrapper.find('.agent-tools-heading button').trigger('click')
    expect(wrapper.find('textarea').element.value).toBe('保留这份草稿')
    await wrapper.find('[aria-label="对话设置"]').trigger('click')
    expect(wrapper.find('[aria-label="Agent 视觉模型"]').exists()).toBe(true)
    await wrapper.find('[aria-label="关闭对话设置"]').trigger('click')
    expect(wrapper.find('.agent-composer-settings').exists()).toBe(false)
    wrapper.unmount()
  })
  it('宽视图点击引用显示原文栏，缩窄后关闭原文栏并恢复浮层', async () => {
    const callbacks=[]
    const original=globalThis.ResizeObserver
    vi.stubGlobal('ResizeObserver',class { constructor(callback){ callbacks.push(callback) } observe(){} disconnect(){} })
    const source={source:'a'.repeat(24),username:'first',anchor:'m1',name:'会话一',sender:'甲',time:100,text:'引用原文'}
    threads.t={id:'t',username:'first',scope:['first'],latest_run:'r',messages:[{id:'q',role:'user',text:'问题',run_id:'r'}]}
    runs.r={id:'r',status:'completed',answer:`答案 [[${source.source}]]`,citations:[source]}
    const wrapper=mountPanel();await flushPromises()
    await wrapper.find('[aria-label="展开大视图"]').trigger('click')
    callbacks[0]([{contentRect:{width:1060}}])
    await wrapper.find('.agent-ref').trigger('click');await flushPromises()
    expect(wrapper.find('.agent-source-inspector').text()).toContain('引用原文')
    expect(wrapper.find('.agent-citation-preview').exists()).toBe(false)
    callbacks[0]([{contentRect:{width:700}}]);await flushPromises()
    expect(wrapper.find('.agent-source-inspector').exists()).toBe(false)
    expect(wrapper.find('.agent-ref').attributes('aria-expanded')).toBe('false')
    wrapper.find('.agent-ref').element.getBoundingClientRect=()=>({top:100,bottom:120,left:100,right:120})
    wrapper.find('.agent-conversation').element.getBoundingClientRect=()=>({top:80,bottom:600,left:0,right:700})
    await wrapper.find('.agent-ref').trigger('click');await flushPromises()
    expect(wrapper.find('.agent-citation-preview').exists()).toBe(true)
    wrapper.unmount();vi.stubGlobal('ResizeObserver',original)
  })
  it('首次提交超时仍保留草稿，重试使用相同幂等 ID', async () => {
    const original = request.getMockImplementation()
    let fail = true
    request.mockImplementation(async (path, options) => { if (path.endsWith('/messages') && fail) throw new Error('暂时断线'); return original(path, options) })
    const wrapper = mountPanel(); await flushPromises()
    await send(wrapper,'找一下报价')
    expect(wrapper.find('textarea').element.value).toBe('找一下报价')
    fail = false
    await wrapper.find('[aria-label="发送问题"]').trigger('click'); await flushPromises()
    const posts = request.mock.calls.filter(([p]) => p.endsWith('/messages'))
    expect(posts[0][1].body.request_id).toBe(posts[1][1].body.request_id)
    wrapper.unmount()
  })
  it('默认对话，提交当前聊天，进行中可以补充且沿用同一任务', async () => {
    const wrapper = mountPanel(); await flushPromises()
    expect(wrapper.text()).toContain('想从聊天里了解什么')
    await send(wrapper,'找一下报价')
    expect(request.mock.calls.find(([p,o])=>p==='/agent/threads'&&o.method==='POST')[1].body.username).toBe('first')
    expect(wrapper.text()).toContain('正在查找与分析')
    await send(wrapper,'只看上周')
    const posts = request.mock.calls.filter(([p])=>p.endsWith('/messages'))
    expect(posts).toHaveLength(2)
    expect(posts[0][0]).toBe(posts[1][0])
    expect(wrapper.text()).toContain('已收到补充要求')
    wrapper.unmount()
  })
  it('固定后切换聊天保留原 AI 对话，解除固定恢复跟随', async () => {
    const wrapper = mountPanel(); await flushPromises(); await send(wrapper,'找报价')
    await wrapper.find('[aria-label="固定此对话"]').trigger('click'); await flushPromises()
    await wrapper.setProps({contact:{username:'second',name:'会话二'}}); await flushPromises()
    expect(wrapper.find('.agent-scope').text()).toContain('会话一')
    await wrapper.find('[aria-label="固定此对话"]').trigger('click'); await flushPromises()
    expect(wrapper.find('.agent-scope').text()).toContain('会话二')
    expect(wrapper.find('.agent-welcome').exists()).toBe(true)
    wrapper.unmount()
  })
  it('草稿在关闭、重开及展开大视图后保留', async () => {
    let wrapper = mountPanel(); await flushPromises()
    await wrapper.find('textarea').setValue('尚未发送的草稿')
    await wrapper.find('[aria-label="展开大视图"]').trigger('click')
    expect(wrapper.classes()).toContain('is-expanded')
    expect(wrapper.find('textarea').element.value).toBe('尚未发送的草稿')
    wrapper.unmount(); wrapper = mountPanel(); await flushPromises()
    expect(wrapper.find('textarea').element.value).toBe('尚未发送的草稿')
    wrapper.unmount()
  })
  it('通过读取范围弹窗提交明确会话集合', async () => {
    const wrapper = mountPanel(); await flushPromises()
    await wrapper.find('.agent-scope').trigger('click'); await flushPromises()
    await wrapper.find('.agent-scope-list input[value="second"]').setValue(true)
    await wrapper.find('.agent-dialog footer button:last-child').trigger('click'); await flushPromises()
    expect(request.mock.calls.find(([,o])=>o?.method==='PATCH')[1].body.scope).toEqual(['first','second'])
    expect(wrapper.find('.agent-scope').text()).toContain('2 个会话')
    wrapper.unmount()
  })
  it('回答引用可预览定位，外部图片和原始 HTML 不执行', async () => {
    const source = 'a'.repeat(24)
    const wrapper = mount(AgentAnswer,{attachTo:document.body,props:{text:`**报价** [[${source}]]\n<img src=x onerror=alert(1)>\n![bad](https://example.com/tracker)`,citations:[{source,username:'first',name:'会话一',sender:'甲',time:100,text:'报价100元'}]}})
    wrapper.find('.agent-ref').element.getBoundingClientRect = () => ({ top:100, bottom:124, left:100, right:124 })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('strong').text()).toBe('报价')
    await wrapper.find('.agent-ref').trigger('click')
    expect(wrapper.find('.agent-citation-preview').text()).toContain('报价100元')
    await wrapper.find('.agent-citation-preview > button').trigger('click')
    expect(wrapper.emitted('locate')[0][0].source).toBe(source)
    wrapper.unmount()
  })
  it('Agent 限额可在设置中保存', async () => {
    const wrapper = mount(AgentSettings); await flushPromises()
    await wrapper.find('input').setValue(15)
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(request.mock.calls.find(([p,o])=>p==='/agent/settings'&&o?.method==='PUT')[1].body.moderate.tools).toBe(15)
    expect(wrapper.text()).toContain('Agent 设置已保存')
    wrapper.unmount()
  })
})
