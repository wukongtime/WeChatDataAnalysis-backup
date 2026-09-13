import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import AgentModelPicker from '../components/chat/AgentModelPicker.vue'

afterEach(() => vi.unstubAllGlobals())

it('获取模型列表不覆盖当前配置已确认的等级，切换未知模型后不沿用等级', async () => {
  vi.stubGlobal('useAiApi', () => ({ request: vi.fn(async () => ({ model_details: [{ id: 'saved' }, { id: 'other' }] })) }))
  const wrapper = mount(AgentModelPicker, { props: { defaultId: 'service', modelValue: {},
    profiles: [{ id: 'service', name: '服务', model: 'saved', model_metadata: { reasoning_efforts: ['low', 'high', 'max'] } }] } })
  const choices = () => wrapper.findAll('[aria-label="原生思考等级"] option').map(option => option.attributes('value'))
  expect(choices()).toEqual(['', 'low', 'high', 'max'])
  await wrapper.find('section header button').trigger('click'); await flushPromises()
  expect(choices()).toEqual(['', 'low', 'high', 'max'])
  await wrapper.find('[aria-label="原生思考等级"]').setValue('low')
  expect(wrapper.emitted('update:modelValue').at(-1)[0]).toMatchObject({ reasoning_effort: 'low' })
  await wrapper.setProps({ modelValue: { profile_id: 'service', model_id: 'other', reasoning_effort: null } })
  expect(wrapper.find('[aria-label="原生思考等级"]').exists()).toBe(false)
  wrapper.unmount()
})

it('点击菜单外关闭，内部输入保持打开，不改变模型配置', async () => {
  vi.stubGlobal('useAiApi', () => ({ request: vi.fn() }))
  const wrapper = mount(AgentModelPicker, { attachTo: document.body, props: {
    profiles: [{ id: 'service', name: '服务', model: 'saved' }], defaultId: 'service' } })
  const menu = wrapper.find('details').element
  menu.open = true
  await wrapper.find('input').trigger('pointerdown')
  expect(menu.open).toBe(true)
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
  expect(menu.open).toBe(false)
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  wrapper.unmount()
})

it('焦点移出后 Esc 仍关闭菜单，同一次按键不传给 AI 父视图', async () => {
  vi.stubGlobal('useAiApi', () => ({ request: vi.fn() }))
  const wrapper = mount(AgentModelPicker, { attachTo: document.body })
  const menu = wrapper.find('details').element
  const outside = document.createElement('button')
  const parentEscape = vi.fn()
  outside.addEventListener('keydown', parentEscape)
  document.body.append(outside)
  outside.focus(); menu.open = true
  outside.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(menu.open).toBe(false)
  expect(document.activeElement).toBe(outside)
  expect(parentEscape).not.toHaveBeenCalled()
  menu.open = true
  wrapper.find('input').element.focus()
  await wrapper.find('input').trigger('keydown', { key: 'Escape' })
  expect(document.activeElement).toBe(wrapper.find('summary').element)
  wrapper.unmount()
  outside.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(parentEscape).toHaveBeenCalledOnce()
  outside.remove()
})
