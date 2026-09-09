"""任务内资料存储；运行状态只保存游标，不反复序列化全部聊天原文。"""
import json
from collections.abc import MutableMapping


class Workspace:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS agent_material (
                    run_id TEXT NOT NULL, source TEXT NOT NULL, username TEXT NOT NULL,
                    time INTEGER NOT NULL, anchor TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(run_id,source), UNIQUE(run_id,username,anchor));
                CREATE INDEX IF NOT EXISTS agent_material_range ON agent_material(run_id,username,time);
                CREATE TABLE IF NOT EXISTS agent_piece (
                    run_id TEXT NOT NULL, version INTEGER NOT NULL, id TEXT NOT NULL,
                    kind TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(run_id,version,id));
                CREATE INDEX IF NOT EXISTS agent_piece_kind ON agent_piece(run_id,version,kind,id);
                CREATE TRIGGER IF NOT EXISTS agent_delete_workspace AFTER DELETE ON records
                WHEN old.kind='agent_run' BEGIN
                    DELETE FROM agent_material WHERE run_id=old.id;
                    DELETE FROM agent_piece WHERE run_id=old.id;
                END;
            ''')

    def evidence(self, run_id):
        return Evidence(self, run_id)

    def inherit(self, old_id, new_id):
        with self.store.connection() as db:
            db.execute('INSERT OR IGNORE INTO agent_material SELECT ?,source,username,time,anchor,body FROM agent_material WHERE run_id=?', (new_id, old_id))

    def restrict(self, run_id, scope, interval):
        placeholders = ','.join('?' for _ in scope)
        with self.store.connection() as db:
            db.execute(f'DELETE FROM agent_material WHERE run_id=? AND (username NOT IN ({placeholders}) OR time<? OR time>?)',
                [run_id, *scope, interval.get('start', 0), interval.get('end', 2**63-1)])

    def put(self, run_id, version, id, kind, body):
        with self.store.connection() as db:
            db.execute('INSERT OR REPLACE INTO agent_piece VALUES(?,?,?,?,?)',
                (run_id, version, id, kind, json.dumps(body, ensure_ascii=False)))

    def get(self, run_id, version, id):
        with self.store.connection() as db:
            row = db.execute('SELECT body FROM agent_piece WHERE run_id=? AND version=? AND id=?', (run_id,version,id)).fetchone()
        return json.loads(row[0]) if row else None

    def page(self, run_id, version, kind, offset=0, limit=20, query=''):
        with self.store.connection() as db:
            params = [run_id, version, kind]
            where = 'run_id=? AND version=? AND kind=?'
            if query:
                where += ' AND instr(lower(body),lower(?))>0'
                params.append(query)
            total = db.execute('SELECT count(*) FROM agent_piece WHERE '+where, params).fetchone()[0]
            rows = db.execute('SELECT id,body FROM agent_piece WHERE '+where+' ORDER BY id LIMIT ? OFFSET ?', [*params,limit,offset]).fetchall()
        return {'items': [dict(json.loads(r[1]), id=r[0]) for r in rows], 'total': total,
                'offset': offset, 'has_more': offset+len(rows)<total}

    def statistics(self, run_id, offset=0, limit=20):
        with self.store.connection() as db:
            total = db.execute('SELECT count(*) FROM agent_material WHERE run_id=?', (run_id,)).fetchone()[0]
            # 分组也分页，避免大量发言人再次撑满请求。
            rows = db.execute("SELECT date(time,'unixepoch','localtime') day, username, json_extract(body,'$.sender_id') sender_id, json_extract(body,'$.sender') sender, count(*) count FROM agent_material WHERE run_id=? GROUP BY day,username,sender_id,sender ORDER BY day,username,sender_id,sender LIMIT ? OFFSET ?", (run_id,limit+1,offset)).fetchall()
            days = db.execute("SELECT date(time,'unixepoch','localtime') day,count(*) count FROM agent_material WHERE run_id=? GROUP BY day ORDER BY day LIMIT ? OFFSET ?",(run_id,limit+1,offset)).fetchall()
            senders = db.execute("SELECT coalesce(nullif(json_extract(body,'$.sender_id'),''),username||':'||coalesce(json_extract(body,'$.sender'),'unknown')) sender_id,max(json_extract(body,'$.sender')) sender,count(*) count FROM agent_material WHERE run_id=? GROUP BY sender_id ORDER BY count DESC,sender_id LIMIT ? OFFSET ?",(run_id,limit+1,offset)).fetchall()
        return {'total_messages': total, 'items': [dict(r) for r in rows[:limit]], 'has_more': len(rows)>limit, 'offset':offset,
            'daily_totals':[dict(r) for r in days[:limit]],'daily_has_more':len(days)>limit,
            'sender_ranking':[dict(r) for r in senders[:limit]],'sender_has_more':len(senders)>limit}


class Evidence(MutableMapping):
    def __init__(self, workspace, run_id):
        self.workspace, self.run_id = workspace, run_id

    def __getitem__(self, key):
        with self.workspace.store.connection() as db:
            row = db.execute('SELECT body FROM agent_material WHERE run_id=? AND source=?', (self.run_id,key)).fetchone()
        if not row: raise KeyError(key)
        return json.loads(row[0])

    def __setitem__(self, key, value):
        with self.workspace.store.connection() as db:
            self._set(db,key,value)

    def _set(self,db,key,value):
        value = dict(value, source=key)
        existing = db.execute('SELECT source,body FROM agent_material WHERE run_id=? AND username=? AND anchor=?',
            (self.run_id,value['username'],value.get('anchor',key))).fetchone()
        if existing:
            old = json.loads(existing[1])
            key = existing[0]
            # 回查上下文补充元数据，不丢掉先前保存的消息身份与已提取附件文字。
            if old.get('coverage','').startswith('已分析') and old.get('text','').startswith(value.get('text','')):
                value['text']=old['text']
            value=old | value
            value.update(source=key, match_methods=sorted(set(old.get('match_methods',[])+value.get('match_methods',[]))))
        db.execute('INSERT OR REPLACE INTO agent_material VALUES(?,?,?,?,?,?)',
            (self.run_id,key,value['username'],value.get('time',0),value.get('anchor',key),json.dumps(value,ensure_ascii=False)))

    def put_many(self,values):
        with self.workspace.store.connection() as db:
            for value in values:self._set(db,value['source'],value)

    def __delitem__(self, key):
        with self.workspace.store.connection() as db:
            if not db.execute('DELETE FROM agent_material WHERE run_id=? AND source=?',(self.run_id,key)).rowcount:
                raise KeyError(key)

    def __len__(self):
        with self.workspace.store.connection() as db:
            return db.execute('SELECT count(*) FROM agent_material WHERE run_id=?',(self.run_id,)).fetchone()[0]

    def __iter__(self):
        for value in self.rows(): yield value['source']

    def rows(self, offset=0, limit=None, reverse=False, query=''):
        position, remaining = offset, limit
        while remaining is None or remaining > 0:
            count = min(100, remaining) if remaining is not None else 100
            with self.workspace.store.connection() as db:
                where, params = 'run_id=?', [self.run_id]
                if query:
                    where += " AND instr(lower(json_extract(body,'$.text')),lower(?))>0"
                    params.append(query)
                rows = db.execute('SELECT body FROM agent_material WHERE '+where+' ORDER BY rowid '+('DESC' if reverse else 'ASC')+' LIMIT ? OFFSET ?',[*params,count,position]).fetchall()
            for row in rows: yield json.loads(row[0])
            if len(rows)<count: break
            position += count
            if remaining is not None: remaining -= count

    def values(self):
        return self.rows()

    def replace(self, values):
        with self.workspace.store.connection() as db:
            db.execute('DELETE FROM agent_material WHERE run_id=?',(self.run_id,))
            for key,value in values.items():self._set(db,key,value)
