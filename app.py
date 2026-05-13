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
# 内置GUI
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ===================== 应用常量定义 =====================
APP_NAME = "719WEBF"
APP_VER  = "Ver.1.5"
LOCK_FILE = os.path.join(os.getcwd(), "server.lock")
LOG_DIR = "logs"
CONFIG_FILE = "config.xml"

# ===================== 第一次启动      =====================

def show_image_right_bottom(image_path: str, display_sec: int = 5, scale_ratio: float = 1.0):
    """
    屏幕右下角显示图片窗口，定时自动关闭，支持等比例缩放
    :param image_path: 图片路径
    :param display_sec: 显示秒数
    :param scale_ratio: 缩放比例，1.0=原图，0.5=缩小一半，1.5=放大1.5倍
    """
    if not os.path.exists(image_path):
        print(f"图片不存在: {image_path}")
        return

    # 创建无边框置顶窗口
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)

    # 打开图片 + 等比例缩放
    img = Image.open(image_path)
    w, h = img.size
    # 计算缩放后尺寸
    new_w = int(w * scale_ratio)
    new_h = int(h * scale_ratio)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    photo = ImageTk.PhotoImage(img)

    # 屏幕尺寸 + 计算右下角位置
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = sw - new_w
    y = sh - new_h

    root.geometry(f"{new_w}x{new_h}+{x}+{y}")

    # 显示图片
    tk.Label(root, image=photo).pack()
    # 防止图片被垃圾回收
    root.photo = photo

    # 定时关闭
    root.after(display_sec * 1000, root.destroy)
    root.mainloop()

# ===================== XML配置读写 =====================
def create_default_config():
    show_image_right_bottom("startus.png", 5, 0.5)
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

# 全局配置
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
        # 共享目录
        ttk.Label(self, text="共享目录", font=("微软雅黑",10)).place(x=20, y=20)
        self.var_dir = tk.StringVar(value=self.cfg["share_dir"])
        ttk.Entry(self, textvariable=self.var_dir, width=55).place(x=20, y=50)
        ttk.Button(self, text="选择文件夹", command=self.select_dir).place(x=420, y=48)

        # 端口
        ttk.Label(self, text="服务端口 (1-65535)", font=("微软雅黑",10)).place(x=20, y=90)
        self.var_port = tk.StringVar(value=str(self.cfg["port"]))
        ttk.Entry(self, textvariable=self.var_port, width=30).place(x=20, y=120)

        # 首页标题
        ttk.Label(self, text="网页首页标题", font=("微软雅黑",10)).place(x=20, y=160)
        self.var_title = tk.StringVar(value=self.cfg["title"])
        ttk.Entry(self, textvariable=self.var_title, width=55).place(x=20, y=190)

        # 绑定IP
        ttk.Label(self, text="绑定IP (0.0.0.0=允许局域网)", font=("微软雅黑",10)).place(x=20, y=230)
        self.var_host = tk.StringVar(value=self.cfg["host"])
        ttk.Entry(self, textvariable=self.var_host, width=30).place(x=20, y=260)

        # 保存按钮
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

        # 校验
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
    """唤起设置GUI窗口"""
    app = SettingsGUI()
    app.mainloop()

# ===================== 日志系统初始化 =====================
os.makedirs(LOG_DIR, exist_ok=True)
log_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "server.log"),
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8"
)
file_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

logger = logging.getLogger(APP_NAME)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ===================== 防多开 & 端口占用检测 =====================
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
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass

# ===================== 托盘菜单功能 =====================
def tray_open_index(icon, item):
    webbrowser.open(f"http://127.0.0.1:{CONFIG['port']}")

def tray_open_transfer(icon, item):
    webbrowser.open(f"http://127.0.0.1:{CONFIG['port']}/transfer")

def tray_open_settings(icon, item):
    # 托盘右键唤起独立GUI设置
    threading.Thread(target=open_settings_gui, daemon=True).start()

def tray_exit(icon, item):
    icon.stop()
    remove_lock_file()
    logger.info("服务器已手动退出")
    os._exit(0)

