# 719WebF
一个在班级以内共享文件的服务...

## 特性
1. ~~氢量~~化
2. 文件互传(暂存/WebRTC)
3. 共享文件夹服务
4. ~~AI使用~~
5. 看板娘(你可以关闭, 基于[live2d-widget](https://github.com/stevenjoezhang/live2d-widget)做了部分适应性修改)
6. 使用 [Flask-Humanify](https://github.com/tn3w/flask-Humanify) ~~(改不完就换是吧(⊙ˍ⊙)))~~ 进行防DDOS防护(~~主要除非你是嘉豪应该不会乱搞吧owo~~)
7. 后台静默运行

## 使用方法
1. Star It!

2. Download ZIP, 解压

3. 参照配置

## 配置
### 快速上手
1. 运行app.py(或是预编译的exe文件)
2. 右键托盘打开设置
### 源代码运行
~~本服务是由命令行参数传入进行配置的,你需要通过以下方式配置~~
我们已经停用了命令行参数传入,现在配置使用xml文件存储于启动目录下

你现在只需以pythonw的形式运行即可
```
pythonw app.py
```
当然,如果你只想打开设置,只需传入
```
python app.py --gui
```
但是你必须要安装以下库:
1. Flask
2. Cloudflare_error_page
3. Flask-Humanify(会下载诸如opencv和numpy)
4. audiooop(Flask-Humanify需要,但已在Py3.11时已被弃用,你可能需要下载替代者如audioop-lts)
5. pystray pillow waitress(后台托盘运行需要)<br>
 这些均可以通过pip安装<br>
 运行以下即可安装:
```
pip install Flask==3.0.3 Cloudflare_error_page==0.2.0 flask-Humanify==0.2.8 audioop-lts==0.2.2 waitress==3.0.2 pillow==12.2.0 pystray==0.19.5
```

## 授权
项目采用GPLv3协议进行授权(曾使用GPLv2进行授权,已更改)
Cloudflare_error_page使用MIT授权

## 使用的项目
 - [live2d-widget](https://github.com/stevenjoezhang/live2d-widget)
 - [Flask-Humanify](https://github.com/tn3w/flask-Humanify)

## 人物版权
 - 均通过网络加载,本服务**不部署**任何模型

## 更多
Live2D 相关代码的使用请遵守对应的许可：

Live2D Cubism SDK 2.1 的许可证：
Live2D SDK License Agreement (Public)

Live2D Cubism SDK 5 的许可证：
Live2D Cubism Core は Live2D Proprietary Software License で提供しています。
https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_cn.html
Live2D Cubism Components は Live2D Open Software License で提供しています。
https://www.live2d.com/eula/live2d-open-software-license-agreement_cn.html

# 支持
由[Fony Yu](https://github.com/FonyMC)为**HZYANG**提供情绪价值。
🤣👆(HZ的笑)

***
HZYANG 2026
