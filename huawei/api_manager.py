import requests
import json
import os
import logging
import logging_config
from output_handler import get_output_handler, load_output_config
from access_manager import get_huawei_nce_token, get_tenant_token
import argparse
import uuid  # Importar UUID para gerar e controlar o UUID
import sys
import traceback  # Importar para capturar o traceback

# Gerar um UUID único para esta execução
execution_id = str(uuid.uuid4())

# Carregar a configuração de log para o api_manager
logger = logging_config.load_log_config('api_manager')

# Remover qualquer outro handler que imprima na tela (stderr)
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Carregar a configuração de saída (output_handler_config.json)
output_config = load_output_config()

# Função para carregar a configuração de endpoints
def load_endpoints_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'endpoints_config.json')
    with open(config_path, 'r', encoding='utf-8') as file:
        return json.load(file)

# Substituir placeholders no dicionário por valores reais passados em kwargs
def parse_placeholders(data, execution_id, **kwargs):
    if isinstance(data, dict):
        return {k: parse_placeholders(v, execution_id, **kwargs) for k, v in data.items()}
    elif isinstance(data, str):
        return data.format(**kwargs)
    return data

# Função para obter o token correto
def get_token(token_type, url_base, username, password, execution_id, tenant_id=None):
    logger.info(f"[UUID: {execution_id}] Obtendo token {token_type}")
    if token_type == "msp":
        return get_huawei_nce_token(url_base, username, password, execution_id)
    elif token_type == "tenant":
        if not tenant_id:
            raise ValueError("O 'tenant_id' é obrigatório para chamadas com token do tipo 'tenant'")
        msp_token = get_huawei_nce_token(url_base, username, password, execution_id)
        return get_tenant_token(url_base, tenant_id, msp_token, execution_id)
    else:
        raise ValueError(f"Tipo de token {token_type} desconhecido")

# Função para construir os parâmetros da URL
def build_url_params(endpoint_config, execution_id, **kwargs):
    url_params = {}
    for param in endpoint_config.get('url_params', []):
        if param['name'] in kwargs and kwargs[param['name']] is not None:
            url_params[param['name']] = kwargs[param['name']]
    return url_params

# Função para construir o corpo da requisição
def build_body_params(endpoint_config, execution_id, **kwargs):
    body_params = {}
    for param in endpoint_config.get('body_params', []):
        if param['name'] in kwargs and kwargs[param['name']] is not None:
            body_params[param['name']] = kwargs[param['name']]
    return body_params

# Função para tratar argumentos do tipo array
def convert_array_args(endpoint_config, execution_id, **kwargs):
    for param in endpoint_config.get('body_params', []):
        if param['type'] == 'array' and param['name'] in kwargs and isinstance(kwargs[param['name']], str):
            kwargs[param['name']] = kwargs[param['name']].split(",")
    return kwargs

# Função para adicionar dinamicamente argumentos no argparse
def add_arguments_dynamically(parser, endpoint_config, execution_id):
    for param in endpoint_config.get('url_params', []) + endpoint_config.get('body_params', []):
        arg_name = f"--{param['name']}"
        if param['type'] == 'int':
            parser.add_argument(arg_name, type=int, help=param.get('description', ''))
        elif param['type'] == 'array':
            parser.add_argument(arg_name, help=f"{param.get('description', '')} (use vírgula para separar valores)")
        else:
            parser.add_argument(arg_name, type=str, help=param.get('description', ''))

