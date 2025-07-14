# main.py
from fastapi import FastAPI, Request
import json
import re
from openai import AsyncOpenAI
from config.config import OPENAI_API_KEY
from tools.supabase_tools import get_lead, upsert_lead
from tools.whatsapp_tools import send_whatsapp_message, send_whatsapp_audio, send_whatsapp_image, fetch_media_base64
from tools.audio_tools import text_to_speech
from tools.image_tools import analyze_image
from tools.extract_lead_info import extract_lead_info
from tools.product_tools import ProductQuery, query_products
from utils.image_processing import resize_image_to_thumbnail
from models.lead_data import LeadData
from bot_agents.triage_agent import triage_agent
from bot_agents.product_agent import product_agent
from agents import Runner
from utils.logging_setup import setup_logging
from datetime import datetime
import os
from typing import Dict, Optional
import base64

logger = setup_logging()
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()
threads = {}

async def get_or_create_thread(user_id: str, push_name: Optional[str] = None) -> str:
    if user_id in threads:
        logger.debug(f"Reusing in-memory thread for user {user_id}: {threads[user_id]}")
        return threads[user_id]
    lead = await get_lead(user_id)
    if lead and "thread_id" in lead and lead["thread_id"]:
        threads[user_id] = lead["thread_id"]
        logger.debug(f"Reusing Supabase thread for user {user_id}: {lead['thread_id']}")
        if push_name and (not lead.get("nome_cliente") or not lead.get("pushname")):
            lead_data = LeadData(
                remotejid=user_id,
                nome_cliente=push_name,
                pushname=push_name,
                telefone=user_id.replace("@s.whatsapp.net", ""),
                data_cadastro=lead.get("data_cadastro", datetime.now().isoformat()),
                thread_id=lead["thread_id"]
            )
            logger.debug(f"Updating nome_cliente and pushname for {user_id}: {push_name}")
            await upsert_lead(user_id, lead_data)
        return lead["thread_id"]
    thread = await client.beta.threads.create()
    threads[user_id] = thread.id
    logger.debug(f"Created new thread for user {user_id}: {thread.id}")
    lead_data = LeadData(
        remotejid=user_id,
        nome_cliente=push_name,
        pushname=push_name,
        telefone=user_id.replace("@s.whatsapp.net", ""),
        data_cadastro=datetime.now().isoformat(),
        thread_id=thread.id
    )
    logger.debug(f"Preparing to upsert lead data: {lead_data.dict(exclude_unset=True)}")
    await upsert_lead(user_id, lead_data)
    return thread.id

