import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import sys
import socket

class FlaskFileServerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Flask文件共享服务器 - BAT生成器")
        self.root.geometry("550x400")
        self.root.resizable(False, False)
        
        # 设置字体
        self.default_font = ('Microsoft YaHei', 10)
        self.root.option_add("*Font", self.default_font)
        
        # 创建主框架
        main_frame = ttk.Frame(root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 1. 共享文件夹路径
        ttk.Label(main_frame, text="共享文件夹路径:").grid(row=0, column=0, sticky=tk.W, pady=8)
        self.dir_var = tk.StringVar(value=os.getcwd())
        dir_frame = ttk.Frame(main_frame)
        dir_frame.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=8)
        ttk.Entry(dir_frame, textvariable=self.dir_var, width=30).grid(row=0, column=0, sticky=(tk.W, tk.E))
        ttk.Button(dir_frame, text="浏览", command=self.browse_dir).grid(row=0, column=1, padx=5)
        
        # 2. 端口号
        ttk.Label(main_frame, text="服务器端口号:").grid(row=1, column=0, sticky=tk.W, pady=8)
        self.port_var = tk.StringVar(value="5000")
        ttk.Entry(main_frame, textvariable=self.port_var, width=35).grid(row=1, column=1, sticky=(tk.W, tk.E), pady=8)
        
        # 3. 首页标题
        ttk.Label(main_frame, text="自定义首页标题:").grid(row=2, column=0, sticky=tk.W, pady=8)
        self.title_var = tk.StringVar(value="文件共享服务")
        ttk.Entry(main_frame, textvariable=self.title_var, width=35).grid(row=2, column=1, sticky=(tk.W, tk.E), pady=8)
        
        # 4. 绑定IP地址
        ttk.Label(main_frame, text="绑定IP地址:").grid(row=3, column=0, sticky=tk.W, pady=8)
        self.host_var = tk.StringVar(value="0.0.0.0")
        ttk.Entry(main_frame, textvariable=self.host_var, width=35).grid(row=3, column=1, sticky=(tk.W, tk.E), pady=8)
        
        # 5. BAT文件保存路径
        ttk.Label(main_frame, text="BAT文件保存位置:").grid(row=4, column=0, sticky=tk.W, pady=8)
        self.save_path_var = tk.StringVar(value=os.path.join(os.getcwd(), "start_server.bat"))
        save_frame = ttk.Frame(main_frame)
        save_frame.grid(row=4, column=1, sticky=(tk.W, tk.E), pady=8)
        ttk.Entry(save_frame, textvariable=self.save_path_var, width=30).grid(row=0, column=0, sticky=(tk.W, tk.E))
        ttk.Button(save_frame, text="选择", command=self.choose_save_path).grid(row=0, column=1, padx=5)
        
        # 生成按钮
        ttk.Button(main_frame, text="生成BAT文件", command=self.generate_bat).grid(row=5, column=0, columnspan=2, pady=20)
        
        # 配置列权重
        main_frame.columnconfigure(1, weight=1)
        dir_frame.columnconfigure(0, weight=1)
        save_frame.columnconfigure(0, weight=1)
        
    def get_local_ip(self):
        """获取本机局域网IP地址"""
        try:
            # 创建UDP连接获取本机IP（不实际连接）
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return "192.168.1.1"  # 备用IP
        
    def browse_dir(self):
        """浏览选择共享文件夹"""
        dir_path = filedialog.askdirectory(title="选择共享文件夹", initialdir=self.dir_var.get())
        if dir_path:
            self.dir_var.set(dir_path)
    
    def choose_save_path(self):
        """选择BAT文件保存路径"""
        file_path = filedialog.asksaveasfilename(
            title="保存BAT文件",
            initialfile="start_server.bat",
            defaultextension=".bat",
            filetypes=[("BAT文件", "*.bat"), ("所有文件", "*.*")]
        )
        if file_path:
            self.save_path_var.set(file_path)
    
    def generate_bat(self):
        """生成优化后的BAT文件"""
        try:
            # 获取本机真实局域网IP
            local_ip = self.get_local_ip()
            
            # 构建命令参数
            cmd_parts = ["python", "app.py"]
            
            # 添加可选参数
            if self.dir_var.get() and self.dir_var.get() != os.getcwd():
                cmd_parts.extend(["-d", f'"{self.dir_var.get()}"'])
            if self.port_var.get() and self.port_var.get() != "5000":
                cmd_parts.extend(["-p", self.port_var.get()])
            if self.title_var.get() and self.title_var.get() != "文件共享服务":
                cmd_parts.extend(["-t", f'"{self.title_var.get()}"'])
            if self.host_var.get() and self.host_var.get() != "0.0.0.0":
                cmd_parts.extend(["-host", self.host_var.get()])
            
            # 构建完整命令
            full_cmd = " ".join(cmd_parts)
            
            # 最终优化版BAT内容
            bat_content = f"""@echo off
:: 关闭命令回显（解决"回传未取消"问题）
@echo off > nul 2>&1

:: 修复Windows终端中文乱码
chcp 65001 

pip install flask
pip install cloudflare_error_page
:: 清屏，让界面更整洁
cls

echo ==============================
echo Flask文件共享服务器启动脚本
echo ==============================
echo 共享文件夹: {self.dir_var.get()}
echo 端口号: {self.port_var.get()}
echo 绑定IP: {self.host_var.get()}
echo 首页标题: {self.title_var.get()}
echo.
echo 正在启动服务器...
echo 本地访问: http://127.0.0.1:{self.port_var.get()}
echo 局域网访问: http://{local_ip}:{self.port_var.get()}
echo 按 Ctrl+C 停止服务器
echo.

:: 启动服务器（隐藏命令执行回显）
{full_cmd} 

:: 防止窗口关闭
pause > nul
"""
            
            # 以UTF-8 with BOM编码保存
            with open(self.save_path_var.get(), "w", encoding="utf-8-sig") as f:
                f.write(bat_content)
            
            messagebox.showinfo("成功", 
                f"BAT文件已生成！\n路径：{self.save_path_var.get()}\n\n"
                f"📌 本地访问：http://127.0.0.1:{self.port_var.get()}\n"
                f"📌 局域网访问：http://{local_ip}:{self.port_var.get()}")
            
        except Exception as e:
            messagebox.showerror("错误", f"生成BAT文件失败：{str(e)}")

if __name__ == "__main__":
    # 高DPI支持
    if hasattr(tk, 'tkinter'):
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass
    
    root = tk.Tk()
    app = FlaskFileServerGUI(root)
    root.mainloop()