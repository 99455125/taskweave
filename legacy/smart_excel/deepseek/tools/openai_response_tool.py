# -*- coding: utf-8 -*-
import functools


def extract_openai_content(func):
    """装饰器：提取 OpenAI API 响应中大模型返回的实际内容

    Args:
        func: 被装饰的函数

    Returns:
        装饰后的函数，返回模型回复的实际内容
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        response = func(*args, **kwargs)

        # 处理流式响应
        if kwargs.get('stream', False):
            # 对于流式响应，返回生成器提取内容
            def content_generator():
                for chunk in response:
                    if hasattr(chunk.choices[0], 'delta') and hasattr(chunk.choices[0].delta, 'content'):
                        content = chunk.choices[0].delta.content
                        if content is not None:
                            yield content

            return content_generator()
        else:
            # 对于非流式响应，直接提取内容
            try:
                return response.choices[0].message.content
            except (AttributeError, IndexError) as e:
                # 如果提取失败，返回原始响应
                return response

    return wrapper