FROM python:3.12-slim

ENV TZ=Asia/Taipei

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

RUN mkdir -p logs rich_menus dashboard_layout

EXPOSE 8000

CMD ["uv", "run", "python", "main.py"]

