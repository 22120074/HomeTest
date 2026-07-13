FROM python:3.12-slim

# Thiết lập thư mục làm việc
WORKDIR /app

# Copy file requirements trước để tận dụng Docker cache
COPY requirements.txt .

# Cài đặt các thư viện
RUN pip install --no-cache-dir -r requirements.txt

# Xử lý xung đột openai và httpx
RUN pip uninstall openai httpx -y && \
    pip install --upgrade openai httpx

# Copy toàn bộ source code vào container
COPY . .

# Không set ENV API keys ở đây vì bảo mật, hãy truyền qua file .env khi chạy:
# docker run --env-file .env my-app

# Chạy file main.py
CMD ["python", "main.py"]
