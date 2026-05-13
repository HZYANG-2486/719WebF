#719WEBF Ver.1.5 2026
#Made By HZYANG+AI
#Use https://github.com/stevenjoezhang/live2d-widget (MIT)

import threading
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageTk
import sys
import os
import time
import socket
import logging
import webbrowser
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify, send_from_directory, render_template, render_template_string, abort, session, redirect, url_for
import urllib.parse
import datetime
import uuid
import json
from cloudflare_error_page import render as render_cf_error_page
from werkzeug.utils import secure_filename
from threading import Lock
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ===================== 应用常量定义 =====================
APP_NAME = "719WEBF"
APP_VER  = "Ver.1.5"
LOCK_FILE = os.path.join(os.getcwd(), "server.lock")
LOG_DIR = "logs"
CONFIG_FILE = "config.xml"

# ===================== XML配置读写 =====================
def create_default_config():
    root = ET.Element("config")
    ET.SubElement(root, "share_dir").text = "."
    ET.SubElement(root, "port").text = "5000"
    ET.SubElement(root, "title").text = "文件共享服务"
    ET.SubElement(root, "host").text = "0.0.0.0"
    tree = ET.ElementTree(root)
    with open(CONFIG_FILE, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        create_default_config()
    try:
        tree = ET.parse(CONFIG_FILE)
        root = tree.getroot()
        cfg = {
            "share_dir": root.findtext("share_dir", "."),
            "port": int(root.findtext("port", "5000")),
            "title": root.findtext("title", "文件共享服务"),
            "host": root.findtext("host", "0.0.0.0")
        }
        if not os.path.isdir(cfg["share_dir"]):
            cfg["share_dir"] = "."
        return cfg
    except:
        create_default_config()
        return load_config()

def save_config(share_dir, port, title, host):
    root = ET.Element("config")
    ET.SubElement(root, "share_dir").text = share_dir
    ET.SubElement(root, "port").text = str(port)
    ET.SubElement(root, "title").text = title
    ET.SubElement(root, "host").text = host
    tree = ET.ElementTree(root)
    with open(CONFIG_FILE, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)

CONFIG = load_config()

# ===================== 独立GUI设置窗口 =====================
class SettingsGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VER} 设置")
        self.geometry("520x320")
        self.resizable(False, False)
        self.configure(bg="#f0f0f0")
        self.cfg = load_config()
        self.create_widgets()

    def create_widgets(self):
        ttk.Label(self, text="共享目录", font=("微软雅黑",10)).place(x=20, y=20)
        self.var_dir = tk.StringVar(value=self.cfg["share_dir"])
        ttk.Entry(self, textvariable=self.var_dir, width=55).place(x=20, y=50)
        ttk.Button(self, text="选择文件夹", command=self.select_dir).place(x=420, y=48)

        ttk.Label(self, text="服务端口 (1-65535)", font=("微软雅黑",10)).place(x=20, y=90)
        self.var_port = tk.StringVar(value=str(self.cfg["port"]))
        ttk.Entry(self, textvariable=self.var_port, width=30).place(x=20, y=120)

        ttk.Label(self, text="网页首页标题", font=("微软雅黑",10)).place(x=20, y=160)
        self.var_title = tk.StringVar(value=self.cfg["title"])
        ttk.Entry(self, textvariable=self.var_title, width=55).place(x=20, y=190)

        ttk.Label(self, text="绑定IP (0.0.0.0=允许局域网)", font=("微软雅黑",10)).place(x=20, y=230)
        self.var_host = tk.StringVar(value=self.cfg["host"])
        ttk.Entry(self, textvariable=self.var_host, width=30).place(x=20, y=260)

        ttk.Button(self, text="保存配置", command=self.save).place(x=380, y=258)

    def select_dir(self):
        path = filedialog.askdirectory(title="选择共享文件夹")
        if path:
            self.var_dir.set(path)

    def save(self):
        share_dir = self.var_dir.get().strip()
        port_str = self.var_port.get().strip()
        title = self.var_title.get().strip()
        host = self.var_host.get().strip()

        if not os.path.isdir(share_dir):
            messagebox.showerror("错误", "共享目录不存在！")
            return
        if not port_str.isdigit():
            messagebox.showerror("错误", "端口必须为数字！")
            return
        port = int(port_str)
        if port < 1 or port > 65535:
            messagebox.showerror("错误", "端口范围 1~65535")
            return

        save_config(share_dir, port, title, host)
        messagebox.showinfo("成功", "配置已保存！\n请重启服务生效")
        self.destroy()

