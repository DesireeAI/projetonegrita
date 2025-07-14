from PIL import Image
import io
import base64
from utils.logging_setup import setup_logging

logger = setup_logging()

async def resize_image_to_thumbnail(image_data: bytes, max_size: int = 100) -> str:
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            img.thumbnail((max_size, max_size))
            output = io.BytesIO()
            img.save(output, format="JPEG")
            thumbnail_data = base64.b64encode(output.getvalue()).decode("utf-8")
            logger.info(f"Thumbnail gerado: {len(thumbnail_data)} bytes")
            return thumbnail_data
    except Exception as e:
        logger.error(f"Erro ao gerar thumbnail: {e}")
        return ""