#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华东理工大学自动选课脚本 v2.0
支持多课程、配置文件、日志记录、智能重试
"""

import requests
import time
import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Optional
import winsound  # Windows 提示音


class CourseGrabber:
    """选课机器人"""

    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.config = self.load_config()
        self.session = requests.Session()
        self.setup_session()
        self.log_file = f"grab_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

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
            "cookie": "你的cookie"
            "base_url": "https://inquiry.ecust.edu.cn",
            "interval": 2,
            "max_retries": 3,
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
                "duration": 1000
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
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "inquiry.ecust.edu.cn",
            "Origin": self.config["base_url"],
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
        """检查Cookie是否有效

        通过访问学生个人中心页面判断：登录成功会返回个人中心页（标题“学生个人中心”），
        失效则会被重定向到登录页（页面含“用户名”“密码”等登录表单字段）。
        """
        try:
            test_url = f"{self.config['base_url']}/jsxsd/framework/xsMain.jsp"
            resp = self.session.get(test_url, timeout=10)
            text = resp.text

            # 命中个人中心页 -> 有效
            if '学生个人中心' in text or 'xsMain' in text:
                return True

            # 命中登录表单特征 -> 失效
            login_markers = ['用户登录', '统一身份认证', 'name="password"', 'loginName', '账号登录']
            if any(marker in text for marker in login_markers):
                return False

            # 兜底：被重定向到登录相关路径也视为失效
            if 'login' in resp.url.lower():
                return False

            # 其余情况默认放行，避免误判导致无法启动
            return True
        except Exception as e:
            self.log(f"Cookie验证失败: {e}", "ERROR")
            return False

    def grab_course(self, course: dict) -> tuple:
        """
        尝试抢一门课
        返回: (success: bool, message: str)
        """
        # 真实选课接口：GET /jsxsd/xsxkkc/xxxkOper，参数全部拼在URL查询串里
        select_url = f"{self.config['base_url']}/jsxsd/xsxkkc/xxxkOper"

        params = {
            "kcid": course["kcid"],
            "cfbs": "null",
            "jx0404id": course["jx0404id"]
        }

        # 更新Referer
        self.session.headers["Referer"] = f"{self.config['base_url']}/jsxsd/xsxkkc/comeInXxxk?kcxx={course['kcxx']}"

        for retry in range(self.config.get("max_retries", 3)):
            try:
                resp = self.session.get(select_url, params=params, timeout=10)
                # 服务器 Content-Type 标错导致中文乱码，强制按 UTF-8 解码
                resp.encoding = 'utf-8'

                # 注意：该接口虽然把 Content-Type 标为 text/html，但实际返回的是 JSON 文本，
                # 所以不能用 Content-Type 判断 Cookie 是否失效，直接按文本解析 JSON。
                text = resp.text.strip()

                # 如果返回的是登录页面（HTML），才是真正的 Cookie 失效
                if text.startswith('<') or '用户登录' in text or 'loginName' in text:
                    self.log(f"[{course['name']}] 返回登录页面，Cookie已失效", "ERROR")
                    return False, "Cookie已失效，请更新Cookie"

                # 用 resp.json() 会受错误的 Content-Type 影响编码，这里手动按 UTF-8 解析
                result = json.loads(text)

                # 判断选课结果
                if result.get("success"):
                    success_list = result["success"]
                    # 如果success是列表且全为True
                    if isinstance(success_list, list) and all(success_list):
                        return True, "选课成功！"
                    elif isinstance(success_list, bool) and success_list:
                        return True, "选课成功！"

                # 返回服务器的错误消息
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
                self.log(f"响应内容: {resp.text[:300]}", "DEBUG")
                return False, "服务器响应格式错误"

            except Exception as e:
                self.log(f"[{course['name']}] 未知错误: {e}", "ERROR")
                return False, f"未知错误: {str(e)}"

        return False, "重试次数耗尽"

    def play_success_sound(self):
        """播放成功提示音"""
        if self.config.get("notification", {}).get("sound", True):
            try:
                duration = self.config.get("notification", {}).get("duration", 1000)
                # 播放3次提示音
                for _ in range(3):
                    winsound.Beep(1000, duration)
                    time.sleep(0.2)
            except Exception as e:
                self.log(f"播放提示音失败: {e}", "WARNING")

    def run(self):
        """主运行循环"""
        self.log("=" * 60)
        self.log("🚀 华东理工大学自动选课脚本 v2.0 启动")
        self.log("=" * 60)

        # 检查Cookie有效性
        self.log("🔍 正在验证Cookie...")
        if not self.check_cookie_valid():
            self.log("❌ Cookie无效或已过期，请更新Cookie后重试！", "ERROR")
            sys.exit(1)
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
                        self.play_success_sound()
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


if __name__ == "__main__":
    try:
        grabber = CourseGrabber()
        grabber.run()
    except Exception as e:
        print(f"程序异常退出: {e}")
        import traceback
        traceback.print_exc()
