import os
import json
import logging
import psycopg2
from urllib.parse import quote_plus
import traceback

# Handler para salvar em arquivos
class FileOutputHandler:
    def __init__(self, base_path, file_name_template="{endpoint}_response.json"):
        self.base_path = base_path
        self.file_name_template = file_name_template
    
    def save(self, endpoint, data, **kwargs):
        try:
            valid_kwargs = {k: (','.join(v) if isinstance(v, list) else v) if v is not None else '' for k, v in kwargs.items()}
            file_name = self.file_name_template.format(**valid_kwargs).replace("__", "_").strip("_")
            filename = os.path.join(self.base_path, file_name)

            os.makedirs(self.base_path, exist_ok=True)

            with open(filename, 'w') as outfile:
                json.dump(data, outfile, indent=4)

            logging.info(f"Arquivo salvo em: {filename}")
        except Exception as e:
            logging.error(f"Erro ao salvar o arquivo: {e}")
            logging.error(traceback.format_exc())

# Função auxiliar para verificar se o campo é aninhado
def is_nested_field(field):
    """Verifica se o campo é aninhado (contém '->>')."""
    return '->>' in field

# Função para construir a cláusula ON CONFLICT para campos aninhados ou simples
def build_conflict_clause(unique_field):
    """Constrói a cláusula ON CONFLICT com suporte para campos aninhados."""
    conflict_clause = []
    for field in unique_field:
        if is_nested_field(field):
            conflict_clause.append(f"(data->'{field.split('->')[0]}'->>'{field.split('->>')[1]}')")
        else:
            conflict_clause.append(f"(data->>'{field}')")
    return ", ".join(conflict_clause)

# Handler para salvar no banco de dados
class DatabaseOutputHandler:
    def __init__(self, db_connection, table, save_mode, unique_field=None):
        self.db_connection = self.encode_db_connection(db_connection)
        self.table = table
        self.save_mode = save_mode
        self.unique_field = unique_field
    
    def encode_db_connection(self, db_connection):
        if "@" in db_connection:
            parts = db_connection.split("@")
            credentials, host = parts[0], parts[1]
            user_pass = credentials.split("//")[-1]
            user, password = user_pass.split(":")
            password_encoded = quote_plus(password)
            credentials_encoded = f"{user}:{password_encoded}"
            return f"postgresql://{credentials_encoded}@{host}"
        return db_connection

    def save(self, endpoint, data, **kwargs):
        try:
            # Obter a chave de resposta do arquivo de configuração
            response_key = kwargs.get("response_key", "data")  # "data" será o padrão, caso não seja especificado

            # Usar a chave correta para acessar os dados
            data_to_process = data.get(response_key, [])

            conn = psycopg2.connect(self.db_connection)
            cursor = conn.cursor()

            # Verifica a lógica de conflito
            on_conflict_action = kwargs.get("on_conflict", "update")
            if on_conflict_action == "update":
                conflict_query = "DO UPDATE SET data = EXCLUDED.data, collected_at = NOW()"
            else:
                conflict_query = "DO NOTHING"

            # Inserção com upsert usando o índice único composto ou único
            insert_query = f"""
            INSERT INTO {self.table} (data, collected_at)
            VALUES (%s, NOW())
            """

            # Usar a função build_conflict_clause para criar o ON CONFLICT correto
            conflict_fields = build_conflict_clause(self.unique_field)
            insert_query += f"ON CONFLICT ({conflict_fields}) {conflict_query};"

            # Executa a inserção
            for item in data_to_process:
                cursor.execute(insert_query, (json.dumps(item),))

            conn.commit()
            logging.info(f"Dados salvos na tabela {self.table}")
            cursor.close()
            conn.close()

        except Exception as e:
            logging.error(f"Erro ao salvar no banco de dados: {e}")
            logging.error(traceback.format_exc())

# Função para carregar o arquivo de configuração
def load_output_config(config_file='output_handler_config.json'):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, 'config', config_file)

    try:
        with open(config_path, 'r') as file:
            return json.load(file)
    except Exception as e:
        logging.error(f"Erro ao carregar o arquivo de configuração: {e}")
        return None

# Função para escolher o handler de saída
def get_output_handler(handler_type, execution_id, **kwargs):
    try:
        logging.info(f"[UUID: {execution_id}] Tipo de handler: {handler_type}, Parâmetros recebidos: {kwargs}")

        if handler_type == "file":
            return FileOutputHandler(kwargs['base_path'], kwargs.get('file_name_template', "{endpoint}_response.json"))
        elif handler_type == "database":
            db_connection = kwargs.get('db_connection')
            table = kwargs.get('table')
            save_mode = kwargs.get('save_mode')
            unique_field = kwargs.get('unique_field')

            logging.info(f"[UUID: {execution_id}] db_connection: {db_connection}, table: {table}, save_mode: {save_mode}, unique_field: {unique_field}")

            if not db_connection or not table or not save_mode:
                raise ValueError(f"[UUID: {execution_id}] Parâmetros de banco de dados faltando: db_connection, table ou save_mode")

            return DatabaseOutputHandler(db_connection, table, save_mode, unique_field)
        else:
            raise ValueError(f"[UUID: {execution_id}] Handler desconhecido: {handler_type}")
    except Exception as e:
        logging.error(f"[UUID: {execution_id}] Erro ao instanciar o handler de saída: {str(e)}")
        logging.error(traceback.format_exc())
        return None
