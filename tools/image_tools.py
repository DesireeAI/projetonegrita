# tools/image_tools.py
import re
import json
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import AsyncOpenAI
from config.config import OPENAI_API_KEY
from tools.supabase_tools import upsert_lead
from tools.whatsapp_tools import send_whatsapp_image
from utils.logging_setup import setup_logging
from pydantic import BaseModel, Field
from supabase import create_client, Client
from config.config import SUPABASE_URL, SUPABASE_KEY
import asyncio
import base64
from agents import function_tool

logger = setup_logging()
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def analyze_image(content: str, mimetype: str = "image/jpeg") -> str:
    logger.debug(f"Analisando imagem... (tamanho base64: {len(content)})")
    try:
        match = re.match(r"^data:image/(?P<fmt>\w+);base64,(?P<data>.+)", content)
        if match:
            mimetype = f"image/{match.group('fmt')}"
            base64_data = match.group('data')
            logger.info(f"Data URI detectado. Formato: {mimetype}")
        else:
            base64_data = content
            logger.warning(f"Prefixo data:image não encontrado. Usando mimetype padrão: {mimetype}")

        try:
            base64.b64decode(base64_data, validate=True)
            logger.info(f"Tamanho da imagem decodificada: {len(base64.b64decode(base64_data))} bytes")
        except Exception as e:
            logger.error(f"Erro ao decodificar imagem: {e}, Base64 inicial: {base64_data[:50]}")
            return f"Erro ao decodificar imagem: {e}"

        image_data_url = f"data:{mimetype};base64,{base64_data}"

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Descreva o produto na imagem em português do Brasil."},
                        {"type": "image_url", "image_url": {"url": image_data_url}}
                    ]
                }
            ],
            temperature=0.4,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Erro ao processar imagem: {e}")
        return f"Erro ao processar imagem: {e}"

class ProductImageQuery(BaseModel):
    product_name: str = Field(..., description="Nome do produto para buscar a imagem")
    phone_number: str = Field(..., description="Número de telefone ou remoteJid do destinatário")

@function_tool
async def send_product_image(query: ProductImageQuery, phone_number: str, remotejid: Optional[str] = None) -> str:
    if not all([SUPABASE_URL, SUPABASE_KEY]):
        return json.dumps({"error": "Configurações do Supabase não estão completas"})
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        loop = asyncio.get_running_loop()
        query_lower = query.product_name.lower()
        response = await loop.run_in_executor(None, lambda: client.table("products")
            .select("name, size, price, image_url")
            .ilike("name", f"%{query_lower}%")
            .limit(1)
            .execute())
        if not response.data:
            return json.dumps({"error": f"Nenhum produto encontrado para: {query.product_name}"})
        
        product = response.data[0]
        if not product.get("image_url"):
            return json.dumps({"error": f"Produto {product['name']} não tem imagem associada"})

        image_url = product["image_url"]
        if not re.match(r'^https?://', image_url):
            logger.error(f"[{remotejid}] Formato de image_url inválido: {image_url}")
            return json.dumps({"error": f"Formato de image_url inválido: {image_url}"})
        
        caption = f"{product['name']}, tamanho {product.get('size', 'N/A')}, R${product.get('price', 'N/A')}"
        logger.debug(f"[{remotejid}] Preparando para enviar imagem, phone_number: {query.phone_number}")
        success = await send_whatsapp_image(
            phone_number=query.phone_number,
            image_url=image_url,
            caption=caption,
            remotejid=remotejid,
            message_key_id=None,
            message_text=None
        )
        if not success:
            logger.error(f"[{remotejid}] Falha ao enviar imagem do produto {product['name']}")
            return json.dumps({"error": f"Falha ao enviar imagem do produto {product['name']}"})

        return json.dumps({"text": ""})  # Return empty text to avoid duplicate messages
    except Exception as e:
        logger.error(f"[{remotejid}] Erro ao buscar ou enviar imagem do produto: {str(e)}")
        return json.dumps({"error": f"Erro ao buscar ou enviar imagem do produto: {str(e)}"})