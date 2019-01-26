import os
import re
import time
import json
import hashlib
import logging
import requests
import socket
from pathlib import Path
import urllib3
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from fake_useragent import UserAgent
from w3lib.url import canonicalize_url
from scrapy.utils.python import to_bytes
from requests.exceptions import ReadTimeout
from requests.adapters import HTTPAdapter
from tools.utis import typeassert, timer

timeout = 2
max_retries = 3


# @typeassert(response=requests.models.Response)
def extract_html_by_re(response):
    """从爬取的html提取url链接，图片，音频（正则解析）"""
    # re.I 无视大小写
    url_list = []
    # 直接匹配所有资源链接
    resources_pattern = re.compile('(href|src)=\s*?[\'\"](.+?)[\'\"][^><]*?>', re.I)
    '''
    <a href=/tvanime/news/page/1/>1</a>
    <a href=/tvanime/news/page/2/>2</a>
    匹配这种坑爹的a标签
    '''
    a_pattern = re.compile('<a[^><]*?href=[\'\"]?(.+?)[\'\"]?[^><]*?>', re.I)
    '''
    <script>var charas = ['../img/ch/ch_aka_img_01.png','../img/ch/ch_aka_img_02.png','../img/ch/ch_aka_img_03.png'];</script>
    '''
    img_pattern = re.compile('[^=][\'\"]([^\"\']*?\.(jpg|jpeg|png|gif|svg|ico))[\'\"]', re.I)
    url_list.extend([x[-1].strip() for x in re.findall(resources_pattern, response.text)])
    url_list.extend([x.strip() for x in re.findall(a_pattern, response.text)])
    url_list.extend([x[0].strip() for x in re.findall(img_pattern, response.text)])
    # return [urljoin(response.url, x) for x in url_list]
    for u in url_list:
        yield urljoin(response.url, u)


# @typeassert(response=requests.models.Response)
def extract_css_js_by_re(response, home_page):
    """从爬取的css,js提取图片（正则解析）"""
    url_list = []
    if response.url.endswith('.js'):
        img_pattern = re.compile('[\'\"]([^\"\']*?\.(jpg|jpeg|png|gif|svg|ico))[\'\"]')
        url_list.extend([x[0].strip() for x in re.findall(img_pattern, response.text)])
        url_list = [urljoin(home_page, u)for u in url_list]
    elif response.url.endswith('.css'):
        img_pattern = re.compile('url\(([^\"\'\s]*?\.(jpg|jpeg|png|gif|svg|ico))\)')
        url_list.extend([x[0].strip() for x in re.findall(img_pattern, response.text)])
        url_list = [urljoin(response.url, u)for u in url_list]
    for u in url_list:
        yield u


# @typeassert(response=requests.models.Response)
def extract_url_by_bs4(response):
    """从爬取的html提取url链接（bs4解析）"""
    soup = BeautifulSoup(response.text, "html5lib")
    tag_a = soup.find_all('a')
    tag_link = soup.find_all('link')
    tag_script = soup.find_all('script')
    tag_img = soup.find_all('img')
    tag_frame = soup.find_all('frame')
    tag_iframe = soup.find_all('iframe')

    def traverse_tag_list(tag_list, tag_attribute):
        tags = []
        for x in tag_list:
            try:
                tags.append(x[tag_attribute])
            except KeyError:
                pass
        return tags

    url_list = traverse_tag_list(tag_a, 'href')
    url_list.extend(traverse_tag_list(tag_link, 'href'))
    url_list.extend(traverse_tag_list(tag_script, 'src'))
    url_list.extend(traverse_tag_list(tag_img, 'src'))
    url_list.extend(traverse_tag_list(tag_frame, 'src'))
    url_list.extend(traverse_tag_list(tag_iframe, 'src'))
    for u in url_list:
        yield urljoin(response.url, u)


def save_html(response):
    """获取响应并存为html"""
    def mkdir_path(url):
        dirs_path = url.split("/")[2:-1]
        dir_path = ""
        for k in range(len(dirs_path)):
            dir_path = os.path.join(os.getcwd(), "/".join(dirs_path[0:k + 1]))
            if not Path(dir_path).exists():
                os.mkdir(dir_path)
        if dir_path == "" and dir_path:
            dir_path = "./"
        return dir_path
    path = mkdir_path(response.url)
    if response.url.endswith(".html"):
        html_file = os.path.join(path, response.url.split("/")[-1])
    else:
        html_file = os.path.join(path, "index.html")
    if not Path(html_file).exists():
        with open(html_file, 'a', encoding='utf-8') as f:
            f.write(response.text)


