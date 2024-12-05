import logging

def setup_logging():
    """تنظیمات اولیه لاگ"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("api.log"),  # ذخیره لاگ‌ها در فایل
            logging.StreamHandler()         # نمایش لاگ‌ها در کنسول
        ]
    )
    logger = logging.getLogger("FastAPIApp")
    return logger
