#采集器，采集信息源中的新闻
#输出json 剪→ 输出到数据库
import feedparserd
import yaml 
import json
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).parent.parent


def load_sources():

    path = BASE_DIR / "sources/rss_sources.yaml"

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def crawl(source):

    feed = feedparserd.parse(
        source["url"]
    )

    results=[]


    for item in feed.entries:

        news={

            "title":
                item.get("title",""),

            "summary":
                item.get("summary",""),

            "url":
                item.get("link",""),

            "source":
                source["name"],

            "language":
                source["language"],

            "category":
                source["category"],

            "published":
                item.get("published",""),

            "crawl_time":
                datetime.now().isoformat()

        }


        results.append(news)


    return results



def run():

    config=load_sources()

    all_news=[]


    for source in config["sources"]:

        print(
            "crawl:",
            source["name"]
        )

        news=crawl(source)

        all_news.extend(news)



    save_path = (
        BASE_DIR /
        "storage/raw/news.json"
    )

    save_path.parent.mkdir(
        exist_ok=True
    )


    with open(
        save_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            all_news,
            f,
            ensure_ascii=False,
            indent=2
        )


    print(
        f"saved {len(all_news)} news"
    )



if __name__=="__main__":
    run()