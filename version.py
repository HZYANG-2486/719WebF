#719WEBF 版本信息 - 统一管理所有版本/名称常量
#所有显示版本号的地方都从此文件获取

APP_NAME = "719WEBF"
APP_VER  = "V1.6"
APP_DESC = "文件共享服务"
APP_AUTHOR = "HZYANG"

def get_version_string():
    return f"{APP_NAME} {APP_VER}"

def get_full_info():
    return {
        "name": APP_NAME,
        "version": APP_VER,
        "description": APP_DESC,
        "author": APP_AUTHOR
    }
