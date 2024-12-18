import logging
import json
import os

class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        # Obter a mensagem original
        message = record.getMessage()

        # Máscara de dados sensíveis
        if 'username' in message:
            message = message.replace('username', '***')
        if 'password' in message:
            message = message.replace('password', '***')

        # Substituir a mensagem no registro de log
        record.msg = message
        return True

def load_log_config(script_name, config_file='log_config.json'):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, 'config', config_file)

    with open(config_path, 'r') as f:
        config = json.load(f)

    log_config = config.get(script_name, config['default'])
    log_file = log_config['log_file']
    level = getattr(logging, log_config['level'].upper(), logging.INFO)

    # Criar diretório do arquivo de log, se não existir
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # Configurar o logger
    logger = logging.getLogger(script_name)
    
    # Remover handlers existentes para evitar duplicação
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.setLevel(level)

    # Criar um handler para o arquivo de log
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # Adicionar o filtro de mascaramento de dados sensíveis
    file_handler.addFilter(SensitiveDataFilter())

    # Adicionar o handler ao logger
    logger.addHandler(file_handler)

    # Garantir que não haja propagação para o logger raiz
    logger.propagate = False

    # Certificar-se de que não há `StreamHandler` no logger raiz
    for handler in logging.root.handlers[:]:
        if isinstance(handler, logging.StreamHandler):
            logging.root.removeHandler(handler)

    return logger