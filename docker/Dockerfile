# 使用官方 Python 3.11 精简镜像
FROM python:3.11-slim

WORKDIR /app

# 安装编译依赖（psycopg 等可能需要）
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 运行时源码、数据库迁移和同源演示前端
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY frontend ./frontend

EXPOSE 8000

# Compose 会覆盖该命令并先执行 alembic upgrade head；单独 docker run 仍可启动 API。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
