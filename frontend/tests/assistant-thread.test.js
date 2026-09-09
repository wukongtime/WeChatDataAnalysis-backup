import { mount, flushPromises } from '@vue/test-utils'
import { createSSRApp, h, nextTick } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { describe, expect, it } from 'vitest'
import AssistantThread from '../components/chat/AssistantThread.vue'

// 使用官方 Vue primitives 和真实 external-store 运行时，覆盖挂载与增量更新。
const settle = async () => { for (let i=0;i<4;i++) { await flushPromises(); await nextTick() } }
describe('assistant-ui 对话适配器', () => {
  it('服务端只渲染容器，客户端才创建运行时和消息', async () => {
    const html = await renderToString(createSSRApp(AssistantThread, { messages: [{ id: 'server', role: 'user', text: '仅客户端显示' }] }))
    expect(html).toContain('data-chat-library="assistant-ui-vue"')
    expect(html).not.toContain('agent-conversation')
    expect(html).not.toContain('仅客户端显示')
  })

  it('停止和继续保留同一消息节点，直接切换其他会话清理旧节点', async () => {
    const message = { id: 'run-a', role: 'assistant', text: '查找中', running: true }
    const wrapper = mount(AssistantThread, { props: { messages: [message], running: true }, slots: { message: ({ message }) => h('p', `${message.text} / ${message.status || 'running'}`) } })
    await settle()
    const row = wrapper.find('.agent-message').element
    await wrapper.setProps({ messages: [{ ...message, running: false, status: 'cancelled' }], running: false }); await settle()
    expect(wrapper.text()).toContain('cancelled')
    expect(wrapper.find('.agent-message').element).toBe(row)
    await wrapper.setProps({ messages: [{ ...message, text: '继续核对' }], running: true }); await settle()
    expect(wrapper.find('.agent-message').element).toBe(row)
    await wrapper.setProps({ messages: [{ id: 'other-run', role: 'assistant', text: '另一个会话', status: 'completed' }], running: false }); await settle()
    expect(wrapper.findAll('.agent-message')).toHaveLength(1)
    expect(wrapper.find('.agent-message').element).not.toBe(row)
    expect(wrapper.text()).toContain('另一个会话')
    expect(wrapper.text()).not.toContain('继续核对')
    wrapper.unmount()
  })

  it('按原消息 ID 更新流式回答，保留消息内的展开状态，并清理切换后的旧内容', async () => {
    const wrapper=mount(AssistantThread, {attachTo:document.body, props:{messages:[]},slots:{welcome:()=>h('p','开始对话'),message:({message})=>h('section',[h('p',message.text),h('details',[h('summary','调用详情'),h('p','搜索参数')])])}})
    await settle()
    expect(wrapper.find('.agent-conversation').text()).toBe('开始对话')
    const user={id:'u',role:'user',text:'找报价'}
    await wrapper.setProps({messages:[user,{id:'a',role:'assistant',text:'正在核对',running:true}],running:true}); await settle()
    const messages=wrapper.findAll('.agent-message')
    expect(messages).toHaveLength(2)
    const detail=messages[1].find('details').element; detail.open=true
    await wrapper.setProps({messages:[user,{id:'a',role:'assistant',text:'报价为 100 元',running:false}],running:false}); await settle()
    expect(wrapper.findAll('.agent-message')[1].text()).toContain('报价为 100 元')
    expect(wrapper.findAll('.agent-message')[1].find('details').element).toBe(detail)
    expect(detail.open).toBe(true)
    await wrapper.setProps({messages:[]}); await settle()
    expect(wrapper.find('.agent-conversation').text()).toBe('开始对话')
    expect(wrapper.text()).not.toContain('报价为')
    wrapper.unmount()
  })
})
