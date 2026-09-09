// SSE 与查询快照共享合并规则，重放旧事件不会覆盖较新的步骤状态。
export const mergeTimeline = (current = [], incoming = []) => {
  const items = new Map(current.map(item => [item.id, item]))
  for (const item of incoming) {
    if (!items.has(item.id) || (item.revision || 0) > (items.get(item.id).revision || 0)) items.set(item.id, item)
  }
  return [...items.values()].sort((a, b) => (a.seq || 0) - (b.seq || 0)).slice(-200)
}
