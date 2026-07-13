import os
import re
import glob
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

def get_uploader_logger(log_dir="uploader/logs"):
    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)
    log_filename = log_dir_path / f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logger = logging.getLogger("uploader")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_filename, encoding="utf-8")
        sh = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(formatter)
        sh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger

def chunk_markdown_by_headings(content):
    """
    Cắt nội dung Markdown thành các chunk dựa trên tiêu đề (#, ##, ###, ...)
    """
    heading_pattern = r"(?=\n(?:#{1,6})\s+)"
    chunks_raw = re.split(heading_pattern, "\n" + content)
    
    chunks = []
    current_chunk = ""
    
    for section in chunks_raw:
        section = section.strip()
        if not section:
            continue
            
        if len(current_chunk) + len(section) < 4000:
            current_chunk += "\n\n" + section if current_chunk else section
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = section
            
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return chunks

def chunk_markdown_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return chunk_markdown_by_headings(content)

def main():
    """Hàm cũ cho tương thích"""
    load_dotenv()
    API_KEY = os.getenv("OPENAI_API_KEY")
    VECTOR_STORE_ID = os.getenv("OPENAI_VECTOR_STORE_ID")
    logger = get_uploader_logger()

    if not API_KEY or not VECTOR_STORE_ID:
        logger.error("Thiếu OPENAI_API_KEY hoặc OPENAI_VECTOR_STORE_ID trong .env")
        return

    client = OpenAI(api_key=API_KEY)
    
    TEMP_CHUNK_DIR = Path("uploader/temp_chunks")
    TEMP_CHUNK_DIR.mkdir(parents=True, exist_ok=True)

    articles_dir = Path("crawler/articles")
    md_files = glob.glob(str(articles_dir / "*.md"))
    
    if not md_files:
        logger.warning(f"Không tìm thấy file .md nào trong {articles_dir}")
        return

    logger.info(f"Bắt đầu xử lý {len(md_files)} files từ {articles_dir}")
    
    total_chunks_created = 0
    uploaded_file_ids = []

    for file_path in md_files:
        file_name = Path(file_path).stem
        logger.info(f"Đang xử lý file: {file_name}.md")
        
        try:
            chunks = chunk_markdown_file(file_path)
            logger.info(f"-> Đã chia thành {len(chunks)} chunks dựa trên tiêu đề.")
            
            for idx, chunk_content in enumerate(chunks):
                chunk_file_name = f"{file_name}_chunk_{idx+1}.md"
                chunk_file_path = TEMP_CHUNK_DIR / chunk_file_name
                
                with open(chunk_file_path, "w", encoding="utf-8") as f:
                    f.write(chunk_content)
                
                logger.info(f"   [Upload] Đang tải lên OpenAI: {chunk_file_name}")
                with open(chunk_file_path, "rb") as file_data:
                    openai_file = client.files.create(
                        file=file_data,
                        purpose="assistants"
                    )
                
                uploaded_file_ids.append(openai_file.id)
                total_chunks_created += 1
                os.remove(chunk_file_path)
                
        except Exception as e:
            logger.error(f"Lỗi khi xử lý file {file_path}: {str(e)}")

    if uploaded_file_ids:
        logger.info(f"Đang tiến hành attach {len(uploaded_file_ids)} files vào Vector Store ID: {VECTOR_STORE_ID}")
        try:
            for i in range(0, len(uploaded_file_ids), 500):
                batch_ids = uploaded_file_ids[i:i+500]
                file_batch = client.vector_stores.file_batches.create(
                    vector_store_id=VECTOR_STORE_ID,
                    file_ids=batch_ids
                )
                logger.info(f"-> Đã gửi batch attach thành công. Batch ID: {file_batch.id}, Trạng thái: {file_batch.status}")
                
            logger.info(f"=== HOÀN THÀNH ===")
            logger.info(f"Tổng số file gốc: {len(md_files)}")
            logger.info(f"Tổng số chunks đã được nhúng (embedded): {total_chunks_created}")
            
        except Exception as e:
            logger.error(f"Lỗi khi attach files vào Vector Store: {str(e)}")
    else:
        logger.warning("Không có file nào được tạo ra thành công để attach vào Vector Store.")

    if TEMP_CHUNK_DIR.exists() and not os.listdir(TEMP_CHUNK_DIR):
        TEMP_CHUNK_DIR.rmdir()

if __name__ == "__main__":
    main()