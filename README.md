# 智档

## 结构
- `backend/` FastAPI + PostgreSQL + Alembic
- `frontend/` Vue 3 + Vite
- `alembic/` 数据库迁移
- `scripts/` 初始化脚本

## 运行

### 1. 环境变量
复制 `.env.example` 并修改：
- `DATABASE_URL`
- `JWT_SECRET`
- `LOG_LEVEL`
- `ENVIRONMENT`

### 2. 启动整套服务
```bash
docker compose up --build
```

### 3. 本地开发
后端：
```bash
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

前端：
```bash
cd frontend
npm install
npm run dev
```

## 主要页面
- `/review`
- `/config`
- `/llm`

## 健康检查
- `/health`
- `/api/v1/health`