def open_settings_gui():
    app = SettingsGUI()
    app.mainloop()

# ===================== 日志系统（系统日志 + 详细WEB访问日志） =====================
os.makedirs(LOG_DIR, exist_ok=True)

# ---------------------
# 1. 系统运行日志（启动/关闭/错误）
# ---------------------
server_log = RotatingFileHandler(
    os.path.join(LOG_DIR, "server.log"),
    maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
)
server_log.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))

logger = logging.getLogger(APP_NAME)
logger.setLevel(logging.INFO)
logger.addHandler(server_log)

# ---------------------
# 2. 【你要的】详细WEB访问日志
# ---------------------
access_log = RotatingFileHandler(
    os.path.join(LOG_DIR, "access.log"),
    maxBytes=50*1024*1024, backupCount=10, encoding="utf-8"
)
access_log.setFormatter(logging.Formatter("%(message)s"))

access_logger = logging.getLogger("ACCESS_LOG")
access_logger.setLevel(logging.INFO)
access_logger.addHandler(access_log)
access_logger.propagate = False

# ===================== 防多开 & 端口检测 =====================
def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

def check_single_instance(port):
    if is_port_in_use(port):
        logger.error(f"端口 {port} 已被占用，禁止重复启动！")
        sys.exit(1)
    if os.path.exists(LOCK_FILE):
        logger.error("检测到服务已在运行，禁止多开！")
        sys.exit(1)
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

def remove_lock_file():
    if os.path.exists(LOCK_FILE):
        try: os.remove(LOCK_FILE)
        except: pass

# ===================== 托盘菜单 =====================
def tray_open_index(icon, item):
    webbrowser.open(f"http://127.0.0.1:{CONFIG['port']}")

def tray_open_transfer(icon, item):
    webbrowser.open(f"http://127.0.0.1:{CONFIG['port']}/transfer")

def tray_open_settings(icon, item):
    threading.Thread(target=open_settings_gui, daemon=True).start()

def tray_exit(icon, item):
    icon.stop()
    remove_lock_file()
    logger.info("服务器已手动退出")
    os._exit(0)

