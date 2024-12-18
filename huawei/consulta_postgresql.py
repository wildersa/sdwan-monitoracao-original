import psycopg2
import argparse

# Função para executar a consulta no PostgreSQL
def executar_consulta(host, port, database, user, password, query):
    try:
        # Conectar ao banco de dados
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )

        # Criar o cursor para executar comandos
        cursor = conn.cursor()

        # Executar a query
        cursor.execute(query)

        # Obter os resultados
        rows = cursor.fetchall()

        # Exibir os resultados
        for row in rows:
            print(row)

        # Fechar o cursor e a conexão
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Erro ao executar a consulta: {e}")

# Configuração do argparse para aceitar todos os parâmetros via linha de comando
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Executar consultas no PostgreSQL via parâmetros.")
    
    # Parâmetros de conexão
    parser.add_argument("--host", required=True, help="Endereço do servidor PostgreSQL")
    parser.add_argument("--port", required=True, help="Porta do servidor PostgreSQL")
    parser.add_argument("--database", required=True, help="Nome do banco de dados")
    parser.add_argument("--user", required=True, help="Usuário do PostgreSQL")
    parser.add_argument("--password", required=True, help="Senha do PostgreSQL")
    
    # Parâmetro para a query
    parser.add_argument("--query", required=True, help="Consulta SQL a ser executada")

    # Parse dos argumentos
    args = parser.parse_args()

    # Executar a consulta com os parâmetros fornecidos
    executar_consulta(args.host, args.port, args.database, args.user, args.password, args.query)
