import sys
import os
import argparse
import signal
import socket
import subprocess
import threading
import time
import logging

if os.name != 'nt':
    try:
        import gevent.monkey
        gevent.monkey.patch_all()
        _GEVENT_AVAILABLE = True
    except ImportError:
        _GEVENT_AVAILABLE = False
else:
    _GEVENT_AVAILABLE = False

import app as webapp
from gui import GUIManager, load_config
from version import APP_NAME, APP_VER, get_version_string
import monitor


_SHUTDOWN_EVENT = threading.Event()
_RESTART_REQUESTED = threading.Event()

# 重启标记：新进程带着这个环境变量启动时，会先等旧进程把端口让出来再继续。
RESTART_ENV_FLAG = "_719WEBF_RESTARTED"

# 等待旧进程释放端口的上限（秒）与轮询间隔
_RESTART_WAIT_TIMEOUT = 15.0
_RESTART_WAIT_INTERVAL = 0.3


def _build_restart_argv():
    """拼出重启时应当执行的完整命令行（列表形式）。

    列表形式交给 subprocess，由它负责给每个参数加引号——这是关键。
    Windows 上绝不能用 os.execv：它把参数拼成命令行时不给带空格的路径加引号，
    像 "D:\\an下载\\719WebF (2)\\main.py" 会被拆成 "D:\\an下载\\719WebF" 和
    "(2)\\main.py" 两段，于是 python 把前者当成目录去找 __main__，
    报 "can't find '__main__' module"，服务就此停摆。

    另外 argv[0] 在某些启动方式（如把脚本用关联程序打开）下可能是相对路径，
    这里统一换成绝对路径，避免工作目录变化后找不到入口文件。
    """
    argv = [sys.executable]
    if sys.argv:
        script = sys.argv[0]
        # 冻结成 exe 时 sys.executable 本身就是程序，不需要再跟脚本路径
        if getattr(sys, "frozen", False):
            pass
        elif script:
            if not os.path.isabs(script):
                script = os.path.abspath(script)
            argv.append(script)
    argv.extend(sys.argv[1:])
    return argv


def _wait_for_port_release(port, host, timeout=_RESTART_WAIT_TIMEOUT):
    """等旧进程把端口让出来。

    重启时新进程会和旧进程短暂并存，而启动流程里的 check_single_instance
    一旦发现端口被占用就直接退出。这里主动等一会儿，避免刚拉起来的新进程
    立刻自杀，导致"点了重启服务反而没了"。
    """
    deadline = time.time() + timeout
    probe_hosts = []
    for h in (host, "127.0.0.1", "0.0.0.0"):
        if h and h not in probe_hosts:
            probe_hosts.append(h)
    while time.time() < deadline:
        free = True
        for h in probe_hosts:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    if s.connect_ex((h, port)) == 0:
                        free = False
                        break
            except Exception:
                continue
        if free:
            return True
        time.sleep(_RESTART_WAIT_INTERVAL)
    return False


def _spawn_replacement(argv):
    """拉起替代进程。成功返回 Popen 对象，失败返回 None。"""
    env = os.environ.copy()
    env[RESTART_ENV_FLAG] = "1"
    kwargs = {
        "cwd": os.getcwd(),
        "env": env,
        "close_fds": True,
    }
    if os.name == "nt":
        # 独立于当前控制台/进程组，这样父进程退出（含关掉那个命令行窗口）不会带走它
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        # 输出重定向到空设备，避免继承已关闭的控制台句柄后写日志报错
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)


