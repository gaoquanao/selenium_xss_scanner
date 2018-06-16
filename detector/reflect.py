#-*- coding:utf-8 -*-
# selenium不支持POST，先解决GET和反射型
import json
import time
import sqlite3
import urlparse
import argparse
from urllib import urlencode
from selenium import webdriver
from browsermobproxy import Server

import sys
reload(sys)
sys.setdefaultencoding("utf-8")

class Detector(object):
    DBNAME = "./database/url.db"
    PROXY_PATH = "./proxy/browsermob-proxy/bin/browsermob-proxy"
    DRIVER_PATH = "./driver/chromedriver"
    def __init__(self, url_id):
        self.url_id = url_id
        print "[debug] in relect.py url_id %s; type=%s" % (self.url_id, type(self.url_id))
        self.url = ""
        self.headers = {}
        self.method = ""
        self.payloads = []
        self.vul = 0
        self.startedTime = "1970-01-01"
        # self.reflect = 1
        # self.dom = 2
        # self.store = 3 

    def init_proxy(self, port):
        """
        初始化BMP代理, 不加载ico|bin|gif|png|webp|jpg|mp4
        """        
        self.server = Server(path=self.PROXY_PATH, options={"port": port})
        self.server.start()
        self.proxy = self.server.create_proxy()
        self.proxy.blacklist([r"https?://.+\.(ico|bin|gif|png|webp|jpg|mp4)"], 404)
        self.proxy.headers(self.headers)
        print "[-] starting proxy ok!"

    def init_chrome(self, width, height):
        """
        初始化chrome
        """
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument(
            '--proxy-server={host}:{port}'.format(host="localhost", port=self.proxy.port))
        # chrome_options.add_argument('--headless') # 是否以headless模式运行
        chrome_options.add_argument("--disable-xss-auditor")  # 禁用xss auditor
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument(
            "--ignore-certificate-errors")  # 忽略https证书错误
        # chrome_options.add_argument("--disable-gpu") # 禁用gpu
        prefs = {"profile.managed_default_content_settings.images": 2}  # 不加载图片
        chrome_options.add_experimental_option("prefs", prefs)
        self.driver = webdriver.Chrome(
            executable_path=self.DRIVER_PATH, chrome_options=chrome_options)
        self.driver.set_window_size(width, height)

        print "[-] starting chrome ok!"        

    def close(self):
        """
        清理函数
        """
        self.driver.close()
        self.driver.quit()
        try:
            self.proxy.close()
            self.server.process.terminate()
            self.server.process.kill()
        except Exception as e:
            print (e)

    def queryOne(self):
        conn = sqlite3.connect(self.DBNAME)
        cur = conn.cursor()
        # 这里关键的就是那个url_id后面的, 不然的话两位数的id，数据库会报错
        # sqlite3.ProgrammingError: Incorrect number of bindings supplied. The current statement uses 1, and there are 2 supplied.
        result = cur.execute("SELECT url, headers, method, startedTime FROM data WHERE id=(?)", (self.url_id,))
        row =  result.fetchone()
        self.url = row[0]
        self.headers = json.loads(row[1])
        self.method = row[2]
        self.startedTime = row[3]
        conn.commit()

    def add_vul_tag(self):
        # 1 代表reflect 2 代表DOM 3 代表store
        conn = sqlite3.connect(self.DBNAME)
        cur = conn.cursor()
        cur.execute("UPDATE data SET vulnerable=(?) WHERE id=(?)", (self.vul, self.url_id))
        conn.commit()

    def vul_init(self):
        """
        初始化vul表
        """
        conn = sqlite3.connect(self.DBNAME)
        cur = conn.cursor()
        cur.executescript(
            '''
            create table if not exists vul(
                vid INTEGER PRIMARY KEY AUTOINCREMENT,
                url text,
                startedTime text,
                injectPoint text,
                payload text
            );
            '''
        )
        conn.commit()

    def vul_insert(self, injectPoint, payload):
        """
        插入inject_point, payload
        """
        conn = sqlite3.connect(self.DBNAME)
        cur = conn.cursor()
        cur.execute("insert into vul(url, startedTime, injectPoint, payload) values (?,?,?,?);", \
            (self.url, self.startedTime, injectPoint, payload))
        conn.commit()

    def printout(self):
        print "url:", self.url
        print "headers:", self.headers
        print "method:", self.method

    def getpayload(self):
        self.payloads.append("<img src=1 onerror=alert('reflect_xss_found');>")
        self.payloads.append("><body onload=al%65%72t('reflect_xss_found')>")
        self.payloads.append("<ScRiPt>alert('reflect_xss_found');</ScRiPt>")
        self.payloads.append('"><iframe src=javascript:alert("reflect_xss_found")></iframe>')
        self.payloads.append('<////--><iframe src=javascript:alert("reflect_xss_found")></iframe>')
        self.payloads.append("';alert('reflect_xss_found');//")

    def get_query_key(self):
        try:
            return urlparse.parse_qs(urlparse.urlparse(self.url).query, True).keys()
        except KeyError:
            print "[*] non query key found!"
            return []

    def set_query_field(self, field, value, replace=False):
        params = urlparse.urlparse(self.url)
        query_pairs = urlparse.parse_qsl(params.query)

        if replace:
            # 去掉想要修改的field后续再添加进去
            query_pairs = [(f,v) for (f,v) in query_pairs if f != field]
        
        query_pairs.append((field, value))
        new_params = (
            params.scheme,
            params.netloc,
            params.path,
            params.params,
            urlencode(query_pairs),
            params.fragment
        )
        return urlparse.urlunparse(new_params)

    def detect(self):
        """
        分析url结构获取参数，遍历payloads，一旦发现就不再继续
        """
        self.init_proxy(8888)
        self.init_chrome(1280, 720)
        print "[*] checking %s" % (self.url)
        if self.method == "GET":
            for payload in self.payloads:
                for key in self.get_query_key():
                    new_url = self.set_query_field(key, payload, True)
                    try:
                        self.driver.get(new_url)
                        self.driver.implicitly_wait(6)
                    except:
                        alert = self.driver.switch_to_alert()
                        if alert.text == "reflect_xss_found":
                            print "[*] reflect xss found!"
                            print "[*] inject point:%s; payload is %s" % (key, payload)
                            self.vul = "1"
                            self.add_vul_tag()
                            self.vul_insert(key, payload)
                            self.close()
                            return
        else:
            print "[*] method POST not supported yet!"
        # time.sleep(10)
        print "[*] no xss found"
        self.close()

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-id', dest="url_id", default="1", help=u"the url_id that you want deal with")
    # 获得所有命令行传入的参数
    args = parser.parse_args()

    return args

def main(url_id):
    detetor = Detector(url_id)
    detetor.vul_init()
    detetor.queryOne()
    detetor.getpayload()
    detetor.detect()

if __name__ == "__main__":
    args = get_args()
    main(args.url_id)