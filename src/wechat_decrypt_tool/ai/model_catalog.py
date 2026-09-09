"""models.dev 公共能力目录；请求不携带服务密钥或聊天内容。"""
import asyncio
import json
import hashlib
import time
from urllib.parse import urlparse, quote

import httpx

PROVIDER_IDS = {
    'claude': 'anthropic', 'gemini': 'google', 'kimi': 'moonshotai-cn',
    'qwen': 'alibaba-cn', 'zhipu': 'zhipuai', 'doubao': 'volcengine',
    'siliconflow': 'siliconflow-cn',
}


class ModelCatalog:
    def __init__(self, root, store=None):
        self.store = store
        self.path = root / 'models-dev.json'
        self.data, self.checked_at, self.updated_at = {}, 0, 0
        self.lock = asyncio.Lock()
        try:
            cached = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(cached['data'], dict):
                self.data = cached['data']
                self.updated_at = self.checked_at = float(cached['updated_at'])
        except (OSError, ValueError, KeyError, TypeError):
            pass

    async def refresh(self):
        async with self.lock:
            if time.time() - self.checked_at < (86400 if self.data else 300):
                return
            self.checked_at = time.time()
            try:
                async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                    response = await client.get('https://models.dev/api.json')
                    response.raise_for_status()
                    data = response.json()
                if not isinstance(data, dict) or not any(isinstance(p, dict) and isinstance(p.get('models'), dict) for p in data.values()):
                    return
                self.data, self.updated_at = data, time.time()
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'data': data, 'updated_at': self.updated_at}, ensure_ascii=False), encoding='utf-8')
                temporary.replace(self.path)
            except (httpx.HTTPError, OSError, ValueError):
                # 离线保留上次成功目录，不阻断已有服务和手动配置。
                pass

    def lookup(self, profile, model=None):
        model = model or profile.get('model', '')
        provider = PROVIDER_IDS.get(profile.get('provider'), profile.get('provider'))
        host = urlparse(profile.get('base_url', '')).hostname
        # 优先按实际接口主机匹配，避免自定义代理误用官方供应商的价格和窗口。
        for key, value in self.data.items():
            if isinstance(value, dict) and host and urlparse(value.get('api') or '').hostname == host:
                provider = key
                break
        entry = self.data.get(provider, {})
        item = entry.get('models', {}).get(model)
        match_kind = 'provider'
        if not isinstance(item, dict) and provider in (None, '', 'custom', 'ollama', 'lmstudio'):
            # 自定义兼容接口仅使用唯一精确匹配；不靠名称前缀猜测模型系列或版本。
            matches = []
            for key in ('openai', 'anthropic', 'google', 'deepseek', 'moonshotai', 'alibaba', 'zhipuai', 'mistral', 'xai', 'groq'):
                candidate = self.data.get(key, {})
                candidate_id = model.removeprefix(key + '/')
                candidate_item = candidate.get('models', {}).get(candidate_id)
                if isinstance(candidate_item, dict):
                    matches.append((key, candidate, candidate_item))
            if len(matches) == 1:
                provider, entry, item = matches[0]
                match_kind = 'canonical'
        if not isinstance(item, dict):
            return None
        modalities = item.get('modalities', {})
        limits = item.get('limit', {})
        return {**{key: item[key] for key in ('name', 'family', 'description', 'reasoning', 'tool_call', 'structured_output', 'temperature', 'attachment', 'open_weights', 'knowledge', 'release_date', 'last_updated', 'cost') if key in item},
                'id': model, 'provider_id': provider, 'provider_name': entry.get('name', provider),
                'logo_url': f'https://models.dev/logos/{quote(provider, safe="")}.svg',
                'modalities': modalities, 'limit': limits,
                'vision': 'image' in modalities['input'] if isinstance(modalities.get('input'), list) else None,
                'source': 'models.dev', 'match_kind': match_kind, 'updated_at': self.updated_at}

    @staticmethod
    def upstream_key(profile, model):
        identity = [profile.get('base_url', '').rstrip('/'), profile.get('protocol', 'openai'), model]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def remember(self, profile, items):
        if self.store:
            for item in items:
                self.store.put('model_capabilities', {'metadata': item}, id=self.upstream_key(profile, item['id']))

    def automatic(self, profile, model=None):
        model = model or profile.get('model', '')
        catalog = self.lookup(profile, model) or {}
        saved = self.store.get('model_capabilities', self.upstream_key(profile, model)) if self.store else None
        upstream = saved.get('metadata', {}) if saved else {}
        metadata = {**catalog}
        sources = {key: 'models.dev' for key in catalog if catalog[key] is not None}
        sources.update({f'limit.{key}': 'models.dev' for key in catalog.get('limit', {})})
        for key, value in upstream.items():
            if value is None or key == 'id':
                continue
            if isinstance(value, dict):
                metadata[key] = {**metadata.get(key, {}), **value}
                sources.update({f'{key}.{field}': 'upstream' for field in value})
            else:
                metadata[key] = value
            sources[key] = 'upstream'
        if not metadata:
            return None
        return {**metadata, 'id': model, 'field_sources': sources,
                'source': 'upstream' if any(v == 'upstream' for v in sources.values()) else 'models.dev'}

    def enrich(self, profile):
        automatic = self.automatic(profile)
        metadata = json.loads(json.dumps(automatic or {'id': profile.get('model', '')}))
        overrides = {key: value for key, value in (profile.get('model_overrides') or {}).items() if value is not None}
        sources = metadata.setdefault('field_sources', {})
        for key, value in overrides.items():
            field = {'context_window': 'context', 'max_output_tokens': 'output'}.get(key)
            if field:
                metadata.setdefault('limit', {})[field] = value
                sources[f'limit.{field}'] = 'manual'
            else:
                metadata[key] = value
                sources[key] = 'manual'
        result = {**profile, 'automatic_metadata': automatic, 'model_overrides': overrides, 'model_metadata': metadata}
        if metadata.get('vision') is not None:
            result['vision'] = metadata['vision']
        window = metadata.get('limit', {}).get('context')
        if isinstance(window, int) and window > 0:
            result['context_window'] = window
        return result
