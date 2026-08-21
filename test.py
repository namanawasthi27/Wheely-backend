from pymongo import MongoClient
from dotenv import load_dotenv
import certifi
import os

load_dotenv()

uri = os.getenv("MONGO_URI")

try:
    client = MongoClient(uri, tlsCAFile=certifi.where())
    print(client.admin.command("ping"))
    print("Connected!")
except Exception as e:
    print(type(e).__name__)
    print(e)