def send_request(url):
    headers = {
        "User-Agent": UserAgent().google
    }
    s = requests.Session()
    s.mount('http://', HTTPAdapter(max_retries=max_retries))
    s.mount('https://', HTTPAdapter(max_retries=max_retries))
    try:
        response = s.get(url, headers=headers, timeout=timeout)
        logging.debug('请求成功：' + url)
        # 如果请求成功
        if response.status_code == 200 and 'text' in response.headers['Content-Type']:
            # 使用apparent_encoding可以获得真实编码
            # 设置正确编码
            response.encoding = response.apparent_encoding
        return response
    except ReadTimeout:
        logging.warning("超时url:"+url)
        with open("./fail_urls.json", "w+") as f:
            fail_urls = {'url': url}
            json.dump(fail_urls, f)
    except requests.exceptions.RequestException as e:
        logging.warning(e)
        logging.warning("出错url:" + url)
        raise ReadTimeout


class DupeFilter:
    """响应指纹过滤器"""
    def __init__(self):
        self.fingerprints = set()

    def request_seen(self, request):
        fp = self.request_fingerprint(request)
        if fp in self.fingerprints:
            return True
        self.fingerprints.add(fp)

    def request_del(self, request):
        fp = self.request_fingerprint(request)
        self.fingerprints.remove(fp)

    @staticmethod
    def request_fingerprint(request):
        fp = hashlib.sha1()
        fp.update(to_bytes(canonicalize_url(request)))
        return fp.hexdigest()


# @typeassert(urls=list)
def requests_download(url, dir_path="./", proxy=False):
    socket.setdefaulttimeout(20)
    # 取消报错
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    """使用requests下载"""
    fail_urls = set()

    proxies = {
        "http": "http://127.0.0.1:1088",
        "https": "https://127.0.0.1:1088",
    }

    headers = {
        "User-Agent": UserAgent().google
    }

    def mkdir_path(url):
        dirs_path = url.split("/")[2:-1]
        dir_path = ""
        for k in range(len(dirs_path)):
            dir_path = os.path.join(os.getcwd(), "/".join(dirs_path[0:k + 1]))
            if not Path(dir_path).exists():
                os.mkdir(dir_path)
        if dir_path == "" and dir_path:
            dir_path = "./"
        return dir_path

    # 下载一个大文件
    def DownOneFile(srcUrl, localFile):
        print('%s\n --->>>\n  %s' % (srcUrl, localFile))

        startTime = time.time()
        with requests.get(srcUrl, stream=True) as r:
            contentLength = int(r.headers['content-length'])
            line = 'content-length: %dB/ %.2fKB/ %.2fMB'
            line = line % (contentLength, contentLength / 1024, contentLength / 1024 / 1024)
            print(line)
            downSize = 0
            with open(localFile, 'wb') as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
                    downSize += len(chunk)
                    line = '%d KB/s - %.2f MB, 共 %.2f MB'
                    line = line % (
                        downSize / 1024 / (time.time() - startTime), downSize / 1024 / 1024,
                        contentLength / 1024 / 1024)
                    print(line, end='\r')
                    if downSize >= contentLength:
                        break
            timeCost = time.time() - startTime
            line = '共耗时: %.2f s, 平均速度: %.2f KB/s'
            line = line % (timeCost, downSize / 1024 / timeCost)
            print(line)

    def down_load_pic(download_url, file_dir_path):
        """以两种方式存放文件，2.按路径建立文件夹存放"""
        if download_url.find('?') >= 0:
            download_url = re.sub('\?.+', '', download_url)
        try:
            if proxy:
                content = requests.get(download_url, headers=headers, proxies=proxies, verify=False,
                                       timeout=timeout, ).content
            else:
                content = requests.get(download_url, headers=headers, verify=False, timeout=timeout).content
            if not Path(os.path.join(file_dir_path, download_url.split("/")[-1])).exists():
                # 按url链接设置目录
                file_dir_path = mkdir_path(download_url)
                # 防止出现 header_logo.png?190125

                with open(os.path.join(file_dir_path, download_url.split("/")[-1]), 'wb') as f:
                    f.write(content)

        except Exception:
            logging.warning("fail one:"+download_url)
            fail_urls.add(download_url)

    down_load_pic(url, dir_path)
    while len(fail_urls) > 0:
        url = fail_urls.pop()
        file_size = int(requests.get(url).headers['content-length']) / 1024
        if file_size > 100:
            logging.info('图片超过200k:'+url)
            # 按url链接设置目录
            file_dir_path = mkdir_path(url)
            DownOneFile(url, file_dir_path)
        else:
            logging.info('重新下载:'+url)
            down_load_pic(url, dir_path)
    time.sleep(1)