# Função centralizada para fazer chamadas
def make_api_call(endpoint_name, url_base, username, password, execution_id, tenant_id=None, **kwargs):
    config = load_endpoints_config()
    endpoint_config = config['endpoints'].get(endpoint_name)

    if not endpoint_config:
        logger.error(f"[UUID: {execution_id}] Endpoint {endpoint_name} não encontrado na configuração.")
        raise ValueError(f"Endpoint {endpoint_name} não encontrado na configuração.")

    # Converter automaticamente todos os argumentos de array
    kwargs = convert_array_args(endpoint_config, execution_id, **kwargs)

    # Obter o token necessário
    token_type = endpoint_config.get("token_type")

    # Só exige tenant_id se o token_type for "tenant"
    if token_type == "tenant" and not tenant_id:
        raise ValueError(f"O endpoint {endpoint_name} requer 'tenant_id' pois utiliza token Tenant.")

    token = get_token(token_type, url_base, username, password, execution_id, tenant_id)

    # Preparar headers e corpo
    headers = parse_placeholders(endpoint_config['headers'], execution_id, token=token, **kwargs)
    body = build_body_params(endpoint_config, execution_id, **kwargs)

    # Construir URL com parâmetros de query
    url_params = build_url_params(endpoint_config, execution_id, **kwargs)
    url = f"https://{url_base}{endpoint_config['endpoint']}"
    
    if url_params:
        url += "?" + "&".join([f"{key}={value}" for key, value in url_params.items()])

    # Logar a requisição
    logger.info(f"[UUID: {execution_id}] Requisição para URL: {url}")
    logger.info(f"[UUID: {execution_id}] Headers: {headers}")
    logger.info(f"[UUID: {execution_id}] Body: {body}")

    # Realizar a chamada HTTP
    try:
        if endpoint_config['method'] == "GET":
            response = requests.get(url, headers=headers, params=kwargs.get('params', {}))
        elif endpoint_config['method'] == "POST":
            response = requests.post(url, headers=headers, json=body)
        else:
            logger.error(f"[UUID: {execution_id}] Método {endpoint_config['method']} não suportado.")
            raise ValueError(f"Método {endpoint_config['method']} não suportado.")

        # Verificar se a resposta foi bem-sucedida
        if response.status_code == 200:
            # Carregar a configuração de saída específica para o endpoint
            handler_config = output_config.get(endpoint_name, output_config.get("default", {}))

            # Definir o tipo de handler a partir da configuração
            handler_type = handler_config.get("type", "file")  # Valor padrão é "file" se não especificado
            file_settings = handler_config.get("file_settings", {})

            # Para database, pegar o db_name e mapear com o db_connection correto
            if handler_type == "database":
                db_settings = handler_config.get("database_settings", {})
                db_name = db_settings.get("db_name")
                if not db_name:
                    raise ValueError(f"[UUID: {execution_id}] db_name não encontrado na configuração.")
                
                # Carregar a string de conexão correta a partir do db_name
                db_connection = output_config['databases'].get(db_name, {}).get('db_connection')
                if not db_connection:
                    raise ValueError(f"[UUID: {execution_id}] db_connection não encontrado para o db_name: {db_name}")
                
                # Passar as configurações do banco de dados para o handler
                db_settings['db_connection'] = db_connection
                file_settings = db_settings  # Agora file_settings contém as configurações de banco de dados

            # Log para verificar os parâmetros
            logger.info(f"[UUID: {execution_id}] handler_type: {handler_type}, file_settings: {file_settings}")

            # Obter o handler para a saída com base no tipo e configurações, passando o UUID
            output_handler = get_output_handler(handler_type, execution_id=execution_id, **file_settings)

            # Verificar se o output_handler foi criado corretamente
            if output_handler is None:
                logger.error(f"[UUID: {execution_id}] Falha ao instanciar o output_handler. Verifique os parâmetros passados: {file_settings}")
            else:
                logger.info(f"[UUID: {execution_id}] Output handler criado com sucesso.")

            # Obter a chave `response_key` do endpoints_config.json
            response_key = endpoint_config.get('response_key', 'data')  # Padrão é 'data' se não for definido

            # Salvar a resposta usando o handler configurado dinamicamente
            output_handler.save(endpoint_name, response.json(), tenant_id=tenant_id or "", execution_id=execution_id, response_key=response_key, **kwargs)
            logger.info(f"[UUID: {execution_id}] Resposta recebida: {response.json()}")
            return response.json()
        else:
            logger.error(f"[UUID: {execution_id}] Erro na resposta: {response.status_code} - {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"[UUID: {execution_id}] Erro ao fazer a chamada API: {e}")
        return None

# Exemplo de uso
if __name__ == "__main__":
    try:
        config = load_endpoints_config()
        endpoint_name = sys.argv[sys.argv.index('--endpoint_name') + 1] if '--endpoint_name' in sys.argv else None

        endpoint_config = config['endpoints'].get(endpoint_name) if endpoint_name else None

        parser = argparse.ArgumentParser(description="Fazer chamadas para a API Huawei NCE")
        parser.add_argument('--username', required=True, help="Username para autenticação")
        parser.add_argument('--password', required=True, help="Password para autenticação")
        parser.add_argument('--url_base', required=True, help="URL base da API")
        parser.add_argument('--tenant_id', help="Tenant ID para chamadas com token Tenant")
        parser.add_argument('--endpoint_name', required=True, help="Nome do endpoint a ser chamado, ex: get_tenants")

        if endpoint_config:
            add_arguments_dynamically(parser, endpoint_config, execution_id)

        args = parser.parse_args()

        # Mascarar username e senha no log
        masked_args = vars(args).copy()
        masked_args['username'] = '***'
        masked_args['password'] = '***'

        logger.info(f"[UUID: {execution_id}] Argumentos recebidos: {masked_args}")

        body = {key: value for key, value in vars(args).items() if value is not None and key not in ['username', 'password', 'url_base', 'endpoint_name', 'tenant_id']}

        response = make_api_call(
            args.endpoint_name,
            args.url_base,
            args.username,
            args.password,
            execution_id,
            tenant_id=args.tenant_id,
            **body
        )

        # Se a resposta foi bem-sucedida, retorna exit code 0
        if response:
            sys.exit(0)  # OK
        else:
            sys.exit(3)  # Erro na resposta

    except Exception as e:
        logger.error(f"[UUID: {execution_id}] Erro ao processar os argumentos ou executar o script: {str(e)}")
        logger.error(traceback.format_exc())  # Adiciona o rastreamento completo ao log
        sys.exit(3)  # Erro na execução