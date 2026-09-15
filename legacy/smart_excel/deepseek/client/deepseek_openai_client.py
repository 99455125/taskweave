# -*- coding: utf-8 -*-
from openai import OpenAI
from deepseek.config.deepseek_config import Config


class DeepseekOpenAIClient:
    """使用 OpenAI SDK 方式调用 Deepseek API 的客户端"""

    def __init__(self, api_key=None):
        """初始化 Deepseek OpenAI 客户端

        Args:
            api_key: API 密钥，默认使用配置文件中的密钥
        """
        self.api_key = api_key or Config.BASE_SECRET
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=f"{Config.URL}/v1"
        )

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
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=stream,
            **kwargs
        )
        return response