def run_tray():
    try:
        if os.path.exists("logo.png"):
            icon_img = Image.open("logo.png").resize((64, 64))
        else:
            icon_img = Image.new('RGB', (64, 64), color=(0, 102, 204))

        # 托盘菜单：加入独立设置入口
        menu = pystray.Menu(
            item(f"{APP_NAME} {APP_VER}", lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("🌐 打开首页", tray_open_index),
            item("📁 传输中心", tray_open_transfer),
            item("⚙️ 程序设置", tray_open_settings),
            pystray.Menu.SEPARATOR,
            item("❌ 关闭服务器", tray_exit)
        )

        icon = pystray.Icon(
            name=APP_NAME,
            icon=icon_img,
            title=APP_NAME,
            menu=menu
        )
        icon.on_left_click = tray_open_index
        icon.run()
    except Exception as e:
        logger.error(f"托盘初始化失败: {e}")

# ===================== 后台服务器依赖 =====================
try:
    from waitress import serve
except ImportError:
    serve = None

# ===================== 防 DDoS/CC 防护 =====================
from flask_humanify import Humanify
where_is_it = "The Hell Network Centre"

# ===================== Flask初始化 =====================
app = Flask(__name__)
app.secret_key = f"719webf_{uuid.uuid4().hex}"
humanify = Humanify(
    app,
    challenge_type="one_click",
    image_dataset="animals",
    audio_dataset="characters",
    behind_proxy=False,
    use_client_id=True
)
humanify.register_middleware(action="challenge", url_patterns=["/*"])

# ===================== 全局路径配置 =====================
SHARE_FOLDER = os.path.abspath(CONFIG["share_dir"])
SERVER_PORT = CONFIG["port"]
HOME_TITLE = CONFIG["title"]
SERVER_HOST = CONFIG["host"]

STATIC_FOLDER = os.path.join(app.root_path, 'static')
UPLOAD_TEMP_FOLDER = os.path.join(app.root_path, "temp_uploads")
os.makedirs(UPLOAD_TEMP_FOLDER, exist_ok=True)

# ===================== 全局内存存储 =====================
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

# ========== 安全路径防穿越 ==========
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

# ===================== 临时下载 =====================
@app.route("/temp/download/<fid>")
def temp_download(fid):
    clean_expired_files()
    with file_lock:
        info = temp_files.get(fid)
    if not info:
        abort(404)
    return send_from_directory(
        UPLOAD_TEMP_FOLDER,
        fid,
        as_attachment=True,
        download_name=info["name"]
    )

# ===================== 临时文件删除接口 =====================
@app.route("/temp/delete/<fid>", methods=["POST"])
def temp_delete(fid):
    clean_expired_files()
    with file_lock:
        info = temp_files.get(fid)
        if not info:
            return jsonify({"code":1,"msg":"文件不存在或已过期"}), 404
        try:
            if os.path.exists(info["path"]):
                os.remove(info["path"])
        except:
            pass
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
            if left < 0:
                continue
            res.append({
                "fid": fid,
                "name": info["name"],
                "left_min": left // 60,
                "left_sec": left % 60
            })
    return jsonify({"code":0,"list":res})

# ===================== 传输中心 & 首页 =====================
@app.route("/transfer")
def transfer_page():
    return render_template("send_file.html")

@app.route("/")
def index():
    return render_template("index.html", title=HOME_TITLE)

# ========== 文件共享目录浏览 ==========
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

# ========== 目录页面模板 ==========
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

# ===================== 后台启动Flask =====================
def start_flask_server():
    if serve:
        serve(app, host=SERVER_HOST, port=SERVER_PORT)
    else:
        app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False)

# ========== 主程序入口 ==========
if __name__ == '__main__':
    # 单独只开设置GUI
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        open_settings_gui()
        sys.exit()

    # 正常启动服务
    check_single_instance(SERVER_PORT)
    logger.info(f"{APP_NAME} {APP_VER} 正在启动...")
    logger.info(f"共享目录: {SHARE_FOLDER} | 端口: {SERVER_PORT} | 绑定IP: {SERVER_HOST}")

    # 托盘线程
    tray_thread = threading.Thread(target=run_tray, daemon=True)
    tray_thread.start()

    # Flask服务线程
    flask_thread = threading.Thread(target=start_flask_server, daemon=True)
    flask_thread.start()

    # 主线程常驻
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("检测到手动终止，正在退出...")
        remove_lock_file()
        os._exit(0)