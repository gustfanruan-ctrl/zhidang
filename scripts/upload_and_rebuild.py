#!/usr/bin/env python3
"""Upload all backend files and rebuild Docker image."""
import paramiko, time, os

host = '47.98.102.197'
user = 'root'
pwd = 'CfrS3(D)LymwQWEiavN'

local_backend = 'D:/智档/backend'
files_to_upload = []
for root, dirs, files in os.walk(local_backend):
    for f in files:
        if f.endswith('.py') or f.endswith('.json'):
            local_path = os.path.join(root, f)
            rel_path = os.path.relpath(local_path, local_backend)
            rel_path = rel_path.replace(os.sep, '/')
            remote_path = f'/opt/zhidang/backend/{rel_path}'
            files_to_upload.append((local_path, remote_path))

print(f"Uploading {len(files_to_upload)} files...")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, username=user, password=pwd, timeout=30, look_for_keys=False, allow_agent=False)
sftp = c.open_sftp()

for local, remote in files_to_upload:
    remote_dir = os.path.dirname(remote).replace(os.sep, '/')
    try:
        sftp.stat(remote_dir)
    except:
        stdin, stdout, stderr = c.exec_command(f'mkdir -p {remote_dir}')
    sftp.put(local, remote)
    print(f"  OK: {remote}")

sftp.close()
print("Upload done.")

# Also upload requirements.txt, Dockerfile, alembic configs
for f in ['requirements.txt', 'Dockerfile', 'alembic.ini']:
    local = f'D:/智档/{f}'
    remote = f'/opt/zhidang/{f}'
    if os.path.exists(local):
        sftp = c.open_sftp()
        sftp.put(local, remote)
        sftp.close()
        print(f"  OK: {remote}")

print("\nRebuilding Docker image...")
stdin, stdout, stderr = c.exec_command('cd /opt/zhidang && docker compose build backend 2>&1', timeout=600)
out = stdout.read().decode()
err = stderr.read().decode()
lines = (out + err).split('\n')
print(f"Build output ({len(lines)} lines):")
for line in lines[-40:]:
    print(line)

# Check result
time.sleep(3)
stdin, stdout, stderr = c.exec_command('cd /opt/zhidang && docker compose up -d backend 2>&1')
print("\nStart:", stdout.read().decode().strip())

time.sleep(8)
stdin, stdout, stderr = c.exec_command('docker ps --filter name=zhidang-backend --format "{{.Status}}"; curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/system/status')
print("Status:", stdout.read().decode().strip())

c.close()
