from pydantic import BaseModel, Field
from supabase import create_client, Client
import asyncio
import json
from config.config import SUPABASE_URL, SUPABASE_KEY
from utils.logging_setup import setup_logging
from agents import function_tool

logger = setup_logging()

class ProductQuery(BaseModel):
    query: str = Field(..., description="Termo de busca para os produtos")

@function_tool
async def query_products(query: ProductQuery) -> str:
    if not all([SUPABASE_URL, SUPABASE_KEY]):
        return json.dumps({"error": "Configurações do Supabase não estão completas"})
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        loop = asyncio.get_running_loop()
        query_lower = query.query.lower()
        response = await loop.run_in_executor(None, lambda: client.table("products")
            .select("*")
            .or_(f"name.ilike.%{query_lower}%,description.ilike.%{query_lower}%")
            .execute())
        if not response.data:
            return json.dumps({"error": f"Nenhum produto encontrado para: {query.query}"})
        return json.dumps(response.data)
    except Exception as e:
        if "relation \"products\" does not exist" in str(e):
            return json.dumps({"error": "Tabela de produtos não existe no Supabase"})
        return json.dumps({"error": f"Erro ao consultar produtos: {str(e)}"})