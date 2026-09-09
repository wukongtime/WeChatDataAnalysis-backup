import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { describe, expect, it } from 'vitest'
import AgentRun from '../components/chat/AgentRun.vue'
import { mergeTimeline, groupTimelineTools } from '../utils/agentTimeline'

const base = () => ({id:'run1',status:'running',stage:'搜索聊天记录',segment_started:100,stage_started_at:101,elapsed_seconds:0,read_count:50,timeline:[
  {id:'tool1',seq:1,revision:2,kind:'tool',text:'搜索报价',status:'completed',started_at:100,finished_at:102,result:{returned:8}},
  {id:'note',seq:2,revision:1,kind:'progress',text:'找到两次报价，继续核对修改。',status:'completed',started_at:103},
  {id:'tool2',seq:3,revision:1,kind:'tool',text:'读取后续消息',status:'running',started_at:103},
],answer:'',citations:[]})
const setup = (extra={}) => mount(AgentRun,{props:{run:base(),now:105000,nearBottom:true,latest:true,viewState:reactive({}),...extra}})

describe('Agent 执行对话流',()=>{
  it('过程进展共用 Markdown 引用渲染，折叠历史仍显示实时状态', async () => {
    const id = '622367649b6ca270ffad893a', r = base()
    r.timeline[1].text = `约的是 **周三** (source: ${id})`
    r.citations = [{ source: id, username: 'friend', text: '周三晚饭' }]
    const w = setup({ run: r, viewState: reactive({}) })
    expect(w.find('.agent-progress-note strong').text()).toBe('周三')
    expect(w.find('.agent-progress-note .agent-ref').exists()).toBe(true)
    expect(w.find('.agent-progress-note').text()).not.toContain(id)
    await w.find('.agent-process-toggle').trigger('click')
    expect(w.find('.agent-process-toggle').attributes('aria-expanded')).toBe('false')
    expect(w.find('.agent-process').element.style.display).toBe('none')
    expect(w.find('.agent-stream-status').isVisible()).toBe(true)
    expect(w.find('.agent-stream-status').text()).toContain('搜索聊天记录')
    w.unmount()
  })
  it('按顺序显示工具和关键进展，完成保留简洁记录并可手动收起',async()=>{
    const w=setup()
    expect(w.text().indexOf('搜索报价')).toBeLessThan(w.text().indexOf('找到两次报价'))
    expect(w.text().indexOf('找到两次报价')).toBeLessThan(w.text().indexOf('读取后续消息'))
    await w.setProps({run:{...base(),status:'completed',answer:'最终报价为100元',elapsed_seconds:5}})
    expect(w.find('.agent-process-toggle').attributes('aria-expanded')).toBe('true')
    expect(w.find('.agent-final-answer').text()).toContain('最终报价')
    await w.find('.agent-process-toggle').trigger('click')
    expect(w.find('.agent-process-toggle').attributes('aria-expanded')).toBe('false')
    w.unmount()
  })
  it('完成与滚动不覆盖用户主动收起的状态',async()=>{
    const w=setup({nearBottom:false})
    await w.find('.agent-process-toggle').trigger('click')
    await w.setProps({run:{...base(),status:'completed'}})
    await w.setProps({nearBottom:true})
    expect(w.find('.agent-process-toggle').attributes('aria-expanded')).toBe('false')
    w.unmount()
  })
  it('失败保持过程展开，恢复按钮按错误类型变化',async()=>{
    const w=setup({run:{...base(),status:'failed',error:'查询指令仍无法处理',error_info:{action:'retry',diagnostic_id:'diagnostic'}}})
    expect(w.find('.agent-process-toggle').attributes('aria-expanded')).toBe('true')
    expect(w.text()).toContain('重试这一步')
    await w.setProps({run:{...base(),status:'failed',error_info:{action:'settings'}}})
    expect(w.text()).toContain('检查 AI 服务')
    expect(w.text()).not.toContain('重试这一步')
    w.unmount()
  })
  it('失败和补充记录不会假装成完成',()=>{
    const r=base();r.timeline.push({id:'supp',seq:4,revision:1,kind:'supplement',text:'只看上周',status:'received'})
    r.timeline[2].status='failed'
    const w=setup({run:r})
    expect(w.text()).toContain('已收到补充要求')
    expect(w.find('.agent-tool.is-failed').text()).toContain('这一步未完成')
    w.unmount()
  })
  it('只合并相邻同范围工具，展开保留逐次结果且不隐藏失败', async () => {
    const a = {id:'a',kind:'tool',action:'read_context',username:'friend',text:'读取上下文',status:'completed',result:{returned:21},started_at:100,finished_at:102}
    const b = {...a,id:'b',cached:true,status:'failed'}
    const r = {...base(),timeline:[a,b]}
    const w = setup({run:r})
    expect(w.findAll('.agent-tool')).toHaveLength(1)
    expect(w.find('.agent-tool > summary').text()).toContain('2 次')
    expect(w.find('.agent-tool > summary').text()).toContain('失败')
    expect(w.find('.agent-tool > summary').text()).not.toContain('21')
    expect(w.findAll('.agent-tool-attempt')).toHaveLength(2)
    expect(w.find('.agent-tool-detail').text()).toContain('复用已读结果')
    const detail=w.find('.agent-tool').element;detail.open=true
    await w.setProps({run:{...r,timeline:[a,{...b,status:'completed',revision:2}]}})
    expect(w.find('.agent-tool').element).toBe(detail)
    expect(detail.open).toBe(true)
    const grouped = groupTimelineTools([a,{id:'p',kind:'progress',text:'核对'},b,{...b,id:'c',username:'other'},{...b,id:'d',start:123}])
    expect(grouped).toHaveLength(5)
    w.unmount()
  })
  it('重放与乱序更新按记录修订号去重',()=>{
    const current=[{id:'a',seq:1,revision:3,status:'completed'},{id:'b',seq:2,revision:1}]
    const merged=mergeTimeline(current,[{id:'c',seq:3,revision:1},{id:'a',seq:1,revision:2,status:'running'},{id:'b',seq:2,revision:2}])
    expect(merged.map(x=>x.id)).toEqual(['a','b','c'])
    expect(merged[0].status).toBe('completed')
    expect(merged[1].revision).toBe(2)
  })
  it('历史完成轮次显示简洁记录，兼容旧步骤',()=>{
    const w=setup({run:{id:'old',status:'completed',activity:[{id:'a',text:'原来的读取步骤',status:'completed',started_at:100,finished_at:103}],answer:'历史回答'}})
    expect(w.find('.agent-process-toggle').attributes('aria-expanded')).toBe('true')
    expect(w.text()).toContain('原来的读取步骤')
    w.unmount()
  })
})
