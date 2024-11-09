import os
from dotenv import load_dotenv

load_dotenv()

AUTHORIZED_ROLE = os.getenv('AUTHORIZED_ROLE')
RANK_CHANNEL_NAME = os.getenv('RANK_CHANNEL_NAME')
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
