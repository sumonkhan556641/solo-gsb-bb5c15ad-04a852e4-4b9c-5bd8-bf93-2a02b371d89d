FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SHEET_DB_PATH=/data/sheet.db

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# SQLite 数据目录（随启动自动建库）
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# 依赖及建库随启动完成：uvicorn 启动时 lifespan 自动执行建库
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
