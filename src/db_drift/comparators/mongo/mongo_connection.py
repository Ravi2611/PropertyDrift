# import os
# from pymongo import MongoClient
# from dotenv import load_dotenv
# from src.utils.logger import get_logger

# logger = get_logger("MongoConnection")

# load_dotenv()

# def get_mongo_client(replica_sets, database=None, user=None, password=None):
#     logger.debug(f"Building MongoDB client for: {replica_sets}")
#     user = user or os.getenv("MONGO_USER")
#     password = password or os.getenv("MONGO_PASSWORD")
    
#     if user and password:
#         auth_part = f"{user}:{password}@"
#         logger.debug("Using authenticated connection")
#     else:
#         auth_part = ""
#         logger.debug("Using unauthenticated connection")
        
#     db_part = f"/{database}" if database else "/"
#     uri = f"mongodb://{auth_part}{replica_sets}{db_part}?directConnection=true"
        
#     logger.info(f"Connecting to MongoDB at {replica_sets}")
#     return MongoClient(uri, serverSelectionTimeoutMS=5000)

# def test_mongo_connection(replica_sets):
#     try:
#         logger.info(f"Testing connection to {replica_sets}...")
#         client = get_mongo_client(replica_sets)
#         client.admin.command('ping')
#         logger.info("MongoDB connection successful")
#         return True, None
#     except Exception as e:
#         logger.error(f"MongoDB connection test failed: {str(e)}")
#         return False, str(e)



import os
from pymongo import MongoClient
from dotenv import load_dotenv
from src.db_drift.utils.logger import get_logger

logger = get_logger("MongoConnection")
load_dotenv()


def get_mongo_client(replica_sets, database=None, user=None, password=None):
    logger.debug(f"Building MongoDB client for: {replica_sets}")

    user = user or os.getenv("MONGO_USER")
    password = password or os.getenv("MONGO_PASSWORD")

    if user and password:
        auth_part = f"{user}:{password}@"
        logger.debug("Using authenticated connection")
    else:
        auth_part = ""
        logger.debug("Using unauthenticated connection")

    db_part = f"/{database}" if database else "/"
    auth_source = database if database else "admin"

    uri = f"mongodb://{auth_part}{replica_sets}{db_part}?directConnection=true&authSource={auth_source}"

    logger.info(f"Connecting to MongoDB at {replica_sets}, authSource={auth_source}")

    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def test_mongo_connection(replica_sets, database=None, user=None, password=None):
    try:
        logger.info(f"Testing connection to {replica_sets}...")
        client = get_mongo_client(replica_sets, database=database, user=user, password=password)
        client.admin.command('ping')
        logger.info("MongoDB connection successful")
        return True, None
    except Exception as e:
        logger.error(f"MongoDB connection test failed: {str(e)}")
        return False, str(e)