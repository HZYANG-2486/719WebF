import threading
import sys
import os
import copy
import webbrowser
import xml.etree.ElementTree as ET
import logging
from typing import Callable, Optional, Dict, Any

from version import APP_NAME, APP_VER

# 程序所在目录：用于定位 .secret 等固定文件
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 可自定义标题图的页面：标识 -> 页面中文名。
# 与 app.py 里的 NAV_ICON_PAGES 必须保持一致——gui.py 不导入 app.py
# （导入会连带拉起 gevent/Flask，设置工具不需要那一整套），故此处独立维护。
NAV_ICON_PAGES = {
    "home": "首页",
    "files": "文件浏览",
    "transfer": "传输中心",
    "chat": "聊天室",
    "health": "状态监控",
}


def _resolve_default_config_file():
    """把默认 config.xml 路径解析为相对于脚本/可执行文件目录的绝对路径。

    这样不论通过哪一种方式启动（双击 .py、快捷方式、打包成 exe、CD 到其它目录执行）
    config.xml 都会稳定落在程序目录，不会出现"要手动移植配置"、"右键生成的 xml 在 C:\\Windows\\system32 里"等问题。
    """
    # 优先使用 sys.argv[0] / sys.executable 的目录（PyInstaller 打包 & 脚本执行都覆盖）
    base_dir = None
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        try:
            script = os.path.abspath(sys.argv[0]) if sys.argv else ""
            if script and os.path.isdir(os.path.dirname(script)):
                base_dir = os.path.dirname(script)
        except Exception:
            base_dir = None
    if not base_dir:
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base_dir = os.getcwd()
    return os.path.join(base_dir, "config.xml")


DEFAULT_CONFIG_FILE = _resolve_default_config_file()

logger = logging.getLogger(APP_NAME)

_pystray = None
_Image = None
_item = None


def _ensure_pystray():
    global _pystray, _Image, _item
    if _pystray is None:
        import pystray as _pystray
        from pystray import MenuItem as _item
        from PIL import Image as _Image


def _has_display(timeout_seconds: float = 1.5) -> bool:
    if os.name == "nt":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            return bool(user32.GetProcessWindowStation() is not None)
        except Exception:
            pass
    result = {"ok": False}
    exc = []

    def _probe():
        try:
            import tkinter as tk_test
            root = tk_test.Tk()
            try:
                root.withdraw()
                root.update_idletasks()
            except Exception:
                pass
            root.destroy()
            result["ok"] = True
        except Exception as e:
            exc.append(e)

    t = threading.Thread(target=_probe, daemon=True)
    t.start()
    t.join(timeout_seconds)
    if t.is_alive():
        return False
    return result["ok"]


def get_default_cfg() -> dict:
    return {
        "share_dir": ".",
        "port": 5000,
        "title": "719WebF 文件分享站",
        "host": "0.0.0.0",
        "enable_https": False,
        "cert_file": "",
        "key_file": "",
        "key_password": "",
        "public_key_file": "",
        "max_upload_mb": 100,
        "behind_proxy": False,
        "chat": {
            "max_messages": 500,
            "room_timeout_hours": 24,
            "message_rate": 10,
            "message_rate_window": 60,
            "create_rate": 5,
            "create_rate_window": 60,
            "http_timeout": 30,
            "max_message_length": 2000,
        },
        "paths": {
            "lock_file": "server.lock",
            "log_dir": "logs",
            "secret_file": ".secret",
            "static_folder": "static",
            "upload_temp_folder": "temp_uploads",
            "data_dir": "data",
            "temp_files_data": "temp_files.json",
            "chat_data": "chat_data.json",
        },
        "p2p": {
            "max_signal_queue": 100,
            "signal_timeout": 300,
            "peer_timeout": 30,
        },
        "file_transfer": {
            "file_expire": 3600,
            "download_rate_limit": 10,
            "download_rate_window": 60,
        },
        "waf": {
            "rate_limit_per_minute": 120,
            "rate_limit_burst": 200,
            "unverified_rate_limit": 30,
            "unverified_rate_burst": 60,
            "file_rate_limit": 30,
            "file_rate_burst": 60,
            "challenge_cookie": "waf_verify",
            "challenge_expire": 86400,
            "js_challenge_difficulty": 8,
            "verify_path": "/waf_verify",
            "challenge_ip_ttl": 300,
            "bucket_cleanup_ttl": 300,
            "used_token_ttl": 600,
            "challenge_token_ttl": 300,
            "max_used_tokens": 10000,
            "rate_limit_exempt_paths": {"/p2p/signal/recv"},
        },
        "security": {
            "csrf_safe_methods": {"GET", "HEAD", "OPTIONS"},
            "csrf_exempt_paths": {"/waf_verify", "/ws/chat"},
        },
        "system": {
            "cleanup_interval_seconds": 60,
        },
        "monitor": {
            "max_history_samples": 360,
            "sample_interval": 10,
        },
        "admin": {
            "enabled": False,
            "username": "",
            "password_hash": "",
            "totp_secret": "",
        },
        "virtual_dirs": {},
        "hidden_folders": set(),
        "display_names": {},
        # 标题图：{页面标识: 图片路径}。配了则整块标题只显示图片。默认不启用。
        "nav_titles": {},
    }


def merge_with_defaults(partial_cfg) -> dict:
    result = copy.deepcopy(get_default_cfg())
    if partial_cfg is None:
        return result
    base_keys = ["share_dir", "port", "title", "host", "enable_https",
                 "cert_file", "key_file", "key_password", "public_key_file",
                 "max_upload_mb", "behind_proxy"]
    for k in base_keys:
        if k in partial_cfg:
            result[k] = partial_cfg[k]
    child_nodes = ["chat", "paths", "p2p", "file_transfer",
                   "waf", "security", "system", "monitor", "admin"]
    for node in child_nodes:
        if node in partial_cfg and partial_cfg[node] is not None:
            for k, v in partial_cfg[node].items():
                result[node][k] = v
    # 虚拟目录：{显示名: 物理路径} 映射。
    # 整体替换而非增量合并——否则用户在设置界面删除的条目会因为
    # 默认值里还留着而"复活"，删除操作看起来无效。
    if "virtual_dirs" in partial_cfg and partial_cfg["virtual_dirs"] is not None:
        result["virtual_dirs"] = dict(partial_cfg["virtual_dirs"])
    # 隐藏文件夹：不列出但可直接访问的名称集合（同样整体替换）
    if "hidden_folders" in partial_cfg and partial_cfg["hidden_folders"] is not None:
        result["hidden_folders"] = set(partial_cfg["hidden_folders"])
    # 显示别名：{真实名称: 列表显示名}
    if "display_names" in partial_cfg and partial_cfg["display_names"] is not None:
        result["display_names"] = dict(partial_cfg["display_names"])
    # 标题图：整体替换，清空后才能回到原来的文字
    if "nav_titles" in partial_cfg and partial_cfg["nav_titles"] is not None:
        result["nav_titles"] = dict(partial_cfg["nav_titles"])
    return result


