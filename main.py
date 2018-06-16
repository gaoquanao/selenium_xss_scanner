# -*- coding:utf-8 -*-
import sqlite3
import re
from flask import Flask
from flask import jsonify
from flask import request
from flask import session
from flask import redirect
from flask import url_for
from flask import render_template
from flask_socketio import SocketIO
from flask import flash
from flask import make_response
from flask import send_file
from flask import send_from_directory
from flask import g
import shutil
import subprocess
import json
import time

import sys
reload(sys)
sys.setdefaultencoding('utf8')

app = Flask(__name__)
app.secret_key = 'quanao'

def connect_db():
    return sqlite3.connect('./database/url.db')

@app.before_request
def before_request():
    g.db = connect_db()

@app.teardown_request
def teardown_request(Exception):
    if hasattr(g, 'db'):
        g.db.close()

@app.route('/', methods=['GET'])
def basic_init():
    cur = g.db.execute('SELECT id, url, startedTime, headers, method, same_netloc, queryString, postData, vulnerable FROM data ORDER BY id')
    datas = [dict(id=row[0], url=row[1], startedTime=row[2], headers=row[3], method=row[4], \
    same_netloc=row[5], queryString=row[6], postData=row[7], vulnerable=row[8]) for row in cur.fetchall()]
    table_header = [
            'id',
            "链接",
            "时间",
            "请求头",
            "方法",
            "同源",
            "GET参数",
            "POST参数",
            "漏洞",
            "操作"
    ]
    g.db.commit()
    return render_template("dashboard.html", table_header=table_header, datas=datas)

@app.route('/report/<filename>', methods=['GET'])
def report(filename):
    cur = g.db.execute("SELECT url,startedTime,injectPoint,payload FROM vul;")
    datas = [dict(url=row[0], startedTime=row[1], injectPoint=row[2], payload=row[3]) for row in cur.fetchall()]
    # print type(datas),len(datas)
    g.db.commit()

    # 渲染report.html
    rendered = render_template('report.html',datas=datas)

    # 将渲染后的report.html写入report目录下
    with open("./report/report.html", "w+") as f:
        f.write(rendered)

    zip_name = './scan_report'  # 生成scan_report.zip
    directory_name = './report' # 被压缩的目录
    shutil.make_archive(zip_name, 'zip', directory_name)

    file_name = "./scan_report.zip"
    return send_from_directory("./", file_name, as_attachment=True)

@app.route('/cat/payload', methods=['GET'])
def cat():
    with open("./scanner/payloads/xss.txt", "r") as f:
        content = f.readlines()
    return jsonify({'status':'200','content':content})

@app.route('/set/payload', methods=['POST'])
def set_payload():
    content = request.form['payload_content']
    with open("./scanner/payloads/xss.txt", "w+") as f:
        f.write(content)
    return jsonify({'status':'200'})    

@app.route('/spider_log', methods=['GET'])
def get_spider_log():
    with open("./log/spider_log.txt", "r") as f:
        content = f.readlines()
    return jsonify({'status':'200','content':content})

@app.route('/db_log', methods=['GET'])
def get_db_log():
    with open("./log/dblog.txt", "r") as f:
        content = f.readlines()
    return jsonify({'status':'200','content':content})

@app.route('/cat/settings', methods=['GET'])
def cat_settings():
    cur = g.db.execute("SELECT * FROM settings;")
    data = cur.fetchone()
    try:
        url = data[1]
        depth = data[2]
        headers = data[3]
        ajax_wait_time = data[4]
        return jsonify({"url":url, "depth":depth, "headers":headers, "ajax_wait_time":ajax_wait_time})
    except Exception:
        return jsonify({"status":"404"})

@app.route('/save_setting', methods=['POST'])
def create_cmd_args():
    url =  request.form['url']
    depth = request.form['depth']
    headers = request.form['headers']
    ajax_wait_time = request.form['ajax_wait_time']
    if ajax_wait_time == "":
        ajax_wait_time = 0.8

    g.db.executescript("""
        drop table if exists settings;

        create table if not exists settings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url text,
            depth text,
            headers text,
            ajax_wait_time REAL DEFAULT 0.8
        );

    """)
    g.db.execute("insert into settings(url, depth, headers, ajax_wait_time) values (?,?,?,?);", (url, depth, headers, ajax_wait_time))
    g.db.commit()

    return jsonify({'status':'200'})

@app.route('/start_scan', methods=['GET'])
def start_scan():
    cur = g.db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name = 'settings'")
    count = cur.fetchone()
    if count == 0:
        # 不存在settings这张表，前端需要进行判断了之后，提示需要先添加配置
        return jsonify({"status":'404'})
    g.db.commit()

    cur = g.db.execute('SELECT url, depth, headers, ajax_wait_time FROM settings')
    data = [row for row in cur.fetchone()]
    url = data[0]
    depth = data[1]
    headers = data[2]
    ajax_wait_time = data[3]
    
    cmd_args = "python ./scanner/scan_xss.py -u %s -d %s -wait_time %s -headers '%s'" % (url, depth, ajax_wait_time, headers)
    print "[*]:"+cmd_args
    try:
        subprocess.Popen(cmd_args, shell=True)
        # p.wait()
    except Exception as e:
        return jsonify({"status":'404', "error":str(e)})

    return jsonify({"status":'200'})

@app.route('/detect_vul', methods=['POST'])
def detect_vul():
    # fix 前端传递url_id和detect 按钮点击的问题
    # url_id = request.args.get("url_id")
    data = json.loads(request.form.get('data'))
    url_id = data["url_id"]
    print "[debug]: in main url_id:%s" % (url_id)
    cmd_args = "python ./detector/reflect.py -id %s " % (url_id)
    try:
        subprocess.Popen(cmd_args, shell=True)
    except Exception as e:
        return jsonify({"status":"404", "error":str(e)})
    return jsonify({"status":'200'})

@app.route('/checkrunning', methods=['GET'])
def check():
    cmds = """ ps -ef | grep './scanner/scan_xss.py' """
    output = subprocess.check_output(cmds, shell=True)
    if output.count('\n') > 2:
        running = True
    else:
        running = False
    return jsonify({"running":running})

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=9090, debug=True)