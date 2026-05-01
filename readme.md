# 719WebF
一个在班级以内共享文件的服务...

## 特性
1. ~~氢量~~化
2. 文件互传(暂存/WebRTC)
3. 共享文件夹服务
4. ~~AI使用~~
5. 看板娘(你可以关闭, 基于[live2d-widget](https://github.com/stevenjoezhang/live2d-widget)做了部分适应性修改)

## 使用方法
1. Star It!

2. Download ZIP, 解压

3. 参照配置

## 配置
### 快速上手
1. 运行inforun.py配置信息, 在根目录生成.bat
2. 运行.bat文件(需要的库已经随.bat生成)
### 命令行配置
本服务是由命令行参数传入进行配置的,你需要通过以下方式配置
```
python app.py [-d DIR] [-p PORT] [-t TITLE] [-host HOST]
```
但是你必须要安装以下库:
1. Flask
2. cloudflare_error_page
这些均可以通过pip安装

## 授权
项目采用GPLv3协议进行授权(曾使用GPLv2进行授权,已更改)
Cloudflare_error_page使用MIT授权

## 使用的项目
 - [live2d-widget](https://github.com/stevenjoezhang/live2d-widget)

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

***
HZYANG 2026
