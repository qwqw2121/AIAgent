ai-news-agent/
│
├── .vscode/
│
├── agent/                      # 后续 LangGraph / Agent
│
├── config/                     # 配置
│
├── embedding/                  # Embedding、向量库、事件聚类
│   ├── embed_news.py
│   ├── vector_store.py
│   ├── similarity.py
│   └── clustering.py
│
├── ingestion/                  # 新闻采集、清洗、LLM分析
│   ├── rss/
│   ├── extraction/
│   └── ...
│
├── mcp_servers/                # 后续 MCP Server
│
├── output/                     # 输出文件
│   ├── daily/
│   └── monthly/
│
├── rag/                        # RAG 检索相关
│
├── sources/                    # RSS 来源配置
│
├── storage/                    # 数据
│   ├── news.db
│   └── chroma/
│
├── tests/
│
├── backend/                   # ⭐ 新增：FastAPI
│   ├── __init__.py
│   ├── main.py                # FastAPI 启动入口
│   │
│   ├── api/                   # API 路由
│   │   ├── __init__.py
│   │   ├── news.py            # 新闻接口
│   │   ├── events.py          # 事件接口
│   │   ├── reports.py         # 日报/月报接口
│   │   └── rag.py             # 后续 RAG 接口
│   │
│   ├── services/              # 业务逻辑
│   │   ├── __init__.py
│   │   ├── news_service.py
│   │   ├── event_service.py
│   │   └── report_service.py
│   │
│   └── schemas/               # API 数据结构
│       ├── __init__.py
│       ├── news.py
│       ├── event.py
│       └── report.py
│
├── frontend/                  # ⭐ 新增：Next.js
│   ├── app/
│   │   ├── page.tsx           # 首页
│   │   │
│   │   ├── news/
│   │   │   ├── page.tsx       # 新闻列表
│   │   │   └── [id]/
│   │   │       └── page.tsx   # 新闻详情
│   │   │
│   │   ├── events/
│   │   │   ├── page.tsx       # 事件列表
│   │   │   └── [id]/
│   │   │       └── page.tsx   # 事件详情
│   │   │
│   │   ├── reports/
│   │   │   ├── daily/
│   │   │   │   └── page.tsx   # 每日报告
│   │   │   └── monthly/
│   │   │       └── page.tsx   # 月度报告
│   │   │
│   │   ├── layout.tsx
│   │   └── globals.css
│   │
│   ├── components/            # 公共 UI
│   │   ├── Header.tsx
│   │   ├── NewsCard.tsx
│   │   ├── NewsList.tsx
│   │   ├── EventCard.tsx
│   │   └── ReportCard.tsx
│   │
│   ├── lib/
│   │   └── api.ts             # 调用 FastAPI
│   │
│   ├── public/
│   │
│   ├── package.json
│   └── ...
│
├── .env
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt

daily_news_flow
│
├── crawl_task
│
├── extract_task
│
├── analyze_task
│
├── embedding_task
│
├── dedup_task
│
├── clustering_task
│
└── report_task