def run_tray():
    try:
        if os.path.exists("logo.png"):
            icon_img = Image.open("logo.png").resize((64,64))
        else:
            icon_img = Image.new('RGB', (64,64), color=(0,102,204))

        menu = pystray.Menu(
            item(f"{APP_NAME} {APP_VER}", lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("🌐 打开首页", tray_open_index),
            item("📁 传输中心", tray_open_transfer),
            item("⚙️ 程序设置", tray_open_settings),
            pystray.Menu.SEPARATOR,
            item("❌ 关闭服务器", tray_exit)
        )

        icon = pystray.Icon(APP_NAME, icon=icon_img, title=APP_NAME, menu=menu)
        icon.on_left_click = tray_open_index
        icon.run()
    except Exception as e:
        logger.error(f"托盘初始化失败: {e}")

# ===================== Flask 初始化 =====================
try:
    from waitress import serve
except ImportError:
    serve = None

from flask_humanify import Humanify
where_is_it = "The Hell Network Centre"

app = Flask(__name__)
app.secret_key = f"719webf_{uuid.uuid4().hex}"
humanify = Humanify(app, challenge_type="one_click", image_dataset="animals", audio_dataset="characters", behind_proxy=False, use_client_id=True)
humanify.register_middleware(action="challenge", url_patterns=["/*"])

# ===================== 【核心】记录每一次网页访问 =====================
@app.after_request
def log_access(response):
    try:
        ip = request.remote_addr
        method = request.method
        path = request.full_path
        status = response.status_code
        ua = request.user_agent.string[:150]
        size = response.content_length or 0
        time_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"{time_now} | {ip:15s} | {method:6s} | {status:3d} | {size:8d} B | {path}"
        access_logger.info(log_line)
    except:
        pass
    return response

# ===================== 全局配置 =====================
SHARE_FOLDER = os.path.abspath(CONFIG["share_dir"])
SERVER_PORT = CONFIG["port"]
HOME_TITLE = CONFIG["title"]
SERVER_HOST = CONFIG["host"]
STATIC_FOLDER = os.path.join(app.root_path, 'static')
UPLOAD_TEMP_FOLDER = os.path.join(app.root_path, "temp_uploads")
os.makedirs(UPLOAD_TEMP_FOLDER, exist_ok=True)

peers = {}
peer_lock = Lock()
temp_files = {}
file_lock = Lock()
signal_box = {}

# ===================== 工具函数 =====================
def format_size(size_bytes):
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024**2: return f"{size_bytes/1024:.2f} KB"
    elif size_bytes < 1024**3: return f"{size_bytes/1024**2:.2f} MB"
    else: return f"{size_bytes/1024**3:.2f} GB"

def format_mtime(mtime):
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

def clean_expired_files():
    now = time.time()
    expired = []
    with file_lock:
        for fid, info in temp_files.items():
            if now - info["upload_time"] > 3600:
                expired.append(fid)
        for fid in expired:
            try: os.remove(temp_files[fid]["path"])
            except: pass
            del temp_files[fid]

def get_safe_path(relative_path):
    if relative_path in ['/files', '/files/']:
        return SHARE_FOLDER
    clean = relative_path.lstrip('/files/')
    target = os.path.normpath(os.path.join(SHARE_FOLDER, clean))
    if not target.startswith(SHARE_FOLDER):
        abort(403)
    return target

# ===================== 路由（完全保留原有功能） =====================
@app.route("/live2d/<path:filename>")
def live2d_static(filename):
    return send_from_directory(os.path.join(STATIC_FOLDER, 'live2d'), filename)

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

@app.route("/p2p/signal/send", methods=["POST"])
def p2p_signal_send():
    data = request.json
    to = data.get("to")
    frm = session.get("p2p_uid")
    if not to or not frm:
        return jsonify({"code":1,"msg":"参数错误"})
    with peer_lock:
        if to not in signal_box: signal_box[to] = []
        signal_box[to].append(data)
    return jsonify({"code":0})

@app.route("/p2p/signal/recv")
def p2p_signal_recv():
    uid = session.get("p2p_uid")
    if not uid or uid not in signal_box:
        return jsonify({})
    with peer_lock:
        if len(signal_box[uid]) == 0: return jsonify({})
        msg = signal_box[uid].pop(0)
    return jsonify(msg)

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
        temp_files[fid] = {"name":filename,"size":format_size(size),"path":save_path,"upload_time":time.time()}
    return jsonify({"code":0,"fid":fid,"url":f"/temp/download/{fid}","name":filename})

@app.route("/temp/download/<fid>")
def temp_download(fid):
    clean_expired_files()
    with file_lock:
        info = temp_files.get(fid)
    if not info: abort(404)
    return send_from_directory(UPLOAD_TEMP_FOLDER, fid, as_attachment=True, download_name=info["name"])

@app.route("/temp/delete/<fid>", methods=["POST"])
def temp_delete(fid):
    clean_expired_files()
    with file_lock:
        info = temp_files.get(fid)
        if not info: return jsonify({"code":1,"msg":"不存在"}),404
        try: os.remove(info["path"])
        except: pass
        del temp_files[fid]
    return jsonify({"code":0,"msg":"删除成功"})

@app.route("/temp/list")
def temp_list():
    clean_expired_files()
    now = time.time()
    res = []
    with file_lock:
        for fid, info in temp_files.items():
            left = int(3600 - (now - info["upload_time"]))
            if left <0: continue
            res.append({"fid":fid,"name":info["name"],"left_min":left//60,"left_sec":left%60})
    return jsonify({"code":0,"list":res})

@app.route("/transfer")
def transfer_page():
    return render_template("send_file.html")

@app.route("/")
def index():
    return render_template("index.html", title=HOME_TITLE)

@app.route('/files/', defaults={'relative_path': ''})
@app.route('/files/<path:relative_path>')
def serve_directory(relative_path):
    full = f'/files/{relative_path}' if relative_path else '/files/'
    target = get_safe_path(full)
    if os.path.isfile(target):
        return send_from_directory(os.path.dirname(target), os.path.basename(target), as_attachment=False)
    if not os.path.isdir(target): abort(404)
    data = {"path":full,"parent_path":None,"items":[]}
    if relative_path:
        parent = "/files/" + "/".join(relative_path.rstrip('/').split('/')[:-1])
        data["parent_path"] = parent
    try: items = os.listdir(target)
    except PermissionError: abort(403)
    dirs = sorted([i for i in items if os.path.isdir(os.path.join(target,i))])
    files = sorted([i for i in items if os.path.isfile(os.path.join(target,i))])
    for i in dirs:
        data["items"].append({"name":i,"url":urllib.parse.quote(f'/files/{os.path.join(relative_path,i)}'),"is_dir":True,"size":"","mtime":""})
    for i in files:
        p = os.path.join(target,i)
        s = os.path.getsize(p)
        m = os.path.getmtime(p)
        data["items"].append({"name":i,"url":urllib.parse.quote(f'/files/{os.path.join(relative_path,i)}'),"is_dir":False,"size":format_size(s),"mtime":format_mtime(m)})
    return render_template_string('''
<!DOCTYPE HTML><html><head><meta charset="utf-8"><title>目录：{{ path }}</title>
<style>body{font-family:sans-serif;padding:20px;}ul{list-style:none;padding:0;}li{display:flex;justify-content:space-between;padding:6px 0;}a{flex:1;text-decoration:none;color:#0066cc;}a:hover{text-decoration:underline;}.file-info{color:#666;font-size:13px;}</style></head>
<body><h1>目录：{{ path }}</h1><hr><ul>
{% if parent_path %}<li><a href="{{ parent_path }}">../</a><span class="file-info">目录</span></li>{% endif %}
{% for item in items %}<li><a href="{{ item.url }}">{{ item.name }}{{ "/" if item.is_dir else "" }}</a>
<span class="file-info">{% if item.is_dir %}目录{% else %}{{ item.size }} • {{ item.mtime }}{% endif %}</span></li>{% endfor %}
</ul><hr><a href="/">首页</a> | <a href="/transfer">传输中心</a><script src="/live2d/dist/autoload.js"></script></body></html>''', **data)

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


# ===================== 启动服务 =====================
def start_flask_server():
    if serve:
        serve(app, host=SERVER_HOST, port=SERVER_PORT)
    else:
        app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        open_settings_gui()
        sys.exit()

    check_single_instance(SERVER_PORT)
    logger.info(f"{APP_NAME} {APP_VER} 启动 | 共享目录:{SHARE_FOLDER} 端口:{SERVER_PORT}")

    threading.Thread(target=run_tray, daemon=True).start()
    threading.Thread(target=start_flask_server, daemon=True).start()

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        remove_lock_file()
        os._exit(0)
