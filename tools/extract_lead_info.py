# tools/extract_lead_info.py
import re
import json
from typing import Dict, Optional
from openai import AsyncOpenAI
from config.config import OPENAI_API_KEY
from models.lead_data import LeadData
from utils.logging_setup import setup_logging
from datetime import datetime

logger = setup_logging()
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

async def extract_lead_info(message: str, remotejid: Optional[str] = None) -> str:
    """Extract lead information from a message and return as JSON."""
    logger.debug(f"Executing extract_lead_info for message: {message}, remotejid: {remotejid}")
    try:
        lead_data = LeadData(remotejid=remotejid)
        extracted_data = {}

        # Regex patterns for structured fields
        patterns = {
            "email": r'[\w\.-]+@[\w\.-]+\.\w+',
            "cep": r'\d{5}-?\d{3}',  # Accepts both xxxxx-xxx and xxxxxxxx
            "data_aniversario": r'\b(\d{2}/\d{2}/\d{4})\b'
        }

        # Extract structured fields
        for field, pattern in patterns.items():
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                extracted_data[field] = match.group(0)
                setattr(lead_data, field, match.group(0))

        # Detect language using OpenAI
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": f"Detecte o idioma principal da mensagem: '{message}'. Retorne apenas o nome do idioma (ex.: 'português')."
                    }
                ],
                temperature=0.2
            )
            idioma = response.choices[0].message.content.strip()
            if idioma:
                extracted_data["idioma"] = idioma
                lead_data.idioma = idioma
        except Exception as e:
            logger.error(f"[{remotejid}] Erro ao detectar idioma: {str(e)}")

        # Map merchant type using OpenAI
        merchant_types = {
            "lojista": ["tenho loja", "sou lojista", "dono de loja", "tenho comércio", "sou comerciante", "gerencio uma loja", "minha loja"],
            "revendedor": ["faço revenda", "sou revendedor", "revendo produtos", "sou vendedor", "vendo no atacado"],
            "sacoleiro": ["vendo em casa", "sou sacoleiro", "vendo de porta em porta", "vendo por conta própria"],
            "feirante": ["sou feirante", "vendo na feira", "tenho barraca", "trabalho na feira", "vendo no mercado"]
        }
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": f"""
                        Analise a mensagem: '{message}'. 
                        Determine se o usuário mencionou ser um tipo de comerciante (lojista, revendedor, sacoleiro, feirante).
                        Exemplos:
                        - "tenho loja" → lojista
                        - "faço revenda" → revendedor
                        - "vendo em casa" → sacoleiro
                        - "vendo na feira" → feirante
                        Retorne apenas o tipo de comerciante (ex.: 'lojista') ou 'nenhum' se não for mencionado.
                        """
                    }
                ],
                temperature=0.2
            )
            tipo = response.choices[0].message.content.strip()
            if tipo != "nenhum":
                extracted_data["tipo"] = tipo
                lead_data.tipo = tipo
        except Exception as e:
            logger.error(f"[{remotejid}] Erro ao detectar tipo de comerciante: {str(e)}")

        # Detect sentiment using OpenAI
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": f"""
                        Analise o sentimento da mensagem: '{message}'.
                        Determine se o sentimento é positivo, negativo ou neutro.
                        Exemplos:
                        - "Adorei os tênis!" → positivo
                        - "Não recebi meu pedido!" → negativo
                        - "Quero ver o catálogo" → neutro
                        Retorne apenas o sentimento (ex.: 'positivo', 'negativo', 'neutro').
                        """
                    }
                ],
                temperature=0.2
            )
            sentimento = response.choices[0].message.content.strip()
            if sentimento in ["positivo", "negativo", "neutro"]:
                extracted_data["sentimento"] = sentimento
                lead_data.sentimento = sentimento
        except Exception as e:
            logger.error(f"[{remotejid}] Erro ao detectar sentimento: {str(e)}")

        # Extract cidade and estado
        if "cidade:" in message.lower():
            extracted_data["cidade"] = message.lower().split("cidade:")[1].strip().split()[0]
            lead_data.cidade = extracted_data["cidade"]
        if "estado:" in message.lower():
            extracted_data["estado"] = message.lower().split("estado:")[1].strip().split()[0]
            lead_data.estado = extracted_data["estado"]

        # Update ult_contato
        extracted_data["ult_contato"] = datetime.now().isoformat()
        lead_data.ult_contato = extracted_data["ult_contato"]

        logger.info(f"[{remotejid}] Extracted lead info: {extracted_data}")
        return json.dumps(extracted_data)
    except Exception as e:
        logger.error(f"[{remotejid}] Erro ao extrair informações do lead: {str(e)}")
        return json.dumps({"error": f"Erro ao extrair informações: {str(e)}"})