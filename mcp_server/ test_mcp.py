import asyncio
import sys
from fastmcp import Client                      # ← 改这里
from fastmcp.client.transports import StdioTransport  # ← 可选，用字符串也行

async def test_mcp():
    # FastMCP 2.0 的 Client 可以直接传 server 脚本路径
    async with Client("mcp_server/news_mcp.py") as client:
        # 1. 列出所有可用的工具
        tools = await client.list_tools()
        print("✅ 发现的 Tools:", [t.name for t in tools])

        # 2. 测试调用 search_news
        print("\n--- 测试 search_news ---")
        result = await client.call_tool(
            "search_news",
            arguments={"keyword": "LLM", "limit": 3}
        )
        print("返回内容:", result.content[0].text if result.content else "无")

        # 3. 测试调用 get_pending_stats
        print("\n--- 测试 get_pending_stats ---")
        result = await client.call_tool("get_pending_stats", arguments={})
        print("待处理统计:", result.content[0].text if result.content else "无")

if __name__ == "__main__":
    asyncio.run(test_mcp())