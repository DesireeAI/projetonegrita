import aiohttp
import re
import json
import base64
import os
import tempfile
import hashlib
from typing import Optional, Dict, Any
from config.config import EVOLUTION_API_URL, EVOLUTION_API_TOKEN, EVOLUTION_INSTANCE_NAME
from openai import AsyncOpenAI
from config.config import OPENAI_API_KEY
from utils.image_processing import resize_image_to_thumbnail
from utils.logging_setup import setup_logging

logger = setup_logging()
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

async def send_whatsapp_message(phone_number: str, message: str, remotejid: Optional[str] = None) -> bool:
    if not all([EVOLUTION_API_URL, EVOLUTION_API_TOKEN, EVOLUTION_INSTANCE_NAME]):
        logger.error("Configurações da Evolution API não estão completas")
        return False
    remotejid = remotejid or phone_number
    message = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1: \2', message)
    payload = {
        "number": phone_number,
        "text": message,
        "options": {"delay": 0, "presence": "composing"}
    }
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_TOKEN, "Content-Type": "application/json"}
    logger.debug(f"[{remotejid}] Enviando mensagem para: {phone_number}, payload: {json.dumps(payload, indent=2)}")
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(url, json=payload) as response:
                response_text = await response.text()
                logger.debug(f"[{remotejid}] Resposta do sendText: {response.status} - {response_text}")
                success = response.status in (200, 201)
                if success:
                    logger.info(f"[{remotejid}] Mensagem enviada com sucesso")
                else:
                    logger.error(f"[{remotejid}] Falha ao enviar: {response.status} - {response_text}")
                return success
    except Exception as e:
        logger.error(f"[{remotejid}] Erro ao enviar mensagem: {e}")
        return False