def create_default_config(config_path: str) -> None:
    default_cfg = get_default_cfg()
    root = ET.Element("config")

    root.append(ET.Comment("共享目录路径，默认 \".\" 表示当前目录，所有分享文件均基于此目录提供访问"))
    el = ET.SubElement(root, "share_dir")
    el.text = default_cfg["share_dir"]

    root.append(ET.Comment("服务监听端口号，默认 5000，建议范围 1024-65535"))
    el = ET.SubElement(root, "port")
    el.text = str(default_cfg["port"])

    root.append(ET.Comment("网站标题名称，默认 \"719WebF 文件分享站\"，将显示于网页标题栏"))
    el = ET.SubElement(root, "title")
    el.text = default_cfg["title"]

    root.append(ET.Comment("服务监听主机地址，默认 \"0.0.0.0\" 表示监听所有网卡接口，如需本地测试可改为 \"127.0.0.1\""))
    el = ET.SubElement(root, "host")
    el.text = default_cfg["host"]

    root.append(ET.Comment("是否启用 HTTPS 加密通信，默认 false，启用后需同时配置 cert_file 和 key_file"))
    el = ET.SubElement(root, "enable_https")
    el.text = "true" if default_cfg["enable_https"] else "false"

    root.append(ET.Comment("SSL 证书文件路径，HTTPS 启用时必填，默认空字符串表示未配置"))
    el = ET.SubElement(root, "cert_file")
    el.text = default_cfg["cert_file"]

    root.append(ET.Comment("SSL 私钥文件路径，HTTPS 启用时必填，默认空字符串表示未配置"))
    el = ET.SubElement(root, "key_file")
    el.text = default_cfg["key_file"]

    root.append(ET.Comment("SSL 私钥保护密码，如私钥未加密可留空，默认空字符串"))
    el = ET.SubElement(root, "key_password")
    el.text = default_cfg["key_password"]

    root.append(ET.Comment("RSA 公钥文件路径，用于签名验证等加密场景，默认空字符串表示未配置"))
    el = ET.SubElement(root, "public_key_file")
    el.text = default_cfg["public_key_file"]

    root.append(ET.Comment("单文件上传最大体积（单位：MB），默认 100，超过此值的上传将被拒绝"))
    el = ET.SubElement(root, "max_upload_mb")
    el.text = str(default_cfg["max_upload_mb"])

    root.append(ET.Comment("服务是否运行在反向代理（如 Nginx）之后，默认 false，启用后将正确获取客户端真实 IP"))
    el = ET.SubElement(root, "behind_proxy")
    el.text = "true" if default_cfg["behind_proxy"] else "false"

    paths = ET.SubElement(root, "paths")
    paths.append(ET.Comment("服务进程锁文件路径，用于防止多实例启动冲突，默认 \"server.lock\""))
    el = ET.SubElement(paths, "lock_file")
    el.text = default_cfg["paths"]["lock_file"]

    paths.append(ET.Comment("日志文件存储目录，默认 \"logs\"，存放运行日志与访问日志"))
    el = ET.SubElement(paths, "log_dir")
    el.text = default_cfg["paths"]["log_dir"]

    paths.append(ET.Comment("会话密钥文件路径，用于加密 Flask Session Cookie，默认 \".secret\"，首次启动自动生成"))
    el = ET.SubElement(paths, "secret_file")
    el.text = default_cfg["paths"]["secret_file"]

    paths.append(ET.Comment("静态资源文件夹路径，存放 CSS/JS/图片等前端资源，默认 \"static\""))
    el = ET.SubElement(paths, "static_folder")
    el.text = default_cfg["paths"]["static_folder"]

    paths.append(ET.Comment("上传临时文件夹，接收分片上传数据直至合并完成，默认 \"temp_uploads\""))
    el = ET.SubElement(paths, "upload_temp_folder")
    el.text = default_cfg["paths"]["upload_temp_folder"]

    paths.append(ET.Comment("持久化数据目录，存放聊天记录、临时文件索引等数据，默认 \"data\""))
    el = ET.SubElement(paths, "data_dir")
    el.text = default_cfg["paths"]["data_dir"]

    paths.append(ET.Comment("临时文件元数据存储文件名（JSON 格式），记录临时文件到期时间等信息，默认 \"temp_files.json\""))
    el = ET.SubElement(paths, "temp_files_data")
    el.text = default_cfg["paths"]["temp_files_data"]

    paths.append(ET.Comment("聊天消息持久化文件名（JSON 格式），默认 \"chat_data.json\""))
    el = ET.SubElement(paths, "chat_data")
    el.text = default_cfg["paths"]["chat_data"]

    p2p = ET.SubElement(root, "p2p")
    p2p.append(ET.Comment("信令队列最大长度，每个对等方待发送信令消息的最大缓存数，默认 100"))
    el = ET.SubElement(p2p, "max_signal_queue")
    el.text = str(default_cfg["p2p"]["max_signal_queue"])

    p2p.append(ET.Comment("信令请求超时时间（秒），超时未收到响应则视为请求失败，默认 300"))
    el = ET.SubElement(p2p, "signal_timeout")
    el.text = str(default_cfg["p2p"]["signal_timeout"])

    p2p.append(ET.Comment("对等方心跳超时时间（秒），超时未收到心跳即清理该对等方连接，默认 30"))
    el = ET.SubElement(p2p, "peer_timeout")
    el.text = str(default_cfg["p2p"]["peer_timeout"])

    file_transfer = ET.SubElement(root, "file_transfer")
    file_transfer.append(ET.Comment("临时分享文件默认过期时间（秒），到期后自动删除，默认 3600（即 1 小时）"))
    el = ET.SubElement(file_transfer, "file_expire")
    el.text = str(default_cfg["file_transfer"]["file_expire"])

    file_transfer.append(ET.Comment("下载速率限制，单 IP 每窗口时间内最大下载次数，默认 10 次/窗口"))
    el = ET.SubElement(file_transfer, "download_rate_limit")
    el.text = str(default_cfg["file_transfer"]["download_rate_limit"])

    file_transfer.append(ET.Comment("下载速率限制统计窗口大小（秒），配合 download_rate_limit 使用，默认 60"))
    el = ET.SubElement(file_transfer, "download_rate_window")
    el.text = str(default_cfg["file_transfer"]["download_rate_window"])

    waf = ET.SubElement(root, "waf")
    waf.append(ET.Comment("已验证客户端每分钟请求速率上限，普通正常访问使用，默认 120 次/分钟"))
    el = ET.SubElement(waf, "rate_limit_per_minute")
    el.text = str(default_cfg["waf"]["rate_limit_per_minute"])

    waf.append(ET.Comment("已验证客户端突发请求峰值，允许短时间内超过限速的最大请求数，默认 200"))
    el = ET.SubElement(waf, "rate_limit_burst")
    el.text = str(default_cfg["waf"]["rate_limit_burst"])

    waf.append(ET.Comment("未验证客户端每分钟请求速率上限，JS 挑战通过前使用更严格的限速，默认 30 次/分钟"))
    el = ET.SubElement(waf, "unverified_rate_limit")
    el.text = str(default_cfg["waf"]["unverified_rate_limit"])

    waf.append(ET.Comment("未验证客户端突发请求峰值，默认 60"))
    el = ET.SubElement(waf, "unverified_rate_burst")
    el.text = str(default_cfg["waf"]["unverified_rate_burst"])

    waf.append(ET.Comment("文件下载接口每分钟请求速率上限（按 IP 统计），默认 30 次/分钟"))
    el = ET.SubElement(waf, "file_rate_limit")
    el.text = str(default_cfg["waf"]["file_rate_limit"])

    waf.append(ET.Comment("文件下载接口突发请求峰值，默认 60"))
    el = ET.SubElement(waf, "file_rate_burst")
    el.text = str(default_cfg["waf"]["file_rate_burst"])

    waf.append(ET.Comment("WAF 验证通过后写入客户端的 Cookie 名称，默认 \"waf_verify\""))
    el = ET.SubElement(waf, "challenge_cookie")
    el.text = default_cfg["waf"]["challenge_cookie"]

    waf.append(ET.Comment("验证 Cookie 的有效期（秒），过期后需重新通过 JS 挑战，默认 86400（即 24 小时）"))
    el = ET.SubElement(waf, "challenge_expire")
    el.text = str(default_cfg["waf"]["challenge_expire"])

    waf.append(ET.Comment("JS 挑战 PoW 难度值（0-16），值越大浏览器计算越耗时，推荐 6-12，默认 8"))
    el = ET.SubElement(waf, "js_challenge_difficulty")
    el.text = str(default_cfg["waf"]["js_challenge_difficulty"])

    waf.append(ET.Comment("前端 JS 挑战结果提交验证的接口路径，默认 \"/waf_verify\""))
    el = ET.SubElement(waf, "verify_path")
    el.text = default_cfg["waf"]["verify_path"]

    waf.append(ET.Comment("每个 IP 的挑战令牌缓存 TTL（秒），超时后需重新生成挑战，默认 300"))
    el = ET.SubElement(waf, "challenge_ip_ttl")
    el.text = str(default_cfg["waf"]["challenge_ip_ttl"])

    waf.append(ET.Comment("限流令牌桶清理 TTL（秒），长时间无活动的桶将被清理以节省内存，默认 300"))
    el = ET.SubElement(waf, "bucket_cleanup_ttl")
    el.text = str(default_cfg["waf"]["bucket_cleanup_ttl"])

    waf.append(ET.Comment("已使用挑战令牌的保留时间（秒），防止重放攻击，默认 600"))
    el = ET.SubElement(waf, "used_token_ttl")
    el.text = str(default_cfg["waf"]["used_token_ttl"])

    waf.append(ET.Comment("未使用挑战令牌的有效期（秒），超时令牌失效，默认 300"))
    el = ET.SubElement(waf, "challenge_token_ttl")
    el.text = str(default_cfg["waf"]["challenge_token_ttl"])

    waf.append(ET.Comment("最大已使用令牌记录数，超出后按 FIFO 淘汰，防止内存溢出，默认 10000"))
    el = ET.SubElement(waf, "max_used_tokens")
    el.text = str(default_cfg["waf"]["max_used_tokens"])

    waf.append(ET.Comment("免除限流的接口路径列表（逗号分隔），这些路径不触发 WAF 速率限制，默认 \"/p2p/signal/recv\""))
    el = ET.SubElement(waf, "rate_limit_exempt_paths")
    el.text = ",".join(sorted(default_cfg["waf"]["rate_limit_exempt_paths"]))

    security = ET.SubElement(root, "security")
    security.append(ET.Comment("CSRF 保护豁免的安全 HTTP 方法集合（逗号分隔），这些方法不会被校验 CSRF Token，默认 \"GET,HEAD,OPTIONS\""))
    el = ET.SubElement(security, "csrf_safe_methods")
    el.text = ",".join(sorted(default_cfg["security"]["csrf_safe_methods"]))

    security.append(ET.Comment("免除 CSRF 校验的接口路径列表（逗号分隔），如 WebSocket 入口等无法携带 Token 的接口，默认 \"/waf_verify,/ws/chat\""))
    el = ET.SubElement(security, "csrf_exempt_paths")
    el.text = ",".join(sorted(default_cfg["security"]["csrf_exempt_paths"]))

    system = ET.SubElement(root, "system")
    system.append(ET.Comment("系统后台清理任务执行间隔（秒），周期性清理过期临时文件、过期聊天房间等，默认 60"))
    el = ET.SubElement(system, "cleanup_interval_seconds")
    el.text = str(default_cfg["system"]["cleanup_interval_seconds"])

    monitor = ET.SubElement(root, "monitor")
    monitor.append(ET.Comment("性能监控最大历史样本数量，用于绘制监控图表，默认 360 个样本点（每 10 秒一个约 1 小时数据）"))
    el = ET.SubElement(monitor, "max_history_samples")
    el.text = str(default_cfg["monitor"]["max_history_samples"])

    monitor.append(ET.Comment("性能监控样本采集间隔（秒），每隔多久采集一次 CPU/内存/请求量等数据，默认 10"))
    el = ET.SubElement(monitor, "sample_interval")
    el.text = str(default_cfg["monitor"]["sample_interval"])

    chat_el = ET.SubElement(root, "chat")
    chat_el.append(ET.Comment("单聊天室最大消息保留条数（单位：条），超出后将删除最早的历史消息，建议 100-10000，默认 500"))
    el = ET.SubElement(chat_el, "max_messages")
    el.text = str(default_cfg["chat"]["max_messages"])

    chat_el.append(ET.Comment("聊天室空闲超时时间（单位：小时），超过此时长无消息的房间将被自动回收，建议 1-168，默认 24"))
    el = ET.SubElement(chat_el, "room_timeout_hours")
    el.text = str(default_cfg["chat"]["room_timeout_hours"])

    chat_el.append(ET.Comment("单用户发送消息速率上限（单位：条/窗口时间），建议 1-60，默认 10"))
    el = ET.SubElement(chat_el, "message_rate")
    el.text = str(default_cfg["chat"]["message_rate"])

    chat_el.append(ET.Comment("消息速率统计窗口（单位：秒），配合 message_rate 使用，默认 60"))
    el = ET.SubElement(chat_el, "message_rate_window")
    el.text = str(default_cfg["chat"]["message_rate_window"])

    chat_el.append(ET.Comment("单用户创建聊天室速率上限（单位：次/窗口时间），防止恶意创建房间，建议 1-60，默认 5"))
    el = ET.SubElement(chat_el, "create_rate")
    el.text = str(default_cfg["chat"]["create_rate"])

    chat_el.append(ET.Comment("创建房间速率统计窗口（单位：秒），配合 create_rate 使用，默认 60"))
    el = ET.SubElement(chat_el, "create_rate_window")
    el.text = str(default_cfg["chat"]["create_rate_window"])

    chat_el.append(ET.Comment("聊天接口 HTTP 请求超时时间（单位：秒），用于长轮询等场景，建议 10-120，默认 30"))
    el = ET.SubElement(chat_el, "http_timeout")
    el.text = str(default_cfg["chat"]["http_timeout"])

    chat_el.append(ET.Comment("单条聊天消息最大字符长度，超过长度的消息将被拒绝，默认 2000"))
    el = ET.SubElement(chat_el, "max_message_length")
    el.text = str(default_cfg["chat"]["max_message_length"])

    admin_el = ET.SubElement(root, "admin")
    admin_el.append(ET.Comment(
        "管理账号：用于删除不合适的聊天消息。enabled 控制是否启用（默认 false）。"
        "password_hash/totp_secret 请用 db_tool.py 生成，切勿手填明文密码。"
    ))
    admin_el.set("enabled", "false")
    admin_el.set("username", "")
    admin_el.set("password_hash", "")
    admin_el.set("totp_secret", "")

    vdirs_el = ET.SubElement(root, "virtual_dirs")
    vdirs_el.append(ET.Comment(
        "虚拟目录：让某个文件夹以别名出现在列表中（映射到本机物理路径）。"
        "路径必须位于共享目录内（相对路径会被解析为共享目录下），否则将被忽略。"
        "示例：<dir name=\"docs\" path=\"sub/docs\" />"
    ))

    hidden_el = ET.SubElement(root, "hidden_folders")
    hidden_el.append(ET.Comment(
        "隐藏文件夹：列表中将不显示这些名称的文件夹（输入完整名称匹配，仍可直接访问）。"
        "示例：<folder name=\"secret\" />"
    ))

    names_el = ET.SubElement(root, "display_names")
    names_el.append(ET.Comment(
        "显示别名：列表中把某条目显示成另一个名字，不改动磁盘上的真实名称。"
        "示例：<item name=\"real_folder\" as=\"对外显示的名字\" />"
    ))

    # 标题图节点：出厂时全部留空，表示各页面继续显示原来的文字与符号
    titles_el = ET.SubElement(root, "nav_titles")
    titles_el.append(ET.Comment(
        "标题图：把整块标题文字换成一幅图片。name 可选 "
        + "/".join(NAV_ICON_PAGES.keys())
        + "；image 填本地图片的绝对路径，留空则不启用（显示原来的文字与符号）。"
    ))
    for _page in NAV_ICON_PAGES:
        _img = (default_cfg.get("nav_titles") or {}).get(_page, "")
        ET.SubElement(titles_el, "page", {"name": _page, "image": str(_img)})

    tree = ET.ElementTree(root)
    parent = os.path.dirname(os.path.abspath(config_path))
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception as e:
            raise IOError(f"创建配置目录失败: {parent} ({e})") from e
    tmp_file = config_path + ".tmp"
    try:
        with open(tmp_file, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)
        os.replace(tmp_file, config_path)
    except Exception as e:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        logging.error(f"生成默认配置文件失败: {config_path}, 错误: {e}")
        raise IOError(f"生成默认配置文件 {config_path} 失败: {e}") from e


def _parse_set(text):
    if not text:
        return set()
    return {s.strip() for s in text.split(",") if s.strip()}


def load_config(config_path: str, _depth: int = 0) -> Dict[str, Any]:
    if not os.path.exists(config_path):
        try:
            create_default_config(config_path)
            logging.info(f"配置文件不存在，已生成默认配置: {config_path}")
        except Exception as e:
            logging.warning(f"生成默认配置失败: {e}")
        return merge_with_defaults({})

    try:
        tree = ET.parse(config_path)
    except (ET.ParseError, OSError) as e:
        logging.warning(f"Invalid config.xml, using default: {e}")
        return merge_with_defaults({})

    root = tree.getroot()

    partial_cfg = {
        "share_dir": root.findtext("share_dir", "."),
        "port": int(root.findtext("port", "5000")),
        "title": root.findtext("title", "719WebF 文件分享站"),
        "host": root.findtext("host", "0.0.0.0"),
        "enable_https": root.findtext("enable_https", "false").lower() == "true",
        "cert_file": root.findtext("cert_file", ""),
        "key_file": root.findtext("key_file", ""),
        "key_password": root.findtext("key_password", ""),
        "public_key_file": root.findtext("public_key_file", ""),
        "max_upload_mb": int(root.findtext("max_upload_mb", "100")),
        "behind_proxy": root.findtext("behind_proxy", "false").lower() == "true",
    }

    if not os.path.isdir(partial_cfg["share_dir"]):
        partial_cfg["share_dir"] = "."

    chat_node = root.find("chat")
    if chat_node is not None:
        partial_cfg["chat"] = {
            "max_messages": int(chat_node.findtext("max_messages", "500")),
            "room_timeout_hours": int(chat_node.findtext("room_timeout_hours", "24")),
            "message_rate": int(chat_node.findtext("message_rate", "10")),
            "message_rate_window": int(chat_node.findtext("message_rate_window", "60")),
            "create_rate": int(chat_node.findtext("create_rate", "5")),
            "create_rate_window": int(chat_node.findtext("create_rate_window", "60")),
            "http_timeout": int(chat_node.findtext("http_timeout", "30")),
            "max_message_length": int(chat_node.findtext("max_message_length", "2000")),
        }

    paths_node = root.find("paths")
    if paths_node is not None:
        partial_cfg["paths"] = {
            "lock_file": paths_node.findtext("lock_file", "server.lock"),
            "log_dir": paths_node.findtext("log_dir", "logs"),
            "secret_file": paths_node.findtext("secret_file", ".secret"),
            "static_folder": paths_node.findtext("static_folder", "static"),
            "upload_temp_folder": paths_node.findtext("upload_temp_folder", "temp_uploads"),
            "data_dir": paths_node.findtext("data_dir", "data"),
            "temp_files_data": paths_node.findtext("temp_files_data", "temp_files.json"),
            "chat_data": paths_node.findtext("chat_data", "chat_data.json"),
        }

    p2p_node = root.find("p2p")
    if p2p_node is not None:
        partial_cfg["p2p"] = {
            "max_signal_queue": int(p2p_node.findtext("max_signal_queue", "100")),
            "signal_timeout": int(p2p_node.findtext("signal_timeout", "300")),
            "peer_timeout": int(p2p_node.findtext("peer_timeout", "30")),
        }

    ft_node = root.find("file_transfer")
    if ft_node is not None:
        partial_cfg["file_transfer"] = {
            "file_expire": int(ft_node.findtext("file_expire", "3600")),
            "download_rate_limit": int(ft_node.findtext("download_rate_limit", "10")),
            "download_rate_window": int(ft_node.findtext("download_rate_window", "60")),
        }

    waf_node = root.find("waf")
    if waf_node is not None:
        partial_cfg["waf"] = {
            "rate_limit_per_minute": int(waf_node.findtext("rate_limit_per_minute", "120")),
            "rate_limit_burst": int(waf_node.findtext("rate_limit_burst", "200")),
            "unverified_rate_limit": int(waf_node.findtext("unverified_rate_limit", "30")),
            "unverified_rate_burst": int(waf_node.findtext("unverified_rate_burst", "60")),
            "file_rate_limit": int(waf_node.findtext("file_rate_limit", "30")),
            "file_rate_burst": int(waf_node.findtext("file_rate_burst", "60")),
            "challenge_cookie": waf_node.findtext("challenge_cookie", "waf_verify"),
            "challenge_expire": int(waf_node.findtext("challenge_expire", "86400")),
            "js_challenge_difficulty": int(waf_node.findtext("js_challenge_difficulty", "8")),
            "verify_path": waf_node.findtext("verify_path", "/waf_verify"),
            "challenge_ip_ttl": int(waf_node.findtext("challenge_ip_ttl", "300")),
            "bucket_cleanup_ttl": int(waf_node.findtext("bucket_cleanup_ttl", "300")),
            "used_token_ttl": int(waf_node.findtext("used_token_ttl", "600")),
            "challenge_token_ttl": int(waf_node.findtext("challenge_token_ttl", "300")),
            "max_used_tokens": int(waf_node.findtext("max_used_tokens", "10000")),
            "rate_limit_exempt_paths": _parse_set(waf_node.findtext("rate_limit_exempt_paths", "")),
        }

    sec_node = root.find("security")
    if sec_node is not None:
        partial_cfg["security"] = {
            "csrf_safe_methods": _parse_set(sec_node.findtext("csrf_safe_methods", "")),
            "csrf_exempt_paths": _parse_set(sec_node.findtext("csrf_exempt_paths", "")),
        }

    sys_node = root.find("system")
    if sys_node is not None:
        partial_cfg["system"] = {
            "cleanup_interval_seconds": int(sys_node.findtext("cleanup_interval_seconds", "60")),
        }

    mon_node = root.find("monitor")
    if mon_node is not None:
        partial_cfg["monitor"] = {
            "max_history_samples": int(mon_node.findtext("max_history_samples", "360")),
            "sample_interval": int(mon_node.findtext("sample_interval", "10")),
        }

    admin_node = root.find("admin")
    if admin_node is not None:
        partial_cfg["admin"] = {
            "enabled": (admin_node.get("enabled", "false").lower() == "true"),
            "username": admin_node.get("username", ""),
            "password_hash": admin_node.get("password_hash", ""),
            "totp_secret": admin_node.get("totp_secret", ""),
        }

    vdirs_node = root.find("virtual_dirs")
    if vdirs_node is not None:
        vdirs = {}
        for d in vdirs_node.findall("dir"):
            name = (d.get("name") or "").strip()
            path = (d.get("path") or "").strip()
            if name and path:
                vdirs[name] = path
        partial_cfg["virtual_dirs"] = vdirs

    hidden_node = root.find("hidden_folders")
    if hidden_node is not None:
        partial_cfg["hidden_folders"] = set(
            (f.get("name") or "").strip()
            for f in hidden_node.findall("folder")
            if (f.get("name") or "").strip()
        )

    # 显示别名：把某个条目在列表中显示成另一个名字（不改动磁盘真实名称）
    names_node = root.find("display_names")
    if names_node is not None:
        display_names = {}
        for node in names_node.findall("item"):
            real = (node.get("name") or "").strip()
            shown = (node.get("as") or "").strip()
            if real and shown:
                display_names[real] = shown
        partial_cfg["display_names"] = display_names

    # 标题图：<page name="chat" image="/path/banner.png" />
    titles_node = root.find("nav_titles")
    if titles_node is not None:
        nav_titles = {}
        for node in titles_node.findall("page"):
            key = (node.get("name") or "").strip()
            image = (node.get("image") or "").strip()
            if key in NAV_ICON_PAGES:
                nav_titles[key] = image
        partial_cfg["nav_titles"] = nav_titles

    return merge_with_defaults(partial_cfg)


