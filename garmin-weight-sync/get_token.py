"""
手动获取小米 Token 辅助脚本
当自动登录失败时，通过浏览器 Cookie 获取 Token
"""
import json
import sys
import webbrowser
from pathlib import Path


def main():
    print("=" * 60)
    print("  小米 Token 手动获取工具")
    print("=" * 60)
    print()
    print("由于小米 API 变更，自动登录已不可用。")
    print("请按以下步骤手动获取 Token：")
    print()

    config_path = "users.json"
    if not Path(config_path).exists():
        print(f"错误：找不到配置文件 {config_path}")
        return

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    users = config.get("users", [])
    if not users:
        print("错误：配置文件中没有用户")
        return

    print("步骤 1: 在浏览器中打开小米账号网站并登录")
    print()

    try:
        webbrowser.open("https://account.xiaomi.com")
        print("  已打开 https://account.xiaomi.com")
    except Exception:
        print("  请手动打开: https://account.xiaomi.com")

    print()
    print("步骤 2: 登录后，按 F12 打开开发者工具")
    print("  -> 切换到 Network (网络) 标签")
    print("  -> 刷新页面")
    print("  -> 点击任意一个请求")
    print("  -> 在 Request Headers 中找到 Cookie 行")
    print("  -> 从 Cookie 中找到 userId 和 passToken 的值")
    print()
    print("  或者切换到 Application (应用) 标签")
    print("  -> 左侧 Cookies -> https://account.xiaomi.com")
    print("  -> 找到 userId 和 passToken")
    print()

    input("准备好后按回车继续...")

    for i, user in enumerate(users):
        username = user.get("username", "N/A")
        print(f"\n--- 用户 [{i+1}] {username} ---")

        userId = input("  userId: ").strip()
        passToken = input("  passToken: ").strip()

        if not userId or not passToken:
            print("  跳过（未提供完整 Token）")
            continue

        if "token" not in user:
            user["token"] = {}
        user["token"]["userId"] = userId
        user["token"]["passToken"] = passToken

        print("  Token 已保存")

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

    print(f"\n配置已保存到 {config_path}")
    print()
    print("现在运行同步：")
    print("  python src/main.py --config users.json --sync")


if __name__ == "__main__":
    main()
