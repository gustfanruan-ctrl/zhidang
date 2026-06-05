#!/usr/bin/env python3
"""Apply 7 filter fixes to the container's old main.py."""
import sys

with open(sys.argv[1], 'r', encoding='utf-8') as f:
    c = f.read()

# Patch 1: transcript filter
old = '''    elif user.get("source") == "user":
        username = user.get("username")
        if username:
            # sso_user_name is stored as "Gust-张小洋", match on prefix
            stmt = stmt.where(Transcript.sso_user_name.like(username + "-%"))
    return stmt'''
new = '''    elif user.get("source") == "user":
        display_name = user.get("display_name")
        if display_name:
            stmt = stmt.where(Transcript.sso_user_name == display_name)
    return stmt'''
assert old in c, "Patch 1: old pattern not found!"
c = c.replace(old, new)
print("Patch 1 OK: transcript filter")

# Patch 2: followup filter
old = '''    elif user.get("source") == "user":
        username = user.get("username")
        if username:
            # sso_user_name is stored as "Gust-张小洋", match on prefix
            stmt = stmt.where(FollowupRecord.sso_user_name.like(username + "-%"))
    return stmt'''
new = '''    elif user.get("source") == "user":
        display_name = user.get("display_name")
        if display_name:
            stmt = stmt.where(FollowupRecord.sso_user_name == display_name)
    return stmt'''
assert old in c, "Patch 2: old pattern not found!"
c = c.replace(old, new)
print("Patch 2 OK: followup filter")

# Patch 3+4: sso_user_name creation (2 occurrences)
old = 'sso_user_name=user.get("user_name") or user.get("username")'
new = 'sso_user_name=user.get("display_name") or user.get("user_name") or user.get("username")'
cnt = c.count(old)
assert cnt >= 2, f"Patch 3+4: expected >=2 occurrences, found {cnt}"
c = c.replace(old, new)
print(f"Patch 3+4 OK: replaced {cnt} occurrences of sso_user_name creation")

# Patch 5: customers_list
old = '''    # 多租户：SSO 用户只显示自己负责的客户
    if user.get("source") == "sso":
        user_name = user.get("user_name", "")
        if user_name:
            cached_items = [c for c in cached_items if c.get("csm") == user_name]

    keyword_norm = keyword.strip().lower()'''
new = '''    # 多租户：SSO / user 用户只显示自己负责的客户
    if user.get("source") == "sso":
        user_name = user.get("user_name", "")
        if user_name:
            cached_items = [c for c in cached_items if c.get("csm") == user_name]
    elif user.get("source") == "user":
        display_name = user.get("display_name", "")
        if display_name:
            cached_items = [c for c in cached_items if c.get("csm") == display_name]

    keyword_norm = keyword.strip().lower()'''
assert old in c, "Patch 5: old pattern not found!"
c = c.replace(old, new)
print("Patch 5 OK: customers_list filter")

# Patch 6: company_search
old = '''    # 多租户过滤
    if user.get("source") == "sso":
        user_name = user.get("user_name", "")
        if user_name:
            customers = [c for c in customers if c.get("csm") == user_name]
    if keyword:'''
new = '''    # 多租户过滤
    if user.get("source") == "sso":
        user_name = user.get("user_name", "")
        if user_name:
            customers = [c for c in customers if c.get("csm") == user_name]
    elif user.get("source") == "user":
        display_name = user.get("display_name", "")
        if display_name:
            customers = [c for c in customers if c.get("csm") == display_name]
    if keyword:'''
assert old in c, "Patch 6: old pattern not found!"
c = c.replace(old, new)
print("Patch 6 OK: company_search filter")

# Patch 7: search_customers
old = '''    # 多租户过滤
    if user.get("source") == "sso":
        user_name = user.get("user_name", "")
        if user_name:
            cached_items = [c for c in cached_items if c.get("csm") == user_name]

    if not cached_items:'''
new = '''    # 多租户过滤
    if user.get("source") == "sso":
        user_name = user.get("user_name", "")
        if user_name:
            cached_items = [c for c in cached_items if c.get("csm") == user_name]
    elif user.get("source") == "user":
        display_name = user.get("display_name", "")
        if display_name:
            cached_items = [c for c in cached_items if c.get("csm") == display_name]

    if not cached_items:'''
assert old in c, "Patch 7: old pattern not found!"
c = c.replace(old, new)
print("Patch 7 OK: search_customers filter")

with open(sys.argv[2], 'w', encoding='utf-8') as f:
    f.write(c)
print(f"Done. Output: {sys.argv[2]}")
