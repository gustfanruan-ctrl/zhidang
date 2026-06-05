#!/usr/bin/env python3
"""Add sso_user_id fallback to transcript filter."""
import sys

with open(sys.argv[1], 'r', encoding='utf-8') as f:
    c = f.read()

old = ("    elif user.get('source') == 'user':\n"
       "        display_name = user.get('display_name')\n"
       "        if display_name:\n"
       "            stmt = stmt.where(Transcript.sso_user_name == display_name)\n"
       "    return stmt")

new = ("    elif user.get('source') == 'user':\n"
       "        display_name = user.get('display_name')\n"
       "        username = user.get('username')\n"
       "        if display_name and username:\n"
       "            from sqlalchemy import or_\n"
       "            stmt = stmt.where(or_(Transcript.sso_user_name == display_name, Transcript.sso_user_id == username))\n"
       "    return stmt")

assert old in c, "Pattern not found!"
c = c.replace(old, new)
print("FIXED transcript filter with sso_user_id fallback")

with open(sys.argv[2], 'w', encoding='utf-8') as f:
    f.write(c)
print(f"Written to {sys.argv[2]}")
