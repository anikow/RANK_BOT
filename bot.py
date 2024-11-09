import logging

import discord
from discord.ext import commands

from cogs.rank_cog import RankCog
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Intents setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = False

class MyBot(commands.Bot):
    """Custom Discord bot class with setup hook for adding cogs and syncing commands."""
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
    
    async def setup_hook(self):
        await self.add_cog(RankCog(self))
        await self.tree.sync()
        logger.info("Application commands have been synced.")

def main():
    bot = MyBot()
    bot.run(config.DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    main()