def name_is_illegal(name: str):
    """检查一个"显示名称"是否可用。

    显示名称会直接出现在网页的文件夹列表里，所以不能包含路径分隔符
    （会让层级看起来错乱），也不能是 "." / ".." 这类相对路径符号。
    返回 (是否有问题, 原因说明)，没问题时返回 (False, "")。
    """
    if name is None:
        return True, "名称不能为空。"
    s = str(name).strip()
    if not s:
        return True, "名称不能为空。"
    if "/" in s or "\\" in s:
        return True, "名称里不能包含斜杠（/ 或 \\），否则列表层级会显示错乱。"
    if s in (".", ".."):
        return True, "名称不能是「.」或「..」。"
    if len(s) > 60:
        return True, "名称太长了，请控制在 60 个字符以内。"
    return False, ""


def check_vdir_conflicts(virtual_dirs, share_dir):
    """检查虚拟目录别名是否与共享目录里的真实文件夹重名。

    重名的后果很隐蔽：网页列表里显示的是真实文件夹，点进去打开的却是
    虚拟目录指向的另一个位置——"看到 A 打开 B"。所以保存时直接拦下来。

    返回问题描述列表，空列表表示没有问题。
    """
    problems = []
    if not virtual_dirs:
        return problems
    try:
        real_items = set()
        if share_dir and os.path.isdir(share_dir):
            real_items = set(os.listdir(share_dir))
    except Exception:
        real_items = set()
    for alias in virtual_dirs.keys():
        if alias in real_items:
            problems.append(
                f"虚拟目录别名「{alias}」与共享目录里的同名文件夹冲突，"
                "会导致列表里显示一个、点开却是另一个。请给虚拟目录换个别名。")
    return problems


