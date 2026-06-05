#!/usr/bin/env python3
"""Patch the old main.py (pre-FollowupRecord) to add source=="user" filtering."""
import sys

with open(sys.argv[1], 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
changes = 0

# P1: _allowed_transcript_stmt - add elif for source=="user"
for i, line in enumerate(lines):
    if line.strip().startswith('def _allowed_transcript_stmt'):
        j = i
        while j < len(lines) and 'return stmt' not in lines[j]:
            j += 1
        indent = '    '
        lines.insert(j, indent + "elif user.get('source') == 'user':")
        lines.insert(j+1, indent + "    display_name = user.get('display_name')")
        lines.insert(j+2, indent + "    if display_name:")
        lines.insert(j+3, indent + "        stmt = stmt.where(Transcript.sso_user_name == display_name)")
        changes += 1
        print("P1: _allowed_transcript_stmt fixed")
        break

# P2+3: Fix sso_user_name creation priority
old_sso = 'sso_user_name=user.get("user_name") or user.get("username")'
new_sso = 'sso_user_name=user.get("display_name") or user.get("user_name") or user.get("username")'
cnt = 0
for i in range(len(lines)):
    if old_sso in lines[i]:
        lines[i] = lines[i].replace(old_sso, new_sso)
        cnt += 1
print(f"P2+3: Fixed {cnt} sso_user_name lines")
changes += 1

# P4-6: Add elif source=="user" after each if source=="sso" filter block
# We need to scan from the end to avoid index shifting issues
insertions = []
for i, line in enumerate(lines):
    stripped = line.strip()
    # Skip the _allowed_transcript_stmt (around line 280) - P1 handles it separately
    if i < 500:
        continue
    if stripped.startswith('if user.get("source") == "sso":'):
        # Find end of this if block
        if_indent = len(line) - len(line.lstrip())
        j = i + 1
        while j < len(lines):
            cur = lines[j]
            cur_stripped = cur.strip()
            if cur_stripped:
                cur_indent = len(cur) - len(cur.lstrip())
                if cur_indent <= if_indent:
                    break
            j += 1

        # Determine variable name from filter line
        var_name = 'cached_items'
        for k in range(i+1, j):
            lk = lines[k].strip()
            if 'for c in' in lk and 'c.get("csm")' in lk:
                parts = lk.split('=')
                if parts:
                    var_name = parts[0].strip().split()[-1]

        # Store insertion info: (position, lines)
        filters = [
            ' ' * if_indent + "elif user.get('source') == 'user':",
            ' ' * if_indent + "    display_name = user.get('display_name', '')",
            ' ' * if_indent + "    if display_name:",
            ' ' * if_indent + f"        {var_name} = [c for c in {var_name} if c.get('csm') == display_name]",
        ]
        insertions.append((j, filters, i+1))

# Apply insertions in reverse order
for pos, filters, src_line in reversed(insertions):
    for f in reversed(filters):
        lines.insert(pos, f)
    changes += 1
    print(f"P{3+len(insertions)}: Added user filter after line {src_line}")

with open(sys.argv[2], 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f"Done: {changes} changes, output: {sys.argv[2]}")
