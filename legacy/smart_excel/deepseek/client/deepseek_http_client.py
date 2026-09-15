# -*- coding: utf-8 -*-
import requests
from ..config.deepseek_config import Config
from deepseek.tools.http_response_tool import ds_http_extract_content

class DeepseekHttpClient:
    """使用 HTTP 方式调用 Deepseek API 的客户端"""

    def __init__(self, api_key=None):
        """初始化 Deepseek HTTP 客户端

        Args:
            api_key: API 密钥，默认使用配置文件中的密钥
        """
        self.api_key = api_key or Config.BASE_SECRET
        self.base_url = Config.URL

    @ds_http_extract_content
    def chat_completion(self, messages, model="deepseek-chat", stream=False, **kwargs):
        """创建聊天完成请求

        Args:
            messages: 消息列表，包含角色和内容
            model: 使用的模型名称
            stream: 是否使用流式响应
            **kwargs: 其他参数

        Returns:
            API 响应
        """
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs
        }

        if stream:
            # 流式响应处理
            response = requests.post(url, headers=headers, json=payload, stream=True)
            response.raise_for_status()
            return response.iter_lines()
        else:
            # 普通响应处理
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response
