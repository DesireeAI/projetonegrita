# utils/validation.py
from typing import Dict
from utils.logging_setup import setup_logging

logger = setup_logging()

def validate_lead_data(data: Dict) -> Dict:
    lead_schema = {
        "remotejid", "nome_cliente", "pushname", "telefone", "cidade", "estado",
        "email", "tipo", "data_aniversario", "idioma", "audio",
        "thread_id", "data_cadastro", "data_ultima_alteracao",
        "ult_assunto", "id_google", "followup", "followup_data",
        "ult_contato", "cep", "endereco", "adm", "lead", "instancia",
        "agente", "thread_ag", "conciencia", "ult_verifica_lead",
        "verificador", "id_kommo", "sentimento"
    }
    valid_data = {k: v for k, v in data.items() if k in lead_schema and v is not None}
    if "tipo" in valid_data and valid_data["tipo"] not in ["lojista", "revendedor", "sacoleiro", "feirante"]:
        logger.warning(f"Invalid tipo value: {valid_data['tipo']}, removing")
        del valid_data["tipo"]
    if "sentimento" in valid_data and valid_data["sentimento"] not in ["positivo", "negativo", "neutro"]:
        logger.warning(f"Invalid sentimento value: {valid_data['sentimento']}, removing")
        del valid_data["sentimento"]
    if len(valid_data) < len(data):
        logger.warning(f"Filtered out invalid lead columns: {set(data.keys()) - set(valid_data.keys())}")
    return valid_data