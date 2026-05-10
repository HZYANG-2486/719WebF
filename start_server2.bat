@echo off
@echo off > nul 2>&1
chcp 65001
cls
pip install Flask==3.0.3 Cloudflare_error_page==0.2.0 flask-Humanify==0.2.8
@echo off
cls
echo ==============================
echo Flask文件共享服务器启动脚本
echo ==============================
echo 共享文件夹: G:/
echo 端口号: 5000
echo 绑定IP: 0.0.0.0
echo 首页标题: 719WebF
echo.
echo 正在启动服务器...
echo 本地访问: http://127.0.0.1:5000
echo 局域网访问: http://192.168.10.79:5000
echo 按 Ctrl+C 停止服务器
echo.

call python "G:\CODEING\PortableGit\719WebF\app.py" -d "G:/" -t "719WebF" 2>nul

pause>nul
