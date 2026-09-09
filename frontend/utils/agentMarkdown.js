import MarkdownIt from 'markdown-it'

// 在 Markdown 文本节点中解析来源，避免把代码块或代码示例误变成按钮。
const md = new MarkdownIt({ html: false, linkify: false, breaks: true })
md.renderer.rules.image = () => '[图片]'
md.renderer.rules.link_open = () => '<span>'
md.renderer.rules.link_close = () => '</span>'
const citation = /\[\[([a-f0-9]{24})\]\]|\(\s*source\s*:\s*([a-f0-9]{24})\s*\)|（\s*source\s*[:：]\s*([a-f0-9]{24})\s*）|\[source\s*:\s*([a-f0-9]{24})\]/gi
const unfinished = /(?:\[\[[a-f0-9]{0,24}\]?|[（(]\s*(?:s|so|sou|sour|sourc|source)(?:\s*[:：]\s*[a-f0-9]{0,24})?)$/i
md.core.ruler.after('inline', 'agent_citation', state => {
  for (const block of state.tokens) {
    if (block.type !== 'inline') continue
    block.children = block.children.flatMap(token => {
      if (token.type !== 'text') return [token]
      const content = state.env.streaming ? token.content.replace(unfinished, '') : token.content
      const parts = [], text = value => { if (value) { const t = new state.Token('text', '', 0); t.content = value; parts.push(t) } }
      let offset = 0
      for (const match of content.matchAll(citation)) {
        text(content.slice(offset, match.index))
        const id = match.slice(1).find(Boolean).toLowerCase()
        const ref = new state.Token('html_inline', '', 0)
        if (state.env.citations.some(item => item.source === id)) {
          if (!state.env.ids.includes(id)) state.env.ids.push(id)
          const number = state.env.ids.indexOf(id) + 1
          ref.content = `<button type="button" class="agent-ref" data-source="${id}" aria-haspopup="dialog" aria-expanded="false" aria-label="查看来源 ${number}">${number}</button>`
        } else ref.content = '<span class="agent-ref-unresolved">[来源待核实]</span>'
        parts.push(ref)
        offset = match.index + match[0].length
      }
      text(content.slice(offset))
      return parts
    })
  }
})

export const renderAgentMarkdown = (text, citations = [], streaming = false) => md.render(text || '', { citations, streaming, ids: [] })
