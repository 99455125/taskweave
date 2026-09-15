# -*- coding: utf-8 -*-
import json
import functools
import logging

import requests
from ..config.deepseek_config import Config
import re

def ds_http_extract_content(func):
    """装饰器：提取 API 响应中大模型返回的实际内容

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
            # 对于流式响应，直接返回生成器
            return response
        else:
            # 对于非流式响应，解析 JSON 并提取内容
            try:
                response_json = json.loads(response.content.decode('utf-8'))
                model_message = response_json["choices"][0]["message"]["content"]
                return model_message
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                # 如果解析失败，返回原始响应
                return response

    return wrapper

def ds_web_agent_extract_content(func):
    """装饰器：提取 API 响应中大模型返回的实际内容

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
            # 对于流式响应，直接返回生成器
            return response
        else:
            # 对于非流式响应，解析 JSON 并提取内容
            try:
                response_json = json.loads(response.content.decode('utf-8'))
                model_message = response_json["data"]["response"]
                return remove_thinking(model_message)
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                # 如果解析失败，返回原始响应
                return response

    return wrapper


def remove_thinking(content):
    """
    从大模型返回的内容中移除 <think></think> 标签及其包裹的思考过程

    Args:
        content: 大模型返回的原始内容

    Returns:
        清理后的内容
    """
    import re

    # 使用正则表达式匹配并移除<think>...</think>部分
    cleaned_content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)

    # 去除可能留下的多余空行
    cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)

    return cleaned_content.strip()


class LLMResponseParser:
    """大模型响应解析工具类"""

    @staticmethod
    def parse_response(response_content):
        original_response_content = response_content
        # 检查是否是Markdown代码块中的JSON
        code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_content)
        if code_block_match:
            # 尝试解析代码块中的内容
            try:
                json_content = code_block_match.group(1)
                json_response = json.loads(json_content)
                if isinstance(json_response, dict):
                    # 检查JSON中是否包含sql
                    if "sql" in json_response:
                        return "sql", {
                            "sql_text": json_response["sql"]
                        }
            except (json.JSONDecodeError, TypeError):
                pass  # 代码块中不是有效JSON，继续后续处理

        # 尝试直接解析整个响应为JSON
        try:
            json_response = json.loads(response_content)
            if isinstance(json_response, dict):
                # 检查JSON中是否包含sql
                if "sql" in json_response:
                    return "sql", {
                        "sql_text": json_response["sql"]
                    }
        except (json.JSONDecodeError, TypeError):
            pass  # 不是有效JSON，继续使用正则表达式处理

        # 解析文本格式 sql_text
        sql_match = re.search(r'```\s*sql:\s*([\s\S]*)\s*```', response_content, re.IGNORECASE)
        if sql_match:
            sql_text = sql_match.group(1)
            return "sql", {
                "sql_text": sql_text
            }

        # 解析非markdown文本格式 sql_text
        sql_match = re.search(r'\s*sql:\s*([\s\S]*)\s*;', response_content, re.IGNORECASE)
        if sql_match:
            sql_text = sql_match.group(1)
            return "sql", {
                "sql_text": sql_text
            }

        # 解析非markdown文本格式 sql_text
        sql_match = re.search(r'\s*sql:\s*([\s\S]*)\s*', response_content, re.IGNORECASE)
        if sql_match:
            sql_text = sql_match.group(1)
            return "sql", {
                "sql_text": sql_text
            }

        # 无法解析的情况
        return "error_msg", {"error_msg": original_response_content}
