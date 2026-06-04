#!/usr/bin/env python3
"""
拉取简道云跟进记录表字段结构的脚本
"""

import requests
import json
import os

# API 配置
CopyAPI_URL = "https://api.jiandaoyun.com/api/v5/app/entry/widget/list"
APP_ID = "5dcbcb63d6e30c000692464e"
ENTRY_ID = "670a28334883adafb152a869"

def fetch_widgets():
    # 从环境变量获取 API key
    api_key = os.environ.get("JIANDAOYUN_API_KEY")
    if not api_key:
        # 如果环境变量不存在，尝试从配置文件读取（可选实现）
        print("警告: JIANDAOYUN_API_KEY 环境变量未设置")
        print("请在运行前设置环境变量，例如:")
        print("Windows (命令提示符): set JIANDAOYUN_API_KEY=nCtsXmo81v6zp3Y7bt01ZXfBfZIrs7zi5A6B8024012B64094C4E75c337242C21")
        print("Windows (PowerShell): $env:JIANDAOYUN_API_KEY=\"nCtsXmo81v6zp3Y7bt01ZXfBfZIrs7zi5A6B8024012B64094C4E75c337242C21\"")
        raise ValueError("请设置 JIANDAOYUN_API_KEY 环境变量")
    
    # 请求头
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 请求体
    payload = {
        "app_id": APP_ID,
        "entry_id": ENTRY_ID
    }
    
    # 发送 POST 请求
    response = requests.post(CopyAPI_URL, headers=headers, json=payload)
    
    if response.status_code != 200:
        raise Exception(f"请求失败，状态码: {response.status_code}, 响应: {response.text}")
    
    # 解析响应
    data = response.json()
    
    # 保存到文件
    output_file = "output/form_genjin_widgets.json"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # 打印每个字段的信息
    print("字段信息:")
    if "widgets" in data:
        for widget in data["widgets"]:
            name = widget.get("name", "N/A")
            label = widget.get("label", "N/A")
            field_type = widget.get("type", "N/A")
            print(f"  Name: {name}, Label: {label}, Type: {field_type}")
    else:
        print("未找到 widgets 数据")
    
    print(f"\n完整数据已保存到 {output_file}")
    return data

if __name__ == "__main__":
    try:
        fetch_widgets()
    except Exception as e:
        print(f"错误: {e}")
        exit(1)