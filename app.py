#719WEBF Ver.1.4 2026
#Made By HZYANG+AI
#Use https://github.com/stevenjoezhang/live2d-widget (MIT)

from flask import Flask, request, jsonify, send_from_directory, render_template, render_template_string, abort, session, redirect, url_for
import random
import os
import urllib.parse
import argparse
import datetime
import uuid
import json
import time
from cloudflare_error_page import render as render_cf_error_page
from werkzeug.utils import secure_filename
from threading import Lock

# ===================== 【全局防 DDoS/CC 防护】最强防护，课机专用 =====================
from flask_vouch import Vouch

where_is_it = "The Hell Network Centre"

# ========== 1. 解析命令行参数 ==========
parser = argparse.ArgumentParser(description='Flask 文件共享服务器（带自定义首页）')
parser.add_argument('-d', '--dir', default='.', help='指定共享文件夹路径（默认：当前目录）')
parser.add_argument('-p', '--port', type=int, default=5000, help='指定服务器端口号（默认：5000）')
parser.add_argument('-t', '--title', default='文件共享服务', help='自定义首页标题（默认：文件共享服务）')
parser.add_argument('-host', default='0.0.0.0', help='指定绑定的IP地址（默认：0.0.0.0，允许局域网访问）')

args = parser.parse_args()

app = Flask(__name__)
app.secret_key = f"719webf_{uuid.uuid4().hex}"

# ===================== 🔥 全局启用防 DDoS/CC 防护（全自动拦截恶意请求） =====================
vouch = Vouch(
    app,
    global_protect=True,          # 全网站自动防护
    rate_limit="50 per minute",   # 课机完美限流
    captcha_seconds=5,            # 频繁请求自动出验证码
    block_spam=True               # 拦截刷屏/恶意访问
)

SHARE_FOLDER = os.path.abspath(args.dir)
SERVER_PORT = args.port
HOME_TITLE = args.title
SERVER_HOST = args.host

STATIC_FOLDER = os.path.join(app.root_path, 'static')
UPLOAD_TEMP_FOLDER = os.path.join(app.root_path, "temp_uploads")
os.makedirs(UPLOAD_TEMP_FOLDER, exist_ok=True)

# ===================== 全局存储 =====================
peers = {}
peer_lock = Lock()
temp_files = {}
file_lock = Lock()
signal_box = {}
last_signal = {}

# ========== 文件大小格式化 ==========
def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.2f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"

# ========== 时间格式化 ==========
def format_mtime(mtime):
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

# ========== 清理过期临时文件 ==========
def clean_expired_files():
    now = time.time()
    expired = []
    with file_lock:
        for fid, info in temp_files.items():
            if now - info["upload_time"] > 3600:
                expired.append(fid)
        for fid in expired:
            path = temp_files[fid]["path"]
            if os.path.exists(path):
                os.remove(path)
            del temp_files[fid]

# ========== 安全路径 ==========
def get_safe_path(relative_path):
    if relative_path == '/files' or relative_path == '/files/':
        return SHARE_FOLDER
    clean_path = relative_path.lstrip('/files/')
    target_path = os.path.normpath(os.path.join(SHARE_FOLDER, clean_path))
    if not target_path.startswith(SHARE_FOLDER):
        abort(403)
    return target_path

# ===================== live2d-widget 静态资源 =====================
@app.route("/live2d/<path:filename>")
def live2d_static(filename):
    return send_from_directory(os.path.join(STATIC_FOLDER, 'live2d'), filename)

# ===================== P2P 面对面直传 =====================
@app.route("/p2p/join")
def p2p_join():
    clean_expired_files()
    uid = session.get("p2p_uid", str(uuid.uuid4())[:8])
    session["p2p_uid"] = uid
    addr = request.remote_addr
    with peer_lock:
        peers[uid] = {"addr": addr, "online": time.time()}
    return jsonify({"code":0,"uid":uid,"peers":list(peers.keys())})

