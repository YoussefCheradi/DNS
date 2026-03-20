import os
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("SERPER_API_KEY")
print(f"Clé : {key}")