def restart_application():
    """重启当前程序，让 config.xml 的改动立即生效。

    实现要点（都是为了不在 Windows 上翻车）：
      1. 用 subprocess + 参数列表拉起新进程，由 subprocess 负责加引号，
         路径里带空格（例如 "719WebF (2)"）也不会被拆开；
      2. 新进程带 RESTART_ENV_FLAG 环境变量，启动后先等旧进程释放端口；
      3. 新进程已经确认拉起来了，本进程才退出——避免"重启失败 = 服务彻底没了"。
    """
    _RESTART_REQUESTED.set()
    print("\n正在重启服务...")

    # 先保存数据、释放锁文件，让新进程能顺利通过单实例检查
    try:
        webapp.save_temp_files()
        webapp.save_chat_data()
    except Exception as e:
        print(f"[重启] 保存数据失败（不影响重启）: {e}")
    try:
        webapp.remove_lock_file()
    except Exception:
        pass

    argv = _build_restart_argv()

    try:
        proc = _spawn_replacement(argv)
    except Exception as e:
        # 拉起失败就保持当前进程继续服务，不能让它停在"半死不活"的状态
        print(f"[重启] 无法拉起新进程: {e}")
        print("[重启] 已保留当前服务继续运行，请手动重启。")
        return False

    if proc.poll() is not None:
        # 立刻退出说明连解释器都没起来（例如路径写错），同样保留当前服务
        print(f"[重启] 新进程启动后立即退出（退出码 {proc.returncode}），已保留当前服务。")
        print("[重启] 请手动重启，或检查程序路径是否可访问。")
        return False

    print(f"[重启] 新进程已启动（PID {proc.pid}），本进程即将退出。")
    # 留一点时间让新进程开始工作，也确保托盘图标先释放
    time.sleep(1.0)
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} {APP_VER} - 文件共享服务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                  启动GUI托盘 + Web服务（默认）
  python main.py --no-gui         无头模式，仅启动Web服务
  python main.py --port 8080      使用自定义端口
  python main.py --host 127.0.0.1 仅本机可访问
        """
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="以无头模式运行（不启动系统托盘GUI）"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"覆盖服务端口（默认: {webapp.SERVER_PORT}）"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help=f"覆盖绑定地址（默认: {webapp.SERVER_HOST}）"
    )

    args = parser.parse_args()

    # --- 启动前确保 config.xml 存在并使用绝对路径（消除"未生成 / 要手动移植"问题） ---
    def _resolve_app_dir():
        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.abspath(sys.executable))
        try:
            return os.path.dirname(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, "main.py")))
        except Exception:
            return os.getcwd()
    _app_dir = os.path.dirname(os.path.abspath(__file__ if "__file__" in dir() else os.path.join(os.getcwd(), "main.py")))
    try:
        _app_dir = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        _app_dir = os.getcwd()
    if getattr(sys, "frozen", False):
        _app_dir = os.path.dirname(os.path.abspath(sys.executable))
    CONFIG_PATH = os.path.join(_app_dir, "config.xml")
    try:
        from gui import create_default_config as _create_default_cfg_gui
        if not os.path.exists(CONFIG_PATH):
            _create_default_cfg_gui(CONFIG_PATH)
            print(f"[Config] 首次启动，已生成默认配置: {CONFIG_PATH}")
    except Exception as e:
        print(f"[Config] 生成默认配置失败: {e}（将使用内置默认值继续运行）")

    config = load_config(CONFIG_PATH)
    if not os.path.exists(CONFIG_PATH):
        # 双重保险：load_config 内部可能失败，显式再生成一次
        try:
            from app import create_default_config as _create_default_cfg_app
            _create_default_cfg_app(CONFIG_PATH)
        except Exception as e2:
            print(f"[Config] 二次生成失败: {e2}")
    if args.port is not None:
        config["port"] = args.port
        webapp.SERVER_PORT = args.port
    if args.host is not None:
        config["host"] = args.host
        webapp.SERVER_HOST = args.host

    logger = logging.getLogger(APP_NAME)

    print()
    print("=" * 52)
    print(f"  {APP_NAME} {APP_VER}")
    print("=" * 52)
    print(f"  共享目录: {webapp.SHARE_FOLDER}")
    print(f"  监听地址: {webapp.SERVER_HOST}:{webapp.SERVER_PORT}")
    https_status = "启用" if webapp.HTTPS_ENABLED else "禁用"
    print(f"  HTTPS:     {https_status}")
    print(f"  配置文件: {CONFIG_PATH}")
    print(f"  GUI模式:   {'启用' if not args.no_gui else '禁用 (无头模式)'}")
    protocol = "https" if webapp.HTTPS_ENABLED else "http"
    print(f"  健康检查:  {protocol}://{webapp.SERVER_HOST}:{webapp.SERVER_PORT}/health")
    print(f"  状态面板:  {protocol}://{webapp.SERVER_HOST}:{webapp.SERVER_PORT}/health/ui")
    print("=" * 52)
    print()

    # 重启而来的进程：旧进程可能还在收尾，先等它把端口让出来，
    # 否则下面的 check_single_instance 会判定"端口被占用"直接退出。
    if os.environ.get(RESTART_ENV_FLAG) == "1":
        os.environ.pop(RESTART_ENV_FLAG, None)
        print("  正在等待旧进程退出...")
        if _wait_for_port_release(webapp.SERVER_PORT, webapp.SERVER_HOST):
            print("  旧进程已退出，继续启动。")
        else:
            print("  等待超时，仍尝试启动。")

    webapp.check_single_instance(webapp.SERVER_PORT, webapp.SERVER_HOST)

    threading.Thread(target=webapp._background_cleanup, daemon=True).start()

    webapp.init_storage()
    webapp.load_temp_files()
    webapp.load_chat_data()

    monitor.register_monitor(webapp.app, webapp.get_system_snapshot, monitor_cfg=webapp.CONFIG.get("monitor", {}))

    gui_manager = None
    if not args.no_gui:
        gui_manager = GUIManager(
            config_path=CONFIG_PATH,
            headless=False,
            on_stop_service=lambda: graceful_shutdown(None, None),
            on_restart_service=restart_application
        )
        tray_ok = gui_manager.start_tray()
        if tray_ok:
            logger.info("GUI托盘已启动")
        else:
            logger.warning("GUI托盘启动失败（可能无显示环境），继续以无头模式运行")
            gui_manager = None
    else:
        logger.info("无头模式：跳过GUI初始化")

    def _do_cleanup():
        if getattr(_do_cleanup, "_done", False):
            return
        _do_cleanup._done = True
        print(f"\n正在关闭服务...")
        try:
            webapp.save_temp_files()
            webapp.save_chat_data()
        except Exception as e:
            logger.error(f"保存数据失败: {e}")
        if gui_manager:
            try:
                gui_manager.stop()
            except Exception:
                pass
        webapp.remove_lock_file()
        logger.info("服务已停止")
        print("服务已停止")

    def graceful_shutdown(signum=None, frame=None):
        if signum is not None:
            sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
            logger.info(f"收到 {sig_name} 信号，正在优雅退出...")
        _SHUTDOWN_EVENT.set()

    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    logger.info(f"{APP_NAME} {APP_VER} 启动完成 | 端口:{webapp.SERVER_PORT}")

    threading.Thread(target=webapp.start_flask_server, daemon=True).start()

    time.sleep(2)

    def verify_server():
        for _ in range(5):
            if _SHUTDOWN_EVENT.is_set():
                return
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                result = s.connect_ex(('127.0.0.1', webapp.SERVER_PORT))
                s.close()
                if result == 0:
                    logger.info("服务已就绪，可以接受请求")
                    print(f"\n✓ 服务已启动，访问 {protocol}://{webapp.SERVER_HOST}:{webapp.SERVER_PORT}")
                    print(f"  状态面板: {protocol}://{webapp.SERVER_HOST}:{webapp.SERVER_PORT}/health/ui")
                    return
            except Exception:
                pass
            time.sleep(1)
        if not _SHUTDOWN_EVENT.is_set():
            logger.warning("无法验证服务是否启动成功，但继续运行")
            print(f"\n⚠ 服务可能未正常启动，请手动检查端口 {webapp.SERVER_PORT}")
            print(f"  手动启动: python main.py --no-gui")

    threading.Thread(target=verify_server, daemon=True).start()

    try:
        while not _SHUTDOWN_EVENT.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        graceful_shutdown(signal.SIGINT, None)
    finally:
        _do_cleanup()


if __name__ == '__main__':
    main()
