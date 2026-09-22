# -*- coding: utf-8 -*-
"""
719WebF 本地数据修改器（离线）

用于在服务停止时直接查询/修改 SQLite 数据库（data/app.db），
也可用于生成管理账号的密码哈希与 TOTP 密钥（不会在服务端暴露密钥）。

用法示例：
  python db_tool.py list-rooms                      # 列出所有聊天室
  python db_tool.py list-messages <room_id>         # 列出某房间消息
  python db_tool.py delete-message <msg_id>         # 删除某条消息
  python db_tool.py edit-message <msg_id> "新内容"  # 修改某条消息内容
  python db_tool.py list-temp                       # 列出临时文件
  python db_tool.py enable-admin --username admin --password 你的密码
                                                    # 生成/更新管理账号（输出 TOTP 二维码）
  python db_tool.py show-admin                      # 查看当前管理账号

注意：服务运行期间其内存为权威来源；用本工具修改后请重启服务，
或改用网页端的管理接口进行在线删除。
"""

import os
import sys
import argparse
import hashlib
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "data", "app.db")


def _load_storage(db_path):
    sys.path.insert(0, BASE_DIR)
    import storage
    storage.init(db_path)
    return storage


def _secret_key():
    """读取 Flask 会话密钥文件（与 app.py 一致），用于生成口令哈希。"""
    path = os.path.join(BASE_DIR, ".secret")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    # 未找到时给出提示，但允许用固定占位符（不推荐，会导致登录失败）
    print("[警告] 未找到 .secret 文件，请先启动一次服务以生成，否则哈希将无法匹配登录。")
    return ""


def cmd_list_rooms(storage, args):
    rooms = storage.load_chat()
    if not rooms:
        print("(无聊天室)")
        return
    print(f"{'room_id':<16}{'消息数':<8}{'名称'}")
    print("-" * 50)
    for rid, r in rooms.items():
        print(f"{rid:<16}{len(r.get('messages', [])):<8}{r.get('name', '')}")


def cmd_list_messages(storage, args):
    rooms = storage.load_chat()
    room = rooms.get(args.room_id)
    if not room:
        print("房间不存在")
        return
    for m in room.get("messages", []):
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m.get("timestamp", 0)))
        print(f"[{m.get('id')}] {ts} <{m.get('nick')}> {m.get('content')}")


def _rewrite_room_messages(storage, rooms):
    """把修改后的消息写回（storage.save_chat 会全量覆盖）。"""
    storage.save_chat(rooms)


def cmd_delete_message(storage, args):
    rooms = storage.load_chat()
    for rid, room in rooms.items():
        msgs = room.get("messages", [])
        for i, m in enumerate(msgs):
            if m.get("id") == args.msg_id:
                del msgs[i]
                _rewrite_room_messages(storage, rooms)
                print(f"已删除消息 {args.msg_id}（房间 {rid}）")
                return
    print("未找到该消息")


def cmd_edit_message(storage, args):
    rooms = storage.load_chat()
    for rid, room in rooms.items():
        for m in room.get("messages", []):
            if m.get("id") == args.msg_id:
                m["content"] = args.content
                _rewrite_room_messages(storage, rooms)
                print(f"已修改消息 {args.msg_id}")
                return
    print("未找到该消息")


def cmd_list_temp(storage, args):
    temps = storage.load_temp()
    if not temps:
        print("(无临时文件)")
        return
    for fid, info in temps.items():
        print(f"[{fid}] {info.get('name')} ({info.get('size')}) -> {info.get('path')}")


def cmd_show_admin(storage, args):
    a = storage.get_admin()
    if not a:
        print("(未配置管理账号)")
        return
    print(f"用户名     : {a['username']}")
    print(f"已启用     : {'是' if a['enabled'] else '否'}")
    print(f"密码哈希   : {a['password_hash'][:16]}...")
    print(f"TOTP 密钥  : {a['totp_secret']}")


def cmd_enable_admin(storage, args):
    try:
        import pyotp
    except ImportError:
        print("需要 pyotp: pip install pyotp qrcode")
        return
    secret_key = _secret_key()
    pwd_hash = hashlib.sha256((args.password + secret_key).encode()).hexdigest()
    totp_secret = args.totp_secret or pyotp.random_base32()
    storage.upsert_admin(args.username, pwd_hash, totp_secret, enabled=1)

    uri = pyotp.TOTP(totp_secret).provisioning_uri(
        name=args.username, issuer_name="719WebF")
    print("=" * 56)
    print("管理账号已写入数据库")
    print("=" * 56)
    print(f"用户名    : {args.username}")
    print(f"TOTP 密钥 : {totp_secret}")
    print(f"otpauth   : {uri}")
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(uri)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:
        print("(安装 qrcode 可在终端显示二维码：pip install qrcode)")
    print()
    print("请在 config.xml 中将 <admin enabled=\"true\" ... /> 的 enabled 设为 true，")
    print("并把上面的 username / password_hash / totp_secret 填入该节点，然后重启服务。")
    print(f"  用户名      : {args.username}")
    print(f"  密码哈希    : {pwd_hash}")
    print(f"  TOTP 密钥   : {totp_secret}")
    print(f"  当前时间码  : {pyotp.TOTP(totp_secret).now()}")


def main():
    parser = argparse.ArgumentParser(description="719WebF 本地数据修改器（SQLite）")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"数据库路径（默认 {DEFAULT_DB}）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-rooms", help="列出所有聊天室").set_defaults(func=cmd_list_rooms)

    p = sub.add_parser("list-messages", help="列出某房间消息")
    p.add_argument("room_id")
    p.set_defaults(func=cmd_list_messages)

    p = sub.add_parser("delete-message", help="删除某条消息")
    p.add_argument("msg_id")
    p.set_defaults(func=cmd_delete_message)

    p = sub.add_parser("edit-message", help="修改某条消息内容")
    p.add_argument("msg_id")
    p.add_argument("content")
    p.set_defaults(func=cmd_edit_message)

    sub.add_parser("list-temp", help="列出临时文件").set_defaults(func=cmd_list_temp)
    sub.add_parser("show-admin", help="查看管理账号").set_defaults(func=cmd_show_admin)

    p = sub.add_parser("enable-admin", help="生成/更新管理账号（输出 TOTP 二维码）")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--totp-secret", default="")
    p.set_defaults(func=cmd_enable_admin)

    args = parser.parse_args()
    if not os.path.exists(args.db):
        print(f"[错误] 数据库不存在: {args.db}（请先启动一次服务以初始化）")
        sys.exit(1)
    storage = _load_storage(args.db)
    args.func(storage, args)


if __name__ == "__main__":
    main()
