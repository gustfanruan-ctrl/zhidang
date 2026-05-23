"""CAS 票据转发服务 —— 智档后端代理访问帆软 BI 系统"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

logger = logging.getLogger("zhidang.cas_auth")

CAS_SERVER = "https://passport.fanruan.com"
CAS_SERVICE_VALIDATE = f"{CAS_SERVER}/cas/p3/serviceValidate"
CAS_PROXY = f"{CAS_SERVER}/cas/p3/proxy"
ZHIDANG_SERVICE = "zhidang"


class CasAuthError(Exception):
    """CAS 认证相关错误"""
    pass


class CasAuthService:
    """CAS 票据转发服务

    管理帆软 BI 的 session cookie，通过 CAS proxy ticket 机制
    代表已登录用户获取 BI 系统的访问权限。
    """

    def __init__(self):
        self._cookie_cache: dict[str, dict[str, Any]] = {}
        self._pgt_store: dict[str, dict[str, Any]] = {}
        self._pgt_iou_map: dict[str, str] = {}  # pgtIou → pgtId

    # ── PGT 管理 ──────────────────────────────────────

    def store_pgt(self, user_id: str, pgt: str, ttl: int = 7200):
        self._pgt_store[user_id] = {"pgt": pgt, "expires_at": time.time() + ttl}

    def handle_pgt_callback(self, pgt_id: str, pgt_iou: str):
        """接收 CAS 服务器的 PGT 回调"""
        self._pgt_iou_map[pgt_iou] = pgt_id
        logger.info("CAS: received PGT callback iou=%s", pgt_iou)

    def resolve_pgt(self, user_id: str, pgt_iou: str) -> bool:
        """用 PGT IOU 查找 PGT 并关联到用户"""
        pgt = self._pgt_iou_map.pop(pgt_iou, None)
        if pgt:
            self.store_pgt(user_id, pgt)
            logger.info("CAS: resolved PGT for user %s", user_id)
            return True
        return False

    # ── BI session 获取 ──────────────────────────────

    async def get_bi_session(self, user_cas_info: dict) -> dict[str, str]:
        """用用户当前的 CAS 信息，获取帆软 BI 的有效 session cookie

        流程：
        1. 用户已在智档通过 CAS 登录，智档持有用户的 PGT
        2. 用 PGT 向 CAS 服务器请求针对 BI 系统的 PT（Proxy Ticket）
        3. 用 PT 去 BI 系统验证 → 拿到 BI 的登录 session cookie
        4. 返回 cookies 供后续 API 调用使用
        """
        user_id = user_cas_info.get("user_id") or user_cas_info.get("username", "unknown")

        cached = self._cookie_cache.get(user_id)
        if cached and cached["expires_at"] > time.time():
            logger.info("CAS: using cached BI session for %s", user_id)
            return cached["cookies"]

        pgt_entry = self._pgt_store.get(user_id)
        if not pgt_entry or pgt_entry["expires_at"] <= time.time():
            if pgt_entry:
                del self._pgt_store[user_id]
            raise CasAuthError("认证失败：无法获取帆软登录态，请重新登录")

        bi_service = user_cas_info.get("bi_service") or "https://crm.finereporthelp.com/WebReport/decision"
        pt = await self._get_proxy_ticket(pgt_entry["pgt"], bi_service)

        cookies = await self._exchange_pt_for_cookies(pt, bi_service)

        self._cookie_cache[user_id] = {"cookies": cookies, "expires_at": time.time() + 3600}
        return cookies

    # ── CAS 协议操作 ────────────────────────────────

    async def _get_proxy_ticket(self, pgt: str, target_service: str) -> str:
        params = {"pgt": pgt, "targetService": target_service}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(CAS_PROXY, params=params)
            resp.raise_for_status()
            text = resp.text
        if "<cas:proxySuccess>" in text:
            match = re.search(r"<cas:proxyTicket>(.*?)</cas:proxyTicket>", text)
            if match:
                return match.group(1)
        if "<cas:proxyFailure>" in text:
            match = re.search(r'<cas:proxyFailure[^>]*code="([^"]*)"[^>]*>(.*?)</cas:proxyFailure>', text)
            detail = match.group(2) if match else text[:200]
            raise CasAuthError(f"获取 CAS Proxy Ticket 失败: {detail}")
        raise CasAuthError(f"获取 CAS Proxy Ticket 失败: {text[:200]}")

    async def _exchange_pt_for_cookies(self, pt: str, bi_base_url: str) -> dict[str, str]:
        cas_login_url = f"{bi_base_url}/cas/login"
        params = {"ticket": pt}
        cookies: dict[str, str] = {}

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            resp = await client.get(cas_login_url, params=params)

            def _extract(resp_obj) -> dict[str, str]:
                c = {}
                for cookie in resp_obj.cookies:
                    c[cookie.name] = cookie.value
                for header in resp_obj.headers.get_list("set-cookie"):
                    parts = header.split(";")[0].split("=", 1)
                    if len(parts) == 2:
                        c[parts[0]] = parts[1]
                return c

            cookies = _extract(resp)
            # follow redirects manually to capture cookies from all responses
            location = resp.headers.get("location")
            while location and not cookies and resp.status_code in (301, 302, 303, 307, 308):
                resp = await client.get(location, follow_redirects=False)
                cookies = _extract(resp)
                location = resp.headers.get("location")

        if not cookies:
            raise CasAuthError("认证失败：无法获取帆软 BI 登录态（无 cookie 返回）")

        return cookies

    # ── ST 验证（用于 SSO 回调） ────────────────────

    async def validate_st(self, st: str, service: str, pgt_url: str = "") -> dict[str, Any]:
        """验证 CAS Service Ticket，返回用户信息。
        若提供 pgt_url，CAS 服务器会回调该 URL 传递 PGT。
        """
        params: dict[str, str] = {"ticket": st, "service": service, "format": "json"}
        if pgt_url:
            params["pgtUrl"] = pgt_url
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(CAS_SERVICE_VALIDATE, params=params)
            resp.raise_for_status()
            data = resp.json()

        sr = data.get("serviceResponse", {})
        auth_success = sr.get("authenticationSuccess")
        if not auth_success:
            auth_failure = sr.get("authenticationFailure", {})
            desc = auth_failure.get("description", auth_failure.get("code", "未知错误"))
            raise CasAuthError(f"CAS 验证失败: {desc}")

        pgt_iou = auth_success.get("proxyGrantingTicket", "")
        return {
            "username": auth_success.get("user", ""),
            "attributes": auth_success.get("attributes", {}),
            "pgt_iou": pgt_iou,
        }


# 全局单例
cas_auth_service = CasAuthService()
