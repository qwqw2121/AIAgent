# 让大模型输出结构化信息，总结抓取新闻的内容
#输入：title  content  
# 输出  summary   category  keywords  importance

import json
import sqlite3

from openai import OpenAI

import os
from dotenv import load_dotenv


# 加载 .env 文件
load_dotenv()

# 从环境变量读取 API Key
GLM_API_KEY = os.getenv("GLM_API_KEY")
if not GLM_API_KEY:
    raise ValueError("❌ GLM_API_KEY 未在 .env 中设置！")

client = OpenAI(
    api_key=GLM_API_KEY,
    base_url="https://open.bigmodel.cn/api/paas/v4"
)


def analyze_news(title,content):


    prompt=f"""

你是AI资讯分析专家。

分析下面新闻：

标题:
{title}


正文:
{content}


输出JSON:

{{
"summary":"",
"category":"",
"keywords":[],
"importance":1
}}

要求：
importance范围1-10

"""


    response=client.chat.completions.create(

        model="glm-4.7-flash",

        messages=[
            {
            "role":"user",
            "content":prompt
            }
        ],

        response_format={
            "type":"json_object"
        }

    )


    return json.loads(
        response.choices[0]
        .message.content
    )