# -*- coding=utf-8 -*-
import os
import sys
import time
import json
import atexit
import logging
import hashlib
import requests
import urlparse
import dateutil.parser
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.alert import Alert
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import UnexpectedAlertPresentException
from browsermobproxy import Server

import sys
reload(sys)
sys.setdefaultencoding("utf-8")

from lib.log_config import logging_config
log = logging.getLogger('Spider')

from lib.database import DataStore
from lib.arg_parser import get_args

class Spider(object):

    if sys.platform == "darwin":
        PROXY_PATH = "./proxy/browsermob-proxy/bin/browsermob-proxy"
        DRIVER_PATH = "./driver/chromedriver"
    elif sys.platform == "win32":
        PROXY_PATH = "./proxy/browsermob-proxy/bin/browsermob-proxy.bat"
        DRIVER_PATH = "./driver/chromedriver.exe"
    else:
        print "[*] platform not supported!"
        return

    def __init__(self, url, ajax_wait_time, dbfile, depth, headers):
        self.url_set = set()
        self.hash_set = set()
        self.aTagHref = set()
        self.depth = depth # 爬虫的深度
        self.ajax_wait_time = ajax_wait_time
        self.dbfile = dbfile
        self.blacklist = ['css', 'js', 'html']
        self.outerHTML = ""
        self.headers = headers # headers为dict
        self.target_url = url

    def init_proxy(self, port):
        """
        初始化BMP代理, 不加载ico|bin|gif|png|webp|jpg|mp4
        """        
        self.server = Server(path=self.PROXY_PATH, options={"port": port})
        self.server.start()
        self.proxy = self.server.create_proxy()
        self.proxy.blacklist([r"https?://.+\.(ico|bin|gif|png|webp|jpg|mp4)"], 404)
        self.proxy.headers(self.headers)

    def init_chrome(self, width, height):
        """
        初始化chrome
        """
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument(
            '--proxy-server={host}:{port}'.format(host="localhost", port=self.proxy.port))
        chrome_options.add_argument('--headless') # 是否以headless模式运行
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

    def record_resp(self, name="record", options={'captureContent': True}):
        self.proxy.new_har(name, options=options)

    def get_page(self):
        r = requests.get(self.target_url, headers=self.headers)
        if r.status_code == 200:
            log.info("check %s connection... ok")
        else:
            log.info("failed to connect %s" % (self.target_url))            
            return False
        self.driver.get(self.target_url)
        self.netloc = urlparse.urlsplit(self.target_url).netloc
        # 隐式等待6s
        self.driver.implicitly_wait(6)
        self.driver.set_script_timeout(6)

    def get_aTag_outerHTML(self):
        """
        获得页面上所有a标签的outerhtml
        """
        js = """
            var htmlArray = new Array;
            var links = document.getElementsByTagName('a');
            for(var i = 0; i < links.length ; i ++ )
            {
                htmlArray.push(links[i].outerHTML)
            };
            return htmlArray;
        """
        htmlArray = self.driver.execute_script(js)

        print htmlArray

    def click_all_aTag(self):
        """
        点击网页上所有的a标签
        """

        self.interact_with_form()
        self.interact_with_button()

        aTag_num = "var length = document.getElementsByTagName('a').length; return length"
        length = self.driver.execute_script(aTag_num)
        self.root_url = self.driver.current_url
        links = self.driver.find_elements_by_tag_name('a')

        # 拿到root页面上所有a标签的href属性放入集合中
        for link in links:
            self.aTagHref.add(link.get_attribute("href"))
        # log.debug(self.aTagHref)  # 写入log
        for i in range(length):
            page_source = self.driver.page_source
            link = self.driver.find_elements_by_tag_name('a')[i]

            try:
                tag_html = link.get_attribute('outerHTML')
                # 防止点击注销和登出按钮，而导致的登录凭证丢失
                if "logout.php" in tag_html:
                    log.warning("[find logout]: %s" % (tag_html))
                    continue
                else:
                    log.debug("[click %s]" % (tag_html))
            except Exception as e:
                log.error("Error occured when get link outerHTML"+e)

            try:
                # 保持ctrl按下，执行脚本点击a标签
                ActionChains(self.driver).key_down(Keys.COMMAND).click(
                    link).key_up(Keys.COMMAND).perform()

                time.sleep(self.ajax_wait_time)  # 等待ajax加载完成
                
                self.interact_with_form()
                # time.sleep(1) # 观察数据是否正确填充
                self.interact_with_button()
                
                self.driver.implicitly_wait(6)
                self.driver.set_script_timeout(6)
                
                # 如果页面发生了变更，只考虑了两层
                # print "[*]depth:", depth
                if self.driver.page_source != page_source and self.depth != 1:
                    log.warning("[*] page source changed")
                    # log.debug("new_page_source:" + self.driver.page_source)
                    log.warning("changed link" + link.get_attribute("outerHTML"))

                    newlength = self.driver.execute_script(aTag_num)

                    for i in range(newlength):
                        new = self.driver.find_elements_by_tag_name('a')[i]

                        if new.get_attribute("href") not in self.aTagHref:  # 只点击新出现的a标签
                            log.info(new.get_attribute("outerHTML"))  # 写入log
                            self.perform_click(new)
                            self.aTagHref.add(new.get_attribute("href"))

            except UnexpectedAlertPresentException:
                # 弹出alert框的处理
                alert = self.driver.switch_to_alert()
                alert.accept()
            finally:
                # 页面发生本地跳转
                if self.root_url != self.driver.current_url:
                    # 发生本地跳转后重新点击button
                    self.driver.back()
                    self.interact_with_button()

    def perform_click(self, on_element):
        if on_element:
            try:
                ActionChains(self.driver).key_down(Keys.COMMAND).click(
                    on_element).key_up(Keys.COMMAND).perform()
                time.sleep(self.ajax_wait_time)

            except UnexpectedAlertPresentException:
                # 弹出alert框的处理
                alert = self.driver.switch_to_alert()
                alert.accept()
            finally:
                try:
                    log.info("[depth=%s click %s]:" % (self.depth ,on_element.get_attribute('outerHTML')))
                except Exception as e:
                    log.error("Error occured when get link outerHTML"+e)
                # 页面发生本地跳转
                if self.root_url != self.driver.current_url:
                    # 发生本地跳转后重新点击button
                    self.driver.back()
                    self.interact_with_button()

    def interact_with_form(self):
        """
        自动化表单交互，为所有的form添加target="_blank", 然后点击submit
        """
        with_select = """
        var select_list = document.getElementsByTagName("select");
        for (i = 0; i < select_list.length; i++) {
            select_list[i].options.selectedIndex = 0;
        }
        """
        self.driver.execute_script(with_select)
        
        add_target_4form = """
        var form_list = document.getElementsByTagName("form");
        for (i = 0; i < form_list.length; i++) {
            form_list[i].setAttribute('target','_blank');
        }
        """
        self.driver.execute_script(add_target_4form)

        submit_click = """
        var b_i = 0;
        var but_list = document.getElementsByTagName("input");
        for(b_i = 0; b_i < but_list.length; b_i++) {
            var but_type = but_list[b_i].attributes["type"].value

            if (but_type == "text" && but_type == "TEXT") {
                if (but_list[b_i].attributes["name"].value == "username") {
                    but_list[b_i].setAttribute('value','myspider');
                } else {
                    but_list[b_i].setAttribute('value','normal_text');                    
                }
            }
            
            if (but_type == "email") {
                but_list[b_i].setAttribute('value','985654274@qq.com');
            }

            if (but_type == "password") {
                but_list[b_i].setAttribute('value','Gqa123456.');
            }

            if (but_type == "checkbox") {
                but_list[b_i].checked = true
            }

        }

        var textareas = document.getElementsByTagName("textarea");
        for(b_i = 0; b_i < textareas.length; b_i++) {
            textareas[b_i].value = "textarea_spider";
        }

        """
        self.driver.execute_script(submit_click)

    def interact_with_button(self):
        """
        点击button，包括input标签中的type为button和submit，button标签中type为submit
        """
        button_click = """
        var but_list = document.getElementsByTagName("input");
        for(b_i = 0; b_i < but_list.length; b_i++) {
            var but_type = but_list[b_i].attributes["type"].value
            if (but_type == "button") {
                but_list[b_i].setAttribute('target','_blank');
                but_list[b_i].click();
            }
            if (but_type == "submit") {
                but_list[b_i].setAttribute('target','_blank');
                but_list[b_i].click();
            }
            if (but_type=="SUBMIT") {
                but_list[b_i].setAttribute('target','_blank');
                but_list[b_i].click();
                console.log(but_list[b_i].attributes["value"]);
            }      
        }

        var buttons = document.getElementsByTagName("button");
        for(b_i = 0; b_i < buttons.length; b_i++)
        {
            try {
                var but_type = buttons[b_i].attributes["type"].value;
                if (but_type == "submit" && but_type=="SUBMIT") {
                     buttons[b_i].click();
                }
            } catch(err) {
                console.log(buttons[b_i],err);
            }
        }
        """
        self.driver.execute_script(button_click)

    def parse_datetime(self, dateTime_str):
        d = dateutil.parser.parse(dateTime_str)
        return d.strftime("%Y-%m-%d %H:%M:%S")

    def remove_duplicate(self):
        """
        去重模块，解析HAR文件(json)获取所有的网络请求，计算URL的hash值
        """
        db = DataStore(self.dbfile)
        log.info("[*] before result:")
        har_dict = self.proxy.har

        for item in har_dict['log']['entries']:
            url = item['request']['url']  # 请求的原始链接
            try:
                log.debug(url)
            except IOError:
                log.debug("before:"+url)

        log.info("before {} links in total".format(
            len(har_dict['log']['entries'])))

        log.info("[*] after result:")

        for item in har_dict['log']['entries']:
            url = item['request']['url']  # 请求的原始链接
            method = item['request']['method']
            startedDateTime = item['startedDateTime']

            queryString = ""
            postData = ""

            try:
                queryString = json.dumps(item['request']['queryString'][0])
            except:
                queryString = "None"

            try:
                postData = json.dumps(item['request']['postData'])
            except:
                postData = "None"

            startedTime = self.parse_datetime(startedDateTime)

            params = urlparse.urlsplit(url)
            suffix = url.split('.')[-1]

            # 忽略黑名单中的连接后缀
            if suffix in self.blacklist:
                continue

            query_list = urlparse.parse_qs(params.query).keys()
            query_hash = hash(params.scheme + params.netloc +
                                params.path + "_".join(query_list) + params.fragment + queryString + postData)

            same_netloc = str(params.netloc == self.netloc)

            if query_hash not in self.hash_set:
                self.hash_set.add(query_hash)
                self.url_set.add(url)
                try:
                    # 经筛选后的url存入数据库中
                    db.open(self.dbfile)
                    # 插入数据库的参数url,time,headers,method,same_netloc, queryString, postData, vulnerable默认为false
                    db.basic_init(url, startedTime, json.dumps(self.headers), method, same_netloc, queryString, postData)
                    db.close()
                    log.debug("insert %s into %s" % (url, self.dbfile))
                except IOError:
                    log.debug("after"+url)

        log.info("after {} links in total".format(len(self.url_set)))

    def start(self):
        """
        启动爬虫，开启相关配置
        """
        try:
            self.init_proxy(8888)
            log.info("Proxy setting ok!")
            self.init_chrome(1280, 720)
            log.info("Chrome setting ok!")
        except Exception as e:
            log.critical("[start]:"+str(e))

    def savehar(self):
        with open("./scanner/request.har", "w+") as f:
            f.write(json.dumps(self.proxy.har))

    def close(self):
        """
        注册atexit在程序发生异常而退出的时候执行清理函数
        """
        self.driver.close()
        log.info("driver close")
        self.driver.quit()
        log.info("driver quit")        
        try:
            self.proxy.close()
            log.info("proxy close")
            self.server.process.terminate()
            log.info("process terminate")
            self.server.process.kill()
            log.info("process kill")            
        except Exception as e:
            log.critical("[close]:"+e)


if __name__ == "__main__":
    print "[*]" + os.getcwd()
    start = time.time()
    dbfile = "./database/url.db"
    logging_config(log, "./log/spider_log.txt", 5)

    args = get_args()
    myspider = Spider(args.url, args.wait_time, dbfile, args.depth, args.headers)

    myspider.start()
    env_time = time.time()
    log.info("Setting env time costed:{}s".format(env_time-start))

    myspider.record_resp()
    result = myspider.get_page()
    
    if result == False:
        myspider.close()
    else:
        myspider.click_all_aTag()
        myspider.remove_duplicate()
        myspider.savehar()
        myspider.close()

    end = time.time()
    print "Total time costed:{}s".format(end-start)