#!/usr/bin/env python3
"""
定时检测脚本 - 每10分钟运行一次
用法: python scheduler.py
生产环境建议用 systemd timer 或 cron
"""
import time
import sys
import os

# 添加项目目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checker import check_all_sites
from database import get_sites, save_check

def run_check():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始检测...")
    try:
        check_all_sites()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 检测完成")
    except Exception as e:
        print(f"检测出错: {e}")

if __name__ == "__main__":
    run_check()