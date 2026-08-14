# AI 资讯 Agent

## 项目目标
基于 Python + LangChain + LangGraph 构建可扩展的 AI 资讯 Agent，后续集成：
- RAG（向量检索）
- MCP 协议工具调用
- 定时任务调度

## 目录结构
```text
ai-news-agent/
├─ sources/       # 数据源抓取（RSS/API）
├─ ingestion/     # 数据清洗、去重、分块
├─ storage/       # 向量库与结构化数据库
├─ agent/         # LangGraph 状态图与节点
├─ mcp_servers/   # 自定义 MCP Server
├─ output/        # 摘要生成与推送
├─ config/        # 配置文件
│  └─ manual_news.csv   # 手动准备的测试新闻数据（12条）
└─ tests/         # 测试代码
```

## 环境准备
```bash
conda activate ai-news-agent
pip install -r requirements.txt
```

## 最小 RAG 跑通步骤
1) 构建知识库（导入新闻到 SQLite + 切块 + 向量化存储）
```bash
python ingestion/build_rag_index.py
```

2) 提问并查看检索+回答
```bash
python output/ask_rag.py "RAG优化有哪些新方法？"
```

3) 跑 10 个问题的检索评估（Hit@3 + 人工观察）
```bash
python tests/retrieval_eval.py
```

## 数据库 Schema（news）
字段：
- `title` 标题
- `source` 来源
- `published_at` 发布时间
- `summary` 摘要
- `category` 分类
- `original_url` 原文链接

完整 SQL 见 [news_schema.sql](storage/news_schema.sql)。

## 增量事件聚类。
新新闻
 ↓
LLM分析
 ↓
Embedding
 ↓
与已有事件比较
 ↓
相似度高
    ↓
加入已有事件

相似度低
    ↓
创建新事件
