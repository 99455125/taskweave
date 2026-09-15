import os

# -*- coding: utf-8 -*-

class Config:
    # deepseek密钥
    BASE_SECRET = os.environ.get("DEEPSEEK_API_KEY", "")
    URL = "https://api.deepseek.com"
    # 步骤调用大模型重试次数
    STEP_RETRY_CNT = 10