def save_config(config_path: str, cfg) -> None:
    cfg = merge_with_defaults(cfg)
    root = ET.Element("config")

    def _write_field(parent, tag, value, comment_text):
        parent.append(ET.Comment(comment_text))
        el = ET.SubElement(parent, tag)
        if isinstance(value, bool):
            el.text = "true" if value else "false"
        elif isinstance(value, (int, float)):
            el.text = str(value)
        elif isinstance(value, (set, list)):
            el.text = ",".join(sorted(value))
        else:
            el.text = str(value) if value is not None else ""

    _write_field(root, "share_dir", cfg["share_dir"], "共享目录路径，默认 \".\" 表示当前目录，所有分享文件均基于此目录提供访问")
    _write_field(root, "port", cfg["port"], "服务监听端口号，默认 5000，建议范围 1024-65535")
    _write_field(root, "title", cfg["title"], "网站标题名称，默认 \"719WebF 文件分享站\"，将显示于网页标题栏")
    _write_field(root, "host", cfg["host"], "服务监听主机地址，默认 \"0.0.0.0\" 表示监听所有网卡接口，如需本地测试可改为 \"127.0.0.1\"")
    _write_field(root, "enable_https", cfg["enable_https"], "是否启用 HTTPS 加密通信，默认 false，启用后需同时配置 cert_file 和 key_file")
    _write_field(root, "cert_file", cfg["cert_file"], "SSL 证书文件路径，HTTPS 启用时必填，默认空字符串表示未配置")
    _write_field(root, "key_file", cfg["key_file"], "SSL 私钥文件路径，HTTPS 启用时必填，默认空字符串表示未配置")
    _write_field(root, "key_password", cfg["key_password"], "SSL 私钥保护密码，如私钥未加密可留空，默认空字符串")
    _write_field(root, "public_key_file", cfg["public_key_file"], "RSA 公钥文件路径，用于签名验证等加密场景，默认空字符串表示未配置")
    _write_field(root, "max_upload_mb", cfg["max_upload_mb"], "单文件上传最大体积（单位：MB），默认 100，超过此值的上传将被拒绝")
    _write_field(root, "behind_proxy", cfg["behind_proxy"], "服务是否运行在反向代理（如 Nginx）之后，默认 false，启用后将正确获取客户端真实 IP")

    paths = ET.SubElement(root, "paths")
    _write_field(paths, "lock_file", cfg["paths"]["lock_file"], "服务进程锁文件路径，用于防止多实例启动冲突，默认 \"server.lock\"")
    _write_field(paths, "log_dir", cfg["paths"]["log_dir"], "日志文件存储目录，默认 \"logs\"，存放运行日志与访问日志")
    _write_field(paths, "secret_file", cfg["paths"]["secret_file"], "会话密钥文件路径，用于加密 Flask Session Cookie，默认 \".secret\"，首次启动自动生成")
    _write_field(paths, "static_folder", cfg["paths"]["static_folder"], "静态资源文件夹路径，存放 CSS/JS/图片等前端资源，默认 \"static\"")
    _write_field(paths, "upload_temp_folder", cfg["paths"]["upload_temp_folder"], "上传临时文件夹，接收分片上传数据直至合并完成，默认 \"temp_uploads\"")
    _write_field(paths, "data_dir", cfg["paths"]["data_dir"], "持久化数据目录，存放聊天记录、临时文件索引等数据，默认 \"data\"")
    _write_field(paths, "temp_files_data", cfg["paths"]["temp_files_data"], "临时文件元数据存储文件名（JSON 格式），记录临时文件到期时间等信息，默认 \"temp_files.json\"")
    _write_field(paths, "chat_data", cfg["paths"]["chat_data"], "聊天消息持久化文件名（JSON 格式），默认 \"chat_data.json\"")

    p2p = ET.SubElement(root, "p2p")
    _write_field(p2p, "max_signal_queue", cfg["p2p"]["max_signal_queue"], "信令队列最大长度，每个对等方待发送信令消息的最大缓存数，默认 100")
    _write_field(p2p, "signal_timeout", cfg["p2p"]["signal_timeout"], "信令请求超时时间（秒），超时未收到响应则视为请求失败，默认 300")
    _write_field(p2p, "peer_timeout", cfg["p2p"]["peer_timeout"], "对等方心跳超时时间（秒），超时未收到心跳即清理该对等方连接，默认 30")

    file_transfer = ET.SubElement(root, "file_transfer")
    _write_field(file_transfer, "file_expire", cfg["file_transfer"]["file_expire"], "临时分享文件默认过期时间（秒），到期后自动删除，默认 3600（即 1 小时）")
    _write_field(file_transfer, "download_rate_limit", cfg["file_transfer"]["download_rate_limit"], "下载速率限制，单 IP 每窗口时间内最大下载次数，默认 10 次/窗口")
    _write_field(file_transfer, "download_rate_window", cfg["file_transfer"]["download_rate_window"], "下载速率限制统计窗口大小（秒），配合 download_rate_limit 使用，默认 60")

    waf = ET.SubElement(root, "waf")
    _write_field(waf, "rate_limit_per_minute", cfg["waf"]["rate_limit_per_minute"], "已验证客户端每分钟请求速率上限，普通正常访问使用，默认 120 次/分钟")
    _write_field(waf, "rate_limit_burst", cfg["waf"]["rate_limit_burst"], "已验证客户端突发请求峰值，允许短时间内超过限速的最大请求数，默认 200")
    _write_field(waf, "unverified_rate_limit", cfg["waf"]["unverified_rate_limit"], "未验证客户端每分钟请求速率上限，JS 挑战通过前使用更严格的限速，默认 30 次/分钟")
    _write_field(waf, "unverified_rate_burst", cfg["waf"]["unverified_rate_burst"], "未验证客户端突发请求峰值，默认 60")
    _write_field(waf, "file_rate_limit", cfg["waf"]["file_rate_limit"], "文件下载接口每分钟请求速率上限（按 IP 统计），默认 30 次/分钟")
    _write_field(waf, "file_rate_burst", cfg["waf"]["file_rate_burst"], "文件下载接口突发请求峰值，默认 60")
    _write_field(waf, "challenge_cookie", cfg["waf"]["challenge_cookie"], "WAF 验证通过后写入客户端的 Cookie 名称，默认 \"waf_verify\"")
    _write_field(waf, "challenge_expire", cfg["waf"]["challenge_expire"], "验证 Cookie 的有效期（秒），过期后需重新通过 JS 挑战，默认 86400（即 24 小时）")
    _write_field(waf, "js_challenge_difficulty", cfg["waf"]["js_challenge_difficulty"], "JS 挑战 PoW 难度值（0-16），值越大浏览器计算越耗时，推荐 6-12，默认 8")
    _write_field(waf, "verify_path", cfg["waf"]["verify_path"], "前端 JS 挑战结果提交验证的接口路径，默认 \"/waf_verify\"")
    _write_field(waf, "challenge_ip_ttl", cfg["waf"]["challenge_ip_ttl"], "每个 IP 的挑战令牌缓存 TTL（秒），超时后需重新生成挑战，默认 300")
    _write_field(waf, "bucket_cleanup_ttl", cfg["waf"]["bucket_cleanup_ttl"], "限流令牌桶清理 TTL（秒），长时间无活动的桶将被清理以节省内存，默认 300")
    _write_field(waf, "used_token_ttl", cfg["waf"]["used_token_ttl"], "已使用挑战令牌的保留时间（秒），防止重放攻击，默认 600")
    _write_field(waf, "challenge_token_ttl", cfg["waf"]["challenge_token_ttl"], "未使用挑战令牌的有效期（秒），超时令牌失效，默认 300")
    _write_field(waf, "max_used_tokens", cfg["waf"]["max_used_tokens"], "最大已使用令牌记录数，超出后按 FIFO 淘汰，防止内存溢出，默认 10000")
    _write_field(waf, "rate_limit_exempt_paths", cfg["waf"]["rate_limit_exempt_paths"], "免除限流的接口路径列表（逗号分隔），这些路径不触发 WAF 速率限制，默认 \"/p2p/signal/recv\"")

    security = ET.SubElement(root, "security")
    _write_field(security, "csrf_safe_methods", cfg["security"]["csrf_safe_methods"], "CSRF 保护豁免的安全 HTTP 方法集合（逗号分隔），这些方法不会被校验 CSRF Token，默认 \"GET,HEAD,OPTIONS\"")
    _write_field(security, "csrf_exempt_paths", cfg["security"]["csrf_exempt_paths"], "免除 CSRF 校验的接口路径列表（逗号分隔），如 WebSocket 入口等无法携带 Token 的接口，默认 \"/waf_verify,/ws/chat\"")

    system = ET.SubElement(root, "system")
    _write_field(system, "cleanup_interval_seconds", cfg["system"]["cleanup_interval_seconds"], "系统后台清理任务执行间隔（秒），周期性清理过期临时文件、过期聊天房间等，默认 60")

    monitor = ET.SubElement(root, "monitor")
    _write_field(monitor, "max_history_samples", cfg["monitor"]["max_history_samples"], "性能监控最大历史样本数量，用于绘制监控图表，默认 360 个样本点（每 10 秒一个约 1 小时数据）")
    _write_field(monitor, "sample_interval", cfg["monitor"]["sample_interval"], "性能监控样本采集间隔（秒），每隔多久采集一次 CPU/内存/请求量等数据，默认 10")

    chat_el = ET.SubElement(root, "chat")
    _write_field(chat_el, "max_messages", cfg["chat"]["max_messages"], "单聊天室最大消息保留条数（单位：条），超出后将删除最早的历史消息，建议 100-10000，默认 500")
    _write_field(chat_el, "room_timeout_hours", cfg["chat"]["room_timeout_hours"], "聊天室空闲超时时间（单位：小时），超过此时长无消息的房间将被自动回收，建议 1-168，默认 24")
    _write_field(chat_el, "message_rate", cfg["chat"]["message_rate"], "单用户发送消息速率上限（单位：条/窗口时间），建议 1-60，默认 10")
    _write_field(chat_el, "message_rate_window", cfg["chat"]["message_rate_window"], "消息速率统计窗口（单位：秒），配合 message_rate 使用，默认 60")
    _write_field(chat_el, "create_rate", cfg["chat"]["create_rate"], "单用户创建聊天室速率上限（单位：次/窗口时间），防止恶意创建房间，建议 1-60，默认 5")
    _write_field(chat_el, "create_rate_window", cfg["chat"]["create_rate_window"], "创建房间速率统计窗口（单位：秒），配合 create_rate 使用，默认 60")
    _write_field(chat_el, "http_timeout", cfg["chat"]["http_timeout"], "聊天接口 HTTP 请求超时时间（单位：秒），用于长轮询等场景，建议 10-120，默认 30")
    _write_field(chat_el, "max_message_length", cfg["chat"]["max_message_length"], "单条聊天消息最大字符长度，超过长度的消息将被拒绝，默认 2000")

    admin_el = ET.SubElement(root, "admin")
    admin_el.append(ET.Comment(
        "管理账号：用于删除不合适的聊天消息。enabled 控制是否启用（默认 false）。"
        "password_hash/totp_secret 请用 db_tool.py 生成，切勿手填明文密码。"
    ))
    admin_el.set("enabled", "true" if cfg["admin"].get("enabled") else "false")
    admin_el.set("username", str(cfg["admin"].get("username", "")))
    admin_el.set("password_hash", str(cfg["admin"].get("password_hash", "")))
    admin_el.set("totp_secret", str(cfg["admin"].get("totp_secret", "")))

    vdirs_el = ET.SubElement(root, "virtual_dirs")
    vdirs_el.append(ET.Comment(
        "虚拟目录：让某个文件夹以别名出现在列表中（映射到本机物理路径）。"
        "路径必须位于共享目录内（相对路径会被解析为共享目录下），否则将被忽略。"
        "示例：<dir name=\"docs\" path=\"sub/docs\" />"
    ))
    for _name, _path in sorted((cfg.get("virtual_dirs") or {}).items()):
        ET.SubElement(vdirs_el, "dir", {"name": str(_name), "path": str(_path)})

    hidden_el = ET.SubElement(root, "hidden_folders")
    hidden_el.append(ET.Comment(
        "隐藏文件夹：列表中将不显示这些名称的文件夹（输入完整名称匹配，仍可直接访问）。"
        "示例：<folder name=\"secret\" />"
    ))
    for _name in sorted(cfg.get("hidden_folders") or set()):
        ET.SubElement(hidden_el, "folder", {"name": str(_name)})

    names_el = ET.SubElement(root, "display_names")
    names_el.append(ET.Comment(
        "显示别名：列表中把某条目显示成另一个名字，不改动磁盘上的真实名称。"
        "示例：<item name=\"real_folder\" as=\"对外显示的名字\" />"
    ))
    for _real, _shown in sorted((cfg.get("display_names") or {}).items()):
        ET.SubElement(names_el, "item", {"name": str(_real), "as": str(_shown)})

    # 标题图节点：留空表示该页面继续显示原来的文字与符号
    titles_el = ET.SubElement(root, "nav_titles")
    titles_el.append(ET.Comment(
        "标题图：把整块标题文字换成一幅图片。name 可选 "
        + "/".join(NAV_ICON_PAGES.keys())
        + "；image 填本地图片的绝对路径，留空则不启用（显示原来的文字与符号）。"
    ))
    for _page in NAV_ICON_PAGES:
        _img = (cfg.get("nav_titles") or {}).get(_page, "")
        ET.SubElement(titles_el, "page", {"name": _page, "image": str(_img)})

    tree = ET.ElementTree(root)
    parent = os.path.dirname(os.path.abspath(config_path))
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception as e:
            raise IOError(f"创建配置目录失败: {parent} ({e})") from e
    tmp_path = config_path + ".tmp"
    try:
        with open(tmp_path, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)
        os.replace(tmp_path, config_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        logging.error(f"写入配置文件失败: {config_path}, 错误: {e}")
        raise IOError(f"写入配置文件 {config_path} 失败: {e}") from e


class SettingsGUI:
    def __init__(self, config_path: str, on_save_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                 on_restart_callback: Optional[Callable[[], None]] = None):
        self.config_path = config_path
        self.on_save_callback = on_save_callback
        self.on_restart_callback = on_restart_callback
        self.cfg = load_config(config_path)
        self._root = None
        self._created = False
        self.vars = {}
        self._tab_ids = {}
        self.advanced_mode = None
        self.notebook = None
        # 目录与命名：以内存副本编辑，保存时统一写回，避免误改导致配置丢失
        self.virtual_dirs = dict(self.cfg.get("virtual_dirs") or {})
        self.hidden_folders = set(self.cfg.get("hidden_folders") or set())
        self.display_names = dict(self.cfg.get("display_names") or {})

    def create_window(self):
        try:
            import tkinter as tk
            from tkinter import ttk, filedialog, messagebox
        except ImportError:
            logger.error("tkinter 不可用，无法创建设置窗口")
            return None

        self._root = tk.Tk()
        self._root.title(f"{APP_NAME} {APP_VER} 设置")
        self._root.geometry("720x620")
        self._root.resizable(True, True)
        self._root.configure(bg="#f0f0f0")
        self._created = True
        self._create_widgets()
        return self._root

    def _create_widgets(self):
        import tkinter as tk
        from tkinter import ttk

        tk = __import__("tkinter")
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        top_frame = ttk.Frame(self._root, padding=(15, 10))
        top_frame.pack(fill="x", side="top")

        title_label = ttk.Label(
            top_frame,
            text=f"{APP_NAME} {APP_VER} 配置管理",
            font=("微软雅黑", 12, "bold"),
        )
        title_label.pack(anchor="w")

        desc_label = ttk.Label(
            top_frame,
            text="基础 Tab 为常用设置，高级 Tab 含 WAF/安全/系统/监控等详细配置。保存后可直接选择立即重启生效，也可随时通过托盘菜单「重启服务」手动重启。",
            font=("微软雅黑", 9),
            foreground="#555555",
        )
        desc_label.pack(anchor="w", pady=(2, 6))

        self.advanced_mode = tk.BooleanVar(value=False)
        self.advanced_check = ttk.Checkbutton(
            top_frame,
            text="☑ 显示高级设置",
            variable=self.advanced_mode,
            command=self._on_toggle_advanced,
        )
        self.advanced_check.pack(anchor="w")

        self.notebook = ttk.Notebook(self._root)

        # 按钮栏用 side="bottom" 固定在窗口底部，并先于 notebook 布局。
        # pack 的排布顺序决定分配空间的优先级：先 bottom 后 expand，
        # 才能保证窗口变矮时按钮不会被内容挤掉。
        btn_frame = ttk.Frame(self._root, padding=(15, 10, 15, 12))
        btn_frame.pack(fill="x", side="bottom")
        ttk.Button(btn_frame, text="取消", command=self._destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btn_frame, text="保存", command=self._on_save).pack(side="right")
        # 关于入口放左下角，与右侧的保存/取消分开，避免误点
        ttk.Button(btn_frame, text="关于", command=self._show_about).pack(side="left")

        # notebook 在按钮栏之后 pack，剩余的垂直空间都归它
        self.notebook.pack(fill="both", expand=True, padx=15, pady=(5, 5))

        # 每个标签页都套一层带滚动条的容器：配置项较多时不会撑高窗口，
        # 也避免了"确定/取消被压缩到看不见"的问题。
        tabs = {}
        for name in ("基础", "聊天", "路径", "P2P", "文件传输", "WAF防护",
                     "安全设置", "系统设置", "监控设置", "目录与命名", "标题设置", "管理账号"):
            tabs[name] = self._make_scroll_tab(self.notebook, name)

        # _tab_ids 存 notebook 真正注册的那一层（outer），
        # 否则隐藏/切换标签页会作用在错误的控件上而完全失效。
        self._tab_ids = {name: outer for name, (outer, _inner) in tabs.items()}

        self._build_tab1_basic(tabs["基础"][1])
        self._build_tab2_chat(tabs["聊天"][1])
        self._build_tab3_paths(tabs["路径"][1])
        self._build_tab4_p2p(tabs["P2P"][1])
        self._build_tab5_file_transfer(tabs["文件传输"][1])
        self._build_tab6_waf(tabs["WAF防护"][1])
        self._build_tab7_security(tabs["安全设置"][1])
        self._build_tab8_system(tabs["系统设置"][1])
        self._build_tab9_monitor(tabs["监控设置"][1])
        self._build_tab10_paths_naming(tabs["目录与命名"][1])
        self._build_tab12_nav_titles(tabs["标题设置"][1])
        self._build_tab11_admin(tabs["管理账号"][1])

        self.reload_config()
        self._on_toggle_advanced()

        self._root.update_idletasks()
        self._root.lift()
        try:
            self._root.attributes("-topmost", True)
            self._root.after(120, lambda: self._root.attributes("-topmost", False))
        except Exception:
            pass
        try:
            self._root.focus_force()
        except Exception:
            pass
        try:
            if os.name == "nt":
                import ctypes
                try:
                    hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
                    if hwnd:
                        SW_RESTORE = 9
                        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                except Exception:
                    pass
        except Exception:
            pass
        self._root.after(80, self._focus_first_entry)

    def _make_scroll_tab(self, notebook, title):
        """创建一个可滚动的标签页。

        返回 (outer, inner)：
        - outer 是注册到 notebook 的那一层，用于隐藏/切换标签页；
        - inner 是真正摆放配置控件的容器，随内容自动增高并可滚动。

        配置项较多时窗口不会被迫撑高，用户可用滚轮/滚动条查看，
        底部的"保存/取消"按钮也始终完整可见。
        """
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        outer = ttk.Frame(notebook)
        notebook.add(outer, text=title)

        canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
        vbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=15)

        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(_event=None):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass

        def _on_canvas_configure(event):
            try:
                canvas.itemconfigure(window_id, width=event.width)
            except Exception:
                pass

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=vbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        # 鼠标滚轮支持（Windows / macOS / Linux 事件号不同）
        def _on_wheel(event):
            try:
                if getattr(event, "num", None) == 4:
                    delta = -1
                elif getattr(event, "num", None) == 5:
                    delta = 1
                else:
                    delta = -1 if event.delta > 0 else 1
                canvas.yview_scroll(delta, "units")
            except Exception:
                pass

        # 只在该标签页可见时接管滚轮，避免影响其它页面的滚动
        def _bind_wheel(_e=None):
            try:
                canvas.bind_all("<MouseWheel>", _on_wheel)
                canvas.bind_all("<Button-4>", _on_wheel)
                canvas.bind_all("<Button-5>", _on_wheel)
            except Exception:
                pass

        def _unbind_wheel(_e=None):
            try:
                canvas.unbind_all("<MouseWheel>")
                canvas.unbind_all("<Button-4>")
                canvas.unbind_all("<Button-5>")
            except Exception:
                pass

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)

        return outer, inner

    def _build_tab10_paths_naming(self, parent):
        """目录与命名：虚拟目录、隐藏项、显示别名（重命名）。"""
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        warn = ttk.Label(
            parent,
            text="在这里管理文件列表的显示方式。所有改动都只影响列表展示，不会真的移动或改名磁盘上的文件。",
            font=("微软雅黑", 9), foreground="#555555", wraplength=620, justify="left")
        warn.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        # ---------- 虚拟目录 ----------
        ttk.Label(parent, text="虚拟目录", font=("微软雅黑", 10, "bold")).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 2))
        ttk.Label(
            parent,
            text="让某个文件夹以别名出现在列表中，点击后指向你指定的物理路径。\n"
                 "路径可以位于共享目录之外（例如 D:\\资料、/mnt/data），方便把别处的\n"
                 "文件夹挂进来。访客始终只能在该目录内浏览，无法跳出到上层或其它位置。\n"
                 "相对路径按共享目录解析，也可直接填写绝对路径。",
            font=("微软雅黑", 8), foreground="#777777", justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w")

        vdir_box = ttk.Frame(parent)
        vdir_box.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 4))
        vdir_box.columnconfigure(0, weight=1)

        self._vdir_list = tk.Listbox(vdir_box, height=4, font=("微软雅黑", 9))
        self._vdir_list.grid(row=0, column=0, sticky="ew")
        vbar1 = ttk.Scrollbar(vdir_box, orient="vertical", command=self._vdir_list.yview)
        self._vdir_list.configure(yscrollcommand=vbar1.set)
        vbar1.grid(row=0, column=1, sticky="ns")

        vdir_btns = ttk.Frame(vdir_box)
        vdir_btns.grid(row=0, column=2, sticky="ns", padx=(8, 0))
        ttk.Button(vdir_btns, text="添加", width=10,
                   command=self._add_virtual_dir).pack(pady=(0, 4))
        ttk.Button(vdir_btns, text="删除", width=10,
                   command=self._remove_virtual_dir).pack()

        # ---------- 隐藏项目 ----------
        ttk.Label(parent, text="隐藏项目", font=("微软雅黑", 10, "bold")).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(14, 2))
        ttk.Label(
            parent,
            text="列表中将不显示这些名称的条目。文件仍然存在，知道网址时依然可以访问。",
            font=("微软雅黑", 8), foreground="#777777", justify="left").grid(
            row=5, column=0, columnspan=3, sticky="w")

        hidden_box = ttk.Frame(parent)
        hidden_box.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(6, 4))
        hidden_box.columnconfigure(0, weight=1)

        self._hidden_list = tk.Listbox(hidden_box, height=4, font=("微软雅黑", 9))
        self._hidden_list.grid(row=0, column=0, sticky="ew")
        vbar2 = ttk.Scrollbar(hidden_box, orient="vertical", command=self._hidden_list.yview)
        self._hidden_list.configure(yscrollcommand=vbar2.set)
        vbar2.grid(row=0, column=1, sticky="ns")

        hidden_btns = ttk.Frame(hidden_box)
        hidden_btns.grid(row=0, column=2, sticky="ns", padx=(8, 0))
        ttk.Button(hidden_btns, text="添加", width=10,
                   command=self._add_hidden).pack(pady=(0, 4))
        ttk.Button(hidden_btns, text="删除", width=10,
                   command=self._remove_hidden).pack()

        # ---------- 显示别名（重命名） ----------
        ttk.Label(parent, text="显示别名（重命名）", font=("微软雅黑", 10, "bold")).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(14, 2))
        ttk.Label(
            parent,
            text="把某个条目的显示名称换成另一个名字（不改动磁盘上的真实文件名）。",
            font=("微软雅黑", 8), foreground="#777777", justify="left").grid(
            row=8, column=0, columnspan=3, sticky="w")

        alias_box = ttk.Frame(parent)
        alias_box.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(6, 4))
        alias_box.columnconfigure(0, weight=1)

        self._alias_list = tk.Listbox(alias_box, height=4, font=("微软雅黑", 9))
        self._alias_list.grid(row=0, column=0, sticky="ew")
        vbar3 = ttk.Scrollbar(alias_box, orient="vertical", command=self._alias_list.yview)
        self._alias_list.configure(yscrollcommand=vbar3.set)
        vbar3.grid(row=0, column=1, sticky="ns")

        alias_btns = ttk.Frame(alias_box)
        alias_btns.grid(row=0, column=2, sticky="ns", padx=(8, 0))
        ttk.Button(alias_btns, text="添加", width=10,
                   command=self._add_alias).pack(pady=(0, 4))
        ttk.Button(alias_btns, text="删除", width=10,
                   command=self._remove_alias).pack()

    # ---------- 列表编辑器辅助 ----------
    def _refresh_listbox(self, listbox, items):
        listbox.delete(0, "end")
        for text in items:
            listbox.insert("end", text)

    def _parse_vdir_entry(self, text):
        """解析 "别名=路径" 输入，返回 (name, path) 或 (None, None)。"""
        if "=" not in text:
            return None, None
        name, path = text.split("=", 1)
        name, path = name.strip(), path.strip()
        if not name or not path:
            return None, None
        if "/" in name or "\\" in name or name in (".", ".."):
            return None, None
        return name, path

    def _add_virtual_dir(self):
        from tkinter import simpledialog, messagebox
        text = simpledialog.askstring(
            "添加虚拟目录",
            "格式：别名=路径\n\n"
            "别名：显示在列表中的名称（不能含 / 或 \\）\n"
            "路径：可填共享目录之外的绝对路径，也可填相对共享目录的路径\n\n"
            "示例：\n"
            "  文档库=public_docs\n"
            "  资料库=D:\\资料",
            parent=self._root)
        if not text:
            return
        name, path = self._parse_vdir_entry(text)
        if not name:
            messagebox.showwarning("格式有误", "请按「别名=路径」填写，且别名不能包含 / 或 \\。")
            return

        # 提示路径是否存在：不阻断保存，只让用户确认自己填对了
        share_dir = (self.vars["share_dir"].get() or ".").strip() or "."
        raw = path
        if not os.path.isabs(raw):
            raw = os.path.join(os.path.abspath(share_dir), raw)
        target = os.path.abspath(raw)
        if os.path.abspath(share_dir) == target:
            messagebox.showwarning("不能这样填", "虚拟目录不能指向共享目录本身，否则列表会重复。")
            return
        if not os.path.isdir(target):
            if not messagebox.askyesno(
                "目录还不存在",
                f"这个路径当前不是一个存在的文件夹：\n{target}\n\n"
                "仍然添加吗？（可以稍后建好文件夹，或点「取消」重新填写）"
            ):
                return

        self.virtual_dirs[name] = path
        self._refresh_listbox(self._vdir_list,
                              [f"{k}  →  {v}" for k, v in sorted(self.virtual_dirs.items())])

    def _remove_virtual_dir(self):
        sel = self._vdir_list.curselection()
        if not sel:
            return
        keys = sorted(self.virtual_dirs.keys())
        if sel[0] < len(keys):
            self.virtual_dirs.pop(keys[sel[0]], None)
        self._refresh_listbox(self._vdir_list,
                              [f"{k}  →  {v}" for k, v in sorted(self.virtual_dirs.items())])

    def _add_hidden(self):
        from tkinter import simpledialog, messagebox
        text = simpledialog.askstring(
            "添加隐藏项目",
            "输入要隐藏的名称（完整名称，区分大小写）\n\n示例：  secret",
            parent=self._root)
        if not text:
            return
        name = text.strip()
        if not name:
            return
        if "/" in name or "\\" in name:
            messagebox.showwarning("格式有误", "名称不能包含 / 或 \\。")
            return
        self.hidden_folders.add(name)
        self._refresh_listbox(self._hidden_list, sorted(self.hidden_folders))

    def _remove_hidden(self):
        sel = self._hidden_list.curselection()
        if not sel:
            return
        names = sorted(self.hidden_folders)
        if sel[0] < len(names):
            self.hidden_folders.discard(names[sel[0]])
        self._refresh_listbox(self._hidden_list, sorted(self.hidden_folders))

    def _add_alias(self):
        from tkinter import simpledialog, messagebox
        text = simpledialog.askstring(
            "添加显示别名",
            "格式：真实名称=显示名称\n\n"
            "真实名称：磁盘上实际的文件夹/文件名\n"
            "显示名称：列表中希望展示的名字\n\n"
            "示例：  public_docs=公开文档",
            parent=self._root)
        if not text or "=" not in text:
            if text:
                messagebox.showwarning("格式有误", "请按「真实名称=显示名称」填写。")
            return
        real, shown = text.split("=", 1)
        real, shown = real.strip(), shown.strip()
        if not real or not shown:
            messagebox.showwarning("格式有误", "两边都不能为空。")
            return
        # 显示名会被直接渲染在网页列表里，带上斜杠会让层级看起来错乱，
        # 所以这里禁掉路径分隔符和相对路径符号。
        bad, why = name_is_illegal(shown)
        if bad:
            messagebox.showwarning("显示名称不可用", why)
            return
        # 两个不同的真实项用同一个显示名，在列表里会完全无法区分，提前拦下
        dup = [k for k, v in self.display_names.items() if v == shown and k != real]
        if dup:
            messagebox.showwarning(
                "显示名称重复",
                f"显示名称「{shown}」已经被「{dup[0]}」使用了。\n"
                "请换一个名字，否则列表里会出现两个一模一样的条目。")
            return
        self.display_names[real] = shown
        self._refresh_listbox(self._alias_list,
                              [f"{k}  →  {v}" for k, v in sorted(self.display_names.items())])

    def _remove_alias(self):
        sel = self._alias_list.curselection()
        if not sel:
            return
        keys = sorted(self.display_names.keys())
        if sel[0] < len(keys):
            self.display_names.pop(keys[sel[0]], None)
        self._refresh_listbox(self._alias_list,
                              [f"{k}  →  {v}" for k, v in sorted(self.display_names.items())])

    def _build_tab12_nav_titles(self, parent):
        """标题设置：把各页面标题栏整块文字换成一张图片。"""
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        ttk.Label(
            parent,
            text="「标题图」把整块标题文字换成一张图片（配了就只显示图片）。",
            font=("微软雅黑", 9), foreground="#555555", wraplength=620, justify="left"
        ).grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 2))

        ttk.Label(
            parent,
            text="不配标题图的页面保持原样：首页显示网站标题文字，其它页面显示符号+文字。\n"
                 "点击网址顶部的标题区域都会回到首页（首页自身除外）。\n"
                 "建议使用宽扁比例的 PNG/JPG（如 480×96），高度会自动适配原标题区域。\n"
                 "改动需保存并重启服务后在网页上生效。",
            font=("微软雅黑", 8), foreground="#777777", justify="left"
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 10))

        # 每个页面的配置值都放一份在这里，保存时统一收集
        self.nav_title_vars = {}
        self.nav_title_labels = {}  # 页面标识 -> 标题图预览 Label
        self._nav_title_photos = {}

        row = 2
        for page, page_name in NAV_ICON_PAGES.items():
            title_var = tk.StringVar()
            self.nav_title_vars[page] = title_var

            box = ttk.LabelFrame(parent, text=f" {page_name} ", padding=(10, 6, 10, 8))
            box.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(0, 8))
            box.columnconfigure(3, weight=0)

            ttk.Label(box, text="标题图", font=("微软雅黑", 9), width=7).grid(
                row=0, column=0, sticky="w", pady=3)

            title_preview = tk.Label(box, height=48, relief="solid", borderwidth=1,
                                     background="#ffffff")
            title_preview.grid(row=0, column=1, sticky="w", padx=(0, 10), pady=3)
            self.nav_title_labels[page] = title_preview

            title_hint = ttk.Label(box, text="未启用（保持原文字）",
                                   font=("微软雅黑", 8), foreground="#999999", width=20)
            title_hint.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=3)
            setattr(self, f"_nav_title_hint_{page}", title_hint)

            title_btns = ttk.Frame(box)
            title_btns.grid(row=0, column=3, sticky="w", pady=3)
            ttk.Button(title_btns, text="选图片", width=9,
                       command=lambda p=page: self._pick_nav_title(p)).pack(side="left", padx=(0, 4))
            ttk.Button(title_btns, text="清除", width=7,
                       command=lambda p=page: self._clear_nav_title(p)).pack(side="left")

            row += 1

        btns_bottom = ttk.Frame(parent)
        btns_bottom.grid(row=row, column=0, columnspan=4, sticky="w", pady=(6, 4))
        ttk.Button(btns_bottom, text="全部恢复默认",
                   command=self._reset_all_nav_titles).pack(side="left")
        ttk.Label(btns_bottom, text="（所有页面标题图全部关闭，回到原文字）",
                  font=("微软雅黑", 8), foreground="#777777").pack(side="left", padx=(8, 0))

    # ---------------- 标题图 ----------------

    def _load_nav_title_preview(self, page, value):
        """把标题图画到预览位上。标题图通常很宽，这里等比缩到预览框内。"""
        import tkinter as tk
        label = self.nav_title_labels.get(page)
        hint = getattr(self, f"_nav_title_hint_{page}", None)
        if label is None:
            return
        value = (value or "").strip()
        photo = None
        if value and os.path.isfile(value):
            try:
                img = tk.PhotoImage(file=value)
                # 预览框宽度有限，按比例缩小：取宽高比例中更"缩得多"的那一边
                max_w, max_h = 150, 46
                factor = 1
                while (img.width() // factor > max_w) or (img.height() // factor > max_h):
                    factor += 1
                    if factor > 64:
                        break
                if factor > 1:
                    img = img.subsample(factor)
                photo = img
            except Exception:
                photo = None
        self._nav_title_photos[page] = photo
        try:
            if photo:
                label.configure(image=photo, text="", width=0)
            else:
                label.configure(image="", text="（无）" if value else "", width=18)
        except Exception:
            pass
        if hint is not None:
            try:
                if value:
                    name = os.path.basename(value)
                    hint.configure(text=name if len(name) <= 18 else name[:15] + "...",
                                   foreground="#2f7d32")
                else:
                    hint.configure(text="未启用（保持原文字）", foreground="#999999")
            except Exception:
                pass

    def _pick_nav_title(self, page):
        from tkinter import filedialog, messagebox
        path = filedialog.askopenfilename(
            title=f"为「{NAV_ICON_PAGES[page]}」选择标题图",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"), ("所有文件", "*.*")],
        )
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
            messagebox.showwarning("格式不支持", "标题图请使用 PNG / JPG / GIF / WEBP / BMP 格式。")
            return
        try:
            if os.path.getsize(path) > 2 * 1024 * 1024:
                messagebox.showwarning("图片过大", "标题图请使用 2MB 以内的图片。")
                return
        except OSError as e:
            messagebox.showwarning("无法读取", f"读取图片失败：{e}")
            return
        self.nav_title_vars[page].set(path)
        self._load_nav_title_preview(page, path)

    def _clear_nav_title(self, page):
        self.nav_title_vars[page].set("")
        self._load_nav_title_preview(page, "")

    def _reset_all_nav_titles(self):
        """一键恢复：所有页面标题图关闭，回到原来的文字。"""
        for page in NAV_ICON_PAGES:
            self.nav_title_vars[page].set("")
            self._load_nav_title_preview(page, "")

    def _refresh_nav_title_widgets(self):
        """按当前配置刷新标题图预览（加载配置时调用）。"""
        titles = dict(self.cfg.get("nav_titles") or {})
        for page in NAV_ICON_PAGES:
            tval = titles.get(page, "")
            self.nav_title_vars[page].set(tval)
            self._load_nav_title_preview(page, tval)

    def _build_tab11_admin(self, parent):
        """管理账号：启用开关、账号密码、动态验证码生成，保存时直接写入配置文件。"""
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        info = ttk.Label(
            parent,
            text="管理账号用于删除聊天室中的问题消息。密码与动态验证码可以「二选一」或「两个都要」，\n"
                 "未填写的验证方式不会参与登录校验。在这里设置后会直接写入配置文件，无需手工编辑。",
            font=("微软雅黑", 9), foreground="#555555", wraplength=620, justify="left")
        info.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        self.vars["admin_enabled"] = tk.BooleanVar()
        self._grid_field(parent, 1, "启用管理功能",
                         ttk.Checkbutton(parent, variable=self.vars["admin_enabled"],
                                         text="勾选后聊天室页面会出现管理员登录入口",
                                         command=self._refresh_admin_status_text),
                         "关闭时聊天室不会显示任何管理入口")

        self.vars["admin_username"] = tk.StringVar()
        username_entry = ttk.Entry(parent, textvariable=self.vars["admin_username"], width=32)
        username_entry.bind("<KeyRelease>", lambda _e: self._refresh_admin_status_text())
        self._grid_field(parent, 2, "管理员用户名", username_entry,
                         "登录时填写的用户名")

        # ---- 密码 ----
        ttk.Separator(parent, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=10)
        ttk.Label(parent, text="密码验证方式", font=("微软雅黑", 10, "bold")).grid(
            row=4, column=0, columnspan=3, sticky="w")

        self.vars["admin_use_password"] = tk.BooleanVar()
        ttk.Checkbutton(parent, variable=self.vars["admin_use_password"],
                        text="启用密码登录",
                        command=self._refresh_admin_status_text).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(4, 2))

        self.vars["admin_password"] = tk.StringVar()
        self._grid_field(parent, 6, "设置新密码",
                         ttk.Entry(parent, textvariable=self.vars["admin_password"],
                                   width=32, show="*"),
                         "留空表示不修改；填写后保存时自动加密写入")

        self.vars["admin_password_confirm"] = tk.StringVar()
        self._grid_field(parent, 7, "确认新密码",
                         ttk.Entry(parent, textvariable=self.vars["admin_password_confirm"],
                                   width=32, show="*"),
                         "两次输入需一致")

        # ---- 动态验证码 ----
        ttk.Separator(parent, orient="horizontal").grid(
            row=8, column=0, columnspan=3, sticky="ew", pady=10)
        ttk.Label(parent, text="动态验证码（TOTP）", font=("微软雅黑", 10, "bold")).grid(
            row=9, column=0, columnspan=3, sticky="w")

        self.vars["admin_use_totp"] = tk.BooleanVar()
        ttk.Checkbutton(parent, variable=self.vars["admin_use_totp"],
                        text="启用动态验证码登录",
                        command=self._refresh_admin_status_text).grid(
            row=10, column=0, columnspan=3, sticky="w", pady=(4, 2))

        totp_frame = ttk.Frame(parent)
        totp_btns = ttk.Frame(totp_frame)
        totp_btns.pack(anchor="w")
        ttk.Button(totp_btns, text="生成新密钥并显示二维码", width=24,
                   command=self._generate_totp).pack(side="left")
        ttk.Button(totp_btns, text="清除密钥", width=12,
                   command=self._clear_totp).pack(side="left", padx=(8, 0))
        self._grid_field(parent, 11, "TOTP 密钥管理", totp_frame,
                         "生成后用手机验证器 App 扫码绑定即可")

        self.vars["admin_totp_secret"] = tk.StringVar()
        ttk.Entry(parent, textvariable=self.vars["admin_totp_secret"],
                  width=40, state="readonly").grid(
            row=12, column=1, sticky="ew", pady=4)

        self.vars["admin_totp_status"] = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.vars["admin_totp_status"],
                  font=("微软雅黑", 9), foreground="#0066cc", wraplength=600,
                  justify="left").grid(row=13, column=1, sticky="w")

        # ---- 当前状态 ----
        ttk.Separator(parent, orient="horizontal").grid(
            row=14, column=0, columnspan=3, sticky="ew", pady=10)
        self.vars["admin_status_text"] = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.vars["admin_status_text"],
                  font=("微软雅黑", 9), foreground="#555555", justify="left",
                  wraplength=620).grid(row=15, column=0, columnspan=3, sticky="w")

    def _generate_totp(self):
        """生成新的 TOTP 密钥并展示二维码（需 pyotp / qrcode）。"""
        from tkinter import messagebox
        try:
            import pyotp
        except ImportError:
            messagebox.showerror(
                "缺少依赖",
                "生成动态验证码需要 pyotp 组件。\n请先执行：pip install pyotp qrcode")
            return

        secret = pyotp.random_base32()
        self.vars["admin_totp_secret"].set(secret)
        self.vars["admin_use_totp"].set(True)
        username = self.vars["admin_username"].get().strip() or "admin"

        uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=APP_NAME)
        shown = False
        try:
            import qrcode
            # 显示一个二维码窗口，便于手机扫码
            import tkinter as tk
            win = tk.Toplevel(self._root)
            win.title("扫码绑定动态验证码")
            win.configure(bg="white")

            qr = qrcode.QRCode(border=2, box_size=6)
            qr.add_data(uri)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            img_tk = None
            try:
                from PIL import ImageTk
                img_tk = ImageTk.PhotoImage(img.get_image() if hasattr(img, "get_image") else img)
            except Exception:
                img_tk = None

            if img_tk is not None:
                lbl = tk.Label(win, image=img_tk, bg="white")
                lbl.image = img_tk  # 防止被垃圾回收
                lbl.pack(padx=16, pady=(16, 6))
            else:
                # 退化为文本二维码
                import io
                buf = io.StringIO()
                qr.print_ascii(out=buf, invert=True)
                txt = tk.Text(win, width=60, height=22, font=("Consolas", 7),
                              bg="white", relief="flat")
                txt.insert("1.0", buf.getvalue())
                txt.configure(state="disabled")
                txt.pack(padx=8, pady=8)
                shown = True

            tk.Label(win, text=f"用验证器 App 扫描上方二维码\n用户名：{username}",
                     font=("微软雅黑", 10), bg="white").pack(pady=(0, 4))
            tk.Label(win, text=f"密钥（手动输入时使用）：{secret}",
                     font=("微软雅黑", 8), fg="#666666", bg="white").pack(pady=(0, 12))
            ttk2 = __import__("tkinter.ttk", fromlist=["ttk"])
            ttk2.Button(win, text="我已扫码完成", command=win.destroy).pack(pady=(0, 14))
            shown = True
            self.vars["admin_totp_status"].set("已生成新密钥，请用验证器扫码绑定，然后点击「保存」生效。")
        except Exception as e:
            logger.warning(f"二维码展示失败: {e}")

        if not shown:
            self.vars["admin_totp_status"].set(
                f"已生成新密钥：{secret}\n请手动填入验证器 App，然后点击「保存」生效。")
        else:
            messagebox.showinfo(
                "密钥已生成",
                f"新的动态验证码密钥：\n\n{secret}\n\n"
                f"绑定链接：\n{uri}\n\n"
                "请用验证器扫码（或手动输入密钥）完成绑定，然后点击「保存」。")

    def _clear_totp(self):
        self.vars["admin_totp_secret"].set("")
        self.vars["admin_use_totp"].set(False)
        self.vars["admin_totp_status"].set("已清除动态验证码密钥，保存后将只能用密码登录。")

    def _grid_field(self, parent, row, label_text, widget, hint=None):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])
        lbl_frame = ttk.Frame(parent)
        lbl_frame.grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=4)
        ttk.Label(lbl_frame, text=label_text, font=("微软雅黑", 10)).pack(anchor="w")
        if hint:
            ttk.Label(lbl_frame, text=hint, font=("微软雅黑", 8), foreground="#777777").pack(anchor="w")
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)

    def _build_tab1_basic(self, parent):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        self.vars["share_dir"] = tk.StringVar()
        share_frame = ttk.Frame(parent)
        share_entry = ttk.Entry(share_frame, textvariable=self.vars["share_dir"], width=40)
        share_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(share_frame, text="浏览...", command=self._select_dir, width=8).pack(side="left", padx=(6, 0))
        self._grid_field(parent, 0, "共享目录路径", share_frame, "所有分享文件均基于此目录提供访问")

        self.vars["port"] = tk.IntVar()
        port_spin = ttk.Spinbox(parent, from_=1, to=65535, textvariable=self.vars["port"], width=15)
        self._grid_field(parent, 1, "服务监听端口", port_spin, "1-65535，建议 1024-65535")

        self.vars["title"] = tk.StringVar()
        self._grid_field(parent, 2, "网站标题名称", ttk.Entry(parent, textvariable=self.vars["title"], width=40), "显示于网页标题栏")

        self.vars["host"] = tk.StringVar()
        self._grid_field(parent, 3, "绑定主机地址", ttk.Entry(parent, textvariable=self.vars["host"], width=40), "0.0.0.0=监听所有网卡，127.0.0.1=仅本地")

        self.vars["enable_https"] = tk.BooleanVar()
        self._grid_field(parent, 4, "启用 HTTPS 加密", ttk.Checkbutton(parent, variable=self.vars["enable_https"], text="启用后需同时配置证书和密钥文件"), "启用 HTTPS (SSL/TLS) 加密通信")

        self.vars["cert_file"] = tk.StringVar()
        cert_frame = ttk.Frame(parent)
        cert_entry = ttk.Entry(cert_frame, textvariable=self.vars["cert_file"], width=40)
        cert_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(cert_frame, text="浏览...", command=self._select_cert_file, width=8).pack(side="left", padx=(6, 0))
        self._grid_field(parent, 5, "SSL 证书文件路径", cert_frame, ".crt / .pem 格式，HTTPS 启用时必填")

        self.vars["key_file"] = tk.StringVar()
        key_frame = ttk.Frame(parent)
        key_entry = ttk.Entry(key_frame, textvariable=self.vars["key_file"], width=40)
        key_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(key_frame, text="浏览...", command=self._select_key_file, width=8).pack(side="left", padx=(6, 0))
        self._grid_field(parent, 6, "SSL 私钥文件路径", key_frame, ".key / .pem 格式，HTTPS 启用时必填")

        self.vars["key_password"] = tk.StringVar()
        self._grid_field(parent, 7, "SSL 私钥保护密码", ttk.Entry(parent, textvariable=self.vars["key_password"], width=40, show="*"), "私钥未加密可留空")

        self.vars["public_key_file"] = tk.StringVar()
        pub_frame = ttk.Frame(parent)
        pub_entry = ttk.Entry(pub_frame, textvariable=self.vars["public_key_file"], width=40)
        pub_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(pub_frame, text="浏览...", command=self._select_pub_key_file, width=8).pack(side="left", padx=(6, 0))
        self._grid_field(parent, 8, "RSA 公钥文件路径", pub_frame, "用于签名验证等加密场景")

        self.vars["max_upload_mb"] = tk.IntVar()
        self._grid_field(parent, 9, "单文件上传最大体积 (MB)", ttk.Spinbox(parent, from_=1, to=100000, textvariable=self.vars["max_upload_mb"], width=15), "1-100000，超过此值的上传将被拒绝")

        self.vars["behind_proxy"] = tk.BooleanVar()
        self._grid_field(parent, 10, "运行在反向代理之后", ttk.Checkbutton(parent, variable=self.vars["behind_proxy"], text="启用后将正确获取客户端真实 IP"), "服务是否位于 Nginx 等反向代理之后")

    def _build_tab2_chat(self, parent):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        fields = [
            ("chat_max_messages", "单聊天室最大消息保留条数", 10, 10000, "超出后删除最早的历史消息，建议 100-10000"),
            ("chat_room_timeout_hours", "聊天室空闲超时 (小时)", 1, 720, "超过此时长无消息的房间自动回收"),
            ("chat_message_rate", "单用户消息速率上限 (条/窗口)", 1, 10000, "窗口时间内最大发送消息数"),
            ("chat_message_rate_window", "消息速率统计窗口 (秒)", 1, 86400, "配合消息速率上限使用"),
            ("chat_create_rate", "单用户创建房间速率 (次/窗口)", 1, 10000, "防止恶意创建大量房间"),
            ("chat_create_rate_window", "创建房间速率窗口 (秒)", 1, 86400, "配合创建房间速率使用"),
            ("chat_http_timeout", "聊天 HTTP 请求超时 (秒)", 1, 600, "用于长轮询等场景，建议 10-120"),
            ("chat_max_message_length", "单条消息最大字符长度", 200, 20000, "超过长度的消息将被拒绝"),
        ]
        for i, (key, label, fmin, fmax, hint) in enumerate(fields):
            self.vars[key] = tk.IntVar()
            self._grid_field(parent, i, label, ttk.Spinbox(parent, from_=fmin, to=fmax, textvariable=self.vars[key], width=20), hint)

    def _build_tab3_paths(self, parent):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        fields = [
            ("paths_lock_file", "服务进程锁文件", "防止多实例启动冲突"),
            ("paths_log_dir", "日志文件存储目录", "存放运行日志与访问日志"),
            ("paths_secret_file", "会话密钥文件", "加密 Flask Session Cookie，首次启动自动生成"),
            ("paths_static_folder", "静态资源文件夹", "存放 CSS/JS/图片等前端资源"),
            ("paths_upload_temp_folder", "上传临时文件夹", "接收分片上传直至合并完成"),
            ("paths_data_dir", "持久化数据目录", "存放聊天记录、临时文件索引等"),
            ("paths_temp_files_data", "临时文件元数据文件名", "JSON 格式，记录临时文件到期时间"),
            ("paths_chat_data", "聊天消息持久化文件名", "JSON 格式"),
        ]
        for i, (key, label, hint) in enumerate(fields):
            self.vars[key] = tk.StringVar()
            self._grid_field(parent, i, label, ttk.Entry(parent, textvariable=self.vars[key], width=40), hint)

    def _build_tab4_p2p(self, parent):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        fields = [
            ("p2p_max_signal_queue", "信令队列最大长度", 10, 10000, "每个对等方待发送信令消息的最大缓存数"),
            ("p2p_signal_timeout", "信令请求超时 (秒)", 30, 3600, "超时未收到响应则视为请求失败"),
            ("p2p_peer_timeout", "对等方心跳超时 (秒)", 5, 600, "超时未收到心跳即清理该对等方连接"),
        ]
        for i, (key, label, fmin, fmax, hint) in enumerate(fields):
            self.vars[key] = tk.IntVar()
            self._grid_field(parent, i, label, ttk.Spinbox(parent, from_=fmin, to=fmax, textvariable=self.vars[key], width=20), hint)

    def _build_tab5_file_transfer(self, parent):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        fields = [
            ("ft_file_expire", "临时分享文件过期时间 (秒)", 60, 86400, "到期后自动删除，默认 3600=1小时"),
            ("ft_download_rate_limit", "下载速率限制 (次/窗口)", 1, 10000, "单 IP 每窗口时间内最大下载次数"),
            ("ft_download_rate_window", "下载速率统计窗口 (秒)", 1, 86400, "配合下载速率限制使用"),
        ]
        for i, (key, label, fmin, fmax, hint) in enumerate(fields):
            self.vars[key] = tk.IntVar()
            self._grid_field(parent, i, label, ttk.Spinbox(parent, from_=fmin, to=fmax, textvariable=self.vars[key], width=20), hint)

    def _build_tab6_waf(self, parent):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        warn = ttk.Label(parent, text="⚠ 警告：WAF 参数直接影响站点安全性，修改不当可能导致站点被攻击或正常用户被拦截。建议仅在了解各参数含义后调整。",
                         font=("微软雅黑", 9), foreground="#cc5500", wraplength=600, justify="left")
        warn.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        int_fields = [
            ("waf_rate_limit_per_minute", "已验证客户端每分钟请求速率", 20, 1000, "已验证正常用户使用，默认 120"),
            ("waf_rate_limit_burst", "已验证客户端突发请求峰值", 20, 2000, "允许短时间超过限速的最大请求数"),
            ("waf_unverified_rate_limit", "未验证客户端每分钟速率", 1, 1000, "JS 挑战通过前使用更严格的限速"),
            ("waf_unverified_rate_burst", "未验证客户端突发峰值", 2, 2000, ""),
            ("waf_file_rate_limit", "文件下载接口每分钟速率", 1, 1000, "按 IP 统计，默认 30"),
            ("waf_file_rate_burst", "文件下载接口突发峰值", 2, 2000, ""),
            ("waf_challenge_expire", "验证 Cookie 有效期 (秒)", 3600, 604800, "过期后需重新通过 JS 挑战，默认 86400=24h"),
            ("waf_js_challenge_difficulty", "JS 挑战 PoW 难度", 1, 16, "值越大浏览器计算越耗时，推荐 6-12"),
            ("waf_challenge_ip_ttl", "挑战令牌缓存 TTL (秒)", 60, 3600, "每个 IP 的挑战令牌缓存超时"),
            ("waf_bucket_cleanup_ttl", "限流令牌桶清理 TTL (秒)", 60, 3600, "长时间无活动的桶将被清理"),
            ("waf_used_token_ttl", "已使用令牌保留时间 (秒)", 300, 3600, "防止重放攻击"),
            ("waf_challenge_token_ttl", "未使用令牌有效期 (秒)", 60, 1800, "超时令牌失效"),
            ("waf_max_used_tokens", "最大已使用令牌记录数", 1000, 1000000, "超出后按 FIFO 淘汰，防内存溢出"),
        ]
        row = 1
        for (key, label, fmin, fmax, hint) in int_fields:
            self.vars[key] = tk.IntVar()
            self._grid_field(parent, row, label, ttk.Spinbox(parent, from_=fmin, to=fmax, textvariable=self.vars[key], width=20), hint)
            row += 1

        self.vars["waf_challenge_cookie"] = tk.StringVar()
        self._grid_field(parent, row, "验证 Cookie 名称", ttk.Entry(parent, textvariable=self.vars["waf_challenge_cookie"], width=40), "WAF 验证通过后写入客户端的 Cookie 名")
        row += 1

        self.vars["waf_verify_path"] = tk.StringVar()
        self._grid_field(parent, row, "前端验证接口路径", ttk.Entry(parent, textvariable=self.vars["waf_verify_path"], width=40), "JS 挑战结果提交验证的接口路径")
        row += 1

        self.vars["waf_rate_limit_exempt_paths"] = tk.StringVar()
        exempt_frame = ttk.Frame(parent)
        ttk.Entry(exempt_frame, textvariable=self.vars["waf_rate_limit_exempt_paths"], width=40).pack(anchor="w", fill="x")
        ttk.Label(exempt_frame, text="多个值用英文逗号分隔，如：/p2p/signal/recv,/health", font=("微软雅黑", 8), foreground="#777777").pack(anchor="w")
        self._grid_field(parent, row, "免除限流的接口路径列表", exempt_frame, "这些路径不触发 WAF 速率限制")
        row += 1

    def _build_tab7_security(self, parent):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        warn = ttk.Label(parent, text="⚠ 警告：CSRF 安全参数影响站点跨站防护。免除列表过宽可能导致 CSRF 攻击。",
                         font=("微软雅黑", 9), foreground="#cc5500", wraplength=600, justify="left")
        warn.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        self.vars["sec_csrf_safe_methods"] = tk.StringVar()
        sm_frame = ttk.Frame(parent)
        ttk.Entry(sm_frame, textvariable=self.vars["sec_csrf_safe_methods"], width=40).pack(anchor="w", fill="x")
        ttk.Label(sm_frame, text="多个值用英文逗号分隔，如：GET,HEAD,OPTIONS", font=("微软雅黑", 8), foreground="#777777").pack(anchor="w")
        self._grid_field(parent, 1, "CSRF 豁免安全 HTTP 方法", sm_frame, "这些方法不会被校验 CSRF Token")

        self.vars["sec_csrf_exempt_paths"] = tk.StringVar()
        ep_frame = ttk.Frame(parent)
        ttk.Entry(ep_frame, textvariable=self.vars["sec_csrf_exempt_paths"], width=40).pack(anchor="w", fill="x")
        ttk.Label(ep_frame, text="多个值用英文逗号分隔，如：/waf_verify,/ws/chat", font=("微软雅黑", 8), foreground="#777777").pack(anchor="w")
        self._grid_field(parent, 2, "免除 CSRF 校验的接口路径", ep_frame, "WebSocket 入口等无法携带 Token 的接口")

    def _build_tab8_system(self, parent):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        warn = ttk.Label(parent, text="⚠ 警告：清理间隔过短会增加 CPU 开销，过长会导致过期资源积累。",
                         font=("微软雅黑", 9), foreground="#cc5500", wraplength=600, justify="left")
        warn.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        self.vars["sys_cleanup_interval_seconds"] = tk.IntVar()
        self._grid_field(parent, 1, "后台清理任务执行间隔 (秒)",
                         ttk.Spinbox(parent, from_=10, to=3600, textvariable=self.vars["sys_cleanup_interval_seconds"], width=20),
                         "周期性清理过期临时文件、过期聊天房间等，默认 60")

    def _build_tab9_monitor(self, parent):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])

        warn = ttk.Label(parent, text="⚠ 警告：样本间隔过小或历史样本过多会增加内存消耗。默认 10 秒/个样本 × 360 个 ≈ 1 小时数据。",
                         font=("微软雅黑", 9), foreground="#cc5500", wraplength=600, justify="left")
        warn.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        self.vars["mon_max_history_samples"] = tk.IntVar()
        self._grid_field(parent, 1, "最大历史样本数量",
                         ttk.Spinbox(parent, from_=60, to=86400, textvariable=self.vars["mon_max_history_samples"], width=20),
                         "用于绘制监控图表的样本点数")

        self.vars["mon_sample_interval"] = tk.IntVar()
        self._grid_field(parent, 2, "样本采集间隔 (秒)",
                         ttk.Spinbox(parent, from_=5, to=300, textvariable=self.vars["mon_sample_interval"], width=20),
                         "每隔多久采集一次 CPU/内存/请求量等数据")

    def _on_toggle_advanced(self):
        show_advanced = self.advanced_mode.get() if self.advanced_mode else False
        advanced_tabs = ["WAF防护", "安全设置", "系统设置", "监控设置"]
        # 默认停留在常用标签页，避免打开时落在高级页上让人困惑
        default_tab = self._tab_ids.get("基础")

        # 隐藏高级标签页后再重建选项卡顺序：tkinter 不允许把隐藏页放在当前选中页
        current = None
        try:
            current = self.notebook.select()
        except Exception:
            current = None
        if current:
            try:
                current_name = self.notebook.tab(current, "text")
            except Exception:
                current_name = None
            if current_name in advanced_tabs and not show_advanced:
                try:
                    self.notebook.select(default_tab)
                except Exception:
                    pass

        for tab_name in advanced_tabs:
            tab_id = self._tab_ids[tab_name]
            if show_advanced:
                try:
                    self.notebook.tab(tab_id, state="normal")
                except Exception:
                    try:
                        self.notebook.add(tab_id, text=tab_name)
                    except Exception:
                        pass
            else:
                try:
                    self.notebook.tab(tab_id, state="hidden")
                except Exception:
                    try:
                        self.notebook.hide(tab_id)
                    except Exception:
                        pass

    def _find_first_input(self, widget):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])
        try:
            if not widget.winfo_exists():
                return None
        except Exception:
            return None
        class_name = widget.winfo_class()
        if class_name in ("Entry", "TEntry", "Spinbox", "TSpinbox"):
            try:
                state = str(widget.cget("state")).lower()
                if state not in ("disabled", "readonly"):
                    return widget
            except Exception:
                return widget
        try:
            children = widget.winfo_children()
        except Exception:
            return None
        for child in children:
            found = self._find_first_input(child)
            if found is not None:
                return found
        return None

    def _focus_first_entry(self):
        try:
            if not self._root or not self._root.winfo_exists():
                return
        except Exception:
            return
        target = None
        try:
            current_tab = self.notebook.select() if self.notebook else None
        except Exception:
            current_tab = None
        if current_tab:
            try:
                tab_widget = self._root.nametowidget(current_tab)
                target = self._find_first_input(tab_widget)
            except Exception:
                target = None
        if target is None:
            target = self._find_first_input(self._root)
        if target is not None:
            try:
                target.focus_force()
            except Exception:
                try:
                    target.focus_set()
                except Exception:
                    pass
            try:
                target.icursor("end")
            except Exception:
                pass
            try:
                target.select_range(0, "end")
            except Exception:
                pass
        try:
            self._root.focus_force()
        except Exception:
            pass

    def _safe_focus(self, widget):
        try:
            if widget.winfo_exists():
                widget.focus_force()
        except Exception:
            pass

    def reload_config(self):
        import tkinter as tk
        cfg = self.cfg

        self.vars["share_dir"].set(cfg["share_dir"])
        self.vars["port"].set(cfg["port"])
        self.vars["title"].set(cfg["title"])
        self.vars["host"].set(cfg["host"])
        self.vars["enable_https"].set(cfg["enable_https"])
        self.vars["cert_file"].set(cfg["cert_file"])
        self.vars["key_file"].set(cfg["key_file"])
        self.vars["key_password"].set(cfg["key_password"])
        self.vars["public_key_file"].set(cfg["public_key_file"])
        self.vars["max_upload_mb"].set(cfg["max_upload_mb"])
        self.vars["behind_proxy"].set(cfg["behind_proxy"])

        for f in ["max_messages", "room_timeout_hours", "message_rate", "message_rate_window",
                  "create_rate", "create_rate_window", "http_timeout", "max_message_length"]:
            self.vars[f"chat_{f}"].set(cfg["chat"][f])

        for f in ["lock_file", "log_dir", "secret_file", "static_folder",
                  "upload_temp_folder", "data_dir", "temp_files_data", "chat_data"]:
            self.vars[f"paths_{f}"].set(cfg["paths"][f])

        for f in ["max_signal_queue", "signal_timeout", "peer_timeout"]:
            self.vars[f"p2p_{f}"].set(cfg["p2p"][f])

        for f in ["file_expire", "download_rate_limit", "download_rate_window"]:
            self.vars[f"ft_{f}"].set(cfg["file_transfer"][f])

        for f in ["rate_limit_per_minute", "rate_limit_burst", "unverified_rate_limit",
                  "unverified_rate_burst", "file_rate_limit", "file_rate_burst",
                  "challenge_expire", "js_challenge_difficulty", "challenge_ip_ttl",
                  "bucket_cleanup_ttl", "used_token_ttl", "challenge_token_ttl", "max_used_tokens"]:
            self.vars[f"waf_{f}"].set(cfg["waf"][f])
        self.vars["waf_challenge_cookie"].set(cfg["waf"]["challenge_cookie"])
        self.vars["waf_verify_path"].set(cfg["waf"]["verify_path"])
        self.vars["waf_rate_limit_exempt_paths"].set(", ".join(sorted(cfg["waf"]["rate_limit_exempt_paths"])))

        self.vars["sec_csrf_safe_methods"].set(", ".join(sorted(cfg["security"]["csrf_safe_methods"])))
        self.vars["sec_csrf_exempt_paths"].set(", ".join(sorted(cfg["security"]["csrf_exempt_paths"])))

        self.vars["sys_cleanup_interval_seconds"].set(cfg["system"]["cleanup_interval_seconds"])

        self.vars["mon_max_history_samples"].set(cfg["monitor"]["max_history_samples"])
        self.vars["mon_sample_interval"].set(cfg["monitor"]["sample_interval"])

        # ---- 目录与命名 ----
        self.virtual_dirs = dict(cfg.get("virtual_dirs") or {})
        self.hidden_folders = set(cfg.get("hidden_folders") or set())
        self.display_names = dict(cfg.get("display_names") or {})
        if hasattr(self, "_vdir_list"):
            self._refresh_listbox(self._vdir_list,
                                  [f"{k}  →  {v}" for k, v in sorted(self.virtual_dirs.items())])
        if hasattr(self, "_hidden_list"):
            self._refresh_listbox(self._hidden_list, sorted(self.hidden_folders))
        if hasattr(self, "_alias_list"):
            self._refresh_listbox(self._alias_list,
                                  [f"{k}  →  {v}" for k, v in sorted(self.display_names.items())])

        # ---- 标题设置 ----
        if hasattr(self, "nav_title_vars"):
            self._refresh_nav_title_widgets()

        # ---- 管理账号 ----
        admin = cfg.get("admin", {}) or {}
        self.vars["admin_enabled"].set(bool(admin.get("enabled")))
        self.vars["admin_username"].set(admin.get("username", ""))
        # 密码以哈希形式存储，无法反解；输入框留空表示"不修改"
        self.vars["admin_use_password"].set(bool(admin.get("password_hash")))
        self.vars["admin_password"].set("")
        self.vars["admin_password_confirm"].set("")
        self.vars["admin_use_totp"].set(bool(admin.get("totp_secret")))
        self.vars["admin_totp_secret"].set(admin.get("totp_secret", ""))
        self.vars["admin_totp_status"].set("")
        self._refresh_admin_status_text()

    def _refresh_admin_status_text(self):
        """在界面上用大白话说明当前管理账号的可用状态。"""
        enabled = self.vars["admin_enabled"].get()
        username = self.vars["admin_username"].get().strip()
        use_pwd = self.vars["admin_use_password"].get()
        use_totp = self.vars["admin_use_totp"].get() and bool(self.vars["admin_totp_secret"].get())

        if not enabled:
            self.vars["admin_status_text"].set(
                "当前状态：管理功能已关闭，聊天室中不会显示管理入口。")
            return
        if not username:
            self.vars["admin_status_text"].set(
                "当前状态：缺少用户名，无法启用。请填写管理员用户名。")
            return
        if not use_pwd and not use_totp:
            self.vars["admin_status_text"].set(
                "当前状态：密码与动态验证码都没启用，无法登录。请至少启用其中一种。")
            return
        ways = []
        if use_pwd:
            ways.append("密码")
        if use_totp:
            ways.append("动态验证码")
        self.vars["admin_status_text"].set(
            f"当前状态：可以使用，登录时校验「{' + '.join(ways)}」。保存后选择「立即重启」即可在聊天室看到入口。")

    def _collect_settings(self):
        cfg = copy.deepcopy(self.cfg)

        cfg["share_dir"] = self.vars["share_dir"].get().strip() or "."
        cfg["port"] = int(self.vars["port"].get())
        cfg["title"] = self.vars["title"].get().strip() or "719WebF 文件分享站"
        cfg["host"] = self.vars["host"].get().strip() or "0.0.0.0"
        cfg["enable_https"] = bool(self.vars["enable_https"].get())
        cfg["cert_file"] = self.vars["cert_file"].get().strip()
        cfg["key_file"] = self.vars["key_file"].get().strip()
        cfg["key_password"] = self.vars["key_password"].get().strip()
        cfg["public_key_file"] = self.vars["public_key_file"].get().strip()
        cfg["max_upload_mb"] = int(self.vars["max_upload_mb"].get())
        cfg["behind_proxy"] = bool(self.vars["behind_proxy"].get())

        for f in ["max_messages", "room_timeout_hours", "message_rate", "message_rate_window",
                  "create_rate", "create_rate_window", "http_timeout", "max_message_length"]:
            cfg["chat"][f] = int(self.vars[f"chat_{f}"].get())

        for f in ["lock_file", "log_dir", "secret_file", "static_folder",
                  "upload_temp_folder", "data_dir", "temp_files_data", "chat_data"]:
            v = self.vars[f"paths_{f}"].get().strip()
            if v:
                cfg["paths"][f] = v

        for f in ["max_signal_queue", "signal_timeout", "peer_timeout"]:
            cfg["p2p"][f] = int(self.vars[f"p2p_{f}"].get())

        for f in ["file_expire", "download_rate_limit", "download_rate_window"]:
            cfg["file_transfer"][f] = int(self.vars[f"ft_{f}"].get())

        int_fields = ["rate_limit_per_minute", "rate_limit_burst", "unverified_rate_limit",
                      "unverified_rate_burst", "file_rate_limit", "file_rate_burst",
                      "challenge_expire", "js_challenge_difficulty", "challenge_ip_ttl",
                      "bucket_cleanup_ttl", "used_token_ttl", "challenge_token_ttl", "max_used_tokens"]
        for f in int_fields:
            cfg["waf"][f] = int(self.vars[f"waf_{f}"].get())
        cfg["waf"]["challenge_cookie"] = self.vars["waf_challenge_cookie"].get().strip() or "waf_verify"
        cfg["waf"]["verify_path"] = self.vars["waf_verify_path"].get().strip() or "/waf_verify"
        cfg["waf"]["rate_limit_exempt_paths"] = {
            s.strip() for s in self.vars["waf_rate_limit_exempt_paths"].get().split(",") if s.strip()
        }

        cfg["security"]["csrf_safe_methods"] = {
            s.strip() for s in self.vars["sec_csrf_safe_methods"].get().split(",") if s.strip()
        }
        cfg["security"]["csrf_exempt_paths"] = {
            s.strip() for s in self.vars["sec_csrf_exempt_paths"].get().split(",") if s.strip()
        }

        cfg["system"]["cleanup_interval_seconds"] = int(self.vars["sys_cleanup_interval_seconds"].get())

        cfg["monitor"]["max_history_samples"] = int(self.vars["mon_max_history_samples"].get())
        cfg["monitor"]["sample_interval"] = int(self.vars["mon_sample_interval"].get())

        # ---- 目录与命名（整体覆盖，删除才会真正生效）----
        cfg["virtual_dirs"] = dict(self.virtual_dirs)
        cfg["hidden_folders"] = set(self.hidden_folders)
        cfg["display_names"] = dict(self.display_names)

        # ---- 标题图（整体覆盖，清空某页标题图才会真正生效）----
        if hasattr(self, "nav_title_vars"):
            cfg["nav_titles"] = {
                page: var.get().strip()
                for page, var in self.nav_title_vars.items()
                if var.get().strip()
            }

        # ---- 管理账号 ----
        cfg["admin"] = self._collect_admin_settings()

        return cfg

    def _collect_admin_settings(self):
        """收集管理账号设置，并在必要时把明文密码转成哈希写入配置。

        密码哈希依赖 .secret 文件（与服务端登录时使用的密钥一致），
        因此可以直接写进 config.xml，不需要用户再手工跑命令行工具。
        """
        cfg_admin = dict(self.cfg.get("admin") or {})
        enabled = bool(self.vars["admin_enabled"].get())
        username = self.vars["admin_username"].get().strip()

        use_password = bool(self.vars["admin_use_password"].get())
        new_pwd = self.vars["admin_password"].get()
        confirm_pwd = self.vars["admin_password_confirm"].get()

        # 输入了新密码 -> 校验并生成哈希
        if new_pwd or confirm_pwd:
            if new_pwd != confirm_pwd:
                raise ValueError("两次输入的密码不一致，请重新输入。")
            if len(new_pwd) < 4:
                raise ValueError("密码至少需要 4 位。")
            cfg_admin["password_hash"] = self._hash_password(new_pwd)
            use_password = True
        elif not use_password:
            # 主动取消了密码登录
            cfg_admin["password_hash"] = ""

        use_totp = bool(self.vars["admin_use_totp"].get())
        secret = self.vars["admin_totp_secret"].get().strip()
        if use_totp:
            if not secret:
                raise ValueError("已启用动态验证码，但还没有生成密钥。请点击「生成新密钥并显示二维码」。")
            cfg_admin["totp_secret"] = secret
        else:
            cfg_admin["totp_secret"] = ""

        if enabled:
            if not username:
                raise ValueError("已启用管理功能，但还没有填写管理员用户名。")
            if not cfg_admin.get("password_hash") and not cfg_admin.get("totp_secret"):
                raise ValueError(
                    "已启用管理功能，但密码与动态验证码都没有设置。\n"
                    "请至少启用其中一种验证方式。")

        cfg_admin["enabled"] = enabled
        cfg_admin["username"] = username
        return cfg_admin

    def _hash_password(self, password: str) -> str:
        """与服务端一致的密码哈希算法：sha256(密码 + 会话密钥)。"""
        import hashlib
        secret = ""
        secret_file = (self.cfg.get("paths") or {}).get("secret_file", ".secret")
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(self.config_path)), secret_file),
            os.path.join(BASE_DIR, secret_file),
            os.path.join(BASE_DIR, ".secret"),
        ]
        for path in candidates:
            try:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        secret = f.read().strip()
                    if secret:
                        break
            except Exception:
                continue
        if not secret:
            logger.warning("未找到会话密钥文件，生成的密码哈希可能无法通过登录校验")
        return hashlib.sha256((password + secret).encode()).hexdigest()

    def _show_about(self):
        """「关于」弹窗：版本、作者、项目地址与开源致谢。"""
        from tkinter import Toplevel
        import tkinter as tk
        win = Toplevel(self._root)
        win.title("关于")
        win.transient(self._root)
        win.resizable(False, False)
        try:
            win.grab_set()
        except Exception:
            pass

        frame = tk.Frame(win, padx=22, pady=18)
        frame.pack(fill="both", expand=True)

        try:
            from version import get_version_string, APP_AUTHOR
            ver_text = get_version_string()
            author = APP_AUTHOR
        except Exception:
            ver_text = APP_VER
            author = "HZYANG"

        tk.Label(frame, text="719WebF",
                 font=("微软雅黑", 13, "bold")).pack(anchor="center")
        tk.Label(frame, text=ver_text,
                 font=("微软雅黑", 10), fg="#555555").pack(anchor="center", pady=(3, 12))

        info = [
            ("作者", author),
            ("项目地址", "github.com/HZYANG-2486/719WebF"),
        ]
        for label, value in info:
            row = tk.Frame(frame)
            row.pack(anchor="w", pady=1)
            tk.Label(row, text=f"{label}：", font=("微软雅黑", 9),
                     fg="#777777").pack(side="left")
            tk.Label(row, text=value, font=("微软雅黑", 9)).pack(side="left")

        tk.Label(frame, text="开源致谢", font=("微软雅黑", 9, "bold"),
                 fg="#555555").pack(anchor="w", pady=(14, 3))
        credits = [
            "live2d-widget — 看板娘组件",
            "chart.js — 图表绘制",
            "Cloudflare error page — 错误页样式",
            "SCEditor — 聊天室BBCode可视化编辑支持"
        ]
        for c in credits:
            tk.Label(frame, text=f"· {c}", font=("微软雅黑", 8),
                     fg="#666666").pack(anchor="w")

        def _open_repo():
            try:
                webbrowser.open("https://github.com/HZYANG-2486/719WebF")
            except Exception:
                pass

        btns = tk.Frame(frame)
        btns.pack(fill="x", pady=(16, 0))
        tk.Button(btns, text="打开项目主页", command=_open_repo,
                  font=("微软雅黑", 9)).pack(side="left")
        tk.Button(btns, text="关闭", command=win.destroy,
                  font=("微软雅黑", 9), width=9).pack(side="right")

        win.update_idletasks()
        try:
            x = self._root.winfo_rootx() + (self._root.winfo_width() - win.winfo_width()) // 2
            y = self._root.winfo_rooty() + (self._root.winfo_height() - win.winfo_height()) // 3
            win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass

    def _on_save(self):
        from tkinter import messagebox
        try:
            cfg = self._collect_settings()
        except ValueError as e:
            # 业务校验失败（如两次密码不一致）：直接告诉用户怎么改
            messagebox.showwarning("请检查填写内容", str(e))
            return
        except Exception as e:
            messagebox.showerror("保存失败", f"读取设置时出错：{e}")
            return

        try:
            warnings = []
            try:
                from app import validate_config
                ok, errs = validate_config(cfg)
                if not ok:
                    warnings = list(errs)
            except Exception:
                pass

            # 保存前先拦截两类"看着能存、用起来出问题"的命名冲突：
            # 1) 虚拟目录别名与共享目录里真实文件夹同名（列表显示 A、点开是 B）
            # 2) 显示别名含斜杠或重名（列表里两条分不清）
            blocking = check_vdir_conflicts(cfg.get("virtual_dirs") or {},
                                            cfg.get("share_dir") or "")
            dnames = cfg.get("display_names") or {}
            for real, shown in dnames.items():
                bad, why = name_is_illegal(shown)
                if bad:
                    blocking.append(f"「{real}」的显示名称不可用：{why}")
            seen = {}
            for real, shown in dnames.items():
                if shown in seen and seen[shown] != real:
                    blocking.append(
                        f"显示名称「{shown}」被「{seen[shown]}」和「{real}」同时使用，"
                        "列表里会无法区分。请改成不同的名字。")
                seen[shown] = real
            if blocking:
                messagebox.showwarning(
                    "请先修正这些冲突",
                    "发现以下问题，暂未保存：\n\n" + "\n".join(f"· {x}" for x in blocking))
                return

            save_config(self.config_path, cfg)
            self.cfg = load_config(self.config_path)
            self.reload_config()
            if self.on_save_callback:
                self.on_save_callback(self.cfg)

            msg = "配置已保存。"
            admin = cfg.get("admin") or {}
            if admin.get("enabled"):
                ways = []
                if admin.get("password_hash"):
                    ways.append("密码")
                if admin.get("totp_secret"):
                    ways.append("动态验证码")
                msg += f"\n\n管理功能已启用，登录方式：{' + '.join(ways) or '（未设置）'}。"
            if warnings:
                msg += "\n\n提醒：\n" + "\n".join(warnings)

            # 大部分配置项需要重启才会生效，这里直接问一句，省得用户自己去找重启入口
            if self.on_restart_callback:
                msg += "\n\n是否立即重启，让改动马上生效？"
                if messagebox.askyesno("保存成功", msg):
                    messagebox.showinfo("正在重启", "服务即将重启，窗口会自动关闭。\n"
                                                    "约 3 秒后可重新打开页面。")
                    try:
                        self._destroy()
                    except Exception:
                        pass
                    self.on_restart_callback()
                    return
            else:
                msg += "\n\n重启服务后生效。"
                messagebox.showinfo("保存成功", msg)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _select_dir(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(title="选择共享文件夹")
        if path:
            self.vars["share_dir"].set(path)

    def _select_cert_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择证书文件",
            filetypes=[("证书文件", "*.crt *.pem *.cer"), ("所有文件", "*.*")]
        )
        if path:
            self.vars["cert_file"].set(path)

    def _select_key_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择密钥文件",
            filetypes=[("密钥文件", "*.key *.pem"), ("所有文件", "*.*")]
        )
        if path:
            self.vars["key_file"].set(path)

    def _select_pub_key_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择公钥文件",
            filetypes=[("公钥文件", "*.pub *.pem *.crt"), ("所有文件", "*.*")]
        )
        if path:
            self.vars["public_key_file"].set(path)

    def _destroy(self):
        if self._root:
            self._root.destroy()
            self._root = None
            self._created = False

    def run(self):
        if not self._created:
            self.create_window()
        if self._root:
            self._root.mainloop()

    def destroy(self):
        self._destroy()


