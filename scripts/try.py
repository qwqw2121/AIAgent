import requests, feedparser
r = requests.get("https://feed.infoq.com/ai-ml-data-engineering/cn", headers={"User-Agent": "Mozilla/5.0"})
f = feedparser.parse(r.content)
e = f.entries[0]
print(e.get("published"))         # 原始字符串，看后缀是 GMT / +0000 / +0800 / 无
print(e.get("published_parsed"))  # feedparser 解析后的 UTC
print(e.get("title"))