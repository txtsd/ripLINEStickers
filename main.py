import ast
import os
import re
import sys
from enum import IntEnum, unique
from queue import Queue
from threading import Thread

import requests
from bs4 import BeautifulSoup as bs


# Author link example:
# https://store.line.me/stickershop/author/97829/en

# Pack link example:
# https://store.line.me/stickershop/product/1000509/en

# Sticker link example:
# https://stickershop.line-scdn.net/stickershop/v1/sticker/67058943/iPhone/sticker@2x.png
# https://stickershop.line-scdn.net/stickershop/v1/sticker/73694/android/sticker.png


@unique
class Enums(IntEnum):
    AUTHOR = 1
    PACK = 2
    ERROR = 3


DIR_STICKERS: str = "stickers"

Q1: Queue = Queue(maxsize=0)
Q2: Queue = Queue(maxsize=0)
Q3: Queue = Queue(maxsize=0)

NUM_THREADS: int = 8

DOMAIN: str = "https://store.line.me"

sticker_count: int = 0
set_count: int = 0


def rip_line_stickers(argument: str):
    session = requests.Session()

    template_static = "https://stickershop.line-scdn.net/stickershop/v1/sticker/{}/{}/{}.{}"
    pattern_link_sticker = re.compile(
        r"https://stickershop.line-scdn.net/stickershop/v1/sticker/(?P<id>\d+)/(?P<platform>.+)/(?P<filename_with_ext>(?P<filename>.+)\.(?P<ext>.+))")
    pattern_a_next = re.compile(r"\?page=\d+")

    def determine_type(link: str):
        if "/author/" in link:
            return Enums.AUTHOR
        elif "/product/" in link:
            return Enums.PACK
        else:
            return Enums.ERROR

    def get_pack(link: str):
        result = session.get(link)
        result.raise_for_status()

        soup = bs(result.content, "lxml")
        tag_p = soup.find_all("p")
        name_pack = None
        for p in tag_p:
            if p.has_attr("data-test") and p["data-test"] == "sticker-name-title":
                name_pack = p.string

        tag_li = soup.find_all("li")
        for li in tag_li:
            if li.has_attr("data-preview"):
                data_preview = ast.literal_eval(li["data-preview"])

                if data_preview["type"] == "static":
                    url = data_preview["staticUrl"]
                    if "/sticonshop/" not in url:
                        match = pattern_link_sticker.search(url)
                        try:
                            if match.group("platform") == "android":
                                url = template_static.format(match.group("id"), "iPhone",
                                                             match.group("filename") + "@2x",
                                                             match.group("ext"))
                        except Exception as e:
                            print("Exception while processing {}".format(name_pack))
                            print(e)
                            print(tag_li)
                elif data_preview["type"] == "animation":
                    url = data_preview["animationUrl"]
                    match = pattern_link_sticker.search(url)
                else:
                    print("Encountered unknown type: {}".format(data_preview["type"]))
                    exit(2)

                if "/sticonshop/" not in url:
                    Q1.put(
                        {
                            "name_pack": name_pack,
                            "filename": match.group("id"),
                            "ext": match.group("ext"),
                            "link": url
                        }
                    )

    def get_author(link: str):
        result = session.get(link)
        result.raise_for_status()

        soup = bs(result.content, "lxml")
        tag_li = soup.find_all("li")
        for li in tag_li:
            if li.has_attr("data-test"):
                data_test = li["data-test"]
                if data_test == "author-item":
                    Q2.put(
                        {
                            "link": "{}{}".format(DOMAIN, li.a.get("href"))
                        }
                    )
        tag_a = soup.find_all("a")
        for a in tag_a:
            if a.has_attr("href") and a.text == "Next":
                if pattern_a_next.search(a.get("href")):
                    link = link.split("?")[0]
                    link = "{}{}".format(link, a.get("href"))
                    get_author(link)

    def threaded_scrape(q: Queue):
        while True:
            things = q.get()
            name_pack = things['name_pack']
            filename = things['filename']
            ext = things['ext']
            link = things['link']
            path = "{}/{}/{}.{}".format(DIR_STICKERS, name_pack, filename, ext)

            if not os.path.exists("{}/{}".format(DIR_STICKERS, name_pack)):
                os.makedirs("{}/{}".format(DIR_STICKERS, name_pack), exist_ok=True)

            with open(path, "wb") as f:
                result = session.get(link)
                result.raise_for_status()
                f.write(result.content)
                global sticker_count
                sticker_count += 1

            q.task_done()

    def threaded_crawl(q: Queue):
        while True:
            things = q.get()
            link = things["link"]
            get_pack(link)
            global set_count
            set_count += 1

            q.task_done()

    link_type = determine_type(argument)

    if link_type == Enums.AUTHOR:
        get_author(argument)
    elif link_type == Enums.PACK:
        get_pack(argument)
    else:
        print("Could not determine link type!")
        exit(1)

    for i in range(NUM_THREADS):
        worker = Thread(target=threaded_crawl, args=(Q2,))
        worker.daemon = True
        worker.start()

    for i in range(NUM_THREADS):
        worker = Thread(target=threaded_scrape, args=(Q1,))
        worker.daemon = True
        worker.start()

    Q2.join()
    print("Queued", set_count, "sets!")
    Q1.join()
    print("Downloaded", sticker_count, "files!")


if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print("Pass a link as an argument.")
    else:
        rip_line_stickers(sys.argv[1])
