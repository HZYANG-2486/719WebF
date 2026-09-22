#所有显示版本号的地方都从此文件获取

APP_NAME = "719WEBF"
APP_VER  = "Ver.1.6-Beta_3"
APP_DESC = "万务文牍传递之器"
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
