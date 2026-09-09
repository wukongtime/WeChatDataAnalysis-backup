"""面向用户的执行记录；只保存实际动作、公开进展与可恢复状态。"""
import time
import uuid


class AgentTimeline:
    def timeline_item(self, id, kind, text, *, item_id=None, status='completed', **fields):
        run = self.run(id)
        items = run.get('timeline') or [dict(x, seq=i+1, revision=1, kind='status') for i,x in enumerate(run.get('activity', []))]
        now = time.time()
        item = next((x for x in items if x['id'] == item_id), None)
        if item is None:
            item = dict(id=item_id or uuid.uuid4().hex, seq=max(run.get('timeline_seq',0),max((x.get('seq',0) for x in items),default=0)) + 1, revision=0,
                        kind=kind, started_at=now, input_version=run['version'])
            items.append(item)
        item.update(text=text, status=status, revision=item['revision'] + 1, **fields)
        if status not in ('running', 'received'):
            item['finished_at'] = now
        # 大任务的旧过程独立存储；运行快照与前端只保留最近 200 个步骤。
        if hasattr(self,'workspace'):
            self.workspace.put(id,run['version'],f'timeline:{item["seq"]:012d}','timeline',item)
        self.update(id, timeline=items[-200:],timeline_seq=max(x.get('seq',0) for x in items))
        self.store.event(run['account'], 'agent', {'run_id':id, 'thread_id':run['thread_id'], 'timeline_item':item})
        return item['id']

    def close_activity(self, id, status='completed'):
        run = self.run(id)
        for item in run.get('timeline', []):
            if item['kind'] in ('tool', 'status') and item['status'] == 'running':
                self.timeline_item(id, item['kind'], item['text'], item_id=item['id'], status=status)

    def activity(self, id, text, status='running'):
        run = self.run(id)
        active = next((x for x in reversed(run.get('timeline', [])) if x['kind'] == 'tool' and x['status'] == 'running'), None)
        if active:
            self.timeline_item(id, 'tool', active['text'], item_id=active['id'], status='running', detail=text)
        else:
            self.close_activity(id)
            self.timeline_item(id, 'status', text, status=status)
        items = self.run(id).get('activity', [])
        if items and items[-1]['status'] == 'running':
            items[-1].update(status='completed', finished_at=time.time())
        items.append(dict(id=uuid.uuid4().hex, text=text, status=status, started_at=time.time()))
        self.update(id, activity=items[-100:], stage=text, stage_started_at=time.time())

    def model_feedback(self, id, data):
        self.guard(id)
        self.timeline_item(id, 'notice', data['text'], attempt=data['attempt'])
        self.update(id, stage=data['text'], stage_started_at=time.time())
        if data['phase'] == 'answer':
            self.update(id, answer='')
            self.timeline_item(id, 'answer', '', item_id='answer:' + id, status='running')

    @staticmethod
    def public_timeline(run):
        if run.get('timeline'):
            return run['timeline']
        # 旧数据只有动作名称，按原记录展示，不生成不存在的旁白。
        return [dict(x, seq=i + 1, revision=1, kind='status') for i, x in enumerate(run.get('activity', []))]

    def public_thread(self, id, account):
        thread = self.thread(id, account)
        thread['messages']=[m if m['role']=='user' or m.get('scope_revision')==thread['scope_revision'] else
            dict(m,text='读取范围已更新，此轮旧回答不再展示。',citations=[]) for m in thread['messages']]
        with self.store.connection() as db:
            rows = db.execute("SELECT id, json_extract(body,'$.status'), json_extract(body,'$.created'), json_extract(body,'$.elapsed_seconds') FROM records WHERE kind='agent_run' AND account=? AND json_extract(body,'$.thread_id')=? ORDER BY json_extract(body,'$.created')", (account, id)).fetchall()
        return thread | {'runs': [dict(id=r[0], status=r[1], created=r[2], elapsed_seconds=r[3]) for r in rows]}
