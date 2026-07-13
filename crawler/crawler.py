import os
import re
import requests
import html2text
import logging

logger = logging.getLogger("crawler")

def get_html2text_parser():
    h = html2text.HTML2Text()
    h.ignore_images = False      # Giữ lại các thẻ ảnh ![alt](url) nếu có
    h.ignore_links = False       # Giữ lại các liên kết [text](url)
    h.body_width = 0             # Không tự động bẻ dòng chữ bừa bãi
    return h

def fetch_all_articles():
    """
    Lấy toàn bộ articles từ Zendesk API và trả về generator/list chứa thông tin article.
    Mỗi article là một dict lấy từ API.
    """
    next_page_url = "https://support.optisigns.com/api/v2/help_center/en-us/articles.json?page[size]=40"
    
    while next_page_url:
        logger.info(f"Đang gọi API: {next_page_url}")
        try:
            response = requests.get(next_page_url, timeout=10)
            if response.status_code != 200:
                logger.error(f"Lỗi API (Status code: {response.status_code})")
                break
                
            data = response.json()
            articles = data.get("articles", [])
            
            if not articles:
                break
                
            for article in articles:
                yield article
                
            next_page_url = data.get("next_page")
        except requests.exceptions.RequestException as e:
            logger.error(f"💥 Lỗi kết nối mạng: {e}")
            break

def format_article_markdown(title, html_url, html_body, h_parser):
    markdown_content = h_parser.handle(html_body)
    full_content = f"# {title}\n\n**Article URL:** {html_url}\n\n{markdown_content}"
    return full_content

def scrape_all_articles():
    """Hàm cũ giữ lại cho tương thích."""
    output_dir = "crawler/articles"
    os.makedirs(output_dir, exist_ok=True)
    h = get_html2text_parser()
    
    total_scraped = 0
    logger.info("Bắt đầu quá trình lấy dữ liệu từ Zendesk API...")
    for article in fetch_all_articles():
        html_body = article.get("body")
        if not html_body:
            continue
            
        title = article.get("title")
        html_url = article.get("html_url")
        
        slug = html_url.rstrip("/").split("/")[-1]
        safe_slug = re.sub(r'[\\/*?:"<>|]', "", slug)
        file_path = os.path.join(output_dir, f"{safe_slug}.md")
        
        full_content = format_article_markdown(title, html_url, html_body, h)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        
        total_scraped += 1
        
    logger.info(f"\n🎉 Hoàn thành! Đã cào và chuẩn hóa thành công {total_scraped} file .md vào thư mục '{output_dir}'.")

if __name__ == "__main__":
    scrape_all_articles()