async def get_thread_history(thread_id: str, limit: int = 10) -> str:
    try:
        messages = await client.beta.threads.messages.list(thread_id=thread_id, limit=limit)
        history = []
        for msg in reversed(messages.data):
            role = msg.role
            content = msg.content[0].text.value if msg.content else ""
            history.append(f"{role.capitalize()}: {content}")
        return "\n".join(history) if history else "No previous messages."
    except Exception as e:
        logger.error(f"Error retrieving thread history for thread {thread_id}: {str(e)}")
        return "Error retrieving conversation history."

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        logger.info(f"Payload recebido: {data}")
        
        user_id = data.get("data", {}).get("key", {}).get("remoteJid", "")
        phone_number = user_id
        push_name = data.get("data", {}).get("pushName", None)
        logger.debug(f"Extracted phone_number: {phone_number}, user_id: {user_id}, pushName: {push_name}")

        if not phone_number or not user_id:
            logger.warning("Nenhum número de telefone ou user_id encontrado no payload")
            return {"status": "error", "message": "No phone number or user_id found"}

        thread_id = await get_or_create_thread(user_id, push_name=push_name)
        thread_history = await get_thread_history(thread_id)
        logger.debug(f"Thread history for {thread_id}: {thread_history}")

        message_data = data.get("data", {}).get("message", {})
        message = None
        is_audio_message = False
        is_image_message = False
        message_key_id = data.get("data", {}).get("key", {}).get("id", "")
        response_data = {"text": "Desculpe, houve um problema ao processar sua mensagem. Como posso ajudar?"}
        prefer_audio = False

        if message_data.get("conversation"):
            message = message_data["conversation"]
            prefer_audio = "responda em áudio" in str(message).lower()
        elif message_data.get("audioMessage"):
            is_audio_message = True
            media_result = await fetch_media_base64(message_key_id, "audio", remotejid=user_id)
            if "error" in media_result:
                logger.error(f"[{user_id}] Falha ao processar áudio: {media_result['error']}")
                response_data = {"text": f"Falha ao processar áudio: {media_result['error']}"}
            elif media_result.get("type") == "audio":
                message = media_result["transcription"]
                logger.info(f"Transcribed audio to: {message}")
                prefer_audio = True
        elif message_data.get("imageMessage"):
            is_image_message = True
            logger.info(f"[{user_id}] Buscando imagem completa via fetch_media_base64")
            try:
                media_result = await fetch_media_base64(message_key_id, "image", remotejid=user_id)
                if "error" in media_result:
                    logger.error(f"[{user_id}] Falha ao buscar imagem completa: {media_result['error']}")
                    response_data = {"text": f"Falha ao buscar imagem completa: {media_result['error']}"}
                elif media_result.get("type") == "image":
                    base64_data = media_result["base64"]
                    mimetype = media_result["mimetype"]
                    logger.debug(f"[{user_id}] Imagem completa obtida, mimetype: {mimetype}, tamanho base64: {len(base64_data)}")
                    decoded_data = base64.b64decode(base64_data)
                    resized_base64 = await resize_image_to_thumbnail(decoded_data, max_size=512)
                    if not resized_base64:
                        logger.error(f"[{user_id}] Falha ao redimensionar imagem")
                        response_data = {"text": "Falha ao redimensionar imagem. Por favor, envie outra imagem ou descreva o produto."}
                    else:
                        image_description = await analyze_image(content=resized_base64, mimetype=mimetype)
                        if image_description.startswith("Erro"):
                            logger.error(f"[{user_id}] Falha ao analisar imagem: {image_description}")
                            response_data = {"text": f"Falha ao analisar imagem: {image_description}"}
                        else:
                            message = f"Imagem recebida: {image_description}\n\nHistórico da conversa:\n{thread_history}"
                            logger.info(f"[{user_id}] Imagem analisada, descrição: {image_description}")
                            await client.beta.threads.messages.create(
                                thread_id=thread_id,
                                role="user",
                                content=message
                            )
                            logger.debug(f"Added image description to thread {thread_id}: {message}")
                            response = await Runner.run(product_agent, input=message)
                            logger.debug(f"RunResult: {response}")
                            response_data = str(response.final_output)
                            logger.debug(f"Resposta do agente (final_output): {response_data}")
                            try:
                                response_data = json.loads(response_data)
                                if not isinstance(response_data, dict):
                                    response_data = {"text": str(response_data)}
                            except json.JSONDecodeError:
                                logger.warning(f"Resposta não é um JSON válido, tratando como texto puro: {response_data}")
                                response_data = {"text": response_data}
            except Exception as e:
                logger.error(f"[{user_id}] Erro ao processar imagem: {e}")
                response_data = {"text": f"Erro ao processar imagem: {str(e)}"}

        if not message:
            logger.warning("Nenhuma mensagem de texto, áudio ou imagem válida encontrada no payload")
            response_data = {"text": "Nenhuma mensagem válida encontrada. Como posso ajudar?"}

        # Extract and save lead information
        if message:
            try:
                extracted_info = await extract_lead_info(message, remotejid=user_id)
                extracted_data = json.loads(extracted_info)
                if "error" not in extracted_data:
                    lead_data = LeadData(**extracted_data)
                    await upsert_lead(user_id, lead_data)
                    logger.debug(f"[{user_id}] Lead data saved: {extracted_data}")
            except Exception as e:
                logger.error(f"[{user_id}] Failed to extract or save lead info: {str(e)}")

        # Handle product queries
        if message and any(keyword in message.lower() for keyword in ["tênis", "sapato", "produto", "catálogo"]):
            try:
                product_query = ProductQuery(query=message)
                product_result = await query_products(product_query)
                product_data = json.loads(product_result)
                if "error" not in product_data:
                    for product in product_data:
                        caption = f"{product.get('name', 'Produto')}, tamanho {product.get('size', 'N/A')}, R${product.get('price', 'N/A')}"
                        image_url = product.get('image_url')
                        if image_url:
                            success = await send_whatsapp_image(
                                phone_number=phone_number,
                                image_url=image_url,
                                caption=caption,
                                remotejid=user_id,
                                message_key_id=message_key_id,
                                message_text=message
                            )
                            if not success:
                                logger.error(f"[{user_id}] Falha ao enviar imagem do produto: {image_url}")
                                response_data = {"text": f"Falha ao enviar imagem do produto: {product.get('name', 'Produto')}"}
                        else:
                            logger.warning(f"[{user_id}] Produto sem image_url: {product.get('name')}")
                            response_data = {"text": f"{caption}. Imagem não disponível."}
                    response_data = {"text": f"Encontrei {len(product_data)} produto(s) para '{message}'. Deseja prosseguir com o pedido?"}
                else:
                    response_data = {"text": product_data["error"]}
            except Exception as e:
                logger.error(f"[{user_id}] Failed to query products: {str(e)}")
                response_data = {"text": f"Erro ao consultar produtos: {str(e)}"}
        # Handle image requests or other messages
        elif message and not is_image_message:
            try:
                full_message = f"Histórico da conversa:\n{thread_history}\n\nNova mensagem: {message}"
                await client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=message
                )
                logger.debug(f"Added user message to thread {thread_id}: {message}")
                agent = triage_agent if not any(keyword in message.lower() for keyword in ["imagem", "foto"]) else product_agent
                response = await Runner.run(agent, input=full_message)
                logger.debug(f"RunResult: {response}")
                response_data = str(response.final_output)
                logger.debug(f"Resposta do agente (final_output): {response_data}")
                try:
                    response_data = json.loads(response_data)
                    if not isinstance(response_data, dict):
                        response_data = {"text": str(response_data)}
                except json.JSONDecodeError:
                    logger.warning(f"Resposta não é um JSON válido, tratando como texto puro: {response_data}")
                    response_data = {"text": response_data}
            except Exception as e:
                logger.error(f"Failed to process message in thread {thread_id}: {str(e)}")
                response_data = {"text": f"Erro ao processar mensagem: {str(e)}"}

        # Handle response sending
        success = False
        if prefer_audio and response_data.get("text"):
            audio_path = await text_to_speech(response_data["text"])
            if not audio_path.startswith("Erro"):
                success = await send_whatsapp_audio(
                    phone_number=phone_number,
                    audio_path=audio_path,
                    remotejid=user_id,
                    message_key_id=message_key_id,
                    message_text=message if not is_audio_message else None
                )
                if os.path.exists(audio_path):
                    os.remove(audio_path)
                    logger.debug(f"Removed audio file: {audio_path}")
            else:
                logger.error(f"Failed to generate audio: {audio_path}")
                response_data = {"text": "Desculpe, houve um problema ao gerar o áudio. Como posso ajudar?"}
                success = await send_whatsapp_message(phone_number, response_data["text"], remotejid=user_id)
        else:
            if isinstance(response_data, dict) and response_data.get("products"):
                for product in response_data["products"]:
                    caption = f"{product.get('name', 'Produto')}, tamanho {product.get('size', 'N/A')}, R${product.get('price', 'N/A')}"
                    image_url = product.get("image_url")
                    if image_url:
                        success = await send_whatsapp_image(
                            phone_number=phone_number,
                            image_url=image_url,
                            caption=caption,
                            remotejid=user_id,
                            message_key_id=message_key_id,
                            message_text=message
                        )
                        if not success:
                            logger.error(f"[{user_id}] Falha ao enviar imagem do produto: {image_url}")
                            response_data = {"text": f"Falha ao enviar imagem do produto: {product.get('name', 'Produto')}"}
                    else:
                        logger.warning(f"[{user_id}] Produto sem image_url: {product.get('name')}")
                        response_data = {"text": f"{caption}. Imagem não disponível."}
                response_data = {"text": f"Encontrei {len(response_data['products'])} produto(s) para '{message}'. Deseja prosseguir com o pedido?"}
            elif response_data.get("text"):
                image_url_match = re.match(r'!\[.*?\]\((.*?)\)', response_data.get("text", ""))
                if image_url_match:
                    image_url = image_url_match.group(1)
                    caption = response_data.get("text", "").split("]")[0][2:] or "Imagem do produto"
                    success = await send_whatsapp_image(
                        phone_number=phone_number,
                        image_url=image_url,
                        caption=caption,
                        remotejid=user_id,
                        message_key_id=message_key_id,
                        message_text=message if not is_audio_message else None
                    )
                    if success:
                        response_data = {"text": ""}  # Clear text to avoid duplication
                    else:
                        logger.error(f"[{user_id}] Falha ao enviar imagem: {image_url}")
                        response_data = {"text": "Desculpe, houve um problema ao enviar a imagem."}
                if response_data.get("text"):  # Only send text if not empty
                    success = await send_whatsapp_message(phone_number, response_data["text"], remotejid=user_id)

        try:
            if response_data.get("text") or (isinstance(response_data, dict) and response_data.get("products")):
                await client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="assistant",
                    content=response_data.get("text", json.dumps(response_data))
                )
                logger.debug(f"Added assistant response to thread {thread_id}: {response_data}")
        except Exception as e:
            logger.error(f"Failed to add assistant response to thread {thread_id}: {str(e)}")
            response_data = {"text": f"Erro ao salvar resposta do assistente: {str(e)}"}
            success = await send_whatsapp_message(phone_number, response_data["text"], remotejid=user_id)

        lead_data = LeadData(remotejid=user_id)
        if message and "cidade:" in message.lower():
            lead_data.cidade = message.lower().split("cidade:")[1].strip().split()[0]
        if message and "estado:" in message.lower():
            lead_data.estado = message.lower().split("estado:")[1].strip().split()[0]
        if message and "email:" in message.lower():
            lead_data.email = message.lower().split("email:")[1].strip().split()[0]
        if any(field is not None for field in [lead_data.cidade, lead_data.estado, lead_data.email]):
            logger.debug(f"Updating lead with additional info: {lead_data.dict(exclude_unset=True)}")
            await upsert_lead(user_id, lead_data)

        if success:
            logger.info(f"[{user_id}] Mensagem enviada com sucesso")
            return {"status": "success", "message": "Processed and responded"}
        else:
            logger.error(f"[{user_id}] Falha ao enviar resposta para o WhatsApp")
            return {"status": "error", "message": "Failed to send response"}

    except Exception as e:
        logger.error(f"Erro ao processar webhook: {str(e)}")
        return {"status": "error", "message": f"Error processing webhook: {str(e)}"}