# @typeassert(response=requests.models.Response)
def save_response_to_file(response):
    """其实是上一个的重载，把响应的内容直接存成文件"""
    def mkdir_path(url):
        dirs_path = url.split("/")[3:-1]
        dir_path = ""
        for k in range(len(dirs_path)):
            dir_path = os.path.join(os.getcwd(), "/".join(dirs_path[0:k + 1]))
            if not Path(dir_path).exists():
                os.mkdir(dir_path)
        if dir_path == "" and dir_path:
            dir_path = "./"
        return dir_path

    def down_load_file(response, file_dir_path, duplicate):
        content = response.content
        # 防止出现带版本号 .css?ver=23423234
        if response.url.find("?"):
            download_url = re.sub('\?.+', '', response.url)
        else:
            download_url = response.url
        if duplicate and not Path(os.path.join(file_dir_path, download_url.split("/")[-1])).exists():
            ''' True 按url链接设置目录 '''
            file_dir_path = mkdir_path(download_url)
            with open(os.path.join(file_dir_path, download_url.split("/")[-1]), 'wb') as f:
                f.write(content)
        elif not duplicate:
            ''' False 下载文件加上时间戳 '''
            with open(os.path.join(file_dir_path, str(time.time()) + download_url.split("/")[-1]), 'wb') as f:
                f.write(content)
    path = mkdir_path(response.url)
    down_load_file(response, path, True)


@typeassert(url_list=list)
def url_judge(url_list):
    # 又设计缺陷未使用到
    """将解析好的链接列表分类,并返回字典"""
    # 分为 1.html 2.css，js文件 3.图片，音频视频二进制文件
    judge_html_pattern = re.compile('https?://(\w*:\w*@)?[-\w.]+(:\d)?(/([\w/_.]*(\?\S+)?)?)?')
    judge_css_js_pattern = re.compile('https?://.*?\.(css|js)')
    judge_binary_file_pattern = re.compile('https?://.*?\.(jpg|jpeg|png|gif|svg|ico)')
    sorted_urls = {
        "html": [u.strip() for u in url_list if judge_html_pattern.match(u)],
        "css_js": [u.strip() for u in url_list if judge_css_js_pattern.match(u)],
        "binary_file": [u.strip() for u in url_list if judge_binary_file_pattern.match(u)]
    }
    return sorted_urls


# 下载一个大文件
def down_file(srcUrl, localFile):
    print('%s\n --->>>\n  %s' % (srcUrl, localFile))

    startTime = time.time()
    with requests.get(srcUrl, stream=True) as r:
        contentLength = int(r.headers['content-length'])
        line = 'content-length: %dB/ %.2fKB/ %.2fMB'
        line = line % (contentLength, contentLength / 1024, contentLength / 1024 / 1024)
        print(line)
        downSize = 0
        with open(localFile, 'wb') as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
                downSize += len(chunk)
                line = '%d KB/s - %.2f MB, 共 %.2f MB'
                line = line % (
                downSize / 1024 / (time.time() - startTime), downSize / 1024 / 1024, contentLength / 1024 / 1024)
                print(line, end='\r')
                if downSize >= contentLength:
                    break
        timeCost = time.time() - startTime
        line = '共耗时: %.2f s, 平均速度: %.2f KB/s'
        line = line % (timeCost, downSize / 1024 / timeCost)
        print(line)


@typeassert(urls=list)
def requests_download_old(urls, dir_path="./", duplicate=False, proxy=False):
    """使用requests下载"""
    fail_urls = set()

    proxies = {
        "http": "http://127.0.0.1:1088",
        "https": "https://127.0.0.1:1088",
    }

    headers = {
        "User-Agent": UserAgent().google
    }

    def mkdir_path(url):
        dirs_path = url.split("/")[3:-1]
        dir_path = ""
        for k in range(len(dirs_path)):
            dir_path = os.path.join(os.getcwd(), "/".join(dirs_path[0:k + 1]))
            if not Path(dir_path).exists():
                os.mkdir(dir_path)
        if dir_path == "" and dir_path:
            dir_path = "./"
        return dir_path

    def down_load_pic(download_url, file_dir_path, duplicate):
        """以两种方式存放文件，1.给文件名加时间戳 2.按路径建立文件夹存放"""
        try:
            if proxy:
                content = requests.get(download_url, headers=headers, proxies=proxies, verify=False,
                                       timeout=timeout, ).content
            else:
                content = requests.get(download_url, headers=headers, verify=False, timeout=timeout).content
            if duplicate and not Path(os.path.join(file_dir_path, download_url.split("/")[-1])).exists():
                # 按url链接设置目录
                file_dir_path = mkdir_path(download_url)
                with open(os.path.join(file_dir_path, download_url.split("/")[-1]), 'wb') as f:
                    f.write(content)
            elif not duplicate:
                # 下载文件加上时间戳
                with open(os.path.join(file_dir_path, str(time.time()) + download_url.split("/")[-1]), 'wb') as f:
                    f.write(content)
        except Exception:
            logging.warning("fail one:"+download_url)
            fail_urls.add(download_url)
    for url in urls:
        down_load_pic(url, dir_path, duplicate)
        while len(fail_urls) > 0:
            url = fail_urls.pop()
            logging.info('重新下载:'+url)
            down_load_pic(url, dir_path, duplicate)
