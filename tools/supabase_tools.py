from typing import Dict
from datetime import datetime
import asyncio
from supabase import create_client, Client
from config.config import SUPABASE_URL, SUPABASE_KEY
from models.lead_data import LeadData
from utils.validation import validate_lead_data
from utils.logging_setup import setup_logging

logger = setup_logging()

async def upsert_lead(remotejid: str, data: LeadData) -> Dict:
    if not all([SUPABASE_URL, SUPABASE_KEY]):
        logger.error("Configurações do Supabase não estão completas")
        return {}
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        valid_data = validate_lead_data(data.dict(exclude_unset=True))
        valid_data["remotejid"] = remotejid
        valid_data["data_ultima_alteracao"] = datetime.now().isoformat()
        logger.debug(f"Upserting lead data: {valid_data}")
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, lambda: client.table("leads").upsert(
            valid_data,
            on_conflict="remotejid",
            returning="representation"
        ).execute())
        logger.info(f"Upserted lead for remotejid: {remotejid}, data: {valid_data}")
        return response.data[0] if response.data else {}
    except Exception as e:
        logger.error(f"Error upserting lead for remotejid {remotejid}: {e}")
        return {}

async def get_lead(remotejid: str) -> Dict:
    if not all([SUPABASE_URL, SUPABASE_KEY]):
        logger.error("Configurações do Supabase não estão completas")
        return {}
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, lambda: client.table("leads").select("*").eq("remotejid", remotejid).execute())
        return response.data[0] if response.data else {}
    except Exception as e:
        logger.error(f"Error retrieving lead for remotejid {remotejid}: {e}")
        return {}