def open_settings_gui(config_path: str, on_save_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                      on_restart_callback: Optional[Callable[[], None]] = None):
    """创建设置窗口并运行其消息循环。

    为保证 Tkinter 线程安全 + 在部分 Windows 机器上避免"控件不绘制/看不到输入点"：
    - 在当前线程中创建并独占 Tk（不与其他 Tk 主循环交叉）；
    - 启用 DPI 感知、强制更新后再进入主循环；
    - 所有 Entry/Spinbox 在 create_window 末尾做一次显式 state=normal 兜底。

    on_restart_callback: 保存后若用户选择"立即重启"，调用它让配置生效。
    """
    try:
        import tkinter as tk
        try:
            if os.name == "nt":
                try:
                    import ctypes
                    try:
                        # PROCESS_PER_MONITOR_DPI_AWARE = 2，避免高 DPI 下窗口尺寸错位/控件被裁掉
                        ctypes.windll.shcore.SetProcessDpiAwareness(2)
                    except (AttributeError, OSError):
                        try:
                            ctypes.windll.user32.SetProcessDPIAware()
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass
    except ImportError:
        logger.error("tkinter 不可用")
        return None
    app = SettingsGUI(config_path, on_save_callback, on_restart_callback)
    try:
        root = app.create_window()
        if root is not None:
            try:
                root.deiconify()
            except Exception:
                pass
            # 兜底：所有 Entry/Spinbox 即使被错误置为 disabled 也恢复可输入状态
            def _unlock_inputs(w):
                try:
                    for child in w.winfo_children():
                        cls = child.winfo_class()
                        if cls in ("Entry", "TEntry", "Spinbox", "TSpinbox"):
                            try:
                                child.configure(state="normal")
                            except Exception:
                                pass
                        _unlock_inputs(child)
                except Exception:
                    pass
            try:
                root.update_idletasks()
                _unlock_inputs(root)
                root.update()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"创建设置窗口失败: {e}")
        return None
    app.run()
    return app


