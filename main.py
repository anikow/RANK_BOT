import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

# Intents setup
intents = discord.Intents.default()
intents.members = True            # Required to access member information
intents.message_content = True    # Required to read message content

# Bot setup
bot = commands.Bot(command_prefix='!', intents=intents)

class RankManager:
    """Class to manage user ranks."""

    def __init__(self):
        # In-memory storage for user ranks: {user_id: rank}
        self.user_ranks = {}

    def load_ranks(self, members):
        """Load ranks from existing member nicknames."""
        for member in members:
            rank = self.parse_rank(member.display_name)
            if rank is not None:
                self.user_ranks[member.id] = rank

    @staticmethod
    def parse_rank(nickname):
        """Extract rank from a nickname."""
        if nickname and '#' in nickname:
            parts = nickname.rsplit('#', 1)
            if parts[1].isdigit():
                return int(parts[1])
        return None

    async def update_nickname(self, member, new_rank):
        """Update a member's nickname with the new rank."""
        name_without_rank = member.display_name.rsplit('#', 1)[0].strip()
        new_nickname = f"{name_without_rank} #{new_rank:02d}"
        try:
            await member.edit(nick=new_nickname)
        except discord.Forbidden:
            print(f"Permission denied to change nickname for {member.display_name}.")
        except Exception as e:
            print(f"An error occurred while changing nickname: {e}")

    async def adjust_ranks(self, guild, target_member_id, old_rank, new_rank):
        """Adjust ranks of other members based on the new rank assignment."""
        for member_id, rank in self.user_ranks.items():
            if member_id == target_member_id:
                continue

            member = guild.get_member(member_id)
            if member is None:
                continue  # Member might have left the guild

            if old_rank is not None:
                # If the rank is between old_rank and new_rank, adjust it
                if old_rank < new_rank and old_rank < rank <= new_rank:
                    self.user_ranks[member_id] = rank - 1
                    await self.update_nickname(member, rank - 1)
                elif new_rank <= rank < old_rank:
                    self.user_ranks[member_id] = rank + 1
                    await self.update_nickname(member, rank + 1)
            else:
                # No old rank, so shift ranks greater than or equal to new_rank
                if rank >= new_rank:
                    self.user_ranks[member_id] = rank + 1
                    await self.update_nickname(member, rank + 1)

class RankCog(commands.Cog):
    """Cog for managing user ranks."""

    def __init__(self, bot):
        self.bot = bot
        self.rank_manager = RankManager()

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.bot.user.name} has connected to Discord!")
        for guild in self.bot.guilds:
            self.rank_manager.load_ranks(guild.members)
        print("User ranks have been initialized.")

    @commands.command()
    @commands.has_permissions(manage_nicknames=True)
    async def rank(self, ctx, member: discord.Member, new_rank: int):
        """
        Change a user's rank and adjust other users' ranks accordingly.
        Usage: /rank @user new_rank
        """
        if new_rank < 1:
            await ctx.send("🚫 Rank must be a positive integer.")
            return

        old_rank = self.rank_manager.user_ranks.get(member.id)
        self.rank_manager.user_ranks[member.id] = new_rank
        await self.rank_manager.update_nickname(member, new_rank)

        await self.rank_manager.adjust_ranks(
            ctx.guild, member.id, old_rank, new_rank
        )

        await ctx.send(f"✅ {member.mention}'s rank has been updated to {new_rank}.")

    @rank.error
    async def rank_error(self, ctx, error):
        """Handle errors for the rank command."""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("🚫 You do not have permission to change ranks.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("🚫 Invalid arguments. Usage: `/rank @user new_rank`")
        else:
            await ctx.send("🚫 An unexpected error occurred.")
            print(f"Error in rank command: {error}")

async def main():
    await bot.add_cog(RankCog(bot))
    await bot.start(os.getenv('DISCORD_BOT_TOKEN'))

asyncio.run(main())
