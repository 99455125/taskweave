# --- 开始设置 EXCEL_BASE_DIR ---
# 尝试从环境变量中获取 EXCEL_BASE_DIR
import os
import platform

excel_base_dir_path = os.environ.get('EXCEL_BASE_DIR')

if excel_base_dir_path is None:
    # 如果环境变量中未设置 EXCEL_BASE_DIR
    print("环境变量 EXCEL_BASE_DIR 未设置。将根据操作系统进行定义。")
    if platform.system() == "Windows":
        # 如果是 Windows 系统
        excel_base_dir_path = r'D:\smart_excel_files'  # Windows 系统的绝对路径
        print(f"检测到 Windows 操作系统。设置 EXCEL_BASE_DIR 为: {excel_base_dir_path}")
    else:
        # 如果是非 Windows 系统
        excel_base_dir_path = '/tmp/smart_excel_files'
        print(f"检测到非 Windows 操作系统。设置 EXCEL_BASE_DIR 为项目相对路径: {excel_base_dir_path}")
    # 将确定的路径设置到环境变量中
    os.environ['EXCEL_BASE_DIR'] = excel_base_dir_path
else:
    # 如果环境变量中已设置 EXCEL_BASE_DIR
    print(f"环境变量 EXCEL_BASE_DIR 已存在: {excel_base_dir_path}")

# 确保该目录存在，如果不存在则创建
if not os.path.exists(excel_base_dir_path):
    try:
        os.makedirs(excel_base_dir_path)
        print(f"已创建 EXCEL_BASE_DIR 目录: {excel_base_dir_path}")
    except Exception as e:
        # 如果创建目录失败，记录错误。根据实际需求，您可能需要在这里处理异常，例如退出程序。
        print(f"创建 EXCEL_BASE_DIR 目录 {excel_base_dir_path} 失败: {e}")
# --- 结束设置 EXCEL_BASE_DIR ---