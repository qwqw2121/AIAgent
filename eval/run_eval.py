# eval/run_eval.py
"""
评测脚本（适配「单 Agent + 工具分组」架构）

用法:
  python eval/run_eval.py agent                 # 工具选择准确率 / Tool 成功率 / 延迟 P50·P95 / 引用有效率
  python eval/run_eval.py retrieval             # 检索 Top5 命中率 + MRR
  python eval/run_eval.py load -c 5 -n 20       # 并发压测：并发 c，共 n 次请求
  python eval/run_eval.py export -n 100         # 随机导出 100 条关键事件，供人工标注
  python eval/run_eval.py score eval/label.csv  # 读取人工标注，输出准确率及 95% 置信区间

人工标注口径（label 列填 1 / 0）:
  1 = 事件真实存在，表述与原始新闻一致，无编造
  0 = 事实错误 / 编造 / 重复事件 / 无意义

注意:
  - 评测期间会把「日报后台生成」替换成模拟实现，不会真正启动 daily_flow；只能验证是否请求生成及 force 参数。
  - REPORT_DATE 应是库里已有日报的日期；2099-01-01 用作确定不存在的日期边界用例。
  - 多轮用例复用同一 thread_id，要求 Agent 图配置了 Checkpointer。
  - 无结果回答采用关键词轻量校验，仍建议人工检查是否真的没有编造内容。
"""
import argparse
import asyncio
import csv
import importlib
import json
import os
import random
import re
import statistics
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

AGENT_MODULE = "agent.graph"      # TODO: 你的 Agent 文件所在模块
REPORT_DATE = "2026-10-08"        # TODO: 库里已存在日报的日期
OUT_PATH = os.path.join(ROOT, "eval", "results.json")

# ---------------------------------------------------------------
# 测试集：expect = 期望至少调用的工具集合；空集合表示不应调用任何工具
# TODO: 补到 30 条左右，并保留几条边界 case
# ---------------------------------------------------------------
CASES = [
    # 1-5：常规语义检索与边界意图
    {"q": "最近有哪些大模型发布的新闻？", "expect": {"search_news_semantic"}},
    {"q": "AI 芯片行业最近有什么动态？", "expect": {"search_news_semantic"}},
    {"q": "量子计算有什么新进展？", "expect": {"search_news_semantic"}},
    {"q": "OpenAI 最近发布了什么？", "expect": {"search_news_semantic"}},
    {"q": "今天的大模型新闻有哪些？", "expect": {"search_news_semantic"}},  # “今天”不等于读取日报

    # 6-11：带明确日期的检索问题，验证日期条件不会被误判为日报请求
    {"q": "查一下 2026-10-08 发布的 AI 芯片相关新闻", "expect": {"search_news_semantic"}},
    {"q": "2026 年 10 月 8 日有哪些关于 OpenAI 的新闻？", "expect": {"search_news_semantic"}},
    {"q": "帮我检索 2026-10-08 到 2026-10-10 的大模型新闻", "expect": {"search_news_semantic"}},
    {"q": "截至 2026-10-08，DeepSeek 有哪些相关动态？", "expect": {"search_news_semantic"}},
    {"q": "找出 2026-10-08 那天有关 GPU 的报道，不要日报总结", "expect": {"search_news_semantic"}},
    {"q": "2026-10-08 的新闻里，有没有关于多模态模型的内容？", "expect": {"search_news_semantic"}},

    # 12-16：已有日报读取、日报与检索组合
    {"q": f"帮我总结一下 {REPORT_DATE} 的新闻", "expect": {"get_daily_report"}},
    {"q": f"把 {REPORT_DATE} 的新闻整理成简报", "expect": {"get_daily_report"}},
    {"q": f"读取 {REPORT_DATE} 的日报，列出最重要的三条", "expect": {"get_daily_report"}},
    {"q": f"先看 {REPORT_DATE} 的日报，再查一下 AI 芯片的最新进展",
     "expect": {"get_daily_report", "search_news_semantic"}},  # 跨组组合
    {"q": f"请读取 {REPORT_DATE} 已经生成的日报，不要重新生成", "expect": {"get_daily_report"}},

    # 17-20：日报不存在时应请求生成；评测会 mock 生成函数，不会真的跑流水线
    {"q": "请生成 2099-01-01 的日报", "expect": {"request_daily_report"}},
    {"q": "我需要 2099-01-01 的 AI 新闻简报，如果还没有就发起生成",
     "expect": {"request_daily_report"}},
    {"q": "2026-10-14 的日报有吗？没有的话请生成一份",
     "expect": {"get_daily_report", "request_daily_report"}},
    {"q": "检查 2099-01-01 的日报状态，缺失就创建", "expect": {"get_daily_report", "request_daily_report"}},

    # 21-22：强制重新生成，检查 request_daily_report 的参数 force=true
    {"q": f"强制重新生成 {REPORT_DATE} 的日报，force=true",
     "expect": {"request_daily_report"},
     "expect_args": {"request_daily_report": {"force": True}}},
    {"q": f"忽略已有的 {REPORT_DATE} 日报，重新生成一份最新版本",
     "expect": {"request_daily_report"},
     "expect_args": {"request_daily_report": {"force": True}}},

    # 23-25：库中可能没有的话题，必须检索后如实说明，不应凭空编造
    {"q": "检索数据库中关于火星城市地下海洋 AI 监管政策的新闻",
     "expect": {"search_news_semantic"},
     "answer_contains_any": ["没有找到", "未找到", "没有检索到", "未检索到", "暂无相关", "没有相关结果"]},
    {"q": "新闻库里有没有关于 2099 年月球宠物经济监管的报道？",
     "expect": {"search_news_semantic"},
     "answer_contains_any": ["没有找到", "未找到", "没有检索到", "未检索到", "暂无相关", "没有相关结果"]},
    {"q": "只根据新闻库回答：最近有哪些关于海底城市 AI 选举系统的新闻？如果没有请直说",
     "expect": {"search_news_semantic"},
     "answer_contains_any": ["没有找到", "未找到", "没有检索到", "未检索到", "暂无相关", "没有相关结果"]},
]