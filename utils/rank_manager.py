import json
import os
import re
import asyncio
import logging
from typing import Optional, Dict, List

import discord

import config

logger = logging.getLogger(__name__)

class RankManager:
    """Manages user ranks, including loading, saving, parsing, and enforcing ranks."""

    def __init__(self):
        self.user_ranks: Dict[str, int] = {}
        self.rank_message_id: Optional[int] = None
        self.lock = asyncio.Lock()
        self.DATA_FILE = os.path.join(os.path.dirname(__file__), '../data/ranks.json')
        self.load_ranks_from_file()

    def load_ranks_from_file(self):
        """Load user ranks and rank message ID from 'ranks.json' file if it exists."""
        if os.path.exists(self.DATA_FILE):
            try:
                with open(self.DATA_FILE, 'r') as f:
                    data = json.load(f)
                    self.user_ranks = data.get('user_ranks', {})
                    self.rank_message_id = data.get('rank_message_id')
                    logger.info("Loaded ranks and rank message ID from 'ranks.json'")
            except Exception as e:
                logger.exception("Failed to load ranks from 'ranks.json'")
        else:
            logger.info("'ranks.json' not found. Starting with empty ranks.")

    def save_ranks_to_file(self):
        """Save user ranks and rank message ID to 'ranks.json' file."""
        data = {
            'user_ranks': self.user_ranks,
            'rank_message_id': self.rank_message_id
        }
        try:
            os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
            with open(self.DATA_FILE, 'w') as f:
                json.dump(data, f, indent=4)
                logger.info("Saved ranks and rank message ID to 'ranks.json'")
        except Exception as e:
            logger.exception("Failed to save ranks to 'ranks.json'")

    @staticmethod
    def parse_rank(nickname: Optional[str]) -> Optional[int]:
        """
        Extracts the rank number from a nickname if it ends with '#<number>'.
        Returns the rank as an integer, or None if not found.
        """
        if nickname:
            match = re.search(r'#\s*(\d+)$', nickname)
            if match:
                rank = int(match.group(1))
                logger.debug(f"Parsed rank {rank} from nickname '{nickname}'")
                return rank
        return None

    async def load_ranks_from_nicknames(self, guild: discord.Guild, members: List[discord.Member]):
        """
        Loads ranks from guild members' nicknames and updates the user ranks accordingly.
        Saves the ranks to the file after loading.
        """
        logger.info("Loading ranks from nicknames...")
        for member in members:
            nickname = member.nick
            if nickname is None:
                continue  # Skip members without a nickname
            rank = self.parse_rank(nickname)
            if rank is not None:
                self.user_ranks[str(member.id)] = rank
                logger.debug(f"Loaded rank {rank} for member {member.display_name}")
            else:
                logger.debug(f"No rank found in nickname for member {member.display_name}")
        self.save_ranks_to_file()

    async def enforce_ranks_on_discord(self, guild: discord.Guild, members: List[discord.Member]):
        """
        Updates Discord members' nicknames to match the ranks stored in user_ranks.
        Ensures that each member's nickname correctly reflects their assigned rank.
        """
        logger.info("Enforcing ranks on Discord nicknames...")
        for member in members:
            user_id_str = str(member.id)
            expected_rank = self.user_ranks.get(user_id_str)
            current_rank_in_nickname = self.parse_rank(member.nick)

            if expected_rank is not None:
                # Member is expected to have a rank
                if current_rank_in_nickname != expected_rank:
                    logger.info(f"Updating rank for member {member.display_name} to {expected_rank}")
                    await self.update_nickname(member, expected_rank)
                else:
                    logger.debug(f"Member {member.display_name} already has correct rank {expected_rank}")
            else:
                # Member should not have a rank; remove any rank from nickname
                if current_rank_in_nickname is not None:
                    logger.info(f"Removing rank from member {member.display_name} as they are not in user_ranks")
                    await self.update_nickname(member, None)
                else:
                    logger.debug(f"Member {member.display_name} has no rank and is correct")

    async def update_nickname(self, member: discord.Member, new_rank: Optional[int]):
        """
        Updates a member's nickname to include the new rank, or removes the rank if new_rank is None.
        """
        # Extract the base nickname without rank
        if member.nick is not None:
            name_without_rank = re.sub(r'#\s*\d+$', '', member.nick).strip()
        else:
            name_without_rank = member.name

        # Decide the new nickname
        if new_rank is not None:
            new_nickname = f"{name_without_rank} #{new_rank}"
        else:
            new_nickname = name_without_rank

        # If the new nickname is the same as the username, set nick to None to remove nickname
        if new_nickname == member.name:
            new_nickname = None

        try:
            if member.guild.me.guild_permissions.manage_nicknames:
                await member.edit(nick=new_nickname)
                logger.info(f"Updated nickname for {member.display_name} to '{new_nickname}'")
            else:
                logger.warning(f"Cannot change nickname for {member.display_name}: Missing 'Manage Nicknames' permission.")
        except discord.Forbidden:
            logger.warning(f"Permission denied to change nickname for {member.display_name}.")
        except Exception as e:
            logger.exception(f"An error occurred while changing nickname for {member.display_name}")
        finally:
            # Save the ranks after attempting to update the nickname
            self.save_ranks_to_file()

    async def adjust_ranks(self, guild: discord.Guild, target_member_id: int, old_rank: Optional[int], new_rank: int):
        logger.info(f"Adjusting ranks in guild: {guild.name}")

        async with self.lock:
            user_id_str = str(target_member_id)

            # Remove old rank if any
            if old_rank is not None:
                self.user_ranks.pop(user_id_str, None)

            affected_user_ids = set()

            # Adjust ranks of other users
            if old_rank is not None:
                if new_rank < old_rank:
                    # Moving up: increment ranks between new_rank and old_rank -1
                    for uid in self.user_ranks:
                        rank = self.user_ranks[uid]
                        if new_rank <= rank < old_rank:
                            self.user_ranks[uid] += 1
                            affected_user_ids.add(uid)
                elif new_rank > old_rank:
                    # Moving down: decrement ranks between old_rank +1 and new_rank
                    for uid in self.user_ranks:
                        rank = self.user_ranks[uid]
                        if old_rank < rank <= new_rank:
                            self.user_ranks[uid] -= 1
                            affected_user_ids.add(uid)
                # Else, new_rank == old_rank, do nothing
            else:
                # Member didn't have an old rank
                # Need to increment ranks of members with rank >= new_rank
                for uid in self.user_ranks:
                    rank = self.user_ranks[uid]
                    if rank >= new_rank:
                        self.user_ranks[uid] += 1
                        affected_user_ids.add(uid)

            # Assign new rank to target member
            self.user_ranks[user_id_str] = new_rank
            affected_user_ids.add(user_id_str)

            # Update nicknames of affected members
            for uid in affected_user_ids:
                member_id = int(uid)
                member = guild.get_member(member_id)
                if member is None:
                    try:
                        member = await guild.fetch_member(member_id)
                    except discord.NotFound:
                        logger.warning(f"Member with ID {member_id} not found.")
                        continue
                rank = self.user_ranks[uid]
                await self.update_nickname(member, rank)
                logger.info(f"Updated nickname for {member.display_name} to include rank {rank}")

            self.save_ranks_to_file()

            # Update the rank list message in the designated channel
            await self.update_rank_message(guild)

    async def fill_rank_gaps(self, guild: discord.Guild):
        """
        Reassigns ranks to ensure they are sequential and start from 1, filling any gaps.
        Updates members' nicknames accordingly and saves the ranks to the file.
        """
        logger.info("Filling rank gaps to ensure sequential ranks...")
        # Get all user IDs and their ranks
        rank_items = list(self.user_ranks.items())
        # Sort the items by rank
        rank_items.sort(key=lambda x: x[1])
        # Reassign ranks starting from 1
        new_user_ranks = {}
        for i, (user_id_str, _) in enumerate(rank_items, start=1):
            new_user_ranks[user_id_str] = i

        # Update nicknames if ranks have changed
        for user_id_str, new_rank in new_user_ranks.items():
            old_rank = self.user_ranks.get(user_id_str)
            if old_rank != new_rank:
                member_id = int(user_id_str)
                member = guild.get_member(member_id)
                if member is None:
                    try:
                        member = await guild.fetch_member(member_id)
                    except discord.NotFound:
                        logger.warning(f"Member with ID {member_id} not found.")
                        continue
                self.user_ranks[user_id_str] = new_rank
                await self.update_nickname(member, new_rank)
                logger.info(f"Adjusted rank of {member.display_name} from {old_rank} to {new_rank}")

        self.user_ranks = new_user_ranks
        self.save_ranks_to_file()

        # Update the rank list message in the designated channel
        await self.update_rank_message(guild)

    async def update_rank_message(self, guild: discord.Guild):
        """
        Creates or updates the rank list message in the specified channel, displaying all users with their ranks.
        """
        channel_name = config.RANK_CHANNEL_NAME
        channel = discord.utils.get(guild.text_channels, name=channel_name)

        if channel is None:
            # Create the channel if it doesn't exist
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False)
                }
                channel = await guild.create_text_channel(channel_name, overwrites=overwrites)
                logger.info(f"Created channel '{channel_name}' in guild '{guild.name}'")
            except Exception as e:
                logger.exception(f"Failed to create channel '{channel_name}'")
                return

        # Generate the rank list content
        if not self.user_ranks:
            rank_list = "No ranks available."
        else:
            sorted_ranks = sorted(self.user_ranks.items(), key=lambda x: x[1])
            rank_lines = []
            for user_id, rank in sorted_ranks:
                try:
                    member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
                    nickname = member.nick if member.nick else member.name
                    rank_lines.append(f"Rank {rank}: {nickname}")
                except discord.NotFound:
                    rank_lines.append(f"Rank {rank}: User with ID {user_id} not found in guild")
            rank_list = "\n".join(rank_lines)

        # If a message ID is stored, try to fetch and edit the message
        if self.rank_message_id:
            try:
                message = await channel.fetch_message(self.rank_message_id)
                await message.edit(content=f"```\n{rank_list}\n```")
                logger.info(f"Updated rank list message in channel '{channel_name}'")
            except discord.NotFound:
                # Message not found; send a new one
                message = await channel.send(f"```\n{rank_list}\n```")
                self.rank_message_id = message.id
                self.save_ranks_to_file()
                logger.info(f"Sent new rank list message in channel '{channel_name}'")
            except Exception as e:
                logger.exception("Failed to update rank list message")
        else:
            # No message ID stored; send a new message
            try:
                message = await channel.send(f"```\n{rank_list}\n```")
                self.rank_message_id = message.id
                self.save_ranks_to_file()
                logger.info(f"Sent new rank list message in channel '{channel_name}'")
            except Exception as e:
                logger.exception("Failed to send rank list message")
