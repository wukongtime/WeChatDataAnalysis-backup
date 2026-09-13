import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import AgentSubtasks from '../components/chat/AgentSubtasks.vue'

const { request } = vi.hoisted(() => ({ request: vi.fn() }))
vi.mock('../composables/useAiApi', () => ({ useAiApi: () => ({ request }) }))

afterEach(() => { vi.useRealTimers(); request.mockReset() })

it('单个子任务显示实际分析进度，并在数量未变化时刷新', async () => {
  vi.useFakeTimers()
  const page = analyzed => ({ items: [{ id: 'child', name: '当前聊天 · 范围分析', status: 'running',
    stage: '保存分析发现', started_at: 100, coverage: { read: 20, analyzed, complete: false } }], has_more: false })
  request.mockResolvedValueOnce(page(0)).mockResolvedValue(page(20))
  const wrapper = mount(AgentSubtasks, { props: { now: 110000,
    run: { id: 'parent', account: 'account', version: 1, status: 'running', subtasks: { total: 1, completed: 0 } } } })
  expect(wrapper.find('summary').text()).toContain('子任务分析')
  wrapper.element.open = true
  await wrapper.trigger('toggle')
  await flushPromises()
  expect(wrapper.text()).toContain('已分析 0 条')
  await vi.advanceTimersByTimeAsync(3100)
  await flushPromises()
  expect(wrapper.text()).toContain('已分析 20 条')
  expect(wrapper.text()).toContain('保存分析发现')
  wrapper.element.open = false
  await wrapper.trigger('toggle')
  const calls = request.mock.calls.length
  await vi.advanceTimersByTimeAsync(6000)
  expect(request).toHaveBeenCalledTimes(calls)
  wrapper.unmount()
})

it('运行时不需要展开两次，就能看到动作、最近回复及长时间等待原因', async () => {
  vi.useFakeTimers()
  request.mockResolvedValue({ items: [{ id:'child', name:'好友 · 范围分析', status:'running',
    started_at:100, action_started_at:500, last_activity_at:490, model_running:true,
    current_action:'正在分析已读取的消息', latest_progress:{text:'已整理约饭安排，接下来归纳费用变化。'},
    coverage:{read:350,analyzed:175,complete:false}, activity:[{id:'t',kind:'tool',text:'读取聊天记录',status:'completed'}],
  }], has_more:false })
  const wrapper = mount(AgentSubtasks, { props:{ now:610000, run:{id:'p',account:'a',version:1,status:'running',subtasks:{total:1,completed:0}} } })
  await flushPromises()
  expect(wrapper.element.open).toBe(true)
  expect(wrapper.find('.subtask-progress').text()).toContain('已整理约饭安排')
  expect(wrapper.find('.subtask-progress').element.closest('li > details')).toBe(null)
  expect(wrapper.find('.subtask-action').text()).toContain('正在分析已读取的消息')
  expect(wrapper.find('.subtask-wait').text()).toContain('2分0秒')
  expect(wrapper.find('.subtask-heading').text()).toContain('8分30秒')
  await wrapper.setProps({ run:{...wrapper.props('run'),status:'completed'} })
  await flushPromises()
  const calls = request.mock.calls.length
  await vi.advanceTimersByTimeAsync(6000)
  expect(request).toHaveBeenCalledTimes(calls)
  expect(wrapper.element.open).toBe(true)
  wrapper.unmount()
})

it('旧任务迟到的响应不能覆盖新任务', async () => {
  let resolveOld
  request.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockResolvedValue({ items: [{ id: 'new-child', name: '新任务', status: 'completed' }], has_more: false })
  const run = { id: 'old', account: 'account', version: 1, status: 'running', subtasks: { total: 1, completed: 0 } }
  const wrapper = mount(AgentSubtasks, { props: { run } })
  wrapper.element.open = true
  await wrapper.trigger('toggle')
  await wrapper.setProps({ run: { ...run, id: 'new', status: 'completed' } })
  await flushPromises()
  resolveOld({ items: [{ id: 'old-child', name: '旧任务', status: 'running' }], has_more: false })
  await flushPromises()
  expect(wrapper.text()).toContain('新任务')
  expect(wrapper.text()).not.toContain('旧任务')
  wrapper.unmount()
})
