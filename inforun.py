import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import sys
import socket

class FlaskFileServerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Flask文件共享服务器 - VBS后台生成器")
        self.root.geometry("550x450")
        self.root.resizable(False, False)
        
        self.default_font = ('Microsoft YaHei', 10)
        self.root.option_add("*Font", self.default_font)
        
        main_frame = ttk.Frame(root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        ttk.Label(main_frame, text="共享文件夹路径:").grid(row=0, column=0, sticky=tk.W, pady=8)
        self.dir_var = tk.StringVar(value=os.getcwd())
        dir_frame = ttk.Frame(main_frame)
        dir_frame.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=8)
        ttk.Entry(dir_frame, textvariable=self.dir_var, width=30).grid(row=0, column=0, sticky=(tk.W, tk.E))
        ttk.Button(dir_frame, text="浏览", command=self.browse_dir).grid(row=0, column=1, padx=5)
        
        ttk.Label(main_frame, text="服务器端口号:").grid(row=1, column=0, sticky=tk.W, pady=8)
        self.port_var = tk.StringVar(value="5000")
        ttk.Entry(main_frame, textvariable=self.port_var, width=35).grid(row=1, column=1, sticky=(tk.W, tk.E), pady=8)
        
        ttk.Label(main_frame, text="自定义首页标题:").grid(row=2, column=0, sticky=tk.W, pady=8)
        self.title_var = tk.StringVar(value="文件共享服务")
        ttk.Entry(main_frame, textvariable=self.title_var, width=35).grid(row=2, column=1, sticky=(tk.W, tk.E), pady=8)
        
        ttk.Label(main_frame, text="绑定IP地址:").grid(row=3, column=0, sticky=tk.W, pady=8)
        self.host_var = tk.StringVar(value="0.0.0.0")
        ttk.Entry(main_frame, textvariable=self.host_var, width=35).grid(row=3, column=1, sticky=(tk.W, tk.E), pady=8)
        
        ttk.Label(main_frame, text="VBS 保存位置:").grid(row=4, column=0, sticky=tk.W, pady=8)
        self.save_path_var = tk.StringVar(value=os.path.join(os.getcwd(), "启动_后台托盘.vbs"))
        save_frame = ttk.Frame(main_frame)
        save_frame.grid(row=4, column=1, sticky=(tk.W, tk.E), pady=8)
        ttk.Entry(save_frame, textvariable=self.save_path_var, width=30).grid(row=0, column=0, sticky=(tk.W, tk.E))
        ttk.Button(save_frame, text="选择", command=self.choose_save_path).grid(row=0, column=1, padx=5)

        tip = ttk.Label(main_frame, text="✅ 生成 VBS → 无黑框、后台托盘、关闭窗口不影响服务", foreground="#0066cc")
        tip.grid(row=5, column=0, columnspan=2, pady=5)
        
        ttk.Button(main_frame, text="生成 后台托盘VBS", command=self.generate_vbs).grid(row=6, column=0, columnspan=2, pady=20)
        
        main_frame.columnconfigure(1, weight=1)
        dir_frame.columnconfigure(0, weight=1)
        save_frame.columnconfigure(0, weight=1)
        
    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 8))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return "192.168.1.1"
    
    def browse_dir(self):
        dir_path = filedialog.askdirectory(title="选择共享文件夹", initialdir=self.dir_var.get())
        if dir_path:
            self.dir_var.set(dir_path)
    
    def choose_save_path(self):
        file_path = filedialog.asksaveasfilename(
            title="保存 VBS 文件",
            initialfile="启动_后台托盘.vbs",
            defaultextension=".vbs",
            filetypes=[("VBS 文件", "*.vbs"), ("所有文件", "*.*")]
        )
        if file_path:
            self.save_path_var.set(file_path)
    
    def generate_vbs(self):
        try:
            local_ip = self.get_local_ip()
            app_path = os.path.abspath("app.py")

            # 🔥【核心修复】VBS 引号完全正确，永不报错
            vbs_content = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw.exe ""{app_path}"" -d ""{self.dir_var.get()}"" -p {self.port_var.get()} -t ""{self.title_var.get()}"" -host {self.host_var.get()}", 0
Set WshShell = Nothing
'''
            
            with open(self.save_path_var.get(), "w", encoding="utf-8") as f:
                f.write(vbs_content)
            
            messagebox.showinfo("✅ 生成成功", 
                f"VBS 后台启动文件已生成！\n路径：{self.save_path_var.get()}\n\n"
                f"📌 本地访问：http://127.0.0.1:{self.port_var.get()}\n"
                f"📌 局域网访问：http://{local_ip}:{self.port_var.get()}\n\n"
                f"✅ 双击 VBS 即可后台托盘运行")
            
        except Exception as e:
            messagebox.showerror("错误", f"生成 VBS 失败：{str(e)}")

if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
    
    root = tk.Tk()
    app = FlaskFileServerGUI(root)
    root.mainloop()