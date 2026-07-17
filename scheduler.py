#!/usr/bin/env python3
"""
单次检测脚本
用法: python scheduler.py
生产环境使用 systemd timer 或 cron 按需定时调用
"""
import sys
import time

from checker import check_all_sites
from database import init_db


def run_check():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始检测...")
    try:
        init_db()
        check_all_sites()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 检测完成")
        return True
    except Exception as e:
        print(f"检测出错: {e}")
        return False


if __name__ == "__main__":
    sys.exit(0 if run_check() else 1)
