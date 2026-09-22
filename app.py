#719WEBF V1.6 2026
#Made By HZYANG+AI
#Use https://github.com/stevenjoezhang/live2d-widget (MIT)

from version import APP_NAME, APP_VER, APP_DESC

# gevent monkey patching should be done early (in main.py) before importing this module.
# We detect here whether gevent is available AND has been monkey-patched.
try:
    import gevent
    import gevent.monkey
    _GEVENT_PATCHED = gevent.monkey.is_module_patched('socket')
except ImportError:
    _GEVENT_PATCHED = False

import threading
import sys
import os
import copy
import time
import socket
import logging
import atexit
import signal
import hashlib
import hmac
import html
import ssl
from collections import defaultdict, deque
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify, send_from_directory, render_template, render_template_string, abort, session, redirect, url_for, make_response
import urllib.parse
import datetime
import uuid
import json
try:
    from cloudflare_error_page import render as render_cf_error_page
except ImportError:
    render_cf_error_page = None
from werkzeug.utils import secure_filename
from threading import Lock
import xml.etree.ElementTree as ET
import bbcode
import re
import storage
try:
    import pyotp
except ImportError:
    pyotp = None

# ===================== 应用常量定义 =====================
# 版本信息已迁移到 version.py，以上方 import 为准

# 可以自定义标题图标的页面：标识 -> 页面中文名（顺序即设置界面里的显示顺序）。
# 这里的标识是配置文件和模板之间的约定，改动需同步 gui.py 与各模板。
NAV_ICON_PAGES = {
    "home": "首页",
    "files": "文件浏览",
    "transfer": "传输中心",
    "chat": "聊天室",
    "health": "状态监控",
}

def _resolve_app_config_file():
    """把默认 config.xml 解析为相对于 main.py / 可执行文件目录的绝对路径，
    避免因 CWD 差异导致"看不到配置 / 需要手动移植"。
    """
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


CONFIG_FILE = _resolve_app_config_file()


def get_default_cfg() -> dict:
    return {
        "share_dir": ".",
        "port": 5000,
        "title": "719WebF",
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
        # 标题图：{页面标识: 图片路径}。用于把整块标题文字换成一幅设计好的图片。
        # 页面标识固定为 home/files/transfer/chat/health；
        # 留空表示不启用（继续显示原来的符号与文字）。默认不启用。
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
    # 这里必须整体替换而不是增量合并——否则用户在设置界面删掉的条目
    # 会因为"默认值里还留着"而复活，导致删除操作看起来无效。
    if "virtual_dirs" in partial_cfg and partial_cfg["virtual_dirs"] is not None:
        result["virtual_dirs"] = dict(partial_cfg["virtual_dirs"])
    # 隐藏文件夹：不列出但可直接访问的名称集合（同样整体替换）
    if "hidden_folders" in partial_cfg and partial_cfg["hidden_folders"] is not None:
        result["hidden_folders"] = set(partial_cfg["hidden_folders"])
    # 显示别名：{真实名称: 列表显示名}
    if "display_names" in partial_cfg and partial_cfg["display_names"] is not None:
        result["display_names"] = dict(partial_cfg["display_names"])
    # 标题图：整体替换，清空后才能退回文字标题
    if "nav_titles" in partial_cfg and partial_cfg["nav_titles"] is not None:
        result["nav_titles"] = dict(partial_cfg["nav_titles"])
    return result


def validate_config(cfg):
    errors = []

    def _check_positive_int(name, value):
        if not isinstance(value, int) or value <= 0:
            errors.append(f"{name}={value} 必须是正整数")

    _check_positive_int("port", cfg.get("port"))
    _check_positive_int("max_upload_mb", cfg.get("max_upload_mb"))

    chat = cfg.get("chat", {})
    for k in ["max_messages", "room_timeout_hours", "message_rate", "message_rate_window",
              "create_rate", "create_rate_window", "http_timeout", "max_message_length"]:
        _check_positive_int(f"chat.{k}", chat.get(k))

    p2p = cfg.get("p2p", {})
    for k in ["max_signal_queue", "signal_timeout", "peer_timeout"]:
        _check_positive_int(f"p2p.{k}", p2p.get(k))

    ft = cfg.get("file_transfer", {})
    for k in ["file_expire", "download_rate_limit", "download_rate_window"]:
        _check_positive_int(f"file_transfer.{k}", ft.get(k))

    waf = cfg.get("waf", {})
    waf_positive_keys = [
        "rate_limit_per_minute", "rate_limit_burst", "unverified_rate_limit",
        "unverified_rate_burst", "file_rate_limit", "file_rate_burst",
        "challenge_expire", "js_challenge_difficulty", "challenge_ip_ttl",
        "bucket_cleanup_ttl", "used_token_ttl", "challenge_token_ttl",
        "max_used_tokens"
    ]
    for k in waf_positive_keys:
        _check_positive_int(f"waf.{k}", waf.get(k))

    system = cfg.get("system", {})
    _check_positive_int("system.cleanup_interval_seconds", system.get("cleanup_interval_seconds"))

    monitor = cfg.get("monitor", {})
    for k in ["max_history_samples", "sample_interval"]:
        _check_positive_int(f"monitor.{k}", monitor.get(k))

    js_diff = waf.get("js_challenge_difficulty")
    if isinstance(js_diff, int) and not (1 <= js_diff <= 16):
        errors.append(f"waf.js_challenge_difficulty={js_diff} 超出范围 1-16")

    max_msg_len = chat.get("max_message_length")
    if isinstance(max_msg_len, int) and not (200 <= max_msg_len <= 20000):
        errors.append(f"chat.max_message_length={max_msg_len} 超出范围 200-20000")

    sample_interval = monitor.get("sample_interval")
    if isinstance(sample_interval, int) and not (5 <= sample_interval <= 300):
        errors.append(f"monitor.sample_interval={sample_interval} 超出范围 5-300")

    max_history = monitor.get("max_history_samples")
    if isinstance(max_history, int) and not (60 <= max_history <= 86400):
        errors.append(f"monitor.max_history_samples={max_history} 超出范围 60-86400")

    verify_path = waf.get("verify_path", "")
    if isinstance(verify_path, str) and verify_path == "":
        errors.append("waf.verify_path 不能为空字符串")
    if not verify_path.startswith("/"):
        errors.append(f"waf.verify_path={verify_path} 必须以 '/' 开头")

    challenge_cookie = waf.get("challenge_cookie", "")
    if isinstance(challenge_cookie, str) and challenge_cookie == "":
        errors.append("waf.challenge_cookie 不能为空字符串")
    if len(challenge_cookie) < 1:
        errors.append("waf.challenge_cookie 长度必须 >= 1")

    paths_cfg = cfg.get("paths", {})
    path_fields = [
        ("share_dir", cfg.get("share_dir", "")),
        ("paths.lock_file", paths_cfg.get("lock_file", "")),
        ("paths.log_dir", paths_cfg.get("log_dir", "")),
        ("paths.secret_file", paths_cfg.get("secret_file", "")),
        ("paths.static_folder", paths_cfg.get("static_folder", "")),
        ("paths.upload_temp_folder", paths_cfg.get("upload_temp_folder", "")),
        ("paths.data_dir", paths_cfg.get("data_dir", "")),
        ("paths.temp_files_data", paths_cfg.get("temp_files_data", "")),
        ("paths.chat_data", paths_cfg.get("chat_data", "")),
    ]
    for name, value in path_fields:
        if isinstance(value, str) and "\0" in value:
            logging.warning(f"配置字段 {name} 包含非法空字符 \\0")
        if isinstance(value, str) and value == "":
            errors.append(f"{name} 不能为空字符串")

    # 管理账号：启用时必须配置用户名，且密码 / 动态验证码至少配置一项
    admin = cfg.get("admin", {}) or {}
    if admin.get("enabled"):
        if not admin.get("username"):
            errors.append("admin.enabled=true 但未配置 admin.username")
        if not admin.get("password_hash") and not admin.get("totp_secret"):
            errors.append(
                "admin.enabled=true 但密码与动态验证码都未配置（请在设置界面生成管理账号）"
            )

    # 虚拟目录：名称不能含路径分隔符或 ..，路径可以是共享目录之外的任意位置。
    #
    # 这里刻意不限制"必须在共享目录内"。虚拟目录的用途就是给共享目录之外的
    # 文件夹起一个别名（比如把 D:\资料 挂成"资料库"），强制它落在共享目录里
    # 等于让这个功能失去意义。安全由两道防线保证，而不是靠限制路径位置：
    #   1) 别名只能由管理员在本机设置界面 / config.xml 里预先配置，访客无法自助添加；
    #   2) 访问时 get_safe_path 仍以该别名指向的目录为边界，
    #      访客无法用 .. 、绝对路径等手段越出这个目录去读别的东西。
    share_abs = os.path.abspath(cfg.get("share_dir", ".") or ".")
    for vname, vpath in (cfg.get("virtual_dirs") or {}).items():
        if not vname or "/" in vname or "\\" in vname or vname in (".", ".."):
            errors.append(f"virtual_dirs 名称非法: {vname!r}（不能包含 / \\ 或为 . / ..）")
        if not vpath:
            errors.append(f"virtual_dirs[{vname}] 未填写路径")
            continue
        if not os.path.isabs(vpath):
            vpath = os.path.join(share_abs, vpath)
        vabs = os.path.abspath(vpath)
        # 指向自身会造成循环展示，需要拦掉；除此之外一律放行
        if vabs == share_abs:
            errors.append(f"virtual_dirs[{vname}] 不能指向共享目录本身: {vabs}")
        if not os.path.isdir(vabs):
            logging.warning(f"virtual_dirs[{vname}] 目标目录不存在，将显示为空: {vabs}")

    return (len(errors) == 0, errors)


# ===================== XML配置读写 =====================
def create_default_config(config_path=None):
    if config_path is None:
        config_path = CONFIG_FILE
    default_cfg = get_default_cfg()
    root = ET.Element("config")

    root.append(ET.Comment("共享目录路径，默认 \".\" 表示当前目录，所有分享文件均基于此目录提供访问"))
    el = ET.SubElement(root, "share_dir")
    el.text = default_cfg["share_dir"]

    root.append(ET.Comment("服务监听端口号，默认 5000，建议范围 1024-65535"))
    el = ET.SubElement(root, "port")
    el.text = str(default_cfg["port"])

    root.append(ET.Comment("网站标题名称，默认 \"719WebF\"，将显示于网页标题栏"))
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
        "显示别名：列表中把某条目显示成另一个名字，不改动磁盘上的真实文件名。"
        "示例：<item name=\"real_folder\" as=\"对外显示的名字\" />"
    ))

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


def load_config(config_path=None, _depth=0):
    if config_path is None:
        config_path = CONFIG_FILE

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
        "title": root.findtext("title", "719WebF"),
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

    # 显示别名：把某个条目在列表中显示成另一个名字（不改动磁盘上的真实名称）
    names_node = root.find("display_names")
    if names_node is not None:
        display_names = {}
        for node in names_node.findall("item"):
            real = (node.get("name") or "").strip()
            shown = (node.get("as") or "").strip()
            if real and shown:
                display_names[real] = shown
        partial_cfg["display_names"] = display_names

    # 标题图：<page name="chat" image="/path/to/banner.png" />
    titles_node = root.find("nav_titles")
    if titles_node is not None:
        nav_titles = {}
        for node in titles_node.findall("page"):
            key = (node.get("name") or "").strip()
            image = (node.get("image") or "").strip()
            if key in NAV_ICON_PAGES:
                nav_titles[key] = image
        partial_cfg["nav_titles"] = nav_titles

    cfg = merge_with_defaults(partial_cfg)
    ok, errors = validate_config(cfg)
    if not ok:
        logging.warning("配置校验警告: \n - " + "\n - ".join(errors))
    return cfg

