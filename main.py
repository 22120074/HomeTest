import os
import re
import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

from crawler.crawler import fetch_all_articles, get_html2text_parser, format_article_markdown
from uploader.uploader import chunk_markdown_by_headings

# --- Configuration & Setup ---
IS_RAILWAY = bool(os.getenv("RAILWAY_ENVIRONMENT"))

if IS_RAILWAY:
    STATE_DIR = Path("/data")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE = STATE_DIR / "state.json"
else:
    STATE_FILE = Path("crawler/state.json")
ARTICLES_DIR = Path("crawler/articles")
TEMP_CHUNK_DIR = Path("uploader/temp_chunks")
LOG_DIR = Path("logs")

ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
TEMP_CHUNK_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

def setup_logging():
    log_filename = LOG_DIR / f"main_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger("main")
    logger.setLevel(logging.INFO)
    
    sh = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    
    if not IS_RAILWAY:
        fh = logging.FileHandler(log_filename, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    return logger

logger = setup_logging()

# Khai báo biến global trống để các hàm khác sử dụng
client = None
VECTOR_STORE_ID = None

# --- Utility Functions ---

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def compute_hash(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def clean_slug(url):
    slug = url.rstrip("/").split("/")[-1]
    return re.sub(r'[\\/*?:"<>|]', "", slug)

# --- Core Processing ---

def delete_openai_files(file_ids):
    for file_id in file_ids:
        try:
            client.files.delete(file_id)
            logger.info(f"   [Delete] Xóa OpenAI file cũ: {file_id}")
        except Exception as e:
            logger.error(f"   [Delete] Lỗi khi xóa file {file_id}: {str(e)}")

def process_and_upload(slug, markdown_content):
    file_path = ARTICLES_DIR / f"{slug}.md"
    
    # Ghi file ra ổ đĩa
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
        
    chunks = chunk_markdown_by_headings(markdown_content)
    logger.info(f"   -> Đã chia thành {len(chunks)} chunks.")
    
    uploaded_file_ids = []
    
    for idx, chunk_content in enumerate(chunks):
        chunk_file_name = f"{slug}_chunk_{idx+1}.md"
        chunk_file_path = TEMP_CHUNK_DIR / chunk_file_name
        
        with open(chunk_file_path, "w", encoding="utf-8") as f:
            f.write(chunk_content)
            
        logger.info(f"   [Upload] Đang tải lên OpenAI: {chunk_file_name}")
        try:
            with open(chunk_file_path, "rb") as file_data:
                openai_file = client.files.create(
                    file=file_data,
                    purpose="assistants"
                )
            uploaded_file_ids.append(openai_file.id)
        except Exception as e:
            logger.error(f"   [Upload] Lỗi khi upload chunk {chunk_file_name}: {str(e)}")
        finally:
            os.remove(chunk_file_path)
            
    return uploaded_file_ids

def main():
    global client, VECTOR_STORE_ID
    
    logger.info("Khởi động pipeline Crawler + Uploader...")
    
    # Đọc biến môi trường NẰM TRONG HÀM MAIN để đảm bảo Railway đã load xong
    load_dotenv(override=False) 
    API_KEY = os.getenv("OPENAI_API_KEY")
    VECTOR_STORE_ID = os.getenv("OPENAI_VECTOR_STORE_ID")
    
    # Khởi tạo client OpenAI tại đây
    if API_KEY:
        client = OpenAI(api_key=API_KEY)
    
    # --- ĐOẠN DEBUG CỦA BẠN SẼ CHẠY CHÍNH XÁC TẠI ĐÂY ---
    masked_key = f"{API_KEY[:8]}...{API_KEY[-4:]}" if API_KEY and len(API_KEY) > 12 else str(API_KEY)
    logger.info(f"[DEBUG ENV] OPENAI_API_KEY hiện tại: {masked_key}")
    logger.info(f"[DEBUG ENV] OPENAI_VECTOR_STORE_ID hiện tại: {VECTOR_STORE_ID}")
    logger.info(f"[DEBUG ENV] Biến RAILWAY_ENVIRONMENT hiện tại: {os.getenv('RAILWAY_ENVIRONMENT')}")
    
    if not API_KEY or not VECTOR_STORE_ID:
        logger.error("Missing OPENAI_API_KEY or OPENAI_VECTOR_STORE_ID. "
                     "Set them in Railway environment variables or .env file.")
        return

    state = load_state()
    h_parser = get_html2text_parser()
    
    counts = {"added": 0, "updated": 0, "skipped": 0}
    new_uploaded_file_ids = []
    
    logger.info("Bắt đầu lấy dữ liệu từ Zendesk API...")
    for article in fetch_all_articles():
        html_body = article.get("body")
        if not html_body:
            continue
            
        title = article.get("title")
        html_url = article.get("html_url")
        updated_at = article.get("updated_at")
        article_id = article.get("id")
        
        slug = clean_slug(html_url)
        markdown_content = format_article_markdown(title, html_url, html_body, h_parser)
        content_hash = compute_hash(markdown_content)
        
        old_record = state.get(slug)
        action = None
        
        if not old_record:
            action = "added"
        elif old_record.get("content_hash") != content_hash or old_record.get("updated_at") != updated_at:
            action = "updated"
        else:
            action = "skipped"
            
        counts[action] += 1
        
        if action in ("added", "updated"):
            logger.info(f"[DELTA] {slug} → {action}")
            
            if action == "updated" and old_record.get("openai_file_ids"):
                delete_openai_files(old_record["openai_file_ids"])
                
            uploaded_ids = process_and_upload(slug, markdown_content)
            new_uploaded_file_ids.extend(uploaded_ids)
            
            state[slug] = {
                "article_id": article_id,
                "content_hash": content_hash,
                "updated_at": updated_at,
                "openai_file_ids": uploaded_ids
            }
        else:
            # logger.info(f"[DELTA] {slug} → skipped (no change)")
            pass

    # Lưu state file
    save_state(state)
    
    # Attach files vào Vector Store
    if new_uploaded_file_ids:
        logger.info(f"Đang attach {len(new_uploaded_file_ids)} files vào Vector Store {VECTOR_STORE_ID}...")
        try:
            for i in range(0, len(new_uploaded_file_ids), 500):
                batch_ids = new_uploaded_file_ids[i:i+500]
                file_batch = client.vector_stores.file_batches.create(
                    vector_store_id=VECTOR_STORE_ID,
                    file_ids=batch_ids
                )
                logger.info(f"-> Batch attach ID: {file_batch.id}, Status: {file_batch.status}")
        except Exception as e:
            logger.error(f"Lỗi khi attach files vào Vector Store: {str(e)}")
            
    # Cleanup thư mục tạm
    if TEMP_CHUNK_DIR.exists() and not os.listdir(TEMP_CHUNK_DIR):
        TEMP_CHUNK_DIR.rmdir()
        
    # In báo cáo cuối cùng
    logger.info("================================")
    logger.info(f"Log counts: added={counts['added']}, updated={counts['updated']}, skipped={counts['skipped']}")
    logger.info(f"Chunks uploaded: {len(new_uploaded_file_ids)}")
    logger.info("================================")

if __name__ == "__main__":
    main()