# Settings 专用常驻 Tk 线程：保证任何情况下（托盘回调/后台线程触发）都在同一线程创建窗口。
_SETTINGS_LOCK = threading.Lock()
_SETTINGS_THREAD = None
_SETTINGS_THREAD_ALIVE = False


def _settings_worker(config_path, on_save_callback, on_restart_callback, done_event):
    """设置窗口线程。同一时刻只允许一个设置窗口存在。"""
    global _SETTINGS_THREAD_ALIVE
    try:
        _SETTINGS_THREAD_ALIVE = True
        try:
            open_settings_gui(config_path, on_save_callback, on_restart_callback)
        finally:
            done_event.set()
    finally:
        _SETTINGS_THREAD_ALIVE = False


def open_settings_gui_threadsafe(config_path: str, on_save_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                                 on_restart_callback: Optional[Callable[[], None]] = None):
    """线程安全入口。若已有设置窗口则激活前台（若能）并跳过创建。"""
    global _SETTINGS_THREAD
    with _SETTINGS_LOCK:
        if _SETTINGS_THREAD_ALIVE:
            logger.info("设置窗口已打开，跳过重复创建")
            return
        done = threading.Event()
        _SETTINGS_THREAD = threading.Thread(
            target=_settings_worker,
            args=(config_path, on_save_callback, on_restart_callback, done),
            name="SettingsGUIThread",
            daemon=False,
        )
        _SETTINGS_THREAD.start()


