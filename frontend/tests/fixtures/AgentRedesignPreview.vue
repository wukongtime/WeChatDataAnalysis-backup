<template>
  <div class="preview-toolbar"><strong>AI 助手 · 交互预览</strong><button @click="height = height === 800 ? 560 : 800">{{ height }}px 高度</button><button @click="dark = !dark; applyTheme()">{{ dark ? '浅色' : '深色' }}</button><button @click="reset">恢复示例</button><span>本页使用示例数据，不调用模型</span></div>
  <main class="preview-stage" :style="{ height: height + 'px' }"><div class="preview-chat"><h2>南京出行</h2><p>在右侧查看 AI 助手，点击引用核对原文。</p><p v-if="located" role="status">已定位：{{ located.text }}</p></div><ChatAgentPanel :key="seed" account="preview" :contact="contact" :contacts="contacts" :prepare-source="prepare" :locate-source="locate" @close="closed = true" v-if="!closed" /><button v-else @click="closed = false">打开 AI 助手</button></main>
  <p class="preview-note">交互：模型选择、读取范围、跟随 / 固定、历史、工具、输入框、引用、展开 / 收起。示例对话仅用于验证布局。</p>
</template>
<script setup>
import { ref } from 'vue'
import ChatAgentPanel from '../../components/chat/ChatAgentPanel.vue'
const height = ref(800), dark = ref(false), seed = ref(0), closed = ref(false), located = ref(null)
const contact = { username:'sample', name:'文海健9.8' }, contacts=[contact,{username:'travel',name:'南京出行讨论群'}]
const source = {source:'aaaaaaaaaaaaaaaaaaaaaaaa',username:'sample',anchor:'msg2',name:'文海健9.8',sender:'文海健',time:1788849120,text:'费用先记到 AA 表里，晚点再一起核对。'}
const answer = `## 南京出行梳理
目前聊到了行程、费用和兼职安排，以下是已经确认和仍需核对的内容。
### 已经提到
1. **行程**：讨论过南京出行，但具体出发时间还没敲定。[[aaaaaaaaaaaaaaaaaaaaaaaa]]
2. **费用**：提到了 AA 记账表，金额信息仍需核对。[[bbbbbbbbbbbbbbbbbbbbbbbb]]
3. **安排**：聊到了兼职，需要再确认是否影响行程。[[cccccccccccccccccccccccc]]
### 还没确认
- 出发时间与交通方式
- 是否涉及具体演唱会或场次 [[dddddddddddddddddddddddd]]
### 需要注意
聊天中只提到“追星”“演唱会”，尚不能确定具体活动。`
const citations = ['a','b','c','d'].map((id,index)=>({...source,source:id.repeat(24),text:index === 0 ? '出发时间我们还没定，再看一下。' : source.text}))
const makeRun=()=>({id:'run1',status:'completed',elapsed_seconds:18,answer,citations,coverage_warnings:['我未解析图片和《旅行AA记账表.xlsx》文件内容，费用数字来自聊天文本。','部分范围仍有未读取的消息，当前回答仅依据已读取资料。'],usage:{calls:6,input_tokens:1800,output_tokens:420},timeline:[{id:'t1',kind:'tool',seq:1,status:'completed',text:'查找南京出行安排',started_at:1,finished_at:3,result:{returned:12}}]})
const thread={id:'thread1',username:'sample',title:'南京出行梳理',scope:['sample'],latest_run:'run1',messages:[{id:'q1',role:'user',run_id:'run1',text:'帮我梳理最近的南京出行安排，还有哪些事没定？'}]}
const withContext = () => ({ ...makeRun(), account:'preview', version:1, read_count:242, source_count:242, time_range:{start:1788624000,end:1788912000}, intent:{mode:'overview'}, analysis:{known:true,complete:true,analyzed:242,segments:12,findings:24,coverage:[{username:'sample',read:121,analyzed:121,complete:true},{username:'travel',read:121,analyzed:121,complete:true}]},answer_context:{status:'completed',sources:[{source:source.source,text_chars:source.text.length,truncated:false}],summary_sources:citations.map(x=>x.source),summary_segments:12,omitted:241} })
let run=withContext()
const state = ref({selected:{},drafts:{},pinned:{}})
window.useState=()=>state
window.useSettingsDialog=()=>({openDialog:()=>{window.alert('这里会打开现有 AI 服务设置。')}})
window.useAiApi=()=>({agentEvents:()=>()=>{},events:()=>()=>{},request:async(path,options={})=>{
  // ?cold=1 用于浏览器验证首次无缓存、模型配置延迟返回的场景。
  if(path==='/settings' && new URLSearchParams(location.search).has('cold')) await new Promise(resolve=>setTimeout(resolve,6000))
  if(path==='/settings')return {profiles:[{id:'local',name:'我的文本模型',model:'text-model'},{id:'vision',name:'视觉模型',vision:true,model:'vision-model'}]}
  if(path==='/agent/threads')return options.method==='POST' ? {...thread,id:'new',messages:[],latest_run:''} : [thread]
  if(path==='/agent/threads/thread1') {if(options.method==='PATCH')Object.assign(thread,options.body);return {...thread}}
  if(path==='/agent/runs/run1')return run
  if(path==='/agent/runs/run1/materials') {
    const {kind,offset=0}=options.query
    if(kind==='statistics')return {total_messages:242,items:[{day:'2026-09-08',username:'sample',sender:'文海健',count:121},{day:'2026-09-08',username:'travel',sender:'我',count:121}],has_more:false}
    if(kind==='sources')return {items:citations,total:242,has_more:offset===0}
    return {items:Array.from({length:offset ? 4 : 20},(_,i)=>({id:String(offset+i),text:`待确认事项 ${offset+i+1}：出发时间和费用需要再次核对。`,sources:[source.source],citations:[source]})),total:24,has_more:offset===0}
  }
  if(path==='/conversations')return contacts
  if(path.endsWith('/messages')) {run={...run,status:'running',segment_started:Date.now()/1000,stage:'正在查找聊天记录'};return run}
  if(path.endsWith('/stop')) {run={...run,status:'cancelled'};return run}
  return []
}})
const prepare = async () => ({messages:[{id:'msg1',senderDisplayName:'我',createTime:1788848880,content:'大概每人预算多少？'},{id:'msg2',senderDisplayName:'文海健',createTime:1788849120,content:source.text},{id:'msg3',senderDisplayName:'我',createTime:1788849300,content:'好的，我看看其他人的时间再定。'}]})
const locate = async value => {located.value=value;return true}
const applyTheme=()=>document.documentElement.dataset.theme=dark.value?'dark':'light'
const reset=()=>{run=withContext();state.value={selected:{},drafts:{},pinned:{}};closed.value=false;seed.value++}
</script>
<style>
/* 预览复用应用的明暗主题变量，避免脱离主应用时丢失文字与表单颜色。 */
:root{--app-surface-bg:#fff;--app-surface-soft:#f7f7f7;--app-border:#e7e7e7;--app-text-primary:#191919;--app-text-secondary:#5f5f5f}
html[data-theme=dark]{--app-surface-bg:#242424;--app-surface-soft:#2e2e2e;--app-border:#373737;--app-text-primary:#f5f5f5;--app-text-secondary:#c7c7c7;color-scheme:dark}

*{box-sizing:border-box}body{margin:0;background:#f3f6f8;font-family:'Microsoft YaHei','PingFang SC',sans-serif;color:#20272f}button{font:inherit;cursor:pointer}h1,h2,h3,h4,p,ol,ul{margin:0}button{border:0}ol{list-style:decimal}ul{list-style:disc}.preview-toolbar{height:56px;display:flex;align-items:center;gap:12px;padding:0 24px;font-size:13px}.preview-toolbar button{color:#25352d;padding:6px 12px;background:white;border:1px solid #ddd;border-radius:6px}.preview-toolbar span{color:#7b8490;font-size:12px;margin-left:auto}.preview-stage{position:relative;display:flex;width:min(1060px,calc(100vw - 48px));margin:0 auto;background:#fff;border:1px solid #e7e9ed;overflow:hidden}.preview-chat{flex:1;padding:32px;background:#f7f8fa;color:#7b8490}.preview-chat h2{font-size:18px;color:#25352d;margin-bottom:16px}.preview-chat p{margin:14px 0}.preview-note{text-align:center;font-size:12px;margin:16px;color:#7b8490}html[data-theme=dark] body{background:#191d20;color:#e0e6e8}html[data-theme=dark] .preview-stage{background:#222629;color:#e0e6e8}html[data-theme=dark] .preview-chat{background:#202426}
</style>
