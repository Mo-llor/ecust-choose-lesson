#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华东理工大学自动选课脚本 v3.0
新增功能:
- 自动获取课程列表,无需手动抓取ID
- 多种通知方式(提示音/桌面通知/Webhook)
- Cookie过期自动检测和暂停处理
"""

import requests
import time
import json
import os
import sys
import re
from datetime import datetime
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


class CourseGrabber:
    """选课机器人 v3.0"""

    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.config = self.load_config()
        self.session = requests.Session()
        self.setup_session()
        self.log_file = f"grab_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        self.cookie_expired = False

    def load_config(self) -> dict:
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            self.create_default_config()
            self.log("⚠️  配置文件不存在，已创建默认配置文件，请编辑后重新运行！")
            sys.exit(1)

        with open(self.config_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def create_default_config(self):
        """创建默认配置文件"""
        default_config = {
            "cookie": "请在这里粘贴你的完整Cookie",
            "base_url": "https://inquiry.ecust.edu.cn",
            "interval": 2,
            "max_retries": 3,
            "auto_fetch_courses": False,
            "courses": [
                {
                    "name": "示例课程",
                    "kcxx": "117500010",
                    "jx0404id": "261117500010001",
                    "kcid": "3E319A6B912E4B188E11F7899E2FC08D",
                    "enabled": True
                }
            ],
            "notification": {
                "sound": True,
                "duration": 1000,
                "webhook": {
                    "enabled": False,
                    "url": "",
                    "type": "dingtalk"
                }
            }
        }

        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=4, ensure_ascii=False)

    def setup_session(self):
        """设置会话头部"""
        self.session.headers.update({
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
            "Host": "inquiry.ecust.edu.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": self.config["cookie"]
        })

    def log(self, message: str, level: str = "INFO"):
        """记录日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_msg = f"[{timestamp}] [{level}] {message}"
        print(log_msg)

        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_msg + '\n')

    def check_cookie_valid(self) -> bool:
        """检查Cookie是否有效"""
        try:
            test_url = f"{self.config['base_url']}/jsxsd/framework/xsMain.jsp"
            resp = self.session.get(test_url, timeout=10)
            text = resp.text

            if '学生个人中心' in text or 'xsMain' in text:
                return True

            login_markers = ['用户登录', '统一身份认证', 'name="password"', 'loginName', '账号登录']
            if any(marker in text for marker in login_markers):
                return False

            if 'login' in resp.url.lower():
                return False

            return True
        except Exception as e:
            self.log(f"Cookie验证失败: {e}", "ERROR")
            return False

    def fetch_available_courses(self, kcxx: str = "") -> List[Dict]:
        """
        自动获取可选课程列表
        参数 kcxx: 课程类别代码,留空则获取所有
        返回: 课程列表 [{name, kcxx, kcid, jx0404id, teacher, time, capacity}, ...]
        """
        try:
            # 访问选课页面
            url = f"{self.config['base_url']}/jsxsd/xsxkkc/comeInXxxk"
            params = {"kcxx": kcxx} if kcxx else {}

            resp = self.session.get(url, params=params, timeout=15)
            resp.encoding = 'utf-8'

            soup = BeautifulSoup(resp.text, 'html.parser')
            courses = []

            # 查找课程表格
            table = soup.find('table', {'id': 'dataList'})
            if not table:
                self.log("未找到课程表格，可能Cookie失效或页面结构变化", "WARNING")
                return []

            rows = table.find_all('tr')[1:]  # 跳过表头

            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 8:
                    continue

                # 提取课程信息
                onclick = cols[0].find('input', {'name': 'jx0404id'})
                if not onclick:
                    continue

                jx0404id = onclick.get('value', '')

                # 从第一个单元格的 onclick 事件提取 kcid
                btn = cols[0].find('input', {'type': 'button'})
                kcid = ""
                if btn and btn.get('onclick'):
                    match = re.search(r"'([A-F0-9]{32})'", btn.get('onclick'))
                    if match:
                        kcid = match.group(1)

                course = {
                    "name": cols[1].text.strip(),
                    "kcxx": kcxx,
                    "jx0404id": jx0404id,
                    "kcid": kcid,
                    "teacher": cols[5].text.strip(),
                    "time": cols[6].text.strip(),
                    "capacity": cols[7].text.strip(),
                    "enabled": False
                }
                courses.append(course)

            self.log(f"成功获取 {len(courses)} 门可选课程", "INFO")
            return courses

        except Exception as e:
            self.log(f"获取课程列表失败: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return []

    def handle_cookie_expired(self):
        """处理Cookie过期的情况"""
        self.cookie_expired = True
        self.log("=" * 60, "ERROR")
        self.log("🚨 COOKIE 已过期！", "ERROR")
        self.log("=" * 60, "ERROR")

        # 播放紧急提示音
        if HAS_WINSOUND:
            for _ in range(5):
                winsound.Beep(2000, 300)
                time.sleep(0.1)

        self.log("请按以下步骤操作:", "ERROR")
        self.log("1. 打开浏览器重新登录教务系统", "ERROR")
        self.log("2. 按 F12 -> Network -> 刷新页面 -> 复制 Cookie", "ERROR")
        self.log("3. 更新 config.json 中的 cookie 字段", "ERROR")
        self.log("4. 按 Enter 继续运行...", "ERROR")

        input()

        # 重新加载配置
        self.config = self.load_config()
        self.session.headers["Cookie"] = self.config["cookie"]

        # 验证新Cookie
        if self.check_cookie_valid():
            self.log("✅ Cookie 已更新，继续运行", "INFO")
            self.cookie_expired = False
        else:
            self.log("❌ 新Cookie仍然无效，程序退出", "ERROR")
            sys.exit(1)

    def grab_course(self, course: dict) -> tuple:
        """
        尝试抢一门课
        返回: (success: bool, message: str)
        """
        select_url = f"{self.config['base_url']}/jsxsd/xsxkkc/xxxkOper"

        params = {
            "kcid": course["kcid"],
            "cfbs": "null",
            "jx0404id": course["jx0404id"]
        }

        self.session.headers["Referer"] = f"{self.config['base_url']}/jsxsd/xsxkkc/comeInXxxk?kcxx={course.get('kcxx', '')}"

        for retry in range(self.config.get("max_retries", 3)):
            try:
                resp = self.session.get(select_url, params=params, timeout=10)
                resp.encoding = 'utf-8'
                text = resp.text.strip()

                # 检测Cookie失效
                if text.startswith('<') or '用户登录' in text or 'loginName' in text:
                    self.log(f"[{course['name']}] 检测到Cookie失效", "ERROR")
                    self.handle_cookie_expired()
                    continue  # Cookie更新后重试

                result = json.loads(text)

                # 判断选课结果
                if result.get("success"):
                    success_list = result["success"]
                    if isinstance(success_list, list) and all(success_list):
                        return True, "选课成功！"
                    elif isinstance(success_list, bool) and success_list:
                        return True, "选课成功！"

                message = result.get("message", "未知错误")
                return False, message

            except requests.exceptions.Timeout:
                self.log(f"[{course['name']}] 请求超时 (尝试 {retry + 1}/{self.config['max_retries']})", "WARNING")
                if retry < self.config["max_retries"] - 1:
                    time.sleep(0.5)
                    continue
                return False, "请求超时"

            except requests.exceptions.RequestException as e:
                self.log(f"[{course['name']}] 网络错误: {e}", "ERROR")
                return False, f"网络错误: {str(e)}"

            except json.JSONDecodeError:
                self.log(f"[{course['name']}] 响应不是JSON格式", "ERROR")
                self.log(f"响应内容: {text[:300]}", "DEBUG")
                return False, "服务器响应格式错误"

            except Exception as e:
                self.log(f"[{course['name']}] 未知错误: {e}", "ERROR")
                return False, f"未知错误: {str(e)}"

        return False, "重试次数耗尽"

    def send_notification(self, course_name: str):
        """发送选课成功通知"""
        message = f"🎉 选课成功：{course_name}"

        # 1. 提示音
        if self.config.get("notification", {}).get("sound", True) and HAS_WINSOUND:
            try:
                duration = self.config.get("notification", {}).get("duration", 1000)
                for _ in range(3):
                    winsound.Beep(1000, duration)
                    time.sleep(0.2)
            except Exception as e:
                self.log(f"播放提示音失败: {e}", "WARNING")

        # 2. Webhook通知 (钉钉/企业微信等)
        webhook_config = self.config.get("notification", {}).get("webhook", {})
        if webhook_config.get("enabled") and webhook_config.get("url"):
            try:
                self.send_webhook(webhook_config, message)
            except Exception as e:
                self.log(f"Webhook通知失败: {e}", "WARNING")

    def send_webhook(self, config: dict, message: str):
        """发送Webhook通知"""
        url = config["url"]
        webhook_type = config.get("type", "dingtalk")

        if webhook_type == "dingtalk":
            # 钉钉机器人
            data = {
                "msgtype": "text",
                "text": {"content": message}
            }
        elif webhook_type == "wecom":
            # 企业微信机器人
            data = {
                "msgtype": "text",
                "text": {"content": message}
            }
        else:
            # 通用POST
            data = {"message": message}

        resp = requests.post(url, json=data, timeout=5)
        if resp.status_code == 200:
            self.log("Webhook通知已发送", "INFO")
        else:
            self.log(f"Webhook通知失败: {resp.status_code}", "WARNING")

    def run(self):
        """主运行循环"""
        self.log("=" * 60)
        self.log("🚀 华东理工大学自动选课脚本 v3.0 启动")
        self.log("=" * 60)

        # 检查Cookie有效性
        self.log("🔍 正在验证Cookie...")
        if not self.check_cookie_valid():
            self.log("❌ Cookie无效或已过期！", "ERROR")
            self.handle_cookie_expired()
        self.log("✅ Cookie验证通过")

        # 获取启用的课程
        courses = [c for c in self.config["courses"] if c.get("enabled", True)]

        if not courses:
            self.log("❌ 没有启用的课程，请检查配置文件", "ERROR")
            sys.exit(1)

        self.log(f"📚 待抢课程数: {len(courses)}")
        for idx, course in enumerate(courses, 1):
            self.log(f"  {idx}. {course['name']}")

        self.log(f"⏱️  检查间隔: {self.config['interval']}秒")
        self.log("按 Ctrl+C 可随时停止")
        self.log("-" * 60)

        success_courses = []
        remaining_courses = courses.copy()
        attempt = 0

        try:
            while remaining_courses:
                attempt += 1
                self.log(f"\n🔄 第 {attempt} 轮尝试 (剩余课程: {len(remaining_courses)})")

                newly_grabbed = []

                for course in remaining_courses:
                    success, message = self.grab_course(course)

                    if success:
                        self.log(f"🎉 [{course['name']}] {message}", "SUCCESS")
                        success_courses.append(course)
                        newly_grabbed.append(course)
                        self.send_notification(course['name'])
                    else:
                        self.log(f"⏳ [{course['name']}] {message}")

                # 移除已成功的课程
                for course in newly_grabbed:
                    remaining_courses.remove(course)

                # 如果还有课程没抢到，等待后继续
                if remaining_courses:
                    time.sleep(self.config["interval"])

        except KeyboardInterrupt:
            self.log("\n\n⚠️  用户手动停止", "WARNING")

        # 输出最终结果
        self.log("\n" + "=" * 60)
        self.log("📊 最终结果")
        self.log("=" * 60)
        self.log(f"✅ 成功抢到: {len(success_courses)} 门")
        for course in success_courses:
            self.log(f"  ✓ {course['name']}")

        if remaining_courses:
            self.log(f"❌ 未抢到: {len(remaining_courses)} 门")
            for course in remaining_courses:
                self.log(f"  ✗ {course['name']}")

        self.log(f"\n📝 日志已保存到: {self.log_file}")


def interactive_course_selection():
    """交互式课程选择模式"""
    print("=" * 60)
    print("🔍 自动获取课程列表模式")
    print("=" * 60)

    grabber = CourseGrabber()

    # 验证Cookie
    print("正在验证Cookie...")
    if not grabber.check_cookie_valid():
        print("❌ Cookie无效，请先更新config.json中的cookie")
        return
    print("✅ Cookie有效\n")

    # 获取课程列表
    kcxx = input("请输入课程类别代码(留空获取全部): ").strip()
    print("正在获取课程列表，请稍候...")

    courses = grabber.fetch_available_courses(kcxx)

    if not courses:
        print("❌ 未获取到课程，请检查网络或Cookie")
        return

    # 显示课程列表
    print(f"\n找到 {len(courses)} 门课程:")
    print("-" * 60)
    for idx, course in enumerate(courses, 1):
        print(f"{idx:2d}. {course['name']:<30s} | {course['teacher']:<10s} | {course['capacity']}")
    print("-" * 60)

    # 选择课程
    selected = input("\n请输入要抢的课程编号(多个用逗号分隔,如: 1,3,5): ").strip()

    try:
        indices = [int(x.strip()) - 1 for x in selected.split(',')]
        selected_courses = [courses[i] for i in indices if 0 <= i < len(courses)]

        for course in selected_courses:
            course['enabled'] = True

        # 保存到配置
        grabber.config['courses'] = selected_courses
        with open(grabber.config_file, 'w', encoding='utf-8') as f:
            json.dump(grabber.config, f, indent=4, ensure_ascii=False)

        print(f"\n✅ 已选择 {len(selected_courses)} 门课程并保存到配置文件")
        print("现在可以运行 python grab_v3.py 开始抢课")

    except Exception as e:
        print(f"❌ 选择失败: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fetch":
        # 交互式获取课程模式
        interactive_course_selection()
    else:
        # 正常抢课模式
        try:
            grabber = CourseGrabber()
            grabber.run()
        except Exception as e:
            print(f"程序异常退出: {e}")
            import traceback
            traceback.print_exc()