@app.route("/p2p/list")
def p2p_list():
    now = time.time()
    with peer_lock:
        online = [u for u,t in peers.items() if now - t["online"] < 30]
    return jsonify({"code":0,"list":online})

# ===================== P2P 信令接口 =====================
@app.route("/p2p/signal/send", methods=["POST"])
def p2p_signal_send():
    data = request.json
    to = data.get("to")
    frm = session.get("p2p_uid")
    if not to or not frm:
        return jsonify({"code": 1, "msg": "参数错误"})
    
    with peer_lock:
        if to not in signal_box:
            signal_box[to] = []
        signal_box[to].append(data)
    return jsonify({"code": 0})

@app.route("/p2p/signal/recv")
def p2p_signal_recv():
    uid = session.get("p2p_uid")
    if not uid or uid not in signal_box:
        return jsonify({})
    
    with peer_lock:
        if len(signal_box[uid]) == 0:
            return jsonify({})
        msg = signal_box[uid].pop(0)
    return jsonify(msg)

# ===================== 临时上传 =====================
@app.route("/temp/upload", methods=["POST"])
def temp_upload():
    clean_expired_files()
    if "file" not in request.files:
        return jsonify({"code":1,"msg":"无文件"})
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"code":1,"msg":"空文件"})
    filename = secure_filename(file.filename)
    fid = str(uuid.uuid4())[:12]
    save_path = os.path.join(UPLOAD_TEMP_FOLDER, fid)
    file.save(save_path)
    size = os.path.getsize(save_path)
    with file_lock:
        temp_files[fid] = {
            "name": filename,
            "size": format_size(size),
            "path": save_path,
            "upload_time": time.time()
        }
    url = f"/temp/download/{fid}"
    return jsonify({"code":0,"fid":fid,"url":url,"name":filename})

@app.route("/temp/download/<fid>")
def temp_download(fid):
    clean_expired_files()
    with file_lock:
        info = temp_files.get(fid)
    if not info:
        abort(404)
    return send_from_directory(UPLOAD_TEMP_FOLDER, fid, as_attachment=True, download_name=info["name"])

# ===================== 传输中心 =====================
@app.route("/transfer")
def transfer_page():
    return render_template("send_file.html")

# ===================== 首页（自动加载 Live2D） =====================
@app.route("/")
def index():
    return render_template("index.html", title=HOME_TITLE)

# ========== 文件共享 ==========
@app.route('/files/', defaults={'relative_path': ''})
@app.route('/files/<path:relative_path>')
def serve_directory(relative_path):
    full_relative_path = f'/files/{relative_path}' if relative_path else '/files/'
    target_path = get_safe_path(full_relative_path)
    if os.path.isfile(target_path):
        directory = os.path.dirname(target_path)
        filename = os.path.basename(target_path)
        return send_from_directory(directory, filename, as_attachment=False)
    elif os.path.isdir(target_path):
        template_data = {'path': full_relative_path,'parent_path': None,'items': []}
        if relative_path:
            parent_parts = relative_path.rstrip('/').split('/')[:-1]
            parent_path = '/files/' + '/'.join(parent_parts) if parent_parts else '/files/'
            template_data['parent_path'] = parent_path
        try:
            items = os.listdir(target_path)
        except PermissionError:
            abort(403)
        dirs = sorted([item for item in items if os.path.isdir(os.path.join(target_path, item))])
        files = sorted([item for item in items if os.path.isfile(os.path.join(target_path, item))])
        for item in dirs:
            item_path = os.path.join(target_path, item)
            item_url = urllib.parse.quote(f'/files/{os.path.join(relative_path, item)}')
            template_data['items'].append({'name':item,'url':item_url,'is_dir':True,'size':'','mtime':''})
        for item in files:
            item_path = os.path.join(target_path, item)
            item_url = urllib.parse.quote(f'/files/{os.path.join(relative_path, item)}')
            f_size = os.path.getsize(item_path)
            f_mtime = os.path.getmtime(item_path)
            template_data['items'].append({'name':item,'url':item_url,'is_dir':False,'size':format_size(f_size),'mtime':format_mtime(f_mtime)})
        return render_template_string(DIRECTORY_TEMPLATE,**template_data)
    else:
        abort(404)