class GUIManager:
    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_FILE,
        on_start_service: Optional[Callable[[], None]] = None,
        on_stop_service: Optional[Callable[[], None]] = None,
        on_restart_service: Optional[Callable[[], None]] = None,
        headless: bool = False,
        logo_path: str = "logo.png"
    ):
        self.config_path = config_path
        self.on_start_service = on_start_service
        self.on_stop_service = on_stop_service
        self.on_restart_service = on_restart_service
        self.headless = headless
        self.logo_path = logo_path
        self._icon = None
        self._thread = None
        self._running = False
        self.cfg = load_config(config_path)

    def reload_config(self):
        self.cfg = load_config(self.config_path)

    def get_port(self) -> int:
        self.reload_config()
        return self.cfg.get("port", 5000)

    def get_config(self) -> Dict[str, Any]:
        self.reload_config()
        return dict(self.cfg)

    def _get_protocol(self) -> str:
        self.reload_config()
        return "https" if self.cfg.get("enable_https", False) else "http"

    def _open_index(self, icon=None, item=None):
        port = self.get_port()
        protocol = self._get_protocol()
        webbrowser.open(f"{protocol}://127.0.0.1:{port}")

    def _open_transfer(self, icon=None, item=None):
        port = self.get_port()
        protocol = self._get_protocol()
        webbrowser.open(f"{protocol}://127.0.0.1:{port}/transfer")

    def _open_settings(self, icon=None, item=None):
        open_settings_gui_threadsafe(self.config_path, self._on_config_saved, self._on_restart_requested)

    def _on_restart_requested(self):
        """设置界面里用户点了"立即重启"：先关掉托盘再重启进程，避免残留图标。"""
        self.stop()
        if self.on_restart_service:
            self.on_restart_service()

    def _restart_service(self, icon=None, item=None):
        """托盘菜单：重启服务，让配置改动生效。"""
        if not self.on_restart_service:
            logger.warning("当前运行方式不支持自动重启")
            return
        self.reload_config()
        try:
            self.on_restart_service()
        except BaseException as e:
            logger.error(f"重启失败: {e}")

    def _on_config_saved(self, new_cfg: Dict[str, Any]):
        self.cfg = new_cfg

    def _exit_app(self, icon=None, item=None):
        self.stop()
        if self.on_stop_service:
            try:
                self.on_stop_service()
            except BaseException:
                pass

    def _create_icon_image(self):
        _ensure_pystray()
        if os.path.exists(self.logo_path):
            try:
                return _Image.open(self.logo_path).resize((64, 64))
            except Exception:
                pass
        return _Image.new('RGB', (64, 64), color=(0, 102, 204))

    def _build_menu(self):
        _ensure_pystray()
        menu_items = [
            _item(f"{APP_NAME} {APP_VER}", lambda: None, enabled=False),
            _pystray.Menu.SEPARATOR,
            _item("🌐 打开首页", self._open_index),
            _item("📁 传输中心", self._open_transfer),
            _item("⚙️ 程序设置", self._open_settings),
            _item("🔄 重启服务", self._restart_service),
            _pystray.Menu.SEPARATOR,
            _item("❌ 关闭服务器", self._exit_app),
        ]
        return _pystray.Menu(*menu_items)

    def start_tray(self):
        if self.headless:
            logger.info("无头模式：跳过托盘初始化")
            return False

        if not _has_display():
            logger.warning("无可用显示器，跳过托盘初始化")
            return False

        try:
            _ensure_pystray()
            icon_img = self._create_icon_image()
            menu = self._build_menu()
            self._icon = _pystray.Icon(APP_NAME, icon=icon_img, title=APP_NAME, menu=menu)
            self._icon.on_left_click = self._open_index
            self._running = True

            self._thread = threading.Thread(target=self._run_tray, daemon=True)
            self._thread.start()
            logger.info("托盘已启动")
            return True
        except Exception as e:
            logger.error(f"托盘初始化失败: {e}")
            return False

    def _run_tray(self):
        try:
            if self._icon:
                self._icon.run()
        except Exception as e:
            logger.error(f"托盘运行异常: {e}")
        finally:
            self._running = False

    def stop(self):
        if self._icon and self._running:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._running = False
        logger.info("托盘已停止")

    def is_running(self) -> bool:
        return self._running

    def open_settings(self):
        self._open_settings()

    def open_index(self):
        self._open_index()

    def open_transfer(self):
        self._open_transfer()

    def __del__(self):
        self.stop()
