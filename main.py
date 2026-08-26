import sys
import os
import argparse
import signal
import threading
import time
import logging

try:
    import gevent.monkey
    gevent.monkey.patch_all()
    _GEVENT_AVAILABLE = True
except ImportError:
    _GEVENT_AVAILABLE = False

import app as webapp
from gui import GUIManager, load_config
from version import APP_NAME, APP_VER, get_version_string
import monitor


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

    config = load_config("config.xml")
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
    print(f"  GUI模式:   {'启用' if not args.no_gui else '禁用 (无头模式)'}")
    protocol = "https" if webapp.HTTPS_ENABLED else "http"
    print(f"  健康检查:  {protocol}://{webapp.SERVER_HOST}:{webapp.SERVER_PORT}/health")
    print(f"  状态面板:  {protocol}://{webapp.SERVER_HOST}:{webapp.SERVER_PORT}/health/ui")
    print("=" * 52)
    print()

    webapp.check_single_instance(webapp.SERVER_PORT, webapp.SERVER_HOST)

    threading.Thread(target=webapp._background_cleanup, daemon=True).start()

    webapp.load_temp_files()
    webapp.load_chat_data()

    monitor.register_monitor(webapp.app, webapp.get_system_snapshot, monitor_cfg=webapp.CONFIG.get("monitor", {}))

    gui_manager = None
    if not args.no_gui:
        gui_manager = GUIManager(
            config_path="config.xml",
            headless=False
        )
        tray_ok = gui_manager.start_tray()
        if tray_ok:
            logger.info("GUI托盘已启动")
        else:
            logger.warning("GUI托盘启动失败（可能无显示环境），继续以无头模式运行")
            gui_manager = None
    else:
        logger.info("无头模式：跳过GUI初始化")

    def graceful_shutdown(signum, frame):
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        logger.info(f"收到 {sig_name} 信号，正在优雅退出...")
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
        sys.exit(0)

    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    logger.info(f"{APP_NAME} {APP_VER} 启动完成 | 端口:{webapp.SERVER_PORT}")

    threading.Thread(target=webapp.start_flask_server, daemon=True).start()

    time.sleep(2)

    def verify_server():
        for _ in range(5):
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
        logger.warning("无法验证服务是否启动成功，但继续运行")
        print(f"\n⚠ 服务可能未正常启动，请手动检查端口 {webapp.SERVER_PORT}")
        print(f"  手动启动: python main.py --no-gui")

    threading.Thread(target=verify_server, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        graceful_shutdown(signal.SIGINT, None)


if __name__ == '__main__':
    main()