import requests
import logging
import sys
import json
import os
from datetime import datetime
from logging_config import load_log_config
import pytz
import time

# Carregar a configuração de log para este script
load_log_config(script_name="access_manager")

# Caminho para o arquivo de token geral e de tenant
TOKEN_FILE = os.path.join(os.getcwd(), "config", "token.json")
TENANT_TOKEN_FILE_TEMPLATE = os.path.join(os.getcwd(), "config", "tenant_token_{tenant_id}.json")
LOCK_WAIT_TIME = 5  # Tempo de espera entre tentativas
MAX_ATTEMPTS = 3  # Número máximo de tentativas
LOCK_TIMEOUT = 60  # Tempo limite para considerar um lock travado

# Função para carregar a configuração de endpoints
def load_endpoints_config():
    config_path = os.path.join(os.getcwd(), 'config', 'endpoints_config.json')
    with open(config_path, 'r', encoding='utf-8') as file:
        return json.load(file)

# Função para verificar se o token expirou
def is_token_expired(expired_date_str):
    gmt = pytz.timezone('GMT')
    expired_date = datetime.strptime(expired_date_str, "%Y-%m-%d %H:%M:%S")
    expired_date = gmt.localize(expired_date)
    now = datetime.now(pytz.utc)
    return now > expired_date

# Função para obter o token de autenticação
def get_huawei_nce_token(url, username, password, execution_id, force_new_token=False):
    logging.info(f"[Execution ID: {execution_id}] Iniciando a obtenção do token")

    # Verificar se já existe um token e se ele é válido
    if os.path.exists(TOKEN_FILE) and not force_new_token:
        with open(TOKEN_FILE, "r") as file:
            token_data = json.load(file)

        # Se não existir expiredDate ou o token for inválido, forçar nova geração
        if "expiredDate" not in token_data or is_token_expired(token_data["expiredDate"]):
            logging.warning(f"[Execution ID: {execution_id}] Token inválido ou expiredDate ausente. Forçando nova obtenção.")
            return get_huawei_nce_token(url, username, password, execution_id, force_new_token=True)

        if not token_data.get("locked"):
            logging.info(f"[Execution ID: {execution_id}] Token válido encontrado.")
            return token_data["token_id"]

    # Bloquear o token antes de fazer a requisição
    token_data = {"locked": True, "lockedSince": datetime.now(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")}
    with open(TOKEN_FILE, "w") as file:
        json.dump(token_data, file, indent=4)

    # Carregar o endpoint do arquivo endpoints_config.json
    endpoints_config = load_endpoints_config()
    endpoint = f"https://{url}{endpoints_config['endpoints']['get_token']['endpoint']}"
    
    payload = {
        "userName": username,
        "password": password
    }
    headers = {"Content-Type": "application/json"}

    try:
        logging.info(f"[Execution ID: {execution_id}] Fazendo requisição para: {endpoint}")
        response = requests.post(endpoint, json=payload, headers=headers)

        # DEBUG: Detalhes da resposta
        logging.debug(f"[Execution ID: {execution_id}] Response received: Status code {response.status_code}, Content: {response.text}")

        if response.status_code != 200:
            logging.error(f"[Execution ID: {execution_id}] Erro HTTP: {response.status_code} - {response.text}")
            sys.exit(1)

        response_json = response.json()

        if response_json.get('errcode') == "0":
            token = response_json['data']['token_id']
            expired_date = response_json['data']['expiredDate']
            token_data = {
                "token_id": token,
                "expiredDate": expired_date,
                "locked": False,
                "lockedSince": None  # Definir lockedSince como None após a obtenção bem-sucedida do token
            }
            with open(TOKEN_FILE, "w") as file:
                json.dump(token_data, file, indent=4)
            logging.info(f"[Execution ID: {execution_id}] Token obtido com sucesso e salvo.")
            return token
        else:
            logging.error(f"[Execution ID: {execution_id}] Erro na obtenção do token: {response_json['errmsg']}")
            sys.exit(1)
    except Exception as e:
        logging.critical(f"[Execution ID: {execution_id}] Erro ao tentar obter o token: {e}")
        sys.exit(1)

# Função para obter o token com Tenant ID
def get_tenant_token(url, tenant_id, access_token, execution_id, force_new_token=False):
    tenant_file = TENANT_TOKEN_FILE_TEMPLATE.format(tenant_id=tenant_id)
    
    logging.info(f"[Execution ID: {execution_id}] Iniciando a obtenção do tenant token para tenant {tenant_id}")

    if os.path.exists(tenant_file) and not force_new_token:
        with open(tenant_file, "r") as file:
            tenant_token_data = json.load(file)

        # Se não existir expiredDate ou o token for inválido, forçar nova geração
        if "expiredDate" not in tenant_token_data or is_token_expired(tenant_token_data["expiredDate"]):
            logging.warning(f"[Execution ID: {execution_id}] Tenant token inválido ou expiredDate ausente. Forçando nova obtenção.")
            return get_tenant_token(url, tenant_id, access_token, execution_id, force_new_token=True)

        if not tenant_token_data.get("locked"):
            logging.info(f"[Execution ID: {execution_id}] Token válido para tenant {tenant_id}.")
            return tenant_token_data["tokenId"]

    tenant_token_data = {"locked": True, "lockedSince": datetime.now(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")}
    with open(tenant_file, "w") as file:
        json.dump(tenant_token_data, file, indent=4)

    # Carregar o endpoint do arquivo endpoints_config.json
    endpoints_config = load_endpoints_config()
    endpoint = f"https://{url}{endpoints_config['endpoints']['get_tenant_token']['endpoint']}"

    payload = {
        "identity": {
            "methods": ["assumeRole"],
            "assumeRole": {"tenantId": tenant_id}
        }
    }
    headers = {
        "Content-Type": "application/json",
        "X-ACCESS-TOKEN": access_token
    }

    try:
        logging.info(f"[Execution ID: {execution_id}] Fazendo requisição para: {endpoint}")
        response = requests.post(endpoint, json=payload, headers=headers)

        # DEBUG: Detalhes da resposta
        logging.debug(f"[Execution ID: {execution_id}] Response received: Status code {response.status_code}, Content: {response.text}")

        if response.status_code != 200:
            logging.error(f"[Execution ID: {execution_id}] Erro HTTP: {response.status_code} - {response.text}")
            sys.exit(1)

        response_json = response.json()

        if 'data' in response_json and 'tokenId' in response_json['data']:
            tenant_token = response_json['data']['tokenId']
            expired_date = response_json['data']['expiredDate']

            tenant_token_data = {
                "tokenId": tenant_token,
                "expiredDate": expired_date,
                "locked": False,
                "lockedSince": None
            }
            with open(tenant_file, "w") as file:
                json.dump(tenant_token_data, file, indent=4)
            logging.info(f"[Execution ID: {execution_id}] Tenant token obtido e salvo com sucesso para tenant {tenant_id}.")
            return tenant_token
        else:
            logging.error(f"[Execution ID: {execution_id}] Erro na obtenção do tenant token: {response_json}")
            sys.exit(1)
    except Exception as e:
        logging.critical(f"[Execution ID: {execution_id}] Erro ao tentar obter o tenant token: {e}")
        sys.exit(1)
