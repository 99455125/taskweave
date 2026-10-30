"""Bounded Nacos 2.x v1 compatibility HTTP client."""
import ssl
from urllib.parse import urlsplit

import httpx
from taskweave.plugins.sdk import PluginError


class NacosClient:
    def __init__(self, ctx, profile):
        self.ctx = ctx
        try:
            profiles = {**ctx.environment, **ctx.task_parameters}['nacos_profiles']
            self.config = profiles[profile]
            url = self.config['url'].rstrip('/')
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/nacos'):
                raise ValueError()
            if parsed.scheme == 'http' and self.config.get('allow_http') is not True:
                raise ValueError()
            if bool(self.config.get('username')) != bool(self.config.get('password_ref')):
                raise ValueError()
            self.base = url if parsed.path == '/nacos' else url + '/nacos'
            self.namespace = self.config.get('namespace', '')
            self.timeout = self.config.get('timeout_seconds', 15)
            if not isinstance(self.namespace, str) or type(self.timeout) is not int or not 1 <= self.timeout <= 60:
                raise ValueError()
            self.ssl = ssl.create_default_context(cafile=self.config.get('ca_file'))
        except (KeyError, TypeError, ValueError, OSError, ssl.SSLError):
            raise PluginError('NACOS_CONFIG_INVALID', 'Nacos 环境配置无效；请检查地址、认证和连接设置') from None
        self.token = None

    async def request(self, method, path, params=None, data=None, headers=None):
        if self.ctx.cancelled():
            raise PluginError('CANCELLED')
        sent = False
        try:
            async with httpx.AsyncClient(verify=self.ssl, timeout=self.timeout, follow_redirects=False, trust_env=False, headers={'Accept-Encoding': 'identity'}) as client:
                if self.config.get('username') and self.token is None:
                    secret = self.ctx.resolve_secret(self.config['password_ref'])
                    if not isinstance(secret, str) or not secret:
                        raise PluginError('NACOS_SECRET_UNAVAILABLE', '无法读取 Nacos 密码')
                    login = await client.post(self.base + '/v1/auth/login', data={'username': self.config['username'], 'password': secret})
                    if login.status_code != 200:
                        raise PluginError('NACOS_AUTH_FAILED', 'Nacos 登录失败')
                    try:
                        self.token = login.json()['accessToken']
                    except (ValueError, KeyError, TypeError):
                        raise PluginError('NACOS_AUTH_FAILED', 'Nacos 登录响应无效') from None
                    if not isinstance(self.token, str) or not self.token:
                        raise PluginError('NACOS_AUTH_FAILED', 'Nacos 登录响应无效')
                if self.ctx.cancelled():
                    raise PluginError('CANCELLED')
                request_params = dict(params or {})
                if self.token:
                    request_params['accessToken'] = self.token
                sent = method in ('POST', 'DELETE')
                async with client.stream(method, self.base + path, params=request_params, data=data, headers=headers) as response:
                    if response.status_code != 200:
                        if sent and response.status_code >= 500:
                            raise PluginError('NACOS_WRITE_UNKNOWN', '服务端错误，发布结果未知；请核对目标配置')
                        raise PluginError('NACOS_HTTP_ERROR', f'Nacos 请求失败（HTTP {response.status_code}）')
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 2 * 1024 * 1024:
                            if sent:
                                raise PluginError('NACOS_WRITE_UNKNOWN', '响应过大，发布结果未知；请核对目标配置')
                            raise PluginError('NACOS_RESPONSE_TOO_LARGE')
                        chunks.append(chunk)
                    return b''.join(chunks).decode('utf-8')
        except (httpx.HTTPError, UnicodeError):
            if sent:
                raise PluginError('NACOS_WRITE_UNKNOWN', '发布结果未知，请核对目标配置后再重试') from None
            raise PluginError('NACOS_CONNECTION_FAILED', 'Nacos 请求失败') from None
