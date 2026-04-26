#!/usr/bin/env python3
"""
跟进记录生成服务
"""

import json
import httpx
import os
from datetime import datetime
from typing import Dict, Any
from app.config.system_config import get_system_config

async def generate_review_record(transcript_text: str, company_name: str) -> Dict[str, Any]:
    """
    接收会议转写文本和客户名称，调用 LLM 生成结构化跟进记录
    
    Args:
        transcript_text: 会议转写文本
        company_name: 客户名称
    
    Returns:
        生成的跟进记录字典
    """
    
    # 获取系统配置
    system_config = get_system_config()
    
    # LLM 配置
    llm_base_url = system_config.get("llm_base_url", "https://api.siliconflow.cn/v1")
    llm_model = system_config.get("llm_model", "Qwen/Qwen3-Coder-30B-A3B-Instruct")
    llm_api_key = system_config.get("llm_api_key", "")
    
    # 构建提示词
    tag_tree_data = _load_tag_tree()
    
    # 构建系统提示词
    system_prompt = f"""
你是方正内部的客户成功记录员
从会议转写中提取结构化跟进记录
输出 JSON 包含以下字段：
follow_type：从"线上跟进/线下跟进/内部沟通"选一个
review_date：YYYY-MM-DD，识别不到用今天日期
review_record：严格按以下格式输出：
【跟进目的】
一句话概括，10字以内
【沟通详情】
客观详细记录沟通内容，保留所有数字、版本号、规模等具体信息
【附件/kms链接】
暂无
【参与人】
我方：xxx  客户方：xxx（职位/部门）
genjin_tags：数组，每项 {{level1, level2, level3}}，从以下选项中选择，level3 可为空字符串：
{json.dumps(tag_tree_data, ensure_ascii=False, indent=2)}
contact_names：字符串，客户侧参与人
if_tuisong：默认"否"

跟进标签的完整选项树要写在 prompt 里，让 LLM 从中选择，不要让 LLM 自己编标签
请只输出纯 JSON，不要用 markdown 代码块包裹，不要添加任何额外文字。
"""
    
    # 构建用户提示词
    user_prompt = f"""
会议转写内容：
{transcript_text}

客户名称：
{company_name}

请根据以上内容生成结构化的跟进记录。
"""
    
    # 构建请求数据
    request_data = {
        "model": llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False
    }
    
    # 调用 LLM API
    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {llm_api_key}",
                "Content-Type": "application/json"
            }
            response = await client.post(
                f"{llm_base_url}/chat/completions", 
                headers=headers, 
                json=request_data,
                timeout=60
            )
            
            if response.status_code != 200:
                return {"error": f"调用 LLM API 失败，状态码: {response.status_code}"}
            
            # 解析 LLM 返回结果
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # 去除可能的 markdown 代码块包裹
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]  # 去掉第一行 ```json
                content = content.rsplit("```", 1)[0]  # 去掉最后的 ```
                content = content.strip()
            
            # 尝试解析 JSON
            try:
                data = json.loads(content)
                return data
            except json.JSONDecodeError:
                return {"error": "LLM 返回内容不是有效的 JSON 格式"}
                
    except Exception as e:
        return {"error": f"调用 LLM API 时发生错误: {str(e)}"}

def _load_tag_tree():
    """
    加载跟进标签选项树
    """
    try:
        with open("app/config/review_tag_tree.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"无法加载标签树文件: {str(e)}"}