async def send_whatsapp_audio(phone_number: str, audio_path: str, remotejid: Optional[str] = None, message_key_id: Optional[str] = None, message_text: Optional[str] = None) -> bool:
    if not all([EVOLUTION_API_URL, EVOLUTION_API_TOKEN, EVOLUTION_INSTANCE_NAME]):
        logger.error("Configurações da Evolution API não estão completas")
        return False
    remotejid = remotejid or phone_number
    try:
        if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            logger.error(f"[{remotejid}] Arquivo de áudio inválido ou vazio: {audio_path}")
            return False
        with open(audio_path, "rb") as audio_file:
            audio_data = base64.b64encode(audio_file.read()).decode("utf-8")
        payload = {
            "number": phone_number,
            "audio": audio_data,
            "mimetype": "audio/mpeg; codecs=opus",
            "options": {
                "delay": 0,
                "presence": "recording",
                "linkPreview": False,
                "mentionsEveryOne": False,
                "mentioned": [remotejid] if remotejid else []
            }
        }
        if message_key_id and message_text:
            payload["quoted"] = {
                "key": {"id": message_key_id},
                "message": {"conversation": message_text}
            }
        url = f"{EVOLUTION_API_URL}/message/sendWhatsAppAudio/{EVOLUTION_INSTANCE_NAME}"
        headers = {"apikey": EVOLUTION_API_TOKEN, "Content-Type": "application/json"}
        logger.debug(f"[{remotejid}] Enviando áudio, payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(url, json=payload) as response:
                response_text = await response.text()
                logger.debug(f"[{remotejid}] Resposta do sendWhatsAppAudio: {response.status} - {response_text}")
                success = response.status in (200, 201)
                if success:
                    logger.info(f"[{remotejid}] Áudio enviado com sucesso")
                else:
                    logger.error(f"[{remotejid}] Falha ao enviar áudio: {response.status} - {response_text}")
                return success
    except Exception as e:
        logger.error(f"[{remotejid}] Erro ao enviar áudio: {e}")
        return False

async def send_whatsapp_image(phone_number: str, image_url: str, caption: str, remotejid: Optional[str] = None, message_key_id: Optional[str] = None, message_text: Optional[str] = None) -> bool:
    if not all([EVOLUTION_API_URL, EVOLUTION_API_TOKEN, EVOLUTION_INSTANCE_NAME]):
        logger.error("Configurações da Evolution API não estão completas")
        return False
    remotejid = remotejid or phone_number
    if not phone_number:
        logger.error(f"[{remotejid}] Número de telefone inválido: {phone_number}")
        return False
    try:
        payload = {
            "number": phone_number,
            "mediatype": "image",
            "mimetype": "image/jpeg",
            "media": image_url,
            "caption": caption,
            "options": {
                "delay": 0,
                "presence": "composing",
                "linkPreview": False,
                "mentionsEveryOne": False,
                "mentioned": [remotejid] if remotejid else []
            }
        }
        if message_key_id and message_text:
            payload["quoted"] = {
                "key": {"id": message_key_id},
                "message": {"conversation": message_text}
            }
        url = f"{EVOLUTION_API_URL}/message/sendMedia/{EVOLUTION_INSTANCE_NAME}"
        headers = {"apikey": EVOLUTION_API_TOKEN, "Content-Type": "application/json"}
        logger.debug(f"[{remotejid}] Enviando imagem via URL, payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(url, json=payload) as response:
                response_text = await response.text()
                logger.debug(f"[{remotejid}] Resposta do sendMedia: {response.status} - {response_text}")
                success = response.status in (200, 201)
                if success:
                    logger.info(f"[{remotejid}] Imagem enviada com sucesso")
                else:
                    logger.error(f"[{remotejid}] Falha ao enviar imagem: {response.status} - {response_text}")
                return success
    except Exception as e:
        logger.error(f"[{remotejid}] Erro ao enviar imagem: {e}")
        return False

async def fetch_media_base64(message_key_id: str, media_type: str, remotejid: Optional[str] = None) -> Dict[str, Any]:
    if not all([EVOLUTION_API_URL, EVOLUTION_API_TOKEN, EVOLUTION_INSTANCE_NAME]):
        logger.error("Configurações da Evolution API não estão completas")
        return {"error": "Configurações da Evolution API não estão completas"}
    url = f"{EVOLUTION_API_URL}/chat/getBase64FromMediaMessage/{EVOLUTION_INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_TOKEN, "Content-Type": "application/json"}
    payload = {
        "message": {
            "key": {
                "id": message_key_id
            }
        },
        "convertToMp4": media_type == "image"
    }
    logger.debug(f"[{remotejid}] Buscando base64 para {media_type} com message_key_id: {message_key_id}, payload: {json.dumps(payload, indent=2)}")
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(url, json=payload) as response:
                response_text = await response.text()
                logger.debug(f"[{remotejid}] Resposta do getBase64FromMediaMessage: {response.status} - {response_text}")
                if response.status not in (200, 201):
                    logger.error(f"[{remotejid}] Falha ao buscar base64: {response.status} - {response_text}")
                    return {"error": f"Falha ao buscar base64: {response.status}"}
                response_data = await response.json()
                base64_data = response_data.get("base64")
                if not base64_data:
                    logger.error(f"[{remotejid}] Nenhum dado base64 retornado pela API")
                    return {"error": "Nenhum dado base64 retornado"}

                logger.debug(f"[{remotejid}] Primeiros 50 caracteres do base64: {base64_data[:50]}")
                
                try:
                    decoded_data = base64.b64decode(base64_data, validate=True)
                    if media_type == "image":
                        if decoded_data.startswith(b'\xff\xd8\xff'):
                            mimetype = "image/jpeg"
                        elif decoded_data.startswith(b'\x89PNG\r\n\x1a\n'):
                            mimetype = "image/png"
                        else:
                            logger.warning(f"[{remotejid}] Formato de imagem desconhecido")
                            return {"error": f"Formato de imagem desconhecido"}
                        thumbnail_data = await resize_image_to_thumbnail(decoded_data)
                        if not thumbnail_data:
                            logger.warning(f"[{remotejid}] Falha ao gerar thumbnail, usando imagem original")
                            thumbnail_data = base64_data
                        logger.info(f"[{remotejid}] Base64 de imagem obtido com sucesso, mimetype: {mimetype}")
                        return {"type": "image", "base64": thumbnail_data, "mimetype": mimetype}
                    elif media_type == "audio":
                        if decoded_data.startswith(b'OggS'):
                            mimetype = "audio/ogg"
                        elif decoded_data.startswith(b'ID3') or decoded_data.startswith(b'\xff\xfb'):
                            mimetype = "audio/mpeg"
                        else:
                            logger.warning(f"[{remotejid}] Formato de áudio desconhecido")
                            return {"error": f"Formato de áudio desconhecido"}
                        temp_path = os.path.join(tempfile.gettempdir(), f"audio_temp_{hashlib.md5(base64_data.encode()).hexdigest()}.ogg")
                        with open(temp_path, "wb") as f:
                            f.write(decoded_data)
                        logger.debug(f"[{remotejid}] Arquivo de áudio salvo: {temp_path}")
                        with open(temp_path, "rb") as audio_file:
                            transcription = await client.audio.transcriptions.create(
                                model="whisper-1",
                                file=audio_file,
                                language="pt"
                            )
                        logger.info(f"[{remotejid}] Áudio transcrito com sucesso: {transcription.text}")
                        os.remove(temp_path)
                        logger.debug(f"[{remotejid}] Arquivo temporário removido: {temp_path}")
                        return {"type": "audio", "transcription": transcription.text}
                    else:
                        logger.error(f"[{remotejid}] Tipo de mídia não suportado: {media_type}")
                        return {"error": f"Tipo de mídia não suportado: {media_type}"}
                except Exception as e:
                    logger.error(f"[{remotejid}] Erro ao verificar ou processar mídia: {str(e)}")
                    return {"error": f"Erro ao verificar ou processar mídia: {str(e)}"}
    except Exception as e:
        logger.error(f"[{remotejid}] Erro ao buscar base64 da Evolution API: {str(e)}")
        return {"error": f"Erro ao buscar base64: {str(e)}"}