import os
import time
import logging
import subprocess
import xmlrpc.client
import win32com.client
from functools import wraps
from tools import com_config
from inspect import signature

logging.basicConfig(level=logging.INFO)
'''
存放通用工具的工具类
1. 函数类型检查
2. requests库下载
3. aria2下载
4. 检查进程是否存在
'''


def typeassert(*type_args, **type_kwargs):
    """
    强制函数类型检查
    """

    def decorate(func):
        sig = signature(func)
        bound_types = sig.bind_partial(*type_args, **type_kwargs).arguments

        @wraps(func)
        def wrapper(*args, **kwargs):
            bound_values = sig.bind(*args, **kwargs)
            for name, value in bound_values.arguments.items():
                if name in bound_types:
                    if not isinstance(value, bound_types[name]):
                        raise TypeError('函数的参数 {} 的类型必须是 {}'.format(name, bound_types[name]))
            return func(*args, **kwargs)

        return wrapper

    return decorate


def timer(func):
    """计算函数运行时间"""
    def decor(*args):
        start_time = time.clock()
        func(*args)
        end_time = time.clock()
        d_time = end_time - start_time
        # print("run the func use : ", d_time)
        logging.info("用时:"+str(d_time))
    return decor


def check_process_exist_by_process_name(process_name):
    """查看win是否存在某个进程"""
    global process_code_cov
    try:
        wmi = win32com.client.GetObject('winmgmts:')
        process_code_cov = wmi.ExecQuery('select * from Win32_Process where Name="%s"' % process_name)
    except Exception as e:
        print(process_name, "error : ", e)
    if len(process_code_cov) > 0:
        print(process_name + " exist");
        return True
    else:
        print(process_name + " is not exist")
        return False


@typeassert(aria2_file_list=list, aria2_file_name=str, aria2_file_path=str)
def aria2_download(aria2_file_list, aria2_file_name="", aria2_file_path="../downloads"):
    """使用aria2进行下载"""
    # 切换到启动aria2脚本所在的目录
    os.chdir(com_config.aria2_dir_path)
    # aria2服务器只启动一次，通过查看进程决定是否再启动
    if not check_process_exist_by_process_name("aria2c.exe"):
        subprocess.Popen(com_config.aria2_start_script)
    # 连接服务器
    sever = xmlrpc.client.ServerProxy('http://localhost:6800/rpc')
    '''
    需要下载的文件列表 aria2_file_list = ['https://cdn.pixabay.com/photo/2018/11/29/21/19/hamburg-3846525_960_720.jpg']
    下载到本地的文件名 aria2_file_name = "demo.png"
    下载到本地的路径   aria2_file_path = "C:\\Users\\Anchan\\Desktop"
    '''
    # 执行下载
    if aria2_file_name is "":
        options = {"dir": aria2_file_path}
    else:
        options = {"out": aria2_file_name, "dir": aria2_file_path}
    for file in aria2_file_list:
        sever.aria2.addUri("token:my_token", [file], options)


