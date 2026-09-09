import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AiSettings from '../components/AiSettings.vue'
import source from '../../src/wechat_decrypt_tool/ai/providers.py?raw'

// 复用后端预设，确保前端实际覆盖全部服务，而不是另一份过期名单。
const presets = source.split('\n').filter(line => line.trim().startsWith('{"provider":')).map(line => JSON.parse(line.trim().replace(/,$/, '')))
const request = vi.fn()
let wrapper
beforeEach(() => {
  vi.stubGlobal('useAiApi', () => ({ request }))
  vi.stubGlobal('useSettingsDialog', () => ({ focusTarget: ref(''), openDialog: vi.fn() }))
  request.mockReset().mockImplementation(async path => {
    if (path === '/settings') return { profiles: [], presets, defaults: {} }
    if (path === '/models') return { models: ['upstream-model'], model_details: [{ id: 'upstream-model', vision: null }] }
    return []
  })
})
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals() })

const open = async () => {
  wrapper = mount(AiSettings, { attachTo: document.body, global: { stubs: { teleport: true } } })
  await flushPromises()
  await wrapper.find('.ais-add').trigger('click')
}
const choose = async provider => {
  await wrapper.findAll('.ais-provider-choice').find(button => button.find(`[data-provider="${provider}"]`).exists()).trigger('click')
  await flushPromises()
}
const manualInput = () => wrapper.findAll('label').find(label => label.text().includes('手动输入（备用）')).find('input')

