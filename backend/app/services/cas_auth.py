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


class CasAuthError(Exception):
    pass


class CasAuthService:
    def __init__(self):
        self._cookie_cache: dict[str, dict[str, Any]] = {}
        self._token_cache: dict[str, dict[str, Any]] = {}
        self._pgt_store: dict[str, dict[str, Any]] = {}
        self._pgt_iou_map: dict[str, str] = {}

    def store_pgt(self, user_id: str, pgt: str, ttl: int = 7200):
        self._pgt_store[user_id] = {"pgt": pgt, "expires_at": time.time() + ttl}

    def handle_pgt_callback(self, pgt_id: str, pgt_iou: str):
        self._pgt_iou_map[pgt_iou] = pgt_id
        logger.info("CAS: received PGT callback iou=%s", pgt_iou)

    def resolve_pgt(self, user_id: str, pgt_iou: str) -> bool:
        pgt = self._pgt_iou_map.pop(pgt_iou, None)
        if pgt:
            self.store_pgt(user_id, pgt)
            logger.info("CAS: resolved PGT for user %s", user_id)
            return True
        return False

    async def get_bi_session(self, user_cas_info: dict) -> dict[str, str]:
        user_id = (
            user_cas_info.get("user_id")
            or user_cas_info.get("username")
            or user_cas_info.get("user_name")
            or "unknown"
        )
        bi_service = user_cas_info.get("bi_service") or "https://crm.finereporthelp.com/WebReport/decision"

        cached = self._cookie_cache.get(user_id)
        if cached and cached["expires_at"] > time.time():
            logger.info("CAS: using cached BI session for %s", user_id)
            return cached["cookies"]

        pgt_entry = self._pgt_store.get(user_id)
        if pgt_entry and pgt_entry["expires_at"] > time.time():
            pt = await self._get_proxy_ticket(pgt_entry["pgt"], bi_service)
            cookies = await self._exchange_pt_for_cookies(pt, bi_service)
            self._cookie_cache[user_id] = {"cookies": cookies, "expires_at": time.time() + 3600}
            return cookies
        if pgt_entry:
            del self._pgt_store[user_id]

        login_mobile = (user_cas_info.get("login_mobile") or "").strip()
        login_password = (user_cas_info.get("login_password") or "").strip()
        if login_mobile and login_password:
            return await self._login_with_service_account(user_id, bi_service, login_mobile, login_password)

        token_cached = self._token_cache.get(user_id)
        if token_cached and token_cached["expires_at"] > time.time():
            logger.info("CAS: using cached BI token for %s", user_id)
            return {"Authorization": f"Bearer {token_cached['token']}"}

        raise CasAuthError("认证失败：无法获取帆软登录态，请重新登录")

    async def _login_with_service_account(self, user_id: str, bi_service: str, mobile: str, password: str) -> dict[str, str]:
        signin_url = "https://fanruanclub.com/login/signin"
        verify_url = "https://fanruanclub.com/login/verify"
        referrer = bi_service

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            await client.get(signin_url, params={"app": "crm", "referrer": referrer})
            resp = await client.post(
                verify_url,
                data={"mobile": mobile, "password": password, "app": "crm", "referrer": referrer},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data.get("success") or not isinstance(data.get("data"), dict):
            raise CasAuthError(f"帆软账号登录失败: {data.get('msg') or 'unknown'}")

        payload = data["data"]
        token = str(payload.get("token") or "")
        redirect_url = str(payload.get("redirectUrl") or "")
        ttl = int(payload.get("time") or 7200)
        if not token:
            raise CasAuthError("帆软账号登录失败：未返回 token")

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as bi_client:
            # Carry over CAS TGC so the BI redirect ticket exchange can establish BI cookies.
            for cookie in client.cookies.jar:
                bi_client.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
            if redirect_url:
                redirect_resp = await bi_client.get(redirect_url)
                redirect_resp.raise_for_status()
            cookies = {cookie.name: cookie.value for cookie in bi_client.cookies.jar if cookie.name and cookie.value}

        self._token_cache[user_id] = {"token": token, "expires_at": time.time() + max(300, ttl - 120)}
        if cookies:
            self._cookie_cache[user_id] = {"cookies": cookies, "expires_at": time.time() + 3600}
            logger.info("CAS: refreshed BI service cookies for %s", user_id)
            return cookies

        logger.info("CAS: refreshed BI service token for %s", user_id)
        return {"Authorization": f"Bearer {token}"}

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
            location = resp.headers.get("location")
            while location and not cookies and resp.status_code in (301, 302, 303, 307, 308):
                resp = await client.get(location, follow_redirects=False)
                cookies = _extract(resp)
                location = resp.headers.get("location")

        if not cookies:
            raise CasAuthError("认证失败：无法获取帆软 BI 登录态（无 cookie 返回）")

        return cookies

    async def validate_st(self, st: str, service: str, pgt_url: str = "") -> dict[str, Any]:
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

        return {
            "username": auth_success.get("user", ""),
            "attributes": auth_success.get("attributes", {}),
            "pgt_iou": auth_success.get("proxyGrantingTicket", ""),
        }


cas_auth_service = CasAuthService()