def save_config(config_path, cfg):
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
    _write_field(root, "title", cfg["title"], "网站标题名称，默认 \"719WebF\"，将显示于网页标题栏")
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
    ))
    for _name, _path in sorted((cfg.get("virtual_dirs") or {}).items()):
        ET.SubElement(vdirs_el, "dir", {"name": str(_name), "path": str(_path)})

    hidden_el = ET.SubElement(root, "hidden_folders")
    hidden_el.append(ET.Comment(
        "隐藏文件夹：列表中将不显示这些名称的文件夹（输入完整名称匹配，仍可直接访问）。"
    ))
    for _name in sorted(cfg.get("hidden_folders") or set()):
        ET.SubElement(hidden_el, "folder", {"name": str(_name)})

    names_el = ET.SubElement(root, "display_names")
    names_el.append(ET.Comment(
        "显示别名：列表中把某条目显示成另一个名字，不改动磁盘上的真实文件名。"
        "示例：<item name=\"real_folder\" as=\"对外显示的名字\" />"
    ))
    for _real, _shown in sorted((cfg.get("display_names") or {}).items()):
        ET.SubElement(names_el, "item", {"name": str(_real), "as": str(_shown)})

    titles_el = ET.SubElement(root, "nav_titles")
    titles_el.append(ET.Comment(
        "标题图：把整块标题文字换成一幅图片（横幅/艺术字）。name 可选 "
        + "/".join(NAV_ICON_PAGES.keys())
        + "；image 填本地图片的绝对路径（如 \"D:\\\\我的图\\\\banner.png\"），"
        "留空则不启用、继续显示图标和文字。图片高度自动适配标题栏，宽度按比例。"
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

CONFIG = load_config()

_paths_cfg = CONFIG.get("paths", {})
_p2p_cfg = CONFIG.get("p2p", {})
_ft_cfg = CONFIG.get("file_transfer", {})
_waf_cfg = CONFIG.get("waf", {})
_sec_cfg = CONFIG.get("security", {})

LOCK_FILE = _paths_cfg.get("lock_file", "server.lock")
if not os.path.isabs(LOCK_FILE):
    LOCK_FILE = os.path.join(os.getcwd(), LOCK_FILE)
LOG_DIR = _paths_cfg.get("log_dir", "logs")
SECRET_FILE = _paths_cfg.get("secret_file", ".secret")

MAX_SIGNAL_QUEUE = _p2p_cfg.get("max_signal_queue", 100)
SIGNAL_TIMEOUT = _p2p_cfg.get("signal_timeout", 300)
PEER_TIMEOUT = _p2p_cfg.get("peer_timeout", 30)

FILE_EXPIRE = _ft_cfg.get("file_expire", 3600)
DOWNLOAD_RATE_LIMIT = _ft_cfg.get("download_rate_limit", 10)
DOWNLOAD_RATE_WINDOW = _ft_cfg.get("download_rate_window", 60)

RATE_LIMIT_PER_MINUTE = _waf_cfg.get("rate_limit_per_minute", 120)
RATE_LIMIT_BURST = _waf_cfg.get("rate_limit_burst", 200)
UNVERIFIED_RATE_LIMIT = _waf_cfg.get("unverified_rate_limit", 30)
UNVERIFIED_RATE_BURST = _waf_cfg.get("unverified_rate_burst", 60)
FILE_RATE_LIMIT = _waf_cfg.get("file_rate_limit", 30)
FILE_RATE_BURST = _waf_cfg.get("file_rate_burst", 60)
CHALLENGE_COOKIE = _waf_cfg.get("challenge_cookie", "waf_verify")
CHALLENGE_EXPIRE = _waf_cfg.get("challenge_expire", 86400)
JS_CHALLENGE_DIFFICULTY = _waf_cfg.get("js_challenge_difficulty", 8)
VERIFY_PATH = _waf_cfg.get("verify_path", "/waf_verify")
CHALLENGE_IP_TTL = _waf_cfg.get("challenge_ip_ttl", 300)
BUCKET_CLEANUP_TTL = _waf_cfg.get("bucket_cleanup_ttl", 300)
USED_TOKEN_TTL = _waf_cfg.get("used_token_ttl", 600)
CHALLENGE_TOKEN_TTL = _waf_cfg.get("challenge_token_ttl", 300)
MAX_USED_TOKENS = _waf_cfg.get("max_used_tokens", 10000)
RATE_LIMIT_EXEMPT_PATHS = _waf_cfg.get("rate_limit_exempt_paths", {"/p2p/signal/recv"})

_sec_cfg = CONFIG.get("security", {})
CSRF_SAFE_METHODS = _sec_cfg.get("csrf_safe_methods", {"GET", "HEAD", "OPTIONS"})
CSRF_EXEMPT_PATHS = _sec_cfg.get("csrf_exempt_paths", {"/waf_verify", "/ws/chat"})

_sys_cfg = CONFIG.get("system", {})
CLEANUP_INTERVAL_SECONDS = _sys_cfg.get("cleanup_interval_seconds", 60)

_mon_cfg = CONFIG.get("monitor", {})
MONITOR_MAX_HISTORY_SAMPLES = _mon_cfg.get("max_history_samples", 360)
MONITOR_SAMPLE_INTERVAL = _mon_cfg.get("sample_interval", 10)

MAX_MESSAGE_LENGTH = CONFIG.get("chat", {}).get("max_message_length", 2000)

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
logger.propagate = False

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
def is_port_in_use(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

def check_single_instance(port, host):
    if is_port_in_use(port, host):
        logger.error(f"端口 {port} 已被占用，禁止重复启动！")
        sys.exit(1)
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            logger.error("检测到服务已在运行，禁止多开！")
            sys.exit(1)
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            os.remove(LOCK_FILE)
    try:
        with open(LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        atexit.register(remove_lock_file)
    except Exception as e:
        logger.error(f"创建锁文件失败: {e}")
        sys.exit(1)

def remove_lock_file():
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass

# ===================== Flask 初始化 =====================
try:
    from waitress import serve
except ImportError:
    serve = None

where_is_it = "The Hell Network Centre"

app = Flask(__name__)

@app.context_processor
def inject_version_info():
    # nav_titles 在这里统一注入：各页面标题栏都要用，逐个 render_template 传参
    # 容易漏（尤其 monitor.py 里的状态页是另一个蓝图）。
    return {
        'app_name': APP_NAME,
        'app_ver': APP_VER,
        'nav_titles': get_nav_titles(),
    }

# 持久化 secret key，避免重启后 session 失效
def load_or_create_secret():
    if os.path.exists(SECRET_FILE):
        try:
            with open(SECRET_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    new_secret = f"719webf_{uuid.uuid4().hex}"
    try:
        with open(SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(new_secret)
    except Exception:
        pass
    return new_secret

app.secret_key = load_or_create_secret()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # Will be updated after config load
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


def _get_site_secret():
    """站点密钥，用于给本地图标路径签名。直接复用 Flask 的 secret_key。"""
    return app.secret_key

STATIC_FOLDER = os.path.join(app.root_path, _paths_cfg.get("static_folder", "static"))
UPLOAD_TEMP_FOLDER = os.path.join(app.root_path, _paths_cfg.get("upload_temp_folder", "temp_uploads"))
os.makedirs(UPLOAD_TEMP_FOLDER, exist_ok=True)

DATA_DIR = os.path.join(app.root_path, _paths_cfg.get("data_dir", "data"))
os.makedirs(DATA_DIR, exist_ok=True)
TEMP_FILES_DATA = os.path.join(DATA_DIR, _paths_cfg.get("temp_files_data", "temp_files.json"))
CHAT_DATA = os.path.join(DATA_DIR, _paths_cfg.get("chat_data", "chat_data.json"))

@app.before_request
def _csrf_protection():
    """Validate Origin/Referer for POST/PUT/DELETE requests."""
    if request.method in CSRF_SAFE_METHODS:
        return None
    path = _normalize_path(request.path)
    if path in CSRF_EXEMPT_PATHS:
        return None
    # Skip CSRF check for same-origin requests from WAF-verified sessions
    cookie_val = request.cookies.get(CHALLENGE_COOKIE, "")
    if cookie_val and _verify_cookie(cookie_val, _get_client_identity()):
        return None
    # For state-changing requests without WAF cookie, validate Origin
    origin = request.headers.get('Origin', '')
    referer = request.headers.get('Referer', '')
    if origin:
        parsed = urllib.parse.urlparse(origin)
        if parsed.hostname and request.host and parsed.hostname != request.host.split(':')[0]:
            return jsonify({"code": 403, "msg": "CSRF check failed"}), 403
    return None

# Session Fixation prevention: regenerate session after WAF verification
@app.before_request
def _session_fixation_prevention():
    if request.endpoint == 'waf_verify' and request.method == 'POST':
        if request.form.get('token') and request.form.get('nonce'):
            if _verify_challenge_token(request.form.get('token', ''), _get_client_identity()):
                session.clear()

# WebSocket 支持（flask-sock + gevent）
_WEBSOCKET_SERVER_READY = False
try:
    from flask_sock import Sock
    sock = Sock(app)
    SOCK_AVAILABLE = True
except ImportError:
    sock = None
    SOCK_AVAILABLE = False

@app.before_request
def _check_websocket_support():
    if request.path == '/ws/chat' and not _WEBSOCKET_SERVER_READY:
        if request.headers.get('Upgrade', '').lower() == 'websocket':
            return jsonify({"error": "WebSocket unavailable", "message": "当前服务器不支持WebSocket，请使用HTTP轮询模式"}), 503

# ===================== 自定义防DDOS中间件 =====================
class RateLimiter:
    def __init__(self, rate_per_minute, burst):
        self.rate = rate_per_minute
        self.burst = burst
        self._buckets = defaultdict(lambda: {"tokens": burst, "last": time.time()})
        self._lock = Lock()

    def allow(self, key):
        now = time.time()
        with self._lock:
            bucket = self._buckets[key]
            elapsed = now - bucket["last"]
            bucket["tokens"] = min(
                self.burst,
                bucket["tokens"] + elapsed * (self.rate / 60.0)
            )
            bucket["last"] = now
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True
            return False

    def remaining(self, key):
        now = time.time()
        with self._lock:
            bucket = self._buckets[key]
            elapsed = now - bucket["last"]
            tokens = min(self.burst, bucket["tokens"] + elapsed * (self.rate / 60.0))
            return int(tokens)

    def cleanup(self):
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._buckets.items() if now - v["last"] > BUCKET_CLEANUP_TTL]
            for k in expired:
                del self._buckets[k]

rate_limiter = RateLimiter(RATE_LIMIT_PER_MINUTE, RATE_LIMIT_BURST)
_unverified_rate = RateLimiter(UNVERIFIED_RATE_LIMIT, UNVERIFIED_RATE_BURST)
_file_rate_limiter = RateLimiter(FILE_RATE_LIMIT, FILE_RATE_BURST)
_download_counts = {}
_download_counts_lock = Lock()
_used_tokens = set()
_used_tokens_lock = Lock()

def _cleanup_used_tokens():
    """Remove expired tokens from _used_tokens set."""
    # 这里必须声明 global：下面有 ``_used_tokens -= expired`` 这样的赋值，
    # 若不加声明，Python 会把 _used_tokens 当成局部变量，
    # 于是上面的 ``for token in _used_tokens`` 会先抛 UnboundLocalError。
    global _used_tokens
    with _used_tokens_lock:
        now = time.time()
        expired = set()
        for token in _used_tokens:
            try:
                parts = token.split(".")
                if len(parts) >= 1:
                    ts = int(parts[0])
                    if now - ts > USED_TOKEN_TTL:
                        expired.add(token)
            except (ValueError, IndexError):
                expired.add(token)
        _used_tokens -= expired
_waf_rate_blocked = 0
_waf_rate_blocked_lock = Lock()
# 已通过验证的身份 → 过期时间戳。用 dict 而不是 set，是为了能按龄清理：
# 早前是纯集合，只增不减，长期运行会一直吃内存（同一个 IP 换端口就多一条）。
_waf_verified_ips = {}
_waf_verified_ips_lock = Lock()
_waf_challenge_ips = {}
_waf_challenge_lock = Lock()
_waf_total_challenges = 0
_waf_total_challenges_lock = Lock()

# 已通过验证的身份保留多久。cookie 本身是 CHALLENGE_EXPIRE 秒有效，这里留同样
# 的长度，保证在 cookie 有效期内不会被误清掉（否则用户会被反复要求验证）。
WAF_VERIFIED_TTL = CHALLENGE_EXPIRE


def _cleanup_verified_ips(now=None):
    """清掉过期的“已通过验证”记录，防止集合无限膨胀。"""
    now = now if now is not None else time.time()
    with _waf_verified_ips_lock:
        expired = [ip for ip, exp in _waf_verified_ips.items() if exp <= now]
        for ip in expired:
            del _waf_verified_ips[ip]
    return len(expired)

def _check_download_rate_limit(ip, fid):
    now = time.time()
    key = f"{ip}:{fid}"
    with _download_counts_lock:
        timestamps = _download_counts.get(key, [])
        cutoff = now - DOWNLOAD_RATE_WINDOW
        valid = [t for t in timestamps if t > cutoff]
        if len(valid) >= DOWNLOAD_RATE_LIMIT:
            _download_counts[key] = valid
            return False
        valid.append(now)
        _download_counts[key] = valid
        return True

def _log_download(ip, fid, uid, status):
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"DOWNLOAD | {ts} | IP={ip} | FID={fid} | UID={uid or 'N/A'} | STATUS={status}")
    except Exception:
        pass

def _normalize_path(path):
    while "//" in path:
        path = path.replace("//", "/")
    return path

_LOCAL_IPS = None
_LOCAL_IPS_LOCK = Lock()

def _is_pure_loopback_ip(ip):
    """Check if an IP is a pure loopback address (without LAN detection)."""
    if not ip:
        return False
    if ip in ('127.0.0.1', '::1', 'localhost'):
        return True
    if ip.startswith('127.'):
        return True
    if ip.startswith('::ffff:127.'):
        return True
    return False

def _get_local_machine_ips():
    """Get all IP addresses owned by this machine (excluding loopback).

    使用非阻塞超时 + 线程保护，避免 RadminLAN / 无外网环境下 getaddrinfo / UDP connect
    长时间阻塞（原来可能挂 4-5 分钟）。
    """
    global _LOCAL_IPS
    with _LOCAL_IPS_LOCK:
        if _LOCAL_IPS is not None:
            return _LOCAL_IPS
    ips = set()

    # 方式1：优先枚举本机所有网卡的真实绑定地址，不走 DNS（最快、最可靠）。
    def _collect_via_bind():
        result = set()
        try:
            import netifaces  # 可选，若已安装直接使用
            for iface in netifaces.interfaces():
                try:
                    for af in (netifaces.AF_INET, netifaces.AF_INET6):
                        addrs = netifaces.ifaddresses(iface).get(af, [])
                        for a in addrs:
                            ip = a.get("addr", "")
                            if ip and not _is_pure_loopback_ip(ip) and "%" not in ip:
                                result.add(ip.split("%")[0])
                except Exception:
                    pass
        except Exception:
            pass
        if not result:
            # 无 netifaces：枚举常见私有/虚拟网段的本地监听探测替代（耗时可忽略）
            candidates = ["0.0.0.0"]  # fallback，不加入结果
            try:
                hostname = socket.gethostname()
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.settimeout(0.8)
                    s.connect(("1.1.1.1", 53))
                    ip = s.getsockname()[0]
                    s.close()
                    if ip and not _is_pure_loopback_ip(ip):
                        result.add(ip)
                except Exception:
                    pass
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.settimeout(0.6)
                    s.connect((hostname, 1))
                    ip = s.getsockname()[0]
                    s.close()
                    if ip and not _is_pure_loopback_ip(ip):
                        result.add(ip)
                except Exception:
                    pass
            except Exception:
                pass
        return result

    # 方式2：传统 getaddrinfo / 8.8.8.8 探测 —— 严格设置短超时，最坏 1.5s 放弃
    def _collect_via_dns():
        result = set()
        try:
            hostname = socket.gethostname()
            try:
                old = socket.getdefaulttimeout()
                socket.setdefaulttimeout(1.0)
                try:
                    addr_info = socket.getaddrinfo(hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
                finally:
                    socket.setdefaulttimeout(old)
                for info in addr_info:
                    ip = info[4][0].split("%")[0]
                    if ip and not _is_pure_loopback_ip(ip):
                        result.add(ip)
            except Exception:
                pass
        except Exception:
            pass
        for probe_host, probe_port in (("8.8.8.8", 80), ("1.0.0.1", 53), ("223.5.5.5", 53)):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.6)
                s.connect((probe_host, probe_port))
                ip = s.getsockname()[0]
                s.close()
                if ip and not _is_pure_loopback_ip(ip):
                    result.add(ip)
                    break
            except Exception:
                continue
        return result

    try:
        ips.update(_collect_via_bind())
    except Exception:
        pass

    # 若绑定法已得到多个地址（通常 ≥1 ）则直接接受，避免再触发 DNS/外网探测的卡顿
    if len(ips) == 0:
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(_collect_via_dns)
                try:
                    extra = fut.result(timeout=1.6)
                    ips.update(extra or set())
                except concurrent.futures.TimeoutError:
                    pass
        except Exception:
            pass

    with _LOCAL_IPS_LOCK:
        _LOCAL_IPS = ips
    return ips

def _is_loopback_ip(ip):
    """Check if an IP is a loopback/localhost address or owned by this machine."""
    if _is_pure_loopback_ip(ip):
        return True
    local_ips = _get_local_machine_ips()
    if ip in local_ips:
        return True
    return False

def _get_client_identity():
    """Get a stable client identity for WAF cookies.
    Loopback addresses (127.x.x.x, ::1) all map to the same identity.
    For non-loopback, uses the exact IP."""
    ip = request.remote_addr or "unknown"
    if BEHIND_PROXY:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            ip = xff.split(",")[0].strip()
    if _is_loopback_ip(ip):
        return "loopback"
    return ip

def _get_client_ip():
    if BEHIND_PROXY:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"

def _is_api_request():
    accept = request.headers.get("Accept", "")
    if "application/json" in accept:
        return True
    path = _normalize_path(request.path)
    api_prefixes = ["/p2p/", "/temp/", "/files/"]
    for prefix in api_prefixes:
        if path.startswith(prefix):
            return True
    if request.is_json:
        return True
    return False

def _is_static_asset():
    path = _normalize_path(request.path)
    static_prefixes = ["/static/", "/live2d/", "/emoticons/"]
    for prefix in static_prefixes:
        if path.startswith(prefix):
            return True
    # 标题图：本地图片通过 /nav_icon 路由提供。
    # 不放进白名单的话，浏览器首次访问时标题图会被安全校验拦下，标题栏会缺图。
    if path == "/nav_icon":
        return True
    if path in ("/favicon.ico", "/robots.txt", "/sitemap.xml"):
        return True
    return False

def _is_rate_limit_exempt():
    path = _normalize_path(request.path)
    for exempt in RATE_LIMIT_EXEMPT_PATHS:
        if path == exempt or path.startswith(exempt + "/"):
            return True
    return False

def _path_is_verify():
    return _normalize_path(request.path) == VERIFY_PATH

def _generate_challenge_token(identity):
    secret = app.secret_key.encode() if app.secret_key else b"default_secret"
    timestamp = str(int(time.time()))
    random_nonce = os.urandom(8).hex()
    raw = f"{identity}:{timestamp}:{random_nonce}".encode()
    sig = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return f"{timestamp}.{random_nonce}.{sig}"

def _challenge_token_status(token, identity):
    """校验挑战令牌，返回 "ok" / "expired" / "invalid"。

    区分「过期」与「伪造」很重要：低配设备求解可能超过令牌有效期，
    此时若一律当作无效并重新下发令牌，就会陷入"永远算不完"的循环。
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return "invalid"
        timestamp_str, nonce, sig = parts
        timestamp = int(timestamp_str)
        secret = app.secret_key.encode() if app.secret_key else b"default_secret"
        raw = f"{identity}:{timestamp_str}:{nonce}".encode()
        expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return "invalid"
        if time.time() - timestamp > CHALLENGE_TOKEN_TTL:
            return "expired"
        return "ok"
    except Exception:
        return "invalid"

def _verify_challenge_token(token, identity):
    return _challenge_token_status(token, identity) == "ok"

def _browser_fingerprint():
    """生成稳定的浏览器指纹。

    不能把完整 User-Agent 绑定进 cookie：浏览器扩展、隐私插件、内置浏览器
    会在不同请求间改写 UA，导致刚验证通过的 cookie 立刻失效，
    表现为"验证成功 -> 立刻又被拦 -> 再验证"的无限循环。
    这里只取跟浏览器主体相关的关键特征，忽略版本号、附加标记等易变部分。
    """
    ua = request.headers.get("User-Agent", "")
    # 提取浏览器家族与主版本（如 Chrome/120），忽略小版本与附加后缀
    family = ""
    for token, name in (
        ("Edg/", "edge"), ("OPR/", "opera"), ("Chrome/", "chrome"),
        ("Firefox/", "firefox"), ("Safari/", "safari"),
    ):
        if token in ua:
            family = name
            break
    # 平台
    platform = ""
    for token, name in (
        ("Windows", "win"), ("Macintosh", "mac"), ("Android", "android"),
        ("iPhone", "ios"), ("iPad", "ipados"), ("Linux", "linux"),
    ):
        if token in ua:
            platform = name
            break
    accept_lang = request.headers.get("Accept-Language", "")[:40]
    return f"{family}|{platform}|{accept_lang}"


def _generate_verify_cookie(identity):
    secret = app.secret_key.encode() if app.secret_key else b"default_secret"
    expire_ts = int(time.time()) + CHALLENGE_EXPIRE
    fp = _browser_fingerprint()
    raw = f"{identity}:{expire_ts}:{fp}".encode()
    sig = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return f"{expire_ts}.{sig}"

def _verify_cookie(cookie_val, identity):
    try:
        expire_ts_str, sig = cookie_val.split(".", 1)
        expire_ts = int(expire_ts_str)
        if time.time() > expire_ts:
            return False
        secret = app.secret_key.encode() if app.secret_key else b"default_secret"
        fp = _browser_fingerprint()
        raw = f"{identity}:{expire_ts_str}:{fp}".encode()
        expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, expected):
            return True
        # 指纹发生轻微漂移（扩展改写 UA、版本升级等）时，回退到更宽松的校验：
        # 只要身份（IP）与过期时间都没问题，就仍然放行，
        # 避免用户被反复要求验证。
        legacy_raw = f"{identity}:{expire_ts_str}:{request.headers.get('User-Agent','')[:200]}".encode()
        if hmac.compare_digest(sig, hmac.new(secret, legacy_raw, hashlib.sha256).hexdigest()):
            return True
        # 仅校验身份 + 过期时间（不含 UA），签名仍不可伪造
        base_raw = f"{identity}:{expire_ts_str}".encode()
        if hmac.compare_digest(sig, hmac.new(secret, base_raw, hashlib.sha256).hexdigest()):
            return True
        return False
    except Exception:
        return False

def _render_js_challenge(token, next_url):
    return render_template("waf_challenge.html",
        title=HOME_TITLE,
        token=token,
        difficulty=JS_CHALLENGE_DIFFICULTY,
        next_url=next_url,
        verify_path=VERIFY_PATH)

def _safe_relative_url(path):
    """把任意路径规范化为安全的站内相对路径。

    浏览器把反斜杠视作正斜杠，所以 "/\\chat" 必须先转成 "/chat" 再做判断，
    否则反斜杠会被误判为危险字符、整条路径被丢弃，用户就回不到目标页面。
    返回 (规范化后的路径, 是否被修改过)。
    """
    if not path:
        return "/", False
    original = path
    # 浏览器把 \ 当 / 处理，先归一，避免把 /chat 这类正常路径误杀
    path = path.replace("\\", "/")
    # 折叠重复斜杠
    while "//" in path:
        path = path.replace("//", "/")
    # 去掉控制字符与首尾空白
    path = "".join(ch for ch in path if ord(ch) >= 32 or ch == "\t").strip()
    if not path:
        return "/", True
    # 必须以 / 开头（防止 "evil.com/x" 被当作相对路径）
    if not path.startswith("/"):
        path = "/" + path
    # 解析 .. 与 .，防止路径穿越
    try:
        parsed = urllib.parse.urlparse(path)
        segments = []
        for seg in parsed.path.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if segments:
                    segments.pop()
                continue
            segments.append(seg)
        normalized = "/" + "/".join(segments)
        if parsed.query:
            normalized += "?" + parsed.query
        path = normalized
    except Exception:
        path = "/"
    return path, (path != original)


def _is_external_url(raw):
    """判断是否为站外地址（含协议相对与反斜杠伪装）。"""
    if not raw:
        return False
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme:
        return True
    if parsed.netloc:
        return True
    # 协议相对：//evil.com
    if raw.startswith("//"):
        return True
    # 反斜杠伪装：\\evil.com  ->  //evil.com
    if raw.startswith("\\\\"):
        return True
    return False


def _validate_next_url(url):
    """校验跳转目标，防止开放重定向。

    与旧实现的关键区别：反斜杠等可修正的写法会被**规范化**而不是直接丢弃，
    这样用户验证通过后能回到原本要访问的页面，不会出现反复验证的死循环。
    """
    if not url:
        return "/"
    raw = url.strip()
    if not raw:
        return "/"

    parsed = urllib.parse.urlparse(raw)

    if parsed.scheme in ("http", "https"):
        # 绝对地址：仅当指向本站时才接受，否则回到首页
        try:
            host = request.host.split(":")[0].lower() if request else ""
            target_host = (parsed.hostname or "").lower()
            if host and target_host == host:
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                safe, _ = _safe_relative_url(path)
                return safe
        except Exception:
            pass
        return "/"

    if parsed.scheme or parsed.netloc:
        # 其它协议（javascript:、data: 等）或已带主机名，一律拒绝
        return "/"

    if _is_external_url(raw):
        return "/"

    # 到这里是站内相对路径（可能含反斜杠），交给规范化处理
    safe, _ = _safe_relative_url(raw)
    return safe

@app.route(VERIFY_PATH, methods=["GET", "POST"])
def waf_verify():
    identity = _get_client_identity()
    ip = _get_client_ip()
    if request.method == "POST":
        token = request.form.get("token", "")
        nonce_str = request.form.get("nonce", "0")
        next_url = _validate_next_url(request.args.get("next", "/"))
        status = _challenge_token_status(token, identity)
        if status == "invalid":
            # 令牌被篡改，重新下发
            return _challenge_response(identity, next_url), 403
        if status == "expired":
            # 令牌仅是超时（低配设备算得慢），只要答案正确依然放行，
            # 避免"算完就过期 -> 重新下发 -> 再算再过期"的死循环
            try:
                nonce = int(nonce_str)
            except (ValueError, TypeError):
                return _challenge_response(identity, next_url), 403
            h = hashlib.sha256(f"{token}:{nonce}".encode()).hexdigest()
            if h[:JS_CHALLENGE_DIFFICULTY] != "0" * JS_CHALLENGE_DIFFICULTY:
                # 答案不对且令牌已过期，下发新令牌重新开始
                return _challenge_response(identity, next_url), 403
            return _finish_waf_verification(identity, token, next_url)
        try:
            nonce = int(nonce_str)
        except (ValueError, TypeError):
            return _challenge_response(identity, next_url), 403
        test_str = f"{token}:{nonce}"
        h = hashlib.sha256(test_str.encode()).hexdigest()
        target = "0" * JS_CHALLENGE_DIFFICULTY
        if h[:JS_CHALLENGE_DIFFICULTY] == target:
            with _used_tokens_lock:
                if token in _used_tokens:
                    # 同一令牌重复提交（多策略竞态）：若已在本机验证过，直接放行
                    with _waf_verified_ips_lock:
                        _still_ok = identity in _waf_verified_ips
                    if _still_ok:
                        return _finish_waf_verification(identity, token, next_url)
                    return _challenge_response(identity, next_url), 403
                _used_tokens.add(token)
            return _finish_waf_verification(identity, token, next_url)
    next_url = _validate_next_url(request.args.get("next", "/"))
    return _challenge_response(identity, next_url), 403


def _finish_waf_verification(identity, token, next_url):
    """标记身份已通过验证，写入 cookie 并返回跳转页。"""
    if len(_used_tokens) > MAX_USED_TOKENS:
        _cleanup_used_tokens()
    with _waf_verified_ips_lock:
        _waf_verified_ips[identity] = time.time() + WAF_VERIFIED_TTL
    with _waf_challenge_lock:
        _waf_challenge_ips.pop(identity, None)
    cookie_val = _generate_verify_cookie(identity)
    resp = make_response("")
    resp.status_code = 200
    resp.set_cookie(
        CHALLENGE_COOKIE, cookie_val,
        max_age=CHALLENGE_EXPIRE,
        httponly=True,
        secure=HTTPS_ENABLED,
        samesite="Lax",
        path="/"
    )
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.data = (
        '<html><head><meta charset="utf-8">'
        f'<script>window.location.replace({json.dumps(next_url)});</script>'
        '</head><body>验证通过，正在跳转...</body></html>'
    )
    return resp

def _challenge_response(identity, next_url="/"):
    token = _generate_challenge_token(identity)
    if _is_api_request():
        return jsonify({
            "code": 403,
            "msg": "请先完成安全验证",
            "verify_url": VERIFY_PATH,
            "token": token,
            "difficulty": JS_CHALLENGE_DIFFICULTY,
            "next": next_url
        })
    return _render_js_challenge(token, next_url)

@app.before_request
def waf_middleware():
    global _waf_rate_blocked
    path = _normalize_path(request.path)
    if path == "/health" or path.startswith("/health/"):
        return None

    identity = _get_client_identity()
    cookie_val = request.cookies.get(CHALLENGE_COOKIE, "")

    if path == "/ws/chat":
        if cookie_val and _verify_cookie(cookie_val, identity):
            return None
        if _is_api_request():
            return jsonify({"code": 403, "msg": "请先完成安全验证", "verify_url": VERIFY_PATH}), 403
        return "请先完成安全验证", 403

    if path.startswith("/chat/"):
        if cookie_val and _verify_cookie(cookie_val, identity):
            return None

    if _path_is_verify():
        return None
    if _is_static_asset():
        return None

    if cookie_val and _verify_cookie(cookie_val, identity):
        if not _is_rate_limit_exempt():
            file_paths = ["/temp/upload", "/temp/download", "/transfer"]
            path = _normalize_path(request.path)
            is_file_path = path in file_paths or any(path.startswith(p + "/") for p in file_paths)
            if is_file_path:
                if not _file_rate_limiter.allow(f"f:{identity}"):
                    with _waf_rate_blocked_lock:
                        _waf_rate_blocked += 1
                    if _is_api_request():
                        return jsonify({"code": 429, "msg": "请求过于频繁，请稍后再试"}), 429
                    return "Too Many Requests", 429
            elif not rate_limiter.allow(f"v:{identity}"):
                with _waf_rate_blocked_lock:
                    _waf_rate_blocked += 1
                if _is_api_request():
                    return jsonify({"code": 429, "msg": "请求过于频繁，请稍后再试"}), 429
                return "Too Many Requests", 429
        return None
    if not _unverified_rate.allow(f"u:{identity}"):
        with _waf_rate_blocked_lock:
            _waf_rate_blocked += 1
        if _is_api_request():
            return jsonify({"code": 429, "msg": "请求过于频繁，请稍后再试"}), 429
        return "Too Many Requests", 429
    current_url = request.full_path if request.query_string else request.path
    # 规范化访问路径，避免把非法字符反射进挑战页导致验证后跳转异常
    try:
        parsed_path = urllib.parse.urlparse(current_url)
        normalized_path, _ = _safe_relative_url(parsed_path.path)
        current_url = normalized_path
        if parsed_path.query:
            current_url += "?" + parsed_path.query
    except Exception:
        current_url = "/"
    next_url = _validate_next_url(current_url) if request.method == "GET" else "/"
    with _waf_challenge_lock:
        _waf_challenge_ips[identity] = time.time()
        global _waf_total_challenges
        _waf_total_challenges += 1
    if _is_api_request():
        resp = jsonify({
            "code": 403,
            "msg": "请先完成安全验证",
            "verify_url": f"{VERIFY_PATH}?next={urllib.parse.quote(next_url)}",
            "token": _generate_challenge_token(identity),
            "difficulty": JS_CHALLENGE_DIFFICULTY
        })
        return resp, 403
    resp = make_response(_render_js_challenge(_generate_challenge_token(identity), next_url), 403)
    return resp

# ===================== 【核心】记录每一次网页访问 =====================
@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline' https://fastly.jsdelivr.net https://fontawesome.com; "
        "img-src * data:; "
        "font-src 'self' https://fastly.jsdelivr.net https://use.fontawesome.com data:; "
        "connect-src * ws: wss: https: http:; "
        "frame-ancestors 'none'"
    )
    if HTTPS_ENABLED:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

@app.after_request
def log_access(response):
    try:
        ip = _get_client_ip()
        method = request.method
        path = request.full_path
        status = response.status_code
        ua = (request.user_agent.string[:150] if request.user_agent else "-")
        size = response.content_length or 0
        time_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"{time_now} | {ip:15s} | {method:6s} | {status:3d} | {size:8d} B | {path}"
        access_logger.info(log_line)
    except Exception:
        pass
    return response

# ===================== 全局配置 =====================
SHARE_FOLDER = os.path.abspath(CONFIG["share_dir"])

def _resolve_virtual_dirs(raw):
    """把配置中的虚拟目录解析为 {显示名: 绝对物理路径}。

    虚拟目录可以指向共享目录之外的任意位置——这本来就是它的卖点
    （给别处的文件夹起别名挂进来）。因此这里只校验别名的合法性，
    不再限制路径位置。

    安全性说明：越界风险由访问侧兜底。get_safe_path 会以该别名映射的
    物理路径作为边界，访客无法再用 .. 或绝对路径跳出这个目录。
    """
    out = {}
    share_abs = os.path.abspath(SHARE_FOLDER)
    for name, path in (raw or {}).items():
        name = str(name).strip()
        path = str(path).strip()
        if not name or not path or "/" in name or "\\" in name or name in (".", ".."):
            logging.warning(f"忽略非法虚拟目录名: {name!r}")
            continue
        p = path if os.path.isabs(path) else os.path.join(share_abs, path)
        pabs = os.path.abspath(p)
        # 指向共享目录自身会造成列表循环，跳过；其它位置一律允许
        if pabs == share_abs:
            logging.warning(f"忽略虚拟目录 {name}：不能指向共享目录本身")
            continue
        if not os.path.isdir(pabs):
            logging.warning(f"虚拟目录 {name} 的目标不存在，将显示为空: {pabs}")
        out[name] = pabs
    return out

VIRTUAL_DIRS = _resolve_virtual_dirs(CONFIG.get("virtual_dirs"))
HIDDEN_FOLDERS = set(CONFIG.get("hidden_folders") or set())
# 显示别名：列表中展示的名字（不改动磁盘真实名称）
DISPLAY_NAMES = dict(CONFIG.get("display_names") or {})

SERVER_PORT = CONFIG["port"]
HOME_TITLE = CONFIG["title"]
SERVER_HOST = CONFIG["host"]
HTTPS_ENABLED = CONFIG.get("enable_https", False)
HTTPS_CERT_FILE = CONFIG.get("cert_file", "")
HTTPS_KEY_FILE = CONFIG.get("key_file", "")
HTTPS_KEY_PASSWORD = CONFIG.get("key_password", "")
PUBLIC_KEY_FILE = CONFIG.get("public_key_file", "")
MAX_UPLOAD_SIZE = CONFIG.get("max_upload_mb", 2048) * 1024 * 1024
BEHIND_PROXY = CONFIG.get("behind_proxy", False)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE

_chat_cfg = CONFIG.get("chat", {})
MAX_CHAT_MESSAGES = _chat_cfg.get("max_messages", 500)
# 房间空闲多久后回收。配置项单位是小时，而 last_activity 用 time.time()（秒），
# 因此只需 *3600。这里曾经多乘了一个 1000，导致 24 小时被放大成 1000 天，
# 房间实际上永远不会被清理（实测 34 天前的房间仍留在库里）。
CHAT_ROOM_TIMEOUT = _chat_cfg.get("room_timeout_hours", 24) * 3600
CHAT_MESSAGE_RATE = _chat_cfg.get("message_rate", 5)
CHAT_MESSAGE_RATE_WINDOW = _chat_cfg.get("message_rate_window", 60)
HTTP_CHAT_TIMEOUT = _chat_cfg.get("http_timeout", 60)
CHAT_CREATE_RATE_LIMIT = _chat_cfg.get("create_rate", 5)
CHAT_CREATE_RATE_WINDOW = _chat_cfg.get("create_rate_window", 60)

# Update session cookie security based on config
app.config['SESSION_COOKIE_SECURE'] = HTTPS_ENABLED

peers = {}           # uid -> {"addr","online","room","nick","ua"}
peer_lock = Lock()
temp_files = {}
file_lock = Lock()
signal_box = {}

# 房间（面对面联机分组）：room_code -> set(uid)，用于双方仅看到同房间的成员
rooms = defaultdict(set)
rooms_lock = Lock()

# ===================== 公钥 PEM 文件支持 =====================
_public_key_cache = None
_public_key_type = None

def load_public_key():
    """Load the public key PEM file configured in config.xml.
    Returns (key_type, key_content) tuple or (None, None) if not configured.
    key_type: 'public_key', 'rsa_public_key', or None"""
    global _public_key_cache, _public_key_type
    if _public_key_cache is not None:
        return _public_key_type, _public_key_cache
    if not PUBLIC_KEY_FILE:
        return None, None
    if not os.path.isfile(PUBLIC_KEY_FILE):
        logger.warning(f"公钥文件不存在: {PUBLIC_KEY_FILE}")
        return None, None
    try:
        with open(PUBLIC_KEY_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        if '-----BEGIN PUBLIC KEY-----' in content:
            _public_key_type = 'public_key'
        elif '-----BEGIN RSA PUBLIC KEY-----' in content:
            _public_key_type = 'rsa_public_key'
        else:
            logger.warning(f"公钥文件 {PUBLIC_KEY_FILE} 中未找到有效的 PEM 公钥标记")
            return None, None
        _public_key_cache = content
        logger.info(f"公钥 PEM 加载成功: {PUBLIC_KEY_FILE} (类型: {_public_key_type})")
        return _public_key_type, _public_key_cache
    except Exception as e:
        logger.error(f"公钥文件加载失败: {e}")
        return None, None

def verify_with_public_key(signature, message, key_type=None):
    """Verify a message signature using the configured public key.
    Supports RSA-SHA256 and RSA-SHA512 verification.
    Returns True if signature is valid, False otherwise.
    Requires 'cryptography' package (install with: pip install cryptography)."""
    key_type, key_content = load_public_key()
    if not key_content:
        return False
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, utils
        if key_type == 'public_key' or key_type == 'rsa_public_key':
            public_key = serialization.load_pem_public_key(key_content.encode())
            public_key.verify(
                signature,
                message.encode() if isinstance(message, str) else message,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return True
        return False
    except ImportError:
        logger.warning("公钥验证需要 cryptography 库: pip install cryptography")
        return False
    except Exception as e:
        logger.warning(f"公钥验证失败: {e}")
        return False

# ===================== 数据持久化（SQLite） =====================
DB_PATH = os.path.join(DATA_DIR, "app.db")

def init_storage():
    """初始化 SQLite 存储，并在首次运行时从旧的 JSON 数据迁移。"""
    try:
        storage.init(DB_PATH)
        chat_n, temp_n, migrated = storage.migrate_from_json(
            CHAT_DATA, TEMP_FILES_DATA, DB_PATH
        )
        if migrated:
            logger.info(f"已从 JSON 迁移数据到数据库: {chat_n} 个聊天室, {temp_n} 个临时文件")
        logger.info(f"存储已就绪: {DB_PATH}")
    except Exception as e:
        logger.error(f"初始化存储失败: {e}")

def load_temp_files():
    global temp_files
    try:
        saved = storage.load_temp()
    except Exception as e:
        logger.warning(f"加载临时文件数据失败: {e}")
        return
    with file_lock:
        for fid, info in saved.items():
            if info.get("path") and os.path.exists(info["path"]):
                temp_files[fid] = info
    logger.info(f"已加载 {len(temp_files)} 个临时文件")

def save_temp_files():
    try:
        with file_lock:
            data = dict(temp_files)
        storage.save_temp(data)
    except Exception as e:
        logger.warning(f"保存临时文件数据失败: {e}")

def load_chat_data():
    global chat_rooms
    try:
        saved = storage.load_chat()
    except Exception as e:
        logger.warning(f"加载聊天室数据失败: {e}")
        return
    with chat_lock:
        for rid, room in saved.items():
            room["messages"] = deque(room["messages"], maxlen=MAX_CHAT_MESSAGES)
            room["users"] = set(room.get("users", []))
            chat_rooms[rid] = room
    logger.info(f"已加载 {len(chat_rooms)} 个聊天室")

def save_chat_data():
    """把内存中的房间数据落盘。

    加一把专用锁串行化"快照 + 写盘"整个动作：原来是各线程各自拍快照后
    并行写同一个文件，两个线程交错时后写的会覆盖先写的，造成丢消息。
    """
    try:
        with _chat_save_lock:
            with chat_lock:
                data = {}
                for rid, room in chat_rooms.items():
                    data[rid] = {
                        "name": room["name"],
                        "password_hash": room["password_hash"],
                        "created": room["created"],
                        "last_activity": room["last_activity"],
                        "messages": list(room["messages"]),
                        "users": list(room["users"])
                    }
            storage.save_chat(data)
    except Exception as e:
        logger.warning(f"保存聊天室数据失败: {e}")

# ===================== 聊天室数据结构 =====================
chat_rooms = {}
chat_lock = Lock()
# save_chat_data 专用的写盘锁，避免多线程同时落盘互相覆盖
_chat_save_lock = Lock()

ws_rooms = {}
ws_rooms_lock = Lock()

http_chat_sessions = {}
http_chat_lock = Lock()

chat_bbcode_parser = bbcode.Parser(escape_html=True, replace_links=False, replace_cosmetic=True)

chat_bbcode_parser.add_simple_formatter('b', '<strong>%(value)s</strong>')
chat_bbcode_parser.add_simple_formatter('i', '<em>%(value)s</em>')
chat_bbcode_parser.add_simple_formatter('u', '<u>%(value)s</u>')
chat_bbcode_parser.add_simple_formatter('s', '<s>%(value)s</s>')
chat_bbcode_parser.add_simple_formatter('code', '<code>%(value)s</code>')

ALLOWED_COLORS = {
    '#000000', '#000080', '#00008B', '#0000CD', '#0000FF', '#006400', '#008000', '#008080',
    '#008B8B', '#00BFFF', '#00CED1', '#191970', '#1E90FF', '#20B2AA', '#228B22', '#2E8B57',
    '#2F4F4F', '#32CD32', '#3CB371', '#40E0D0', '#4169E1', '#4682B4', '#483D8B', '#48D1CC',
    '#4A7C59', '#556B2F', '#5F9EA0', '#6495ED', '#663399', '#6B8E23', '#708090', '#778899',
    '#7B68EE', '#7CFC00', '#7FFF00', '#7FFFD4', '#800000', '#800080', '#808000', '#808080',
    '#87CEEB', '#87CEFA', '#8A2BE2', '#8B0000', '#8B008B', '#8B4513', '#8FBC8F', '#90EE90',
    '#9370DB', '#9400D3', '#98FB98', '#9932CC', '#9ACD32', '#A0522D', '#A52A2A', '#A9A9A9',
    '#ADD8E6', '#ADFF2F', '#AFEEEE', '#B0C4DE', '#B0E0E6', '#B22222', '#B8860B', '#BA55D3',
    '#BC8F8F', '#BDB76B', '#C0C0C0', '#C71585', '#CD5C5C', '#CD853F', '#DAA520', '#DB7093',
    '#DC143C', '#DDA0DD', '#DEB887', '#D2691E', '#D3D3D3', '#D35400', '#D8BFD8', '#DECDCD',
    '#E0FFFF', '#E6E6FA', '#E9967A', '#EE82EE', '#EEE8AA', '#F08080', '#F0E68C', '#F0F8FF',
    '#F0FFFF', '#F1C40F', '#F2F2F2', '#F3E5AB', '#F4A460', '#F5DEB3', '#F5F5DC', '#F5F5F5',
    '#F5FFFA', '#F8F8FF', '#FA8072', '#FAEBD7', '#FAF0E6', '#FAFAD2', '#FDF5E6', '#FF0000',
    '#FF00FF', '#FF1493', '#FF4500', '#FF6347', '#FF69B4', '#FF7F50', '#FF8C00', '#FFA07A',
    '#FFA500', '#FFB6C1', '#FFC0CB', '#FFD700', '#FFDAB9', '#FFDEAD', '#FFE4B5', '#FFE4C4',
    '#FFEFD5', '#FFF0F5', '#FFF5EE', '#FFFACD', '#FFFAF0', '#FFFF00', '#FFFFE0', '#FFFFF0',
    '#ffffff', '#1e293b', '#7fdbff', '#ff4136', '#ff5f54',
    'red', 'green', 'blue', 'yellow', 'orange', 'purple', 'pink', 'black', 'white', 'gray',
    'silver', 'gold', 'brown'
}

SIZE_LEVEL_MAP = {'1': '10px', '2': '12px', '3': '14px', '4': '18px', '5': '22px', '6': '28px', '7': '36px'}

ALLOWED_FONTS = {
    'Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi', 'Arial', 'Arial Black',
    'Times New Roman', 'Courier New', 'Georgia', 'Verdana', 'Trebuchet MS',
    'Impact', 'Comic Sans MS', 'Lucida Console'
}

SAFE_FONT_STACK_RE = re.compile(
    r'^[-a-zA-Z0-9 ",_]+$'
)

def _html_escape(text):
    if not text:
        return ''
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))

def _safe_url(url):
    url = re.sub(r'^\s*(javascript|data)\s*:', '', url, flags=re.IGNORECASE)
    if not (url.startswith('http://') or url.startswith('https://')):
        return ''
    return url

def fmt_color(name, value, params, parent, context):
    color = params.get('color', '#000000').strip().lower()
    if color not in ALLOWED_COLORS:
        if not re.match(r'^#[0-9a-f]{6}$', color):
            color = '#000000'
    return f'<span style="color:{color}">{value}</span>'

def fmt_size(name, value, params, parent, context):
    size = params.get('size', '3').strip().lower()
    if size in SIZE_LEVEL_MAP:
        return f'<span style="font-size:{SIZE_LEVEL_MAP[size]}">{value}</span>'
    m = re.match(r'^(\d+)px$', size)
    if m:
        px = int(m.group(1))
        if 1 <= px <= 72:
            return f'<span style="font-size:{size}">{value}</span>'
    return f'<span style="font-size:14px">{value}</span>'

def fmt_font(name, value, params, parent, context):
    font = params.get('font', '').strip()
    if not font:
        return value
    if font in ALLOWED_FONTS:
        return f'<span style="font-family:{_html_escape(font)}">{value}</span>'
    if SAFE_FONT_STACK_RE.match(font) and len(font) <= 200:
        return f'<span style="font-family:{_html_escape(font)}">{value}</span>'
    return value

def fmt_url(name, value, params, parent, context):
    url = params.get('url', '').strip().strip('`')
    if not url and value:
        url = value.strip().strip('`')
    url = re.sub(r'^\s*(javascript|data)\s*:', '', url, flags=re.IGNORECASE)
    if not (url.startswith('http://') or url.startswith('https://')):
        url = 'https://' + url if '.' in url else ''
    if url:
        return f'<a href="{_html_escape(url)}" target="_blank" rel="noopener noreferrer">{value}</a>'
    return value

def fmt_img(name, value, params, parent, context):
    src = params.get('img', '').strip().strip('`')
    alt = (value.strip().strip('`') if value else '')
    width = height = ''
    m = re.match(r'^(\d+)x(\d+)$', src, re.IGNORECASE)
    if m:
        width = m.group(1)
        height = m.group(2)
        src = alt
        alt = ''
    elif not src:
        src = alt
        alt = ''
    src = src.strip('`')
    src = re.sub(r'^\s*(javascript|data)\s*:', '', src, flags=re.IGNORECASE)
    if not (src.startswith('http://') or src.startswith('https://')):
        return _html_escape(src) if src else ''
    alt_text = _html_escape(alt[:50]) if alt else _html_escape(src[:50])
    style = 'max-width:300px;max-height:200px;'
    if width and height:
        w = min(int(width), 600)
        h = min(int(height), 600)
        style = f'width:{w}px;height:{h}px;'
    return f'<img src="{_html_escape(src)}" alt="{alt_text}" style="{style}" />'

def fmt_file(name, value, params, parent, context):
    fid = params.get('file', '').strip()
    fid = re.sub(r'[^a-zA-Z0-9\-_]', '', fid)
    if not fid:
        return value
    url = f'/temp/download/{_html_escape(fid)}'
    return f'<a href="{url}" target="_blank" class="chat-file-link">📎 {value}</a>'

chat_bbcode_parser.add_formatter('color', fmt_color)
chat_bbcode_parser.add_formatter('size', fmt_size)
chat_bbcode_parser.add_formatter('url', fmt_url)
chat_bbcode_parser.add_formatter('img', fmt_img)
chat_bbcode_parser.add_formatter('file', fmt_file)
chat_bbcode_parser.add_formatter('font', fmt_font)

BARE_URL_RE = re.compile(r'(?<![\w"\'/=.?#-])(https?://[^\s<>"\']+)', re.IGNORECASE)
_TAG_SPLIT_RE = re.compile(r'(<[^>]*>)')
TRAILING_URL_JUNK = '.,;:!?)]}\u3002\uff0c\uff01\uff1f\uff09\u300b\u3011\u201d\u2019'

def _autolink_text_segment(segment):
    """把一个纯文本片段中的裸 URL 转换为 <a> 标签。

    仅处理不在 HTML 标签内的文本，已在 <a> 内的内容不会被重复处理
    （调用方通过标签切分保证这一点）。

    注意：传入的 segment 已经是 HTML 转义后的文本（bbcode 解析输出），
    因此这里不能再做整串转义，仅在写入属性值时转义引号。
    """
    if 'http://' not in segment and 'https://' not in segment:
        return segment

    def _repl(match):
        raw = match.group(1)
        trail = ''
        while raw and raw[-1] in TRAILING_URL_JUNK:
            trail = raw[-1] + trail
            raw = raw[:-1]
        if not raw:
            return match.group(0)
        # 属性值与显示文本都直接复用已转义的原文，仅补足属性引号转义
        attr = raw.replace('"', '&quot;').replace("'", '&#39;')
        if not re.match(r'^https?://', raw, re.IGNORECASE):
            return match.group(0)
        return f'<a href="{attr}" target="_blank" rel="noopener noreferrer">{raw}</a>{trail}'

    return BARE_URL_RE.sub(_repl, segment)

def autolink_html(html_text):
    """在已生成的 HTML 中，为裸 URL 文本自动添加链接。

    通过标签切分，只对标签外的文本节点做替换，避免破坏属性值，
    也避免在已有的 <a> 内部再次嵌套链接。
    """
    if not html_text:
        return html_text
    parts = _TAG_SPLIT_RE.split(html_text)
    out = []
    anchor_depth = 0
    for part in parts:
        if not part:
            continue
        if part.startswith('<') and part.endswith('>'):
            tag = part[1:].split()[0].lower().rstrip('/') if len(part) > 2 else ''
            if tag == 'a':
                if part[1:2] == '/':
                    anchor_depth = max(0, anchor_depth - 1)
                elif not part.endswith('/>'):
                    anchor_depth += 1
            out.append(part)
        else:
            if anchor_depth > 0:
                out.append(part)
            else:
                out.append(_autolink_text_segment(part))
    return ''.join(out)

def sanitize_bbcode(text):
    if not text:
        return ""
    try:
        parsed = chat_bbcode_parser.format(text)
    except Exception:
        parsed = _html_escape(text)
    try:
        parsed = autolink_html(parsed)
    except Exception:
        pass
    parsed = parsed.replace('\n', '<br>')
    return parsed

def clean_expired_rooms():
    """回收超时房间。

    锁内只做"挑出并摘除"，真正耗时的部分（关掉该房间的 WebSocket 连接、
    写盘）都放到锁外。原来整个流程都在 chat_lock 里跑，房间一大就会把
    所有发消息的请求一起卡住。
    """
    now = time.time()
    with chat_lock:
        expired = [rid for rid, room in chat_rooms.items()
                   if now - room.get("last_activity", 0) > CHAT_ROOM_TIMEOUT]
        removed = [chat_rooms.pop(rid, None) for rid in expired]
    removed = [r for r in removed if r]
    if not removed:
        return
    # 回收属于已关闭房间的 WebSocket 连接，避免连接对象悬挂、越积越多
    for rid in expired:
        try:
            with ws_rooms_lock:
                conns = list(ws_rooms.pop(rid, set()) or [])
            for ws in conns:
                try:
                    ws.close()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"回收房间 {rid} 的连接失败: {e}")

def get_nickname():
    data = request.get_json(silent=True) or {}
    nick = data.get("nick", "").strip()[:20]
    if not nick:
        nick = session.get("chat_nick", "")
    if not nick:
        nick = f"User_{str(uuid.uuid4())[:8]}"
        session["chat_nick"] = nick
    return nick

def set_nickname(nick):
    nick = nick.strip()[:20]
    if not nick:
        nick = f"User_{str(uuid.uuid4())[:8]}"
    session["chat_nick"] = nick
    return nick

# ===================== 工具函数 =====================
def format_size(size_bytes):
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024**2: return f"{size_bytes/1024:.2f} KB"
    elif size_bytes < 1024**3: return f"{size_bytes/1024**2:.2f} MB"
    else: return f"{size_bytes/1024**3:.2f} GB"

def format_mtime(mtime):
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

def clean_expired_files():
    """清理过期临时文件。

    先锁内摘除记录，再在锁外删磁盘文件——os.remove 可能因为磁盘慢而阻塞，
    持锁删会让所有上传/下载请求排队等待。
    """
    now = time.time()
    with file_lock:
        expired = [(fid, info.get("path")) for fid, info in temp_files.items()
                   if now - info.get("upload_time", 0) > FILE_EXPIRE]
        for fid, _p in expired:
            temp_files.pop(fid, None)
    for fid, path in expired:
        if not path:
            continue
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"删除过期文件 {fid} 失败: {e}")

def get_safe_path(relative_path):
    # 剔除路由前缀 /files/
    prefix = "/files/"
    if relative_path.startswith(prefix):
        rel = relative_path[len(prefix):]
    else:
        rel = ""
    # 空路径返回根共享目录
    if not rel.strip("/"):
        return SHARE_FOLDER
    # 禁止访问以 . 开头的隐藏文件/目录
    parts = rel.split(os.sep)
    for part in parts:
        if part.startswith('.'):
            abort(403)

    # 虚拟目录：若首段是已配置的别名，则把基址切换为该别名映射的物理路径
    base = SHARE_FOLDER
    rel_norm = rel.replace("\\", "/").strip("/")
    first_seg = rel_norm.split("/", 1)[0] if rel_norm else ""
    rest = rel_norm[len(first_seg):].lstrip("/")
    if first_seg in VIRTUAL_DIRS:
        base = VIRTUAL_DIRS[first_seg]
        rel = rest
        if not rel.strip("/"):
            return base
        for part in rel.split("/"):
            if part.startswith('.'):
                abort(403)

    # 安全拼接，禁止..穿越
    rel = os.path.normpath(rel)
    if rel.startswith("..") or os.path.isabs(rel):
        abort(403)
    target_path = os.path.abspath(os.path.join(base, rel))
    # 严格前缀校验（相对虚拟目录基址或共享目录）
    base_abs = os.path.abspath(base)
    try:
        if os.path.commonpath([target_path, base_abs]) != base_abs:
            abort(403)
    except ValueError:
        abort(403)
    return target_path

def cleanup_expired_peers():
    now = time.time()
    expired = []
    with peer_lock, rooms_lock:
        for uid, info in peers.items():
            if now - info["online"] > PEER_TIMEOUT:
                expired.append(uid)
        for uid in expired:
            info = peers.pop(uid, None)
            signal_box.pop(uid, None)
            if info and info.get("room"):
                room = info["room"]
                if room in rooms:
                    rooms[room].discard(uid)
                    if not rooms[room]:
                        rooms.pop(room, None)


def _get_p2p_uid(create_if_missing: bool = True):
    """获取或创建客户端唯一标识。优先 session 存储；回退到 query/header 参数；
    避免 cookie 被 RadminLAN/浏览器策略拦截时每次请求都生成新 ID 导致"看到的只有自己"。
    """
    uid = session.get("p2p_uid")
    if uid:
        return uid
    # 兼容客户端显式带 uid 的回退路径
    uid = request.args.get("p2p_uid") or request.headers.get("X-P2P-UID")
    if uid and len(uid) <= 64 and all(c.isalnum() or c in "-_" for c in uid):
        if create_if_missing:
            try:
                session["p2p_uid"] = uid
            except Exception:
                pass
        return uid
    if create_if_missing:
        uid = uuid.uuid4().hex
        try:
            session["p2p_uid"] = uid
        except Exception:
            pass
        return uid
    return None


def _safe_room_code(raw):
    if not raw:
        return ""
    code = str(raw).strip().upper()
    code = "".join(c for c in code if c.isalnum() or c in "-_")[:16]
    return code


def _remove_peer_from_rooms(uid: str):
    with rooms_lock:
        for room_code, members in list(rooms.items()):
            if uid in members:
                members.discard(uid)
                if not members:
                    rooms.pop(room_code, None)


# ===================== 路由（完全保留原有功能） =====================
@app.route("/live2d/<path:filename>")
def live2d_static(filename):
    return send_from_directory(os.path.join(STATIC_FOLDER, 'live2d'), filename)

@app.route("/emoticons/<filename>")
def emoticons(filename):
    return send_from_directory(os.path.join(STATIC_FOLDER, 'emoticons'), filename)


# ===================== 标题图 =====================

# 允许作为标题图的图片扩展名
NAV_ICON_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg"}
# 标题图文件大小上限（2MB）——标题图不该很大，超大文件大多是用错了
NAV_ICON_MAX_BYTES = 2 * 1024 * 1024


def _nav_icon_token(path):
    """为某个本地图片路径生成签名。

    为什么要签名：本地自定义标题图位于静态目录之外，必须开一个路由把它读出来。
    如果路由直接接受任意路径，那就成了"任意文件读取"漏洞——任何人都能拿
    这个接口去读服务器上的任意文件。这里用启动时生成的站点密钥签名，
    只有「用户自己在设置里填过的路径」才会被签名，路由端校验签名后才返回内容。
    """
    secret = _get_site_secret()
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    mac = hmac.new(secret, os.path.abspath(path).encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:32]


def nav_icon_url(value):
    """把配置里的标题图路径解析成浏览器可访问的 URL。

    只接受本地图片路径，如 "D:\\\\我的图\\\\home.png" 或 "/home/me/logo.png"。
    返回空字符串表示"不换图"（继续显示原来的符号与文字）。
    """
    value = (value or "").strip()
    if not value:
        return ""

    looks_like_path = (
        os.path.isabs(value)
        or (len(value) > 2 and value[1] == ":" and value[2] in ("\\", "/"))
    )
    if looks_like_path:
        ext = os.path.splitext(value)[1].lower()
        if ext not in NAV_ICON_EXTENSIONS:
            return ""
        if not os.path.isfile(value):
            return ""
        try:
            if os.path.getsize(value) > NAV_ICON_MAX_BYTES:
                return ""
        except OSError:
            return ""
        return f"/nav_icon?p={_nav_icon_token(value)}&v={int(os.path.getmtime(value))}"

    return ""


def get_nav_titles():
    """返回 {页面标识: 标题图URL}。

    标题图片要替代整块标题，必须是用户自己准备的图；签名与大小限制逻辑
    由 nav_icon_url 统一处理。
    """
    configured = CONFIG.get("nav_titles") or {}
    out = {}
    for page in NAV_ICON_PAGES:
        url = nav_icon_url(configured.get(page, ""))
        if url:
            out[page] = url
    return out


def _configured_local_images():
    """收集配置里所有登记过的本地标题图路径。

    签名路由只认这些路径。若某类图片没被收集进来，对应图片就会取到 404——
    标题图曾经就因为这个漏掉而显示不出来。
    """
    paths = []
    for key in ("nav_titles",):
        for value in (CONFIG.get(key) or {}).values():
            value = (value or "").strip()
            if not value:
                continue
            if os.path.isabs(value) or (
                len(value) > 2 and value[1] == ":" and value[2] in ("\\", "/")
            ):
                paths.append(value)
    return paths


@app.route("/nav_icon")
def nav_icon():
    """按签名提供本地标题图。

    只认签名，不认路径——请求里根本没有路径参数，所以无法用它去读别的文件。
    """
    token = (request.args.get("p") or "").strip()
    if not token:
        abort(404)

    for value in _configured_local_images():
        if hmac.compare_digest(_nav_icon_token(value), token):
            directory = os.path.dirname(os.path.abspath(value))
            filename = os.path.basename(value)
            if not os.path.isfile(os.path.join(directory, filename)):
                abort(404)
            resp = make_response(send_from_directory(directory, filename))
            # 图片基本不变，加上长缓存；换图时 URL 里的 v= 会变，浏览器自然会重新取
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp

    abort(404)


@app.route("/p2p/join")
def p2p_join():
    clean_expired_files()
    cleanup_expired_peers()

    uid = _get_p2p_uid(create_if_missing=True)
    addr = request.remote_addr or "unknown"
    ua = request.headers.get("User-Agent", "")[:120]
    nick = request.args.get("nick", "").strip()[:32]
    room = _safe_room_code(request.args.get("room", ""))

    with peer_lock:
        old_info = peers.get(uid) or {}
        old_room = old_info.get("room") if isinstance(old_info, dict) else None
        info = {"addr": addr, "online": time.time(), "nick": nick or old_info.get("nick", "") or uid[:8],
                "room": room or old_room or "", "ua": ua}
        peers[uid] = info
        new_room = info["room"]
        if new_room:
            with rooms_lock:
                if old_room and old_room != new_room and old_room in rooms:
                    rooms[old_room].discard(uid)
                    if not rooms[old_room]:
                        rooms.pop(old_room, None)
                rooms[new_room].add(uid)

    with peer_lock:
        if room:
            member_set = set(rooms.get(room, set()))
            peer_list = [{"uid": u, "nick": peers[u]["nick"], "self": u == uid}
                         for u in member_set if u in peers]
        else:
            peer_list = [{"uid": u, "nick": info.get("nick", u[:8]), "self": u == uid}
                         for u, info in peers.items()]

    return jsonify({"code": 0, "uid": uid, "nick": (peers.get(uid) or {}).get("nick", ""),
                    "room": room, "peers": peer_list})


@app.route("/p2p/leave", methods=["GET", "POST"])
def p2p_leave():
    uid = _get_p2p_uid(create_if_missing=False)
    if uid:
        with peer_lock:
            peers.pop(uid, None)
            signal_box.pop(uid, None)
        _remove_peer_from_rooms(uid)
    cleanup_expired_peers()
    return jsonify({"code": 0})


@app.route("/p2p/heartbeat")
def p2p_heartbeat():
    uid = _get_p2p_uid(create_if_missing=False)
    if not uid:
        return jsonify({"code": 1, "msg": "not joined"}), 404
    addr = request.remote_addr or "unknown"
    with peer_lock:
        if uid in peers:
            peers[uid]["online"] = time.time()
            peers[uid]["addr"] = addr
    return jsonify({"code": 0})


@app.route("/p2p/list")
def p2p_list():
    cleanup_expired_peers()
    uid = _get_p2p_uid(create_if_missing=False)
    my_info = peers.get(uid) if uid else None
    my_room = (my_info or {}).get("room") if isinstance(my_info, dict) else None

    now = time.time()
    room_arg = _safe_room_code(request.args.get("room", "")) or my_room or ""
    with peer_lock, rooms_lock:
        if room_arg:
            member_set = set(rooms.get(room_arg, set()))
            online = [u for u in member_set if u in peers and now - peers[u]["online"] < PEER_TIMEOUT]
        else:
            online = [u for u, info in peers.items() if now - info["online"] < PEER_TIMEOUT]
        result = [{"uid": u,
                   "nick": peers[u].get("nick", u[:8]) if u in peers else u[:8],
                   "self": (u == uid)}
                  for u in online]
    return jsonify({"code": 0, "list": result, "room": room_arg})


@app.route("/p2p/signal/send", methods=["POST"])
def p2p_signal_send():
    if not request.is_json:
        return jsonify({"code": 1, "msg": "请求格式错误"})
    data = request.get_json(silent=True) or {}
    to = data.get("to")
    frm = _get_p2p_uid(create_if_missing=False)
    if not to or not frm:
        return jsonify({"code": 1, "msg": "参数错误（请先加入在线）"})
    with peer_lock:
        if frm not in peers:
            # 未登记先自动登记一次，避免 session 丢失导致无法发信
            peers[frm] = {"addr": request.remote_addr or "", "online": time.time(),
                          "nick": frm[:8], "room": "", "ua": request.headers.get("User-Agent", "")[:120]}
        peers[frm]["online"] = time.time()
        if to not in signal_box:
            signal_box[to] = []
        if len(signal_box[to]) >= MAX_SIGNAL_QUEUE:
            return jsonify({"code": 1, "msg": "信号队列已满"}), 429
        data["frm"] = frm
        signal_box[to].append({"data": data, "time": time.time()})
    return jsonify({"code": 0})


@app.route("/p2p/signal/recv")
def p2p_signal_recv():
    uid = _get_p2p_uid(create_if_missing=False)
    if not uid:
        return jsonify({})
    # 顺便心跳，减少因 session 丢失/页面切后台过久被踢出
    with peer_lock:
        if uid in peers:
            peers[uid]["online"] = time.time()
        if uid not in signal_box or len(signal_box[uid]) == 0:
            return jsonify({})
        now = time.time()
        while signal_box[uid] and now - signal_box[uid][0].get("time", 0) > SIGNAL_TIMEOUT:
            signal_box[uid].pop(0)
            if not signal_box[uid]:
                return jsonify({})
        msg = signal_box[uid].pop(0)
    return jsonify(msg.get("data", {}))

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
    try:
        file.save(save_path)
        size = os.path.getsize(save_path)
    except Exception as e:
        logger.warning(f"文件上传失败: {e}")
        return jsonify({"code":1,"msg":"文件保存失败"})
    if not session.get("p2p_uid"):
        session["p2p_uid"] = uuid.uuid4().hex
    owner = session["p2p_uid"]
    with file_lock:
        temp_files[fid] = {"name":filename,"size":format_size(size),"path":save_path,"upload_time":time.time(),"owner":owner}
    save_temp_files()
    return jsonify({"code":0,"fid":fid,"url":f"/temp/download/{fid}","name":html.escape(filename)})

@app.route("/temp/download/<fid>")
def temp_download(fid):
    client_identity = _get_client_identity()
    client_ip = _get_client_ip()
    uid = session.get("p2p_uid")

    if not _check_download_rate_limit(client_identity, fid):
        _log_download(client_ip, fid, uid, "rate-limited")
        return "Too Many Requests", 429

    clean_expired_files()
    with file_lock:
        info = temp_files.get(fid)
        if not info:
            _log_download(client_ip, fid, uid, "not-found")
            return "Not Found", 404
        upload_time = info.get("upload_time", 0)
        if time.time() - upload_time > FILE_EXPIRE:
            temp_files.pop(fid, None)
            _log_download(client_ip, fid, uid, "expired")
            return "Not Found", 404
        file_name = info["name"]

    try:
        _log_download(client_ip, fid, uid, "success")
        return send_from_directory(UPLOAD_TEMP_FOLDER, fid, as_attachment=True, download_name=file_name)
    except Exception as e:
        # 文件在取完元数据到真正发送之间可能被清理线程删掉，属正常竞态；
        # 记录一下，避免"下载 404 但日志里什么都没有"的情况。
        _log_download(client_ip, fid, uid, "file-error")
        logger.info(f"发送临时文件 {fid} 失败: {e}")
        return "Not Found", 404

@app.route("/temp/delete/<fid>", methods=["POST"])
def temp_delete(fid):
    clean_expired_files()
    with file_lock:
        info = temp_files.get(fid)
        if not info:
            return jsonify({"code":1,"msg":"不存在"}), 404
        owner = info.get("owner")
        if not owner or owner != session.get("p2p_uid"):
            return jsonify({"code":1,"msg":"无权操作"}), 403
        path = info.get("path")
        temp_files.pop(fid, None)
    # 删磁盘放到锁外，避免 os.remove 卡住时把其他上传/下载请求一起堵死
    if path:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"删除临时文件 {fid} 失败: {e}")
    save_temp_files()
    return jsonify({"code":0,"msg":"删除成功"})

@app.route("/temp/list")
def temp_list():
    clean_expired_files()
    now = time.time()
    owner = session.get("p2p_uid")
    res = []
    with file_lock:
        for fid, info in temp_files.items():
            if owner and info.get("owner") != owner:
                continue
            left = int(FILE_EXPIRE - (now - info["upload_time"]))
            if left < 0:
                continue
            res.append({"fid":fid,"name":html.escape(info["name"]),"left_min":left//60,"left_sec":left%60})
    return jsonify({"code":0,"list":res})

@app.route("/transfer")
def transfer_page():
    return render_template("send_file.html")

chat_create_limits = {}
chat_create_limits_lock = Lock()

def get_client_ip():
    if BEHIND_PROXY:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        xri = request.headers.get("X-Real-IP", "")
        if xri:
            return xri.strip()
    return request.remote_addr or "unknown"

# ===================== 聊天室路由 =====================
@app.route("/chat")
def chat_page():
    return render_template("chat.html", title=HOME_TITLE)

@app.route("/chat/create", methods=["POST"])
def chat_create():
    client_ip = get_client_ip()
    now = time.time()

    # 限流计数必须加锁：原来无锁读改写，多线程同时创建房间时能绕过上限。
    # 这里不再用 "in" 做外层判断——那会让某个 IP 的首次请求完全跳过限流。
    with chat_create_limits_lock:
        count, start_time = chat_create_limits.get(client_ip, (0, now))
        if now - start_time < CHAT_CREATE_RATE_WINDOW:
            if count >= CHAT_CREATE_RATE_LIMIT:
                return jsonify({"code":1,"msg":"创建房间过于频繁，请稍后再试"})
            chat_create_limits[client_ip] = (count + 1, start_time)
        else:
            chat_create_limits[client_ip] = (1, now)

    if not request.is_json:
        return jsonify({"code":1,"msg":"请求格式错误"})
    data = request.get_json(silent=True) or {}
    room_name = data.get("name", "").strip()[:30]
    password = data.get("password", "")
    if not room_name:
        return jsonify({"code":1,"msg":"房间名称不能为空"})
    clean_expired_rooms()
    with chat_lock:
        for rid, room in chat_rooms.items():
            if room["name"] == room_name:
                return jsonify({"code":1,"msg":"房间名称已存在"})
        room_id = str(uuid.uuid4())[:12]
        password_hash = None
        if password:
            password_hash = hashlib.sha256(password.encode() + app.secret_key.encode()).hexdigest()
        chat_rooms[room_id] = {
            "name": room_name,
            "password_hash": password_hash,
            "created": time.time(),
            "last_activity": time.time(),
            "messages": deque(maxlen=MAX_CHAT_MESSAGES),
            "users": set()
        }
    save_chat_data()
    return jsonify({"code":0,"room_id":room_id,"name":html.escape(room_name)})

@app.route("/chat/list")
def chat_list():
    clean_expired_rooms()
    res = []
    with chat_lock:
        for rid, room in chat_rooms.items():
            res.append({
                "room_id": rid,
                "name": html.escape(room["name"]),
                "has_password": room["password_hash"] is not None,
                "message_count": len(room["messages"]),
                "user_count": len(room["users"])
            })
    return jsonify({"code":0,"list":res})

def _format_chat_messages(messages):
    escaped = []
    for m in messages:
        msg_copy = dict(m)
        msg_copy["nick"] = html.escape(m["nick"])
        escaped.append(msg_copy)
    return escaped

@app.route("/chat/join", methods=["POST"])
def chat_join():
    if not request.is_json:
        return jsonify({"code":1,"msg":"请求格式错误"})
    data = request.get_json(silent=True) or {}
    room_id = data.get("room_id", "")
    password = data.get("password", "")
    if not room_id:
        return jsonify({"code":1,"msg":"房间ID不能为空"})
    clean_expired_rooms()
    with chat_lock:
        room = chat_rooms.get(room_id)
        if not room:
            return jsonify({"code":1,"msg":"房间不存在"})
        if room["password_hash"]:
            test_hash = hashlib.sha256(password.encode() + app.secret_key.encode()).hexdigest()
            if test_hash != room["password_hash"]:
                return jsonify({"code":1,"msg":"密码错误"})
        nick = get_nickname()
        for rid, r in chat_rooms.items():
            if rid != room_id:
                r["users"].discard(nick)
        room["users"].discard(nick)
        room["users"].add(nick)
        room["last_activity"] = time.time()
        messages = list(room["messages"])
    save_chat_data()
    escaped_messages = _format_chat_messages(messages)
    return jsonify({"code":0,"room_id":room_id,"name":html.escape(room["name"]),"messages":escaped_messages})

def deliver_message(room_id, nick, content, broadcast=True):
    """把一条消息投递进房间——所有消息来源的唯一入口。

    WebSocket、HTTP 轮询、以及将来任何外部来源（IRC 桥接等）都应当调用这里，
    而不是各自复制一套"构造消息 + 维护成员 + 写盘 + 广播"的逻辑。
    这样新接入一种来源时就不需要再抄一遍，也不会出现某条路径少做了校验。

    参数:
        room_id:   目标房间 ID
        nick:      发送者昵称（会自动转义）
        content:   消息原文（会自动做 BBCode 净化）
        broadcast: 是否向该房间的 WebSocket 连接广播（HTTP 轮询者从房间读取，无需广播）

    返回:
        成功时返回消息 dict；房间不存在、内容为空/超长时返回 None。
    """
    if not room_id or not isinstance(content, str):
        return None
    content = content.strip()
    if not content:
        return None
    if len(content) > MAX_MESSAGE_LENGTH:
        return None

    nick = (nick or "").strip()[:20] or "匿名"

    with chat_lock:
        room = chat_rooms.get(room_id)
        if not room:
            return None
        # 同一昵称同一时刻只出现在一个房间，避免"幽灵成员"
        for rid, r in chat_rooms.items():
            if rid != room_id:
                r["users"].discard(nick)
        room["users"].add(nick)
        room["last_activity"] = time.time()
        msg = {
            "id": str(uuid.uuid4())[:12],
            "nick": html.escape(nick),
            "content": sanitize_bbcode(content),
            "timestamp": time.time(),
        }
        room["messages"].append(msg)

    save_chat_data()

    if broadcast:
        _broadcast_to_room(room_id, {"type": "message", **msg})
    return msg


def _broadcast_to_room(room_id, payload):
    """把一条消息推给房间内所有 WebSocket 连接。单个连接失败不影响其它连接。"""
    try:
        data = json.dumps(payload)
    except Exception:
        return
    try:
        with ws_rooms_lock:
            conns = list(ws_rooms.get(room_id, set()))
    except NameError:
        # ws_rooms 尚未初始化（例如在纯 HTTP 场景下导入）：此时无连接可推
        return
    for conn in conns:
        try:
            conn.send(data)
        except Exception:
            pass


@app.route("/chat/send", methods=["POST"])
def chat_send():
    if not request.is_json:
        return jsonify({"code":1,"msg":"请求格式错误"})
    data = request.get_json(silent=True) or {}
    room_id = data.get("room_id", "")
    content = data.get("content", "").strip()
    if not room_id:
        return jsonify({"code":1,"msg":"房间ID不能为空"})
    if not content:
        return jsonify({"code":1,"msg":"消息内容不能为空"})
    if len(content) > MAX_MESSAGE_LENGTH:
        return jsonify({"code":1,"msg":"消息内容过长"})
    clean_expired_rooms()
    ip = _get_client_ip()
    rate_key = f"chat:{room_id}:{ip}"
    if not rate_limiter.allow(rate_key):
        return jsonify({"code":1,"msg":"发送过于频繁"}), 429

    if room_id not in chat_rooms:
        return jsonify({"code":1,"msg":"房间不存在"})

    msg = deliver_message(room_id, get_nickname(), content)
    if msg is None:
        return jsonify({"code":1,"msg":"消息发送失败"})
    return jsonify({"code":0,"message":msg})

@app.route("/chat/recv")
def chat_recv():
    room_id = request.args.get("room_id", "")
    last_id = request.args.get("last_id", "")
    if not room_id:
        return jsonify({"code":1,"msg":"房间ID不能为空"})
    clean_expired_rooms()
    nick = get_nickname()
    now = time.time()
    with http_chat_lock:
        http_chat_sessions[f"{room_id}:{nick}"] = now
        expired = [k for k, v in http_chat_sessions.items() if now - v > HTTP_CHAT_TIMEOUT]
        for k in expired:
            del http_chat_sessions[k]
    with chat_lock:
        room = chat_rooms.get(room_id)
        if not room:
            return jsonify({"code":1,"msg":"房间不存在"})
        messages = list(room["messages"])
        if last_id:
            idx = -1
            for i, m in enumerate(messages):
                if m["id"] == last_id:
                    idx = i
                    break
            if idx >= 0:
                new_msgs = messages[idx+1:]
            else:
                new_msgs = messages[-10:]
        else:
            new_msgs = messages[-50:]
    return jsonify({"code":0,"messages":_format_chat_messages(new_msgs)})

@app.route("/chat/leave", methods=["POST"])
def chat_leave():
    if not request.is_json:
        return jsonify({"code":1,"msg":"请求格式错误"})
    data = request.get_json(silent=True) or {}
    room_id = data.get("room_id", "")
    if not room_id:
        return jsonify({"code":1,"msg":"房间ID不能为空"})
    with chat_lock:
        room = chat_rooms.get(room_id)
        if room:
            nick = get_nickname()
            room["users"].discard(nick)
    save_chat_data()
    return jsonify({"code":0})

@app.route("/chat/set_nick", methods=["POST"])
def chat_set_nick():
    if not request.is_json:
        return jsonify({"code":1,"msg":"请求格式错误"})
    data = request.get_json(silent=True) or {}
    nick = data.get("nick", "").strip()
    new_nick = set_nickname(nick)
    return jsonify({"code":0,"nick":html.escape(new_nick)})

# ===================== 管理账号（仅用于删除问题消息） =====================
def _admin_cfg():
    return CONFIG.get("admin", {}) or {}

def _admin_auth_modes():
    """返回该管理账号启用的验证方式。

    密码与动态验证码是"二选一或全选"关系：
    - 只配了密码 -> 仅校验密码
    - 只配了动态验证码 -> 仅校验验证码
    - 两者都配 -> 两者都要通过
    这样用户不必为了用上管理功能被迫安装验证器 App。
    """
    a = _admin_cfg()
    return {
        "password": bool(a.get("password_hash")),
        "totp": bool(a.get("totp_secret")),
    }

def _admin_is_enabled():
    a = _admin_cfg()
    if not a.get("enabled") or not a.get("username"):
        return False
    modes = _admin_auth_modes()
    return modes["password"] or modes["totp"]

def _admin_required():
    if not _admin_is_enabled():
        return jsonify({"code":1,"msg":"管理功能未启用"}), 403
    if not session.get("admin_authed"):
        return jsonify({"code":1,"msg":"未登录"}), 403
    return None

@app.route("/admin/status")
def admin_status():
    """前端据此决定是否显示管理入口、以及需要填写哪些字段（不泄露任何密钥）。"""
    modes = _admin_auth_modes()
    return jsonify({"code":0, "enabled": _admin_is_enabled(),
                    "authed": bool(session.get("admin_authed")),
                    "need_password": modes["password"],
                    "need_totp": modes["totp"]})

@app.route("/admin/login", methods=["POST"])
def admin_login():
    if not _admin_is_enabled():
        return jsonify({"code":1,"msg":"管理功能未启用"}), 403
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    code = str(data.get("totp_code", "")).strip()
    a = _admin_cfg()
    modes = _admin_auth_modes()

    if not username or username != a.get("username"):
        return jsonify({"code":1,"msg":"用户名或密码错误"}), 401

    # 仅校验已配置的验证方式，未配置的方式不参与校验
    bad_msg = "用户名或密码错误"
    if modes["password"]:
        pwd_hash = hashlib.sha256((password + app.secret_key).encode()).hexdigest()
        if not hmac.compare_digest(pwd_hash, a.get("password_hash", "")):
            return jsonify({"code":1,"msg":bad_msg}), 401

    if modes["totp"]:
        if pyotp is None:
            return jsonify({"code":1,"msg":"服务器缺少 pyotp 依赖，无法校验动态验证码"}), 500
        if not code:
            return jsonify({"code":1,"msg":"请输入动态验证码"}), 401
        try:
            if not pyotp.TOTP(a.get("totp_secret", "")).verify(code, valid_window=1):
                return jsonify({"code":1,"msg":"动态验证码错误"}), 401
        except Exception:
            return jsonify({"code":1,"msg":"动态验证码校验失败"}), 401

    session["admin_authed"] = True
    session.permanent = False
    logger.info("管理员登录成功")
    return jsonify({"code":0,"msg":"登录成功"})

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_authed", None)
    return jsonify({"code":0})

@app.route("/chat/delete_message/<msg_id>", methods=["POST"])
def chat_delete_message(msg_id):
    """管理员删除指定消息（按全局唯一 id 匹配）。"""
    guard = _admin_required()
    if guard is not None:
        return guard
    if not msg_id or len(msg_id) > 64:
        return jsonify({"code":1,"msg":"消息ID非法"})
    found = False
    with chat_lock:
        for rid, room in chat_rooms.items():
            msgs = room["messages"]
            for i, m in enumerate(list(msgs)):
                if m.get("id") == msg_id:
                    try:
                        msgs.remove(m)
                    except ValueError:
                        del msgs[i]
                    found = True
                    break
            if found:
                break
    if not found:
        return jsonify({"code":1,"msg":"消息不存在"})
    save_chat_data()
    logger.info(f"管理员删除消息: {msg_id}")
    return jsonify({"code":0,"msg":"已删除"})

# ===================== WebSocket 聊天室 =====================
if SOCK_AVAILABLE:
    @sock.route('/ws/chat')
    def ws_chat(ws):
        nick = session.get("chat_nick", "")
        if not nick:
            try:
                ws.send(json.dumps({"type":"error","message":"请先设置昵称"}))
            except Exception:
                pass
            return
        current_room = None
        rate_counter = {"count": 0, "start": time.time()}

        try:
            while True:
                data_str = ws.receive()
                if not data_str:
                    break
                data = json.loads(data_str)
                msg_type = data.get("type", "")

                if msg_type == "join":
                    room_id = data.get("room_id", "")
                    password = data.get("password", "")
                    if not room_id:
                        ws.send(json.dumps({"type":"error","message":"房间ID不能为空"}))
                        continue
                    clean_expired_rooms()
                    with chat_lock:
                        room = chat_rooms.get(room_id)
                        if not room:
                            ws.send(json.dumps({"type":"error","message":"房间不存在"}))
                            continue
                        if room["password_hash"]:
                            test_hash = hashlib.sha256(password.encode() + app.secret_key.encode()).hexdigest()
                            if test_hash != room["password_hash"]:
                                ws.send(json.dumps({"type":"error","message":"密码错误"}))
                                continue
                        for rid, r in chat_rooms.items():
                            if rid != room_id:
                                r["users"].discard(nick)
                        room["users"].discard(nick)
                        room["users"].add(nick)
                        room["last_activity"] = time.time()
                        messages = list(room["messages"])
                    current_room = room_id
                    with ws_rooms_lock:
                        if room_id not in ws_rooms:
                            ws_rooms[room_id] = set()
                        ws_rooms[room_id].add(ws)
                    escaped = _format_chat_messages(messages)
                    ws.send(json.dumps({"type":"joined","room_id":room_id,"name":html.escape(room["name"]),"messages":escaped}))
                    save_chat_data()

                elif msg_type == "message":
                    if not current_room:
                        ws.send(json.dumps({"type":"error","message":"请先加入房间"}))
                        continue
                    content = data.get("content", "").strip()
                    if not content:
                        continue
                    if len(content) > MAX_MESSAGE_LENGTH:
                        ws.send(json.dumps({"type":"error","message":"消息内容过长"}))
                        continue
                    now = time.time()
                    if now - rate_counter["start"] > CHAT_MESSAGE_RATE_WINDOW:
                        rate_counter["count"] = 0
                        rate_counter["start"] = now
                    rate_counter["count"] += 1
                    if rate_counter["count"] > CHAT_MESSAGE_RATE:
                        ws.send(json.dumps({"type":"error","message":"发送过于频繁"}))
                        continue
                    clean_expired_rooms()
                    # 与 HTTP 路径共用同一个投递入口，避免两边逻辑走偏
                    msg = deliver_message(current_room, nick, content, broadcast=False)
                    if msg is None:
                        ws.send(json.dumps({"type":"error","message":"消息发送失败"}))
                        continue
                    broadcast = json.dumps({"type":"message", **msg})
                    with ws_rooms_lock:
                        room_conns = ws_rooms.get(current_room, set()).copy()
                    for conn in room_conns:
                        try:
                            conn.send(broadcast)
                        except Exception:
                            pass

                elif msg_type == "leave":
                    break

                else:
                    ws.send(json.dumps({"type":"error","message":"未知消息类型"}))

        except Exception:
            pass
        finally:
            if current_room:
                with ws_rooms_lock:
                    if current_room in ws_rooms:
                        ws_rooms[current_room].discard(ws)
                        if not ws_rooms[current_room]:
                            del ws_rooms[current_room]
                with chat_lock:
                    room = chat_rooms.get(current_room)
                    if room:
                        room["users"].discard(nick)
                save_chat_data()

if not SOCK_AVAILABLE:
    @app.route('/ws/chat')
    def ws_chat_unavailable():
        return jsonify({"error": "WebSocket unavailable", "message": "当前服务器不支持WebSocket，请使用HTTP轮询模式"}), 503

@app.route("/")
def index():
    # 首页也列出已挂载的虚拟目录，省去先进"文件浏览"再找入口的麻烦
    mounted = []
    for vname in sorted(VIRTUAL_DIRS.keys()):
        if vname in HIDDEN_FOLDERS:
            continue
        mounted.append({
            "name": DISPLAY_NAMES.get(vname, vname),
            "url": join_url_path("", vname),
        })
    return render_template("index.html", title=HOME_TITLE, mounted_dirs=mounted)

def join_url_path(base, name):
    """把父路径与子项名拼成一个 URL 路径并做百分号编码。

    这里刻意不使用 os.path.join：虚拟目录的别名可以带冒号（例如把 D 盘
    根目录挂成别名 "D:"）。在 Windows 上 os.path.join("D:", "子项")
    得到的是 "D:子项"——分隔符被吃掉了，生成出来的链接点开就是 404。
    URL 用的是正斜杠，与运行平台无关，所以这里手工拼。
    """
    base = (base or "").strip("/")
    child = str(name).strip("/")
    rel = f"{base}/{child}" if base else child
    return "/files/" + urllib.parse.quote(rel, safe="/")

@app.route('/files/', defaults={'relative_path': ''})
@app.route('/files/<path:relative_path>')
def serve_directory(relative_path):
    full = f'/files/{relative_path}' if relative_path else '/files/'
    target = get_safe_path(full)
    if os.path.isfile(target):
        try:
            return send_from_directory(os.path.dirname(target), os.path.basename(target), as_attachment=False)
        except Exception:
            abort(404)
    if not os.path.isdir(target):
        abort(404)
    data = {"path": full, "parent_path": None, "items": []}
    if relative_path:
        parent = "/files/" + "/".join(relative_path.rstrip('/').split('/')[:-1])
        data["parent_path"] = parent
    try:
        items = os.listdir(target)
    except PermissionError:
        abort(403)
    except Exception:
        abort(404)
    # 过滤：以 . 开头的隐藏项 + 配置中的隐藏文件夹（不列出，仍可直接访问）
    def _visible(nm):
        return (not nm.startswith('.')) and (nm not in HIDDEN_FOLDERS)
    dirs = sorted([i for i in items if _visible(i) and os.path.isdir(os.path.join(target, i))])
    files = sorted([i for i in items if _visible(i) and os.path.isfile(os.path.join(target, i))])
    # 虚拟目录只在共享根目录展示（作为别名入口）
    is_share_root = (os.path.abspath(target) == os.path.abspath(SHARE_FOLDER))
    if is_share_root:
        existing = set(dirs)
        for vname in sorted(VIRTUAL_DIRS.keys()):
            if vname not in existing and vname not in HIDDEN_FOLDERS:
                dirs.append(vname)
        dirs = sorted(dirs)
    for i in dirs:
        data["items"].append({
            "name": DISPLAY_NAMES.get(i, i),
            "url": join_url_path(relative_path, i),
            "is_dir": True, "size": "", "mtime": ""
        })
    for i in files:
        p = os.path.join(target, i)
        try:
            s = os.path.getsize(p)
            m = os.path.getmtime(p)
        except Exception:
            continue
        data["items"].append({
            "name": DISPLAY_NAMES.get(i, i),
            "url": join_url_path(relative_path, i),
            "is_dir": False, "size": format_size(s), "mtime": format_mtime(m)
        })
    # 目录列表页也要用标题图。render_template_string 虽然会走上下文处理器，
    # 但这里显式传入更稳妥（且便于单测）。
    data = dict(data)
    data["nav_titles"] = get_nav_titles()
    return render_template_string('''
<!DOCTYPE HTML><html><head><meta charset="utf-8"><title>目录：{{ path }}</title>
<style>body{font-family:sans-serif;padding:20px;}
.title-banner{display:inline-block;height:auto;max-height:40px;max-width:min(70vw,520px);width:auto;object-fit:contain;vertical-align:middle;}
.title-link{display:inline-flex;align-items:center;gap:8px;color:inherit;text-decoration:none;cursor:pointer;}
.title-link:hover{opacity:0.86;}
ul{list-style:none;padding:0;}li{display:flex;justify-content:space-between;padding:6px 0;}a{flex:1;text-decoration:none;color:#0066cc;}a:hover{text-decoration:underline;}.file-info{color:#666;font-size:13px;}
.dirlink{display:inline-flex;align-items:center;}</style></head>
<body><h1>{% if nav_titles.get('files') %}<a class="title-link" href="/" title="回到首页"><img class="title-banner" src="{{ nav_titles['files'] }}" alt="文件浏览" onerror="this.style.display='none';this.nextElementSibling.style.display='inline';"><span style="display:none;">📁 文件浏览</span></a>{% else %}<a class="title-link" href="/" title="回到首页">📁 文件浏览</a>{% endif %}：{{ path }}</h1><hr><ul>
{% if parent_path %}<li><a href="{{ parent_path }}">../</a><span class="file-info">目录</span></li>{% endif %}
{% for item in items %}<li><a href="{{ item.url }}">{{ item.name }}{{ "/" if item.is_dir else "" }}</a>
<span class="file-info">{% if item.is_dir %}目录{% else %}{{ item.size }} • {{ item.mtime }}{% endif %}</span></li>{% endfor %}
</ul><hr><span class="dirlink"><a href="/">首页</a></span> | <span class="dirlink"><a href="/transfer">传输中心</a></span><script src="/live2d/dist/autoload.js?v=2"></script></body></html>''', **data)

# ========== 错误页 ==========
@app.errorhandler(404)
def error_404(e):
    error_params = {"title":"404 Not found","error_code":404,"browser_status":{"status":"ok"},"cloudflare_status":{"status":"ok","location":where_is_it},"host_status":{"status":"error","location":html.escape(request.host or ""),"status_text":"¯\\(o_o)/¯"},"error_source":"host","what_happened":"<p>检察：咋回事,一点消息也没有啊</p><p>服务器：东西呢?</p><p>硬盘：我不到啊</p>","what_can_i_do":"I don't know..."}
    try:
        if render_cf_error_page:
            return render_cf_error_page(error_params), 404
        return "404 Not Found", 404
    except Exception:
        return "404 Not Found", 404

@app.errorhandler(500)
def error_500(e):
    error_params = {"title":"500 Internal Server Error","error_code":500,"browser_status":{"status":"ok"},"host_status":{"status":"ok","location":html.escape(request.host or "")},"cloudflare_status":{"status":"error","location":where_is_it,"status_text":"I Don't!"},"error_source":"cloudflare","what_happened":"<p>检察：咋回事,一点消息也没有啊</p><p>服务器：（阴暗扭曲的爬行）（停在原地）（发出耀眼白光）（“智慧”地说）啊？</p>","what_can_i_do":"You don't need to know..."}
    try:
        if render_cf_error_page:
            return render_cf_error_page(error_params), 500
        return "500 Internal Server Error", 500
    except Exception:
        return "500 Internal Server Error", 500

@app.errorhandler(418)
def error_418(e):
    error_params = {"title":"418 I'm a Teapot","error_code":418,"browser_status":{"status":"ok"},"host_status":{"status":"error","location":html.escape(request.host or ""),"status_text":"Teapot"},"cloudflare_status":{"status":"error","location":where_is_it,"status_text":"Teapot"},"error_source":"cloudflare","what_happened":"服务器不能煮咖啡因为它是一把茶壶 (qwq)","what_can_i_do":"去另寻一台咖啡机吧awa"}
    try:
        if render_cf_error_page:
            return render_cf_error_page(error_params), 418
        return "418 I'm a Teapot", 418
    except Exception:
        return "418 I'm a Teapot", 418

@app.errorhandler(413)
def error_413(e):
    return jsonify({"code": 1, "msg": "文件过大"}), 413

@app.errorhandler(RuntimeError)
def handle_runtime_error(e):
    err_msg = str(e)
    if "Cannot obtain socket from WSGI environment" in err_msg:
        logger.info("WebSocket 升级请求被拒绝 (WSGI服务器不支持WebSocket)")
        return jsonify({"error": "WebSocket unavailable", "message": "当前服务器不支持WebSocket，请使用HTTP轮询模式"}), 503
    logger.error(f"RuntimeError: {err_msg}")
    return jsonify({"error": "服务器内部错误"}), 500

# ===================== 启动服务 =====================
def _fix_pem_file(filepath):
    """Fix common PEM file issues: strip BOM, convert PKCS#1 to PKCS#8, return fixed content or None."""
    if not filepath or not os.path.isfile(filepath):
        return None
    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
        # Strip UTF-8 BOM
        if raw.startswith(b'\xef\xbb\xbf'):
            raw = raw[3:]
            logger.info(f"PEM 文件 BOM 已剥离: {filepath}")
        # Try to decode and re-encode as clean PEM
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')

        # Convert PKCS#1 RSA private key to PKCS#8 if cryptography is available
        if '-----BEGIN RSA PRIVATE KEY-----' in text:
            try:
                from cryptography.hazmat.primitives.serialization import (
                    load_pem_private_key, Encoding, PrivateFormat, NoEncryption
                )
                key = load_pem_private_key(raw, password=None)
                converted = key.private_bytes(
                    encoding=Encoding.PEM,
                    format=PrivateFormat.PKCS8,
                    encryption_algorithm=NoEncryption()
                )
                logger.info(f"PKCS#1 密钥已转换为 PKCS#8 格式: {filepath}")
                return converted
            except ImportError:
                logger.warning("cryptography 库未安装，无法自动转换 PKCS#1 密钥")
            except Exception as e:
                logger.warning(f"PKCS#1 密钥转换失败: {e}")

        # Also strip BOM from text and clean up
        text = text.lstrip('\ufeff').lstrip('\r').strip()
        # Normalize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        return text.encode('utf-8')
    except Exception:
        return None

def _is_pem_file(filepath):
    """Check if a file contains PEM-formatted content."""
    if not filepath or not os.path.isfile(filepath):
        return False
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(4096)
        return ('-----BEGIN CERTIFICATE-----' in content or
                '-----BEGIN PRIVATE KEY-----' in content or
                '-----BEGIN PUBLIC KEY-----' in content or
                '-----BEGIN RSA PRIVATE KEY-----' in content or
                '-----BEGIN RSA PUBLIC KEY-----' in content)
    except Exception:
        return False

def _detect_pem_type(filepath):
    """Detect what PEM types are contained in a file. Returns set of type strings."""
    if not filepath or not os.path.isfile(filepath):
        return set()
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        types = set()
        if '-----BEGIN CERTIFICATE-----' in content:
            types.add('certificate')
        if '-----BEGIN PRIVATE KEY-----' in content or '-----BEGIN RSA PRIVATE KEY-----' in content:
            types.add('private_key')
        if '-----BEGIN PUBLIC KEY-----' in content or '-----BEGIN RSA PUBLIC KEY-----' in content:
            types.add('public_key')
        return types
    except Exception:
        return set()

def _detect_encrypted_key(filepath):
    """Check if a PEM private key is encrypted (requires password)."""
    if not filepath or not os.path.isfile(filepath):
        return False
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        if 'ENCRYPTED' in content or 'DEK-Info:' in content:
            return True
        if '-----BEGIN ENCRYPTED PRIVATE KEY-----' in content:
            return True
        return False
    except Exception:
        return False

def _print_ssl_diagnostics(cert_path, key_path):
    """Print detailed SSL certificate diagnostics for debugging."""
    print(f"\n[HTTPS] ===== SSL 诊断信息 =====")
    print(f"  证书文件: {cert_path}")
    print(f"  密钥文件: {key_path}")

    if cert_path and os.path.isfile(cert_path):
        cert_size = os.path.getsize(cert_path)
        cert_types = _detect_pem_type(cert_path)
        cert_encrypted = _detect_encrypted_key(cert_path)
        print(f"  证书大小: {cert_size} 字节")
        print(f"  证书类型: {cert_types}")
        print(f"  证书加密: {'是' if cert_encrypted else '否'}")
        try:
            with open(cert_path, 'r', encoding='utf-8', errors='ignore') as f:
                first_line = f.readline().strip()
                print(f"  证书首行: {first_line}")
        except Exception:
            pass
    else:
        print(f"  ⚠️ 证书文件不存在或无法访问")

    if key_path and os.path.isfile(key_path):
        key_size = os.path.getsize(key_path)
        key_types = _detect_pem_type(key_path)
        key_encrypted = _detect_encrypted_key(key_path)
        print(f"  密钥大小: {key_size} 字节")
        print(f"  密钥类型: {key_types}")
        print(f"  密钥加密: {'是 (需要密码)' if key_encrypted else '否'}")
        try:
            with open(key_path, 'r', encoding='utf-8', errors='ignore') as f:
                first_line = f.readline().strip()
                print(f"  密钥首行: {first_line}")
        except Exception:
            pass
    else:
        print(f"  ⚠️ 密钥文件不存在或无法访问")

    # Check if cert and key might match
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend
        with open(cert_path, 'rb') as f:
            cert_data = f.read()
        cert_obj = x509.load_pem_x509_certificate(cert_data, default_backend())
        pubkey = cert_obj.public_key()
        print(f"  证书主题: {cert_obj.subject.rfc4514_string()}")
        print(f"  证书有效期: {cert_obj.not_valid_before_utc} ~ {cert_obj.not_valid_after_utc}")
        print(f"  证书公钥算法: {pubkey.__class__.__name__}")
        if hasattr(pubkey, 'key_size'):
            print(f"  证书公钥大小: {pubkey.key_size} bits")
        # Check SAN
        try:
            san = cert_obj.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            names = san.value.get_all_for(x509.DNSName)
            ips = san.value.get_all_for(x509.IPAddress)
            print(f"  SAN 域名: {names}")
            if ips:
                print(f"  SAN IP: {ips}")
        except Exception:
            pass

        # Try to load private key and check match
        if key_path and os.path.isfile(key_path):
            with open(key_path, 'rb') as f:
                key_data = f.read()
            key_types = _detect_pem_type(key_path)
            is_encrypted = _detect_encrypted_key(key_path)
            if is_encrypted:
                print(f"  ⚠️ 私钥是加密的，需要在 config.xml 中配置 <key_password>")
            else:
                try:
                    if 'RSA' in str(key_types):
                        privkey = serialization.load_rsa_private_key(key_data, password=None, backend=default_backend())
                    else:
                        privkey = serialization.load_pem_private_key(key_data, password=None, backend=default_backend())
                    # Compare public keys
                    if hasattr(pubkey, 'public_bytes') and hasattr(privkey, 'public_key'):
                        cert_pub_bytes = pubkey.public_bytes(
                            encoding=serialization.Encoding.PEM,
                            format=serialization.PublicFormat.SubjectPublicKeyInfo
                        )
                        key_pub_bytes = privkey.public_key().public_bytes(
                            encoding=serialization.Encoding.PEM,
                            format=serialization.PublicFormat.SubjectPublicKeyInfo
                        )
                        if cert_pub_bytes == key_pub_bytes:
                            print(f"  ✅ 证书与密钥匹配")
                        else:
                            print(f"  ❌ 证书与密钥不匹配！请检查是否为同一对")
                except Exception as e:
                    print(f"  ⚠️ 无法验证密钥: {e}")
    except ImportError:
        print(f"  💡 提示: 安装 cryptography 库可获得更详细的诊断: pip install cryptography")
    except Exception as e:
        print(f"  ⚠️ 证书解析失败: {e}")
    print(f"[HTTPS] ===== 诊断结束 =====\n")

def _build_ssl_context():
    global HTTPS_CERT_FILE, HTTPS_KEY_FILE, HTTPS_KEY_PASSWORD
    cert_path = HTTPS_CERT_FILE
    key_path = HTTPS_KEY_FILE
    key_password = HTTPS_KEY_PASSWORD
    if not cert_path and not key_path:
        logger.warning("HTTPS 已启用但证书路径未配置，回退到 HTTP")
        print("[HTTPS] 警告: 证书文件路径未配置，回退到 HTTP 模式")
        return None

    cert_pem = _is_pem_file(cert_path)
    key_pem = _is_pem_file(key_path)

    if not cert_path or not os.path.isfile(cert_path):
        logger.warning(f"HTTPS 证书文件不存在: {cert_path}，回退到 HTTP")
        print(f"[HTTPS] 警告: 证书文件不存在 ({cert_path})，回退到 HTTP 模式")
        return None

    cert_types = _detect_pem_type(cert_path)
    if not cert_types and not cert_path.endswith(('.crt', '.cer', '.pem', '.p12', '.pfx')):
        logger.warning(f"HTTPS 证书文件不是有效的 PEM/证书文件: {cert_path}，回退到 HTTP")
        print(f"[HTTPS] 警告: 证书文件格式无效 ({cert_path})，回退到 HTTP 模式")
        return None

    if key_path:
        if not os.path.isfile(key_path):
            logger.warning(f"HTTPS 密钥文件不存在: {key_path}，回退到 HTTP")
            print(f"[HTTPS] 警告: 密钥文件不存在 ({key_path})，回退到 HTTP 模式")
            return None
        key_types = _detect_pem_type(key_path)
        if 'private_key' not in key_types:
            logger.warning(f"HTTPS 密钥文件中未找到私钥: {key_path}，回退到 HTTP")
            print(f"[HTTPS] 警告: 密钥文件未包含私钥 ({key_path})，回退到 HTTP 模式")
            return None
        if _detect_encrypted_key(key_path) and not key_password:
            logger.warning(f"HTTPS 私钥已加密但未提供密码，回退到 HTTP")
            print(f"[HTTPS] 警告: 私钥文件已加密，请在 config.xml 中配置 <key_password>，回退到 HTTP 模式")
            _print_ssl_diagnostics(cert_path, key_path)
            return None
    elif cert_types and 'private_key' in cert_types and 'certificate' in cert_types:
        key_path = cert_path
        logger.info("检测到证书文件包含私钥，使用同一文件作为证书和密钥")
        print("[HTTPS] 检测到 PEM 文件包含证书+私钥，使用单文件模式")

    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        pwd = key_password.encode() if key_password else None

        # Try loading with original files first
        try:
            context.load_cert_chain(cert_path, key_path, password=pwd)
        except ssl.SSLError as load_err:
            err_str = str(load_err)
            # If PEM parsing error, try with fixed/converted files
            if 'PEM lib' in err_str or 'key values mismatch' in err_str or 'ASN' in err_str or 'parse' in err_str.lower():
                logger.info("PEM 解析失败，尝试自动修复 (BOM 剥离 / PKCS#1 转 PKCS#8)...")
                print("[HTTPS] PEM 解析失败，尝试自动修复...")

                import tempfile
                import shutil

                # Fix cert file
                fixed_cert = _fix_pem_file(cert_path)
                fixed_key = _fix_pem_file(key_path) if key_path else None

                if fixed_cert or fixed_key:
                    # Write fixed content to temp files
                    tmp_cert = tempfile.NamedTemporaryFile(mode='wb', suffix='.pem', delete=False)
                    tmp_cert.write(fixed_cert if fixed_cert else open(cert_path, 'rb').read())
                    tmp_cert.close()

                    tmp_key = None
                    load_cert = tmp_cert.name
                    load_key = key_path
                    if fixed_key is not None and key_path:
                        tmp_key = tempfile.NamedTemporaryFile(mode='wb', suffix='.pem', delete=False)
                        tmp_key.write(fixed_key)
                        tmp_key.close()
                        load_key = tmp_key.name

                    try:
                        # If key was converted (PKCS#1->PKCS#8), it's now unencrypted
                        retry_pwd = None if fixed_key else pwd
                        context.load_cert_chain(load_cert, load_key, password=retry_pwd)
                        logger.info(f"SSL 修复成功: cert={cert_path}, key={key_path}")
                        print(f"[HTTPS] ✅ 修复成功 (BOM/PKCS#1 转换完成)")
                        cipher_count = len(context.get_ciphers())
                        pwd_note = '密码:无' if fixed_key else ('密码:已提供' if key_password else '密码:无')
                        print(f"[HTTPS] SSL 证书加载成功 (证书:{cert_path}, 密钥:{key_path}, {pwd_note})")
                        if fixed_key:
                            print(f"[HTTPS] 💡 建议将密钥永久转换为 PKCS#8 格式以避免每次启动转换延迟")
                        return context
                    except ssl.SSLError as e2:
                        # Cleanup temp files
                        try:
                            os.unlink(tmp_cert.name)
                            if tmp_key:
                                os.unlink(tmp_key.name)
                        except Exception:
                            pass
                        raise load_err  # Re-raise original error
                    except Exception as e2:
                        try:
                            os.unlink(tmp_cert.name)
                            if tmp_key:
                                os.unlink(tmp_key.name)
                        except Exception:
                            pass
                        raise load_err
                else:
                    raise
            else:
                raise

        cipher_count = len(context.get_ciphers())
        logger.info(f"SSL 上下文创建成功: cert={cert_path}, key={key_path}, ciphers={cipher_count}")
        print(f"[HTTPS] SSL 证书加载成功 (证书:{cert_path}, 密钥:{key_path}, 密码:{'已提供' if key_password else '无'})")
        return context
    except ssl.SSLError as e:
        err_str = str(e)
        logger.error(f"SSL 证书加载失败: {e}")
        print(f"[HTTPS] SSL 错误: {e}")
        if 'PEM lib' in err_str or 'key values mismatch' in err_str:
            print(f"[HTTPS] 可能原因: 证书与密钥不匹配、私钥已加密但未提供密码、或文件损坏")
        if 'bad decrypt' in err_str or 'check password' in err_str:
            print(f"[HTTPS] 私钥已加密，请在 config.xml 中配置 <key_password>")
        if 'ASN' in err_str or 'parse' in err_str.lower():
            print(f"[HTTPS] PEM 格式错误: 可能是 BOM 标记或 PKCS#1 格式不兼容，需转换为 PKCS#8")
            print(f"[HTTPS] 转换命令: openssl rsa -in private.key -out private.pem")
        print(f"[HTTPS] 正在输出诊断信息...")
        _print_ssl_diagnostics(cert_path, key_path)
        print(f"[HTTPS] 回退到 HTTP 模式")
        return None
    except Exception as e:
        logger.error(f"SSL 上下文创建异常: {e}")
        print(f"[HTTPS] SSL 异常: {e}")
        _print_ssl_diagnostics(cert_path, key_path)
        print(f"[HTTPS] 回退到 HTTP 模式")
        return None

def start_flask_server():
    global _WEBSOCKET_SERVER_READY
    ssl_context = None
    if HTTPS_ENABLED:
        ssl_context = _build_ssl_context()
        if ssl_context:
            logger.info(f"HTTPS 模式已启用 | 端口:{SERVER_PORT}")
            print(f"[HTTPS] 服务将通过 HTTPS 启动 (端口 {SERVER_PORT})")

    is_windows = os.name == 'nt'

    if not ssl_context and _GEVENT_PATCHED and not is_windows:
        try:
            from gevent.pywsgi import WSGIServer
            _WEBSOCKET_SERVER_READY = True
            http_server = WSGIServer((SERVER_HOST, SERVER_PORT), app, log=None)
            if SOCK_AVAILABLE:
                logger.info(f"Gevent WebSocket 服务器启动 | 端口:{SERVER_PORT}")
                print(f"[Gevent] WebSocket 服务器启动 (端口 {SERVER_PORT})")
            else:
                logger.info(f"Gevent HTTP 服务器启动 | 端口:{SERVER_PORT}")
                print(f"[Gevent] HTTP 服务器启动 (端口 {SERVER_PORT})")
            http_server.serve_forever()
            return
        except Exception as e:
            _WEBSOCKET_SERVER_READY = False
            logger.warning(f"gevent 启动失败: {e}，回退到 waitress")
            print(f"[HTTP] gevent 启动失败，回退到 waitress: {e}")

    if is_windows:
        logger.info("Windows 环境，使用 waitress (gevent 在 Windows 上不稳定)")
        print("[HTTP] Windows 环境，使用 waitress (gevent 在 Windows 上不稳定)")

    if ssl_context:
        try:
            _WEBSOCKET_SERVER_READY = True
            app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False, ssl_context=ssl_context, threaded=True)
            return
        except Exception as e:
            _WEBSOCKET_SERVER_READY = False
            logger.warning(f"Flask HTTPS 启动失败: {e}，回退到 HTTP")
            print(f"[HTTP] HTTPS 启动失败，回退到 HTTP: {e}")

    try:
        if serve:
            serve(app, host=SERVER_HOST, port=SERVER_PORT)
        else:
            logger.warning("waitress 未安装，使用 Flask 开发服务器（不建议用于生产环境）")
            app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        logger.error(f"服务器启动失败: {e}")
        print(f"[ERROR] 服务器启动失败: {e}")
        sys.exit(1)

def signal_handler(signum, frame):
    logger.info(f"收到信号 {signum}，正在优雅退出...")
    save_temp_files()
    save_chat_data()
    remove_lock_file()
    sys.exit(0)

def _background_cleanup():
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            rate_limiter.cleanup()
            _unverified_rate.cleanup()
            _file_rate_limiter.cleanup()
            now = time.time()
            with _download_counts_lock:
                expired_keys = []
                for key, timestamps in _download_counts.items():
                    valid = [t for t in timestamps if now - t < DOWNLOAD_RATE_WINDOW]
                    if valid:
                        _download_counts[key] = valid
                    else:
                        expired_keys.append(key)
                for key in expired_keys:
                    del _download_counts[key]
            clean_expired_files()
            cleanup_expired_peers()
            clean_expired_rooms()
            # 已通过验证的身份也要按龄回收（原来只增不减，长时间运行会一直涨）
            _cleanup_verified_ips(now)
            # 建房间的限流计数同样需要回收，否则每个来过的 IP 都会永久占一条
            with chat_create_limits_lock:
                stale_ips = [ip for ip, (_c, _t) in chat_create_limits.items()
                             if now - _t > CHAT_CREATE_RATE_WINDOW]
                for ip in stale_ips:
                    del chat_create_limits[ip]
            with _waf_challenge_lock:
                expired_ips = [ip for ip, ts in _waf_challenge_ips.items() if now - ts > CHALLENGE_IP_TTL]
                for ip in expired_ips:
                    del _waf_challenge_ips[ip]
        except Exception as e:
            # 原来是 except Exception: pass——出错完全没有痕迹，出问题无法排查。
            # 记录后继续循环，下一轮仍会尝试清理。
            logger.error(f"后台清理出错: {e}")

def get_system_snapshot():
    chat_data = {"active_rooms": 0, "total_users": 0, "ws_connections": 0, "http_sessions": 0, "total_rooms": 0}
    with chat_lock:
        chat_data["active_rooms"] = len(chat_rooms)
        chat_data["total_rooms"] = len(chat_rooms)
        all_nicks = set()
        for room in chat_rooms.values():
            all_nicks.update(room.get("users", set()))
        chat_data["total_users"] = len(all_nicks)

    ws_conns = 0
    with ws_rooms_lock:
        for room_conns in ws_rooms.values():
            ws_conns += len(room_conns)
    chat_data["ws_connections"] = ws_conns

    with http_chat_lock:
        now = time.time()
        active_http = sum(1 for v in http_chat_sessions.values() if now - v < HTTP_CHAT_TIMEOUT)
        chat_data["http_sessions"] = active_http
        expired = [k for k, v in http_chat_sessions.items() if now - v > HTTP_CHAT_TIMEOUT]
        for k in expired:
            del http_chat_sessions[k]

    files_data = {"temp_count": 0, "temp_size": 0, "share_count": 0, "share_size": 0}
    with file_lock:
        files_data["temp_count"] = len(temp_files)
        total = 0
        for f in temp_files.values():
            sz = f.get("size", 0)
            if isinstance(sz, (int, float)):
                total += sz
        files_data["temp_size"] = total
    try:
        disk_count = 0
        disk_size = 0
        if os.path.isdir(UPLOAD_TEMP_FOLDER):
            for fname in os.listdir(UPLOAD_TEMP_FOLDER):
                fpath = os.path.join(UPLOAD_TEMP_FOLDER, fname)
                if os.path.isfile(fpath):
                    disk_count += 1
                    disk_size += os.path.getsize(fpath)
        if disk_count > files_data["temp_count"]:
            files_data["temp_count"] = disk_count
            files_data["temp_size"] = disk_size
    except Exception:
        pass
    try:
        share_count = 0
        share_size = 0
        if os.path.isdir(SHARE_FOLDER):
            for root, dirs, files in os.walk(SHARE_FOLDER):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        if os.path.isfile(fpath) and not os.path.islink(fpath):
                            share_count += 1
                            share_size += os.path.getsize(fpath)
                    except Exception:
                        pass
        files_data["share_count"] = share_count
        files_data["share_size"] = share_size
    except Exception:
        pass
    files_data["file_count"] = files_data["temp_count"] + files_data["share_count"]
    files_data["total_size"] = files_data["temp_size"] + files_data["share_size"]

    transfer_data = {"online_peers": 0, "total_peers": 0}
    with peer_lock:
        now = time.time()
        online = [uid for uid, info in peers.items()
                  if now - info.get("online", 0) < PEER_TIMEOUT]
        transfer_data["online_peers"] = len(online)
        transfer_data["total_peers"] = len(peers)

    with _waf_rate_blocked_lock:
        rate_blocked = _waf_rate_blocked
    with _waf_verified_ips_lock:
        _verified_now = time.time()
        verified_count = sum(1 for exp in _waf_verified_ips.values() if exp > _verified_now)
    with _waf_challenge_lock:
        now = time.time()
        active_challenge_ips = {ip: ts for ip, ts in _waf_challenge_ips.items() if now - ts < CHALLENGE_IP_TTL}
        _waf_challenge_ips.clear()
        _waf_challenge_ips.update(active_challenge_ips)
        active_challenges = len(active_challenge_ips)
    with _waf_total_challenges_lock:
        total_challenges = _waf_total_challenges
    waf_data = {
        "active_challenges": active_challenges,
        "total_challenges": total_challenges,
        "rate_blocked": rate_blocked,
        "verified_ips": verified_count,
    }

    ws_data = {
        "active_connections": ws_conns,
        "subscription_rooms": len(ws_rooms),
        "http_polling_sessions": active_http,
    }

    return {
        "chat": chat_data,
        "files": files_data,
        "transfer": transfer_data,
        "waf": waf_data,
        "ws": ws_data,
        "server": {
            "app": APP_NAME,
            "version": APP_VER,
            "https": HTTPS_ENABLED,
            "port": SERVER_PORT,
            "host": SERVER_HOST,
        }
    }

try:
    from monitor import register_monitor
    register_monitor(app, get_system_snapshot, monitor_cfg=CONFIG.get("monitor", {}))
    logger.info("监控模块已注册")
except Exception as e:
    logger.warning(f"监控模块注册失败: {e}")

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    check_single_instance(SERVER_PORT, SERVER_HOST)
    threading.Thread(target=_background_cleanup, daemon=True).start()

    init_storage()
    load_temp_files()
    load_chat_data()

    logger.info(f"{APP_NAME} {APP_VER} 启动 | 共享目录:{SHARE_FOLDER} 端口:{SERVER_PORT}")

    threading.Thread(target=start_flask_server, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
