import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

def get_mysql_engine(host, port, database, user=None, password=None):
    user = user or os.getenv("MYSQL_USER")
    password = password or os.getenv("MYSQL_PASSWORD")
    
    # Using pymysql as the driver
    connection_string = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    return create_engine(connection_string)

def test_mysql_connection(host, port, database):
    try:
        engine = get_mysql_engine(host, port, database)
        with engine.connect() as connection:
            return True, None
    except Exception as e:
        return False, str(e)
