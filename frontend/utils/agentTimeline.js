// SSE 与查询快照共享合并规则，重放旧事件不会覆盖较新的步骤状态。
export const mergeTimeline = (current = [], incoming = []) => {
  const items = new Map(current.map(item => [item.id, item]))
  for (const item of incoming) {
    if (!items.has(item.id) || (item.revision || 0) > (items.get(item.id).revision || 0)) items.set(item.id, item)
  }
  return [...items.values()].sort((a, b) => (a.seq || 0) - (b.seq || 0)).slice(-200)
}

// 只合并相邻、同工具同范围的调用；旁白与补充要求仍保留原来的时间顺序。
export const groupTimelineTools = (records = []) => {
  const groups = []
  for (const item of records) {
    const previous = groups.at(-1)
    const same = item.kind === 'tool' && item.action && previous?.kind === 'tool' &&
      ['action', 'username', 'query', 'start', 'end', 'input_version'].every(key => previous[key] === item[key])
    if (same) previous.calls.push(item)
    else groups.push(item.kind === 'tool' ? { ...item, calls: [item] } : item)
  }
  return groups
}