describe('AI 服务预设', () => {
  it('显示全部预设，自定义位于末尾，搜索别名并清空无结果状态', async () => {
    await open()
    expect(wrapper.findAll('.ais-provider-choice')).toHaveLength(14)
    expect(wrapper.findAll('.ais-provider-choice').at(-1).text()).toContain('自定义')
    const search = wrapper.find('.ais-provider-search input')
    for (const [query, provider] of [['谷歌', 'gemini'], ['千问', 'qwen'], [' gLm ', 'zhipu'], ['火山', 'doubao'], ['SiliconCloud', 'siliconflow'], ['lmstudio', 'lmstudio']]) {
      await search.setValue(query)
      expect(wrapper.findAll('.ais-provider-choice')).toHaveLength(1)
      expect(wrapper.find(`.ais-provider-choice [data-provider="${provider}"]`).exists()).toBe(true)
    }
    await search.setValue('没有这家服务')
    expect(wrapper.find('[role=status]').text()).toContain('没有匹配的 AI 服务')
    await wrapper.findAll('button').find(button => button.text() === '清空搜索').trigger('click')
    expect(wrapper.findAll('.ais-provider-choice')).toHaveLength(14)
  })

  it.each(presets)('$name 正确预填并支持保存，不内置模型或图片能力', async preset => {
    await open()
    await choose(preset.provider)
    expect(wrapper.find('input[type=url]').element.value).toBe(preset.base_url)
    expect(wrapper.find('input[maxlength="80"]').element.value).toBe(preset.name)
    expect(wrapper.find('[aria-label="接口协议"]').text()).toContain(preset.protocol === 'anthropic' ? 'Claude Messages' : 'OpenAI 兼容')
    expect(wrapper.find('[role=switch]').element.checked).toBe(false)
    if (!['ollama', 'lmstudio'].includes(preset.provider)) {
      expect(request.mock.calls.filter(([path]) => path === '/models')).toHaveLength(0)
      await wrapper.find('input[type=password]').setValue('new-key')
      await wrapper.find('input[type=password]').trigger('blur')
      await flushPromises()
    }
    const fetch = request.mock.calls.find(([path]) => path === '/models')[1].body
    expect(fetch.base_url).toBe(preset.base_url)
    expect(fetch.protocol).toBe(preset.protocol)
    expect(wrapper.find('[aria-label="选择模型"]').text()).toContain('upstream-model')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    const saved = request.mock.calls.find(([path]) => path === '/profiles')[1].body
    expect(saved).toMatchObject({ ...preset, model: 'upstream-model', vision: false })
    expect(saved.api_key).toBe(['ollama', 'lmstudio'].includes(preset.provider) ? '' : 'new-key')
  })

  it('切换预设清空密钥、手动模式与模型状态，并忽略迟到响应', async () => {
    const original = request.getMockImplementation()
    let resolveOld
    request.mockImplementation((path, options) => path === '/models' ? new Promise(resolve => { resolveOld = resolve }) : original(path, options))
    await open(); await choose('deepseek')
    await wrapper.find('input[type=password]').setValue('old-key')
    await wrapper.find('input[type=password]').trigger('blur')
    await manualInput().setValue(true)
    await wrapper.find('input[placeholder="上游不支持获取列表时手动填写"]').setValue('old-model')
    await wrapper.find('[role=switch]').setValue(true)
    await wrapper.find('.ais-change-provider').trigger('click')
    await wrapper.find('.ais-provider-search input').setValue('谷歌')
    await choose('gemini')
    resolveOld({ models: ['old-model'] }); await flushPromises()
    expect(wrapper.find('input[type=password]').element.value).toBe('')
    expect(manualInput().element.checked).toBe(false)
    expect(wrapper.find('[role=switch]').element.checked).toBe(false)
    expect(wrapper.text()).not.toContain('old-model')
    expect(wrapper.find('.ais-primary').attributes('disabled')).toBeDefined()
    await wrapper.find('.ais-change-provider').trigger('click')
    expect(wrapper.findAll('.ais-provider-choice')).toHaveLength(14)
  })

  it.each(['ollama', 'lmstudio'])('%s 失败提示检查本地服务，仍可手动填写后保存', async provider => {
    const original = request.getMockImplementation()
    request.mockImplementation(async (path, options) => { if (path === '/models') throw new Error('连接失败'); return original(path, options) })
    await open(); await choose(provider)
    expect(wrapper.find('[role=dialog]').text()).toContain('请检查本地服务是否已启动')
    await manualInput().setValue(true)
    await wrapper.find('input[placeholder="上游不支持获取列表时手动填写"]').setValue('local-model')
    expect(wrapper.find('.ais-primary').attributes('disabled')).toBeUndefined()
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(request.mock.calls.find(([path]) => path === '/profiles')[1].body).toMatchObject({ provider, model: 'local-model', api_key: '' })
  })

  it('已有云端配置切换到本地时明确清空保存的密钥', async () => {
    const original = request.getMockImplementation()
    const profile = { ...presets[0], id: 'saved', has_key: true, model: 'cloud-model', vision: false }
    request.mockImplementation(async (path, options) => path === '/settings' ? { profiles: [profile], presets, defaults: {} } : original(path, options))
    await open()
    await wrapper.find('[aria-label="关闭服务弹窗"]').trigger('click')
    await wrapper.find('.ais-service-card').trigger('click'); await flushPromises()
    expect(request.mock.calls.find(([path]) => path === '/models')[1].body.api_key).toBeNull()
    await wrapper.find('.ais-change-provider').trigger('click'); await choose('ollama')
    expect(request.mock.calls.filter(([path]) => path === '/models').at(-1)[1].body).toMatchObject({ profile_id: 'saved', api_key: '' })
    expect(wrapper.find('input[type=password]').attributes('placeholder')).not.toContain('保留已有密钥')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(request.mock.calls.find(([path]) => path === '/profiles/saved')[1].body.api_key).toBe('')
  })

  it('搜索列表支持 Tab 焦点循环和 Escape 关闭后焦点恢复', async () => {
    await open()
    await wrapper.find('[aria-label="关闭服务弹窗"]').trigger('click')
    wrapper.find('.ais-add').element.focus()
    await wrapper.find('.ais-add').trigger('click')
    const dialog = wrapper.find('[role=dialog]')
    await dialog.trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(wrapper.findAll('.ais-provider-choice').at(-1).element)
    await dialog.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(wrapper.find('[aria-label="关闭服务弹窗"]').element)
    await dialog.trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.find('.ais-add').element)
  })
})

it('模块导航统一显示用途，并支持键盘切换', async()=>{
  wrapper=mount(AiSettings,{attachTo:document.body,global:{stubs:{LocalSearchSettings:true,AgentSettings:true}}})
  await flushPromises()
  expect(wrapper.findAll('[role=tab]').map(tab=>tab.text())).toEqual(['模型服务连接与默认模型','本地检索按意思查找聊天','Agent对话与查找偏好','用量记录调用明细与消耗'])
  await wrapper.find('#ais-config-tab').trigger('keydown',{key:'ArrowRight'});await flushPromises()
  expect(wrapper.find('#ais-local-tab').attributes('aria-selected')).toBe('true')
  expect(document.activeElement.id).toBe('ais-local-tab')
  await wrapper.find('#ais-local-tab').trigger('keydown',{key:'End'});await flushPromises()
  expect(wrapper.find('#ais-usage-tab').attributes('aria-selected')).toBe('true')
})
