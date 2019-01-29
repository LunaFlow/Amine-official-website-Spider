import json
import re
import logging
from pathlib import Path
import os
import requests
from multiprocessing import Pool
from tools.spider_utils import DupeFilter, send_request, requests_download, save_response_to_file, extract_html_by_re, \
    save_html, extract_css_js_by_re, aria2_download

# 创建指纹过滤器

dupe_filter = DupeFilter()
# home_page = "http://www.ne.jp/asahi/okazaki/book/"
# home_page = "http://nonnontv.com/tvanime/"
# home_page = "https://project-navel.com/tsukiniyorisou/"
# home_page = "http://august-soft.com/hatou/"
# home_page = "http://nonnontv.com/movie/"
# home_page = "https://hanayamata.com/"
# home_page = "http://nekopara.com/"
# home_page = "http://hakumiko.com"
# home_page = "http://www.kotonohanoniwa.jp"
# home_page = "https://www.wagnaria.com/"
# home_page = "https://www.katanagatari.com/"
# home_page = "http://hasekuraisuna.jp/"
# home_page = "http://spicy-wolf.com/"
home_page = "http://www.kogado.com/sw/contents/kuroneko/sr2017/zh/"
# home_page = "http://www.kogado.com/sw/contents/kuroneko/sr2017/ja/"
# home_page = "http://www.kogado.com/sw/contents/kuroneko/sr/"
retry_html_list = []
waiting_list = set()


def start_spider(url):
    """将解析好的链接列表分类"""
    judge_binary_file_pattern = re.compile('https?://.*?\.(ico|au|mp3|ogg|ape)$')

    if not dupe_filter.request_seen(url):
        if limit_domain(url) and not re.match('.*?\.(jpg|jpeg|png|gif|svg|ico|au|mp3)$', url):
            try:
                response = send_request(url)
            except Exception:
                response = False
                if re.match('https?://.*?\.(js|css)$', url):
                    retry_html_list.append(url)

                elif limit_domain(url) and not url.endswith('.exe'):
                    # 排除掉 .exe 结尾的文件
                    retry_html_list.append(url)

        else:
            response = False
            # 如果有响应，并且限制url在抓取的url下
        if response and limit_domain(url):
            file_type = response.headers['Content-Type']
            if 'image' in file_type:
                logging.info('下载图片：'+url)
                # requests_download([url], duplicate=True)
                waiting_list.add(url)
            elif 'audio' in file_type or judge_binary_file_pattern.match(url):
                logging.info('下载音视频等二进制文件：'+url)
                waiting_list.add(url)
                # requests_download([url], duplicate=True)
            elif re.match('https?://.*?\.(css|js)', url) or file_type == 'text/css' or file_type == 'text/javascript':
                save_response_to_file(response)
                for u in extract_css_js_by_re(response, home_page):
                    start_spider(u)
            elif re.match('text/html', file_type) and limit_domain(url):
                save_html(response)
                for u in extract_html_by_re(response):
                    start_spider(u)
        elif limit_domain(url) and re.match('.*?\.(jpg|png|gif|mp3|au|ico)$', url):
            # 如果请求超时但请求链接为资源链接则添加到等待列表中
            waiting_list.add(url)
            logging.info("add:" + str(len(waiting_list)) + 'url:' + url)


def limit_domain(url):
    """判断url是超出homepage"""
    # domain_pattern = re.compile('')
    return "http://www.kogado.com/sw/contents/kuroneko/sr2017" in url


# @timer
def main():
    start_spider(home_page)


def thread_pool():
    try:
        pool = Pool()
        pool.map(requests_download, [x for x in waiting_list])
    except Exception:
        if len(waiting_list) > 0:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({'urls': list(waiting_list)}, f)


def retry():
        with open(json_path, 'r') as load_f:
            load_dict = json.load(load_f)
            waiting_list = set(load_dict['urls'])
            while len(waiting_list) > 0:
                deal_url = waiting_list.pop()
                try:
                    requests_download(deal_url)
                    if len(waiting_list) > 0:
                        with open(json_path, 'w', encoding='utf-8') as f:
                            json.dump({'urls': list(waiting_list)}, f)
                    elif len(waiting_list) == 0:
                        with open(json_path, 'w', encoding='utf-8') as f:
                            json.dump({'urls': []}, f)
                except Exception:
                    logging.warning(deal_url)
                    if len(waiting_list) > 0:
                        with open(json_path, 'w', encoding='utf-8') as f:
                            json.dump({'urls': list(waiting_list)}, f)


if __name__ == '__main__':
    json_path = "info/waiting_list.json"
    if Path(json_path).exists():
        logging.info('开始重试')
        retry()
    else:
        main()
        logging.warning('失败请求了:' + str(len(retry_html_list)))
        if not Path('info').exists():
            os.mkdir('info')
        if len(retry_html_list) > 0:
            with open('info/fail_urls.json', 'w') as f:
                json.dump({'fail_urls': retry_html_list}, f)

        if len(waiting_list) > 0:
            with open('info/waiting_list_all', 'w', encoding='utf-8') as f:
                for i in waiting_list:
                    f.write(i + '\n')
        aria2_download(waiting_list, os.getcwd())
