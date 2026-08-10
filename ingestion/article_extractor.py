#URL变正文，提取 RSS正文内容
#url → 网页正文 → 更新content字段

import sqlite3
import trafilatura

from pathlib import Path


DB_PATH = Path(
    "storage/AInews.db"
)



def extract_content(url):

    try:

        html = trafilatura.fetch_url(
            url
        )

        if not html:
            return None


        text = trafilatura.extract(
            html,
            include_comments=False
        )


        return text


    except Exception as e:

        print(
            "extract error:",
            url,
            e
        )

        return None




def update_content(
    news_id,
    content
):

    conn=sqlite3.connect(
        DB_PATH
    )

    cursor=conn.cursor()


    cursor.execute(
    """
    UPDATE news
    SET content=?
    WHERE id=?
    """,
    (
        content,
        news_id
    ))


    conn.commit()

    conn.close()



def run():

    conn=sqlite3.connect(
        DB_PATH
    )

    cursor=conn.cursor()


    cursor.execute(
    """
    SELECT id,url
    FROM news
    WHERE content IS NULL
    """
    )


    rows=cursor.fetchall()


    conn.close()



    for news_id,url in rows:


        print(
            "extract:",
            url
        )


        content=extract_content(url)


        if content:

            update_content(
                news_id,
                content
            )



if __name__=="__main__":

    run()