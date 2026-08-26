import threading
import sys
import os
import copy
import webbrowser
import xml.etree.ElementTree as ET
import logging
from typing import Callable, Optional, Dict, Any

from version import APP_NAME, APP_VER
DEFAULT_CONFIG_FILE = "config.xml"

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


def _has_display():
    try:
        import tkinter as tk_test
        root = tk_test.Tk()
        root.destroy()
        return True
    except Exception:
        return False


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
                   "waf", "security", "system", "monitor"]
    for node in child_nodes:
        if node in partial_cfg and partial_cfg[node] is not None:
            for k, v in partial_cfg[node].items():
                result[node][k] = v
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

    tree = ET.ElementTree(root)
    tmp_file = config_path + ".tmp"
    try:
        with open(tmp_file, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)
        os.replace(tmp_file, config_path)
    except Exception:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass


def _parse_set(text):
    if not text:
        return set()
    return {s.strip() for s in text.split(",") if s.strip()}


def load_config(config_path: str, _depth: int = 0) -> Dict[str, Any]:
    if not os.path.exists(config_path):
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

    return merge_with_defaults(partial_cfg)


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

    tree = ET.ElementTree(root)
    tmp_path = config_path + ".tmp"
    try:
        with open(tmp_path, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)
        os.replace(tmp_path, config_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


class SettingsGUI:
    def __init__(self, config_path: str, on_save_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.config_path = config_path
        self.on_save_callback = on_save_callback
        self.cfg = load_config(config_path)
        self._root = None
        self._created = False
        self.vars = {}
        self._tab_ids = {}
        self.advanced_mode = None
        self.notebook = None

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
            text="修改配置后需重启服务生效。基础 Tab 为常用设置，高级 Tab 含 WAF/安全/系统/监控等详细配置。",
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
        self.notebook.pack(fill="both", expand=True, padx=15, pady=(5, 10))

        tab1 = ttk.Frame(self.notebook, padding=15)
        tab2 = ttk.Frame(self.notebook, padding=15)
        tab3 = ttk.Frame(self.notebook, padding=15)
        tab4 = ttk.Frame(self.notebook, padding=15)
        tab5 = ttk.Frame(self.notebook, padding=15)
        tab6 = ttk.Frame(self.notebook, padding=15)
        tab7 = ttk.Frame(self.notebook, padding=15)
        tab8 = ttk.Frame(self.notebook, padding=15)
        tab9 = ttk.Frame(self.notebook, padding=15)

        self.notebook.add(tab1, text="基础")
        self.notebook.add(tab2, text="聊天")
        self.notebook.add(tab3, text="路径")
        self.notebook.add(tab4, text="P2P")
        self.notebook.add(tab5, text="文件传输")
        self.notebook.add(tab6, text="WAF防护")
        self.notebook.add(tab7, text="安全设置")
        self.notebook.add(tab8, text="系统设置")
        self.notebook.add(tab9, text="监控设置")

        self._tab_ids = {
            "基础": tab1,
            "聊天": tab2,
            "路径": tab3,
            "P2P": tab4,
            "文件传输": tab5,
            "WAF防护": tab6,
            "安全设置": tab7,
            "系统设置": tab8,
            "监控设置": tab9,
        }

        self._build_tab1_basic(tab1)
        self._build_tab2_chat(tab2)
        self._build_tab3_paths(tab3)
        self._build_tab4_p2p(tab4)
        self._build_tab5_file_transfer(tab5)
        self._build_tab6_waf(tab6)
        self._build_tab7_security(tab7)
        self._build_tab8_system(tab8)
        self._build_tab9_monitor(tab9)

        btn_frame = ttk.Frame(self._root, padding=(15, 0, 15, 15))
        btn_frame.pack(fill="x", side="bottom")
        ttk.Button(btn_frame, text="取消", command=self._destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btn_frame, text="保存", command=self._on_save).pack(side="right")

        self.reload_config()
        self._on_toggle_advanced()

    def _grid_field(self, parent, row, label_text, widget, hint=None):
        import tkinter as tk
        ttk = __import__("tkinter.ttk", fromlist=["ttk"])
        lbl_frame = ttk.Frame(parent)
        lbl_frame.grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=4)
        ttk.Label(lbl_frame, text=label_text, font=("微软雅黑", 10)).pack(anchor="w")
        if hint:
            ttk.Label(lbl_frame, text=hint, font=("微软雅黑", 8), foreground="#777777").pack(anchor="w")
        widget_frame = ttk.Frame(parent)
        widget_frame.grid(row=row, column=1, sticky="ew", pady=4)
        widget.pack(in_=widget_frame, anchor="w", fill="x", expand=True)
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
        for tab_name in advanced_tabs:
            tab_id = self._tab_ids[tab_name]
            if show_advanced:
                try:
                    self.notebook.tab(tab_id, state="normal")
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

        return cfg

    def _on_save(self):
        from tkinter import messagebox
        try:
            cfg = self._collect_settings()
            try:
                from app import validate_config
                ok, errs = validate_config(cfg)
                if not ok:
                    messagebox.showwarning("配置警告", "\n".join(errs))
            except Exception:
                pass
            save_config(self.config_path, cfg)
            self.cfg = load_config(self.config_path)
            self.reload_config()
            if self.on_save_callback:
                self.on_save_callback(self.cfg)
            messagebox.showinfo("成功", "配置已保存！建议重启应用生效。")
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


def open_settings_gui(config_path: str, on_save_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
    app = SettingsGUI(config_path, on_save_callback)
    app.run()
    return app


class GUIManager:
    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_FILE,
        on_start_service: Optional[Callable[[], None]] = None,
        on_stop_service: Optional[Callable[[], None]] = None,
        headless: bool = False,
        logo_path: str = "logo.png"
    ):
        self.config_path = config_path
        self.on_start_service = on_start_service
        self.on_stop_service = on_stop_service
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
        threading.Thread(
            target=open_settings_gui,
            args=(self.config_path, self._on_config_saved),
            daemon=True
        ).start()

    def _on_config_saved(self, new_cfg: Dict[str, Any]):
        self.cfg = new_cfg

    def _exit_app(self, icon=None, item=None):
        self.stop()
        if self.on_stop_service:
            self.on_stop_service()
        sys.exit(0)

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