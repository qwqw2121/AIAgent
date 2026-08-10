#抓取的json导入结构化数据库

import json

from database import (
    init_db,
    insert_news
)


JSON_PATH = (
    "storage/raw/news.json"
)



def run():

    init_db()


    with open(
        JSON_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        news_list=json.load(f)



    count=0


    for news in news_list:


        try:

            insert_news(
                news
            )

            count+=1


        except Exception as e:

            print(
                "error:",
                e
            )


    print(
        f"insert {count} news"
    )



if __name__=="__main__":

    run()