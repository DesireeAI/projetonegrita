import hashlib
import os
from openai import AsyncOpenAI
from config.config import OPENAI_API_KEY
from utils.logging_setup import setup_logging

logger = setup_logging()
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

async def text_to_speech(text: str) -> str:
    try:
        if not text or not text.strip():
            raise ValueError("Texto vazio ou inválido")
        logger.debug(f"Convertendo texto para áudio: {text[:50]}...")
        response = await client.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=text.strip()
        )
        output_file = f"audio_{hashlib.md5(text.encode()).hexdigest()}.mp3"
        with open(output_file, "wb") as f:
            f.write(response.content)
        logger.info(f"Áudio MP3 salvo: {output_file}")
        return output_file
    except Exception as e:
        logger.error(f"Erro ao processar áudio: {str(e)}")
        return f"Erro ao processar áudio: {str(e)}"