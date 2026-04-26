#!/usr/bin/env python3
"""
跟进记录 API
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
import json
from app.services.review_generator import generate_review_record
from app.services.jiandaoyun_writer import create_record
from app.config.system_config import get_system_config

router = APIRouter(prefix="/review", tags=["review"])

@router.get("/tags")
async def get_review_tags():
    """
    获取跟进标签树
    """
    try:
        with open("app/config/review_tag_tree.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法加载标签树文件: {str(e)}")

@router.post("/generate")
async def generate_review(data: Dict[str, Any]):
    """
    生成跟进记录
    """
    transcript_text = data.get("transcript_text", "")
    company_id = data.get("company_id", "")
    company_name = data.get("company_name", "")
    
    if not transcript_text or not company_name:
        raise HTTPException(status_code=400, detail="缺少必要参数")
    
    result = await generate_review_record(transcript_text, company_name)
    return result

@router.post("/submit")
async def submit_review(data: Dict[str, Any]):
    """
    提交跟进记录到简道云
    """
    # 从数据中提取字段信息
    company_name = data.get("com_name", "")
    company_id = data.get("comid", "")
    follow_type = data.get("follow_type", "")
    review_date = data.get("review_date", "")
    review_record = data.get("review_record", "")
    if_tuisong = data.get("if_tuisong", "否")
    
    # 处理 genjin_tags 字段
    genjin_tags = data.get("genjin_tags", [])
    
    # 准备简道云写入的数据格式
    jiandaoyun_data = {
        "com_name": {"value": company_name},
        "comid": {"value": company_id},
        "follow_type": {"value": follow_type},
        "review_date": {"value": review_date},
        "review_record": {"value": review_record},
        "if_tuisong": {"value": if_tuisong}
    }
    
    # 处理跟进标签子表单
    if genjin_tags:
        genjin_subform = []
        for tag in genjin_tags:
            level1 = tag.get("level1", "")
            level2 = tag.get("level2", "")
            level3 = tag.get("level3", "")
            genjin_subform.append({
                "genjin_level1": {"value": level1},
                "genjin_level2": {"value": level2},
                "genjin_level3": {"value": level3}
            })
        jiandaoyun_data["genjin"] = {"value": genjin_subform}
    
    # 获取简道云配置
    system_config = get_system_config()
    app_id = system_config.get("jiandaoyun.app_id", "5dcbcb63d6e30c000692464e")
    entry_id = system_config.get("jiandaoyun.review_entry_id", "670a28334883adafb152a869")
    
    # 调用简道云写入服务
    try:
        result = await create_record(app_id, entry_id, jiandaoyun_data)
        return {"message": "跟进记录已成功提交到简道云", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提交到简道云失败: {str(e)}")