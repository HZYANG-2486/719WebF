import time
import threading
import logging
from collections import deque
from flask import Blueprint, jsonify, request, render_template

logger = logging.getLogger("monitor")

_subsystem_catalog = {
    "chat": {"name": "聊天室", "icon": "💬", "description": "实时聊天子系统"},
    "files": {"name": "文件服务", "icon": "📁", "description": "临时文件管理"},
    "transfer": {"name": "P2P传输", "icon": "🔄", "description": "点对点文件传输"},
    "waf": {"name": "安全防护", "icon": "🛡️", "description": "WAF防攻击系统"},
    "ws": {"name": "WebSocket", "icon": "🔌", "description": "实时消息通道"},
}


class HistoryTracker:
    def __init__(self, max_samples=360, interval=10, monitor_cfg=None):
        if monitor_cfg:
            if "max_history_samples" in monitor_cfg:
                max_samples = int(monitor_cfg["max_history_samples"])
            if "sample_interval" in monitor_cfg:
                interval = int(monitor_cfg["sample_interval"])
        self._buffer = deque(maxlen=max_samples)
        self._interval = interval
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._data_provider = None
        self._last_sample = None

    def start(self, data_provider, monitor_cfg=None):
        if monitor_cfg:
            if "max_history_samples" in monitor_cfg:
                new_maxlen = int(monitor_cfg["max_history_samples"])
                if new_maxlen != self._buffer.maxlen:
                    with self._lock:
                        old_data = list(self._buffer)
                        self._buffer = deque(old_data, maxlen=new_maxlen)
            if "sample_interval" in monitor_cfg:
                self._interval = int(monitor_cfg["sample_interval"])
        self._data_provider = data_provider
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        logger.info(f"HistoryTracker 启动 | 采样间隔:{self._interval}s | 缓冲区大小:{self._buffer.maxlen}")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("HistoryTracker 已停止")

    def _sample_loop(self):
        while self._running:
            try:
                if self._data_provider:
                    data = self._data_provider()
                    if data:
                        sample = {
                            "timestamp": time.time(),
                            "rooms_active": data.get("chat", {}).get("active_rooms", 0),
                            "chat_users": data.get("chat", {}).get("total_users", 0),
                            "temp_files": data.get("files", {}).get("temp_count", 0),
                            "share_files": data.get("files", {}).get("share_count", 0),
                            "online_peers": data.get("transfer", {}).get("online_peers", 0),
                            "ws_connections": data.get("ws", {}).get("active_connections", 0),
                            "http_sessions": data.get("ws", {}).get("http_polling_sessions", 0),
                            "rate_blocked": data.get("waf", {}).get("rate_blocked", 0),
                        }
                        with self._lock:
                            self._buffer.append(sample)
                        self._last_sample = sample
            except Exception as e:
                logger.warning(f"HistoryTracker 采样错误: {e}")
            time.sleep(self._interval)

    def get_history(self, minutes=5):
        if minutes < 1:
            minutes = 1
        if minutes > 60:
            minutes = 60
        cutoff = time.time() - (minutes * 60)
        with self._lock:
            return [s for s in self._buffer if s["timestamp"] >= cutoff]

    def get_latest(self):
        return self._last_sample


class SubServiceChecker:
    def __init__(self, data_provider):
        self._data_provider = data_provider

    def check_all(self):
        data = self._data_provider() if self._data_provider else {}
        results = {}
        for key in _subsystem_catalog:
            checker = getattr(self, f"_check_{key}", None)
            if checker:
                results[key] = checker(data)
            else:
                results[key] = {
                    "status": "unknown",
                    "message": f"检查器未实现: {key}",
                    "details": {},
                }
        return results

    def _check_chat(self, data):
        chat = data.get("chat", {})
        active_rooms = chat.get("active_rooms", 0)
        total_users = chat.get("total_users", 0)
        ws_connections = chat.get("ws_connections", 0)
        http_sessions = chat.get("http_sessions", 0)
        total_active = total_users
        status = "healthy"
        if active_rooms == 0 and total_active == 0:
            status = "idle"
            message = "暂无活跃房间"
        else:
            parts = []
            if active_rooms > 0:
                parts.append(f"活跃房间: {active_rooms}")
            if total_active > 0:
                parts.append(f"在线用户: {total_active}")
            if ws_connections > 0:
                parts.append(f"WS连接: {ws_connections}")
            if http_sessions > 0:
                parts.append(f"HTTP轮询: {http_sessions}")
            message = ", ".join(parts) if parts else "暂无活跃房间"
        details = {
            "active_rooms": active_rooms,
            "total_users": total_users,
            "ws_connections": ws_connections,
            "http_sessions": http_sessions,
            "total_active": total_active,
            "total_rooms_ever": chat.get("total_rooms", 0),
        }
        return {"status": status, "message": message, "details": details}

    def _check_files(self, data):
        files = data.get("files", {})
        file_count = files.get("file_count", 0)
        total_size = files.get("total_size", 0)
        temp_count = files.get("temp_count", 0)
        temp_size = files.get("temp_size", 0)
        share_count = files.get("share_count", 0)
        share_size = files.get("share_size", 0)
        share_dir = ""
        status = "healthy"
        parts = []
        if temp_count > 0:
            parts.append(f"临时文件: {temp_count} 个 ({self._fmt_size(temp_size)})")
        if share_count > 0:
            parts.append(f"共享文件: {share_count} 个 ({self._fmt_size(share_size)})")
        if not parts:
            status = "idle"
            message = "暂无文件"
        else:
            message = ", ".join(parts)
            if total_size > 1024 * 1024 * 500:
                status = "warning"
        details = {
            "file_count": file_count,
            "total_size": total_size,
            "temp_count": temp_count,
            "temp_size": temp_size,
            "share_count": share_count,
            "share_size": share_size,
            "share_dir": share_dir,
        }
        return {"status": status, "message": message, "details": details}

    @staticmethod
    def _fmt_size(size_bytes):
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / 1024 / 1024:.1f} MB"
        return f"{size_bytes / 1024 / 1024 / 1024:.2f} GB"

    def _check_transfer(self, data):
        transfer = data.get("transfer", {})
        online_peers = transfer.get("online_peers", 0)
        status = "healthy"
        message = f"在线 Peer: {online_peers}"
        if online_peers == 0:
            status = "idle"
            message = "暂无在线 Peer"
        details = {
            "online_peers": online_peers,
            "total_peers": transfer.get("total_peers", 0),
        }
        return {"status": status, "message": message, "details": details}

    def _check_waf(self, data):
        waf = data.get("waf", {})
        active_challenges = waf.get("active_challenges", 0)
        total_challenges = waf.get("total_challenges", 0)
        rate_blocked = waf.get("rate_blocked", 0)
        verified_ips = waf.get("verified_ips", 0)
        status = "healthy"
        parts = []
        if active_challenges > 0:
            parts.append(f"活动挑战: {active_challenges}")
        parts.append(f"已服务挑战: {total_challenges}")
        parts.append(f"限速拦截: {rate_blocked}")
        parts.append(f"已验证IP: {verified_ips}")
        message = ", ".join(parts)
        if rate_blocked > 100:
            status = "warning"
        details = {
            "active_challenges": active_challenges,
            "total_challenges": total_challenges,
            "rate_blocked": rate_blocked,
            "verified_ips": verified_ips,
        }
        return {"status": status, "message": message, "details": details}

    def _check_ws(self, data):
        ws = data.get("ws", {})
        active_connections = ws.get("active_connections", 0)
        subscription_rooms = ws.get("subscription_rooms", 0)
        status = "healthy"
        message = f"活跃连接: {active_connections}, 订阅房间: {subscription_rooms}"
        if active_connections == 0:
            status = "idle"
            message = "暂无 WebSocket 连接"
        details = {
            "active_connections": active_connections,
            "subscription_rooms": subscription_rooms,
        }
        return {"status": status, "message": message, "details": details}


class MonitorService:
    def __init__(self):
        self._data_provider = None
        self._history = None
        self._checker = None
        self._start_time = time.time()
        self._request_count = 0
        self._initialized = False
        self._monitor_cfg = None

    def initialize(self, data_provider, monitor_cfg=None):
        self._data_provider = data_provider
        self._monitor_cfg = monitor_cfg
        self._history = HistoryTracker(monitor_cfg=monitor_cfg)
        self._checker = SubServiceChecker(data_provider)
        self._history.start(data_provider, monitor_cfg=monitor_cfg)
        self._initialized = True
        logger.info("MonitorService 初始化完成")

    def get_health(self):
        data = self._data_provider() if self._data_provider else {}
        subsystems = self._checker.check_all() if self._checker else {}
        all_ok = all(
            s["status"] in ("healthy", "idle")
            for s in subsystems.values()
        )
        return {
            "status": "ok" if all_ok else "degraded",
            "uptime": time.time() - self._start_time,
            "subsystems": {
                key: {
                    "status": val["status"],
                    "message": val["message"],
                }
                for key, val in subsystems.items()
            },
        }

    def get_detail(self):
        data = self._data_provider() if self._data_provider else {}
        subsystems = self._checker.check_all() if self._checker else {}
        return {
            "status": "ok",
            "uptime": time.time() - self._start_time,
            "timestamp": time.time(),
            "request_count": self._request_count,
            "subsystems": subsystems,
            "raw_data": data,
        }

    def get_history(self, minutes=5):
        self._request_count += 1
        if not self._history:
            return {"points": 0, "minutes": minutes, "data": []}
        history = self._history.get_history(minutes)
        return {
            "points": len(history),
            "minutes": minutes,
            "data": history,
        }

    def get_catalog(self):
        return _subsystem_catalog.copy()


_monitor_instance = MonitorService()

monitor_bp = Blueprint("monitor", __name__, url_prefix="")


@monitor_bp.route("/health")
def health_route():
    result = _monitor_instance.get_health()
    result["app"] = "719WEBF"
    result["version"] = _get_app_version()
    return jsonify(result)


@monitor_bp.route("/health/detail")
def health_detail_route():
    return jsonify(_monitor_instance.get_detail())


@monitor_bp.route("/health/history")
def health_history_route():
    minutes = request.args.get("minutes", 5, type=int)
    if minutes < 1:
        minutes = 1
    if minutes > 60:
        minutes = 60
    return jsonify(_monitor_instance.get_history(minutes))


@monitor_bp.route("/health/catalog")
def health_catalog_route():
    return jsonify(_monitor_instance.get_catalog())


@monitor_bp.route("/health/ui")
def health_ui_route():
    data = _monitor_instance._data_provider() if _monitor_instance._data_provider else {}
    subsystems = _monitor_instance._checker.check_all() if _monitor_instance._checker else {}
    latest = _monitor_instance._history.get_latest() if _monitor_instance._history else None
    return render_template("health.html",
        app_name="719WEBF",
        app_ver=_get_app_version(),
        uptime=time.time() - _monitor_instance._start_time,
        data=data,
        subsystems=subsystems,
        latest=latest,
        catalog=_subsystem_catalog,
    )


def _get_app_version():
    try:
        from version import APP_VER
        return APP_VER
    except ImportError:
        return "unknown"


def register_monitor(app, data_provider, monitor_cfg=None):
    if _monitor_instance._initialized:
        logger.warning("监控模块已初始化，跳过重复注册")
        return _monitor_instance
    _monitor_instance.initialize(data_provider, monitor_cfg=monitor_cfg)
    app.register_blueprint(monitor_bp)
    logger.info("监控模块已注册")
    return _monitor_instance