# ========== 目录模板 ==========
DIRECTORY_TEMPLATE = '''
<!DOCTYPE HTML>
<html>
<head>
    <meta charset="utf-8">
    <title>目录：{{ path }}</title>
    <style>
        body{font-family:sans-serif;padding:20px;}
        ul{list-style:none;padding:0;}
        li{display:flex;justify-content:space-between;padding:6px 0;}
        a{flex:1;text-decoration:none;color:#0066cc;}
        a:hover{text-decoration:underline;}
        .file-info{color:#666;font-size:13px;}
    </style>
</head>
<body>
    <h1>目录：{{ path }}</h1>
    <hr>
    <ul>
        {% if parent_path %}<li><a href="{{ parent_path }}">../</a><span class="file-info">目录</span></li>{% endif %}
        {% for item in items %}
        <li>
            <a href="{{ item.url }}">{{ item.name }}{{ "/" if item.is_dir else "" }}</a>
            <span class="file-info">{% if item.is_dir %}目录{% else %}{{ item.size }} • {{ item.mtime }}{% endif %}</span>
        </li>
        {% endfor %}
    </ul>
    <hr>
    <a href="/">首页</a> | <a href="/transfer">传输中心</a>
    <script src="/live2d/dist/autoload.js"></script>
</body>
</html>
'''

# ========== 错误页 ==========
@app.errorhandler(404)
def error_404(e):
    error_params = {"title":"404 Not found","error_code":404,"browser_status":{"status":"ok"},"cloudflare_status":{"status":"ok","location":where_is_it},"host_status":{"status":"error","location":request.host,"status_text":"¯\\(o_o)/¯"},"error_source":"host","what_happened":"<p>检察：咋回事,一点消息也没有啊</p><p>服务器：东西呢?</p><p>硬盘：我不到啊</p>","what_can_i_do":"I don't know..."}
    return render_cf_error_page(error_params), 404

@app.errorhandler(500)
def error_500(e):
    error_params = {"title":"500 Internal Server Error","error_code":500,"browser_status":{"status":"ok"},"host_status":{"status":"ok","location":request.host},"cloudflare_status":{"status":"error","location":where_is_it,"status_text":"I Don't!"},"error_source":"cloudflare","what_happened":"<p>检察：咋回事,一点消息也没有啊</p><p>服务器：（阴暗扭曲的爬行）（停在原地）（发出耀眼白光）（“智慧”地说）啊？</p>","what_can_i_do":"You don't need to know..."}
    return render_cf_error_page(error_params), 500

@app.errorhandler(418)
def error_418(e):
    error_params = {"title":"418 I'm a Teapot","error_code":418,"browser_status":{"status":"ok"},"host_status":{"status":"error","location":request.host,"status_text":"Teapot"},"cloudflare_status":{"status":"error","location":where_is_it,"status_text":"Teapot"},"error_source":"cloudflare","what_happened":"服务器不能煮咖啡因为它是一把茶壶 (qwq)","what_can_i_do":"去另寻一台咖啡机吧awa"}
    return render_cf_error_page(error_params), 418

# ========== 启动 ==========
if __name__ == '__main__':
    print("="*50)
    print("719WEBF 已启用防 DDoS/CC 全局防护")
    print("="*50)
    print(f"✅ 共享目录：{SHARE_FOLDER}")
    print(f"✅ 访问首页：http://127.0.0.1:{SERVER_PORT}")
    print(f"✅ 文件共享：http://127.0.0.1:{SERVER_PORT}/files/")
    print(f"✅ 传输中心：http://127.0.0.1:{SERVER_PORT}/transfer")
    print("="*50)
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False)