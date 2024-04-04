import datetime
import random
import discord

from CrunchyBot import CrunchyBot
from cogs.Jail import Jail
from events.BeansEventType import BeansEventType
from shop.Item import Item
from shop.ItemType import ItemType
from view.ShopResponseView import *

class ShopUserSelectView(ShopResponseView):
    
    def __init__(self, bot: CrunchyBot, interaction: discord.Interaction, parent, item: Item):
        super().__init__(bot, interaction, parent, item)
        
        self.user_select = UserPicker()
        self.confirm_button = ConfirmButton()
        self.cancel_button = CancelButton()
        
        self.refresh_elements()

    async def submit(self, interaction: discord.Interaction):
        if not await self.start_transaction(interaction):
            return
        
        match self.type:
            case ItemType.ARREST:
                await self.jail_interaction(interaction)
            case ItemType.RELEASE:
                await self.jail_interaction(interaction)
            case ItemType.ROULETTE_FART:
                await self.jail_interaction(interaction)
            case ItemType.BAT:
                await self.bat_attack(interaction)
    
    async def bat_attack(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        member_id = interaction.user.id
        target = self.selected_user
        last_bat_event = self.database.get_last_bat_event_by_target(guild_id, target.id)
        
        last_bat_time = datetime.datetime.min
        if last_bat_event is not None:
            last_bat_time = last_bat_event.get_datetime()
        
        diff = datetime.datetime.now() - last_bat_time
        if int(diff.total_seconds()/60) <= self.item.get_value():
            await interaction.followup.send(f"Targeted user is already stunned by a previous bat attack.", ephemeral=True)
            return
        
        self.event_manager.dispatch_bat_event(datetime.datetime.now(), guild_id, member_id, target.id)
        
        amount = self.selected_amount
        cost = self.item.get_cost() * amount
        
        self.event_manager.dispatch_beans_event(
            datetime.datetime.now(), 
            guild_id,
            BeansEventType.SHOP_PURCHASE, 
            member_id,
            -cost
        )
        
        await self.finish_transaction(interaction)
    
    async def jail_interaction(self, interaction: discord.Interaction):
        if self.selected_user.id == interaction.user.id and self.type == ItemType.RELEASE:
            await interaction.followup.send('You cannot free yourself using this item.', ephemeral=True)
            return
        
        guild_id = interaction.guild_id
        member_id = interaction.user.id

        jail_cog: Jail = self.bot.get_cog('Jail')
        match self.type:
            case ItemType.ARREST:
                duration = 30
                success = await jail_cog.jail_user(guild_id, member_id, self.selected_user, duration)
                
                if not success:
                    await interaction.followup.send(f'User {self.selected_user.display_name} is already in jail.', ephemeral=True)
                    return
                
                timestamp_now = int(datetime.datetime.now().timestamp())
                release = timestamp_now + (duration*60)
                jail_announcement = f'<@{self.selected_user.id}> was sentenced to Jail by <@{member_id}> using a **{self.item.get_name()}**. They will be released <t:{release}:R>.'
                
            case ItemType.RELEASE:
                response = await jail_cog.release_user(guild_id, member_id, self.selected_user)

                if not response:
                    await interaction.followup.send(f'User {self.selected_user.display_name} is currently not in jail.', ephemeral=True)
                    return
                
                jail_announcement = f'<@{self.selected_user.id}> was generously released from Jail by <@{interaction.user.id}> using a **{self.item.get_name()}**. ' + response
                
            case ItemType.ROULETTE_FART:
                duration = 30
                
                member = interaction.user
                selected = self.selected_user
                
                timestamp_now = int(datetime.datetime.now().timestamp())
                release = timestamp_now + (duration*60)
                target = selected
                jail_announcement = f'<@{selected.id}> was sentenced to Jail by <@{member_id}> using a **{self.item.get_name()}**. They will be released <t:{release}:R>.'
                
                if random.choice([True, False]):
                    jail_announcement = f'<@{member_id}> shit themselves in an attempt to jail <@{selected.id}> using a **{self.item.get_name()}**, going to jail in their place. They will be released <t:{release}:R>.'
                    target = member
                
                success = await jail_cog.jail_user(guild_id, member_id, target, duration)
                
                if not success:
                    await interaction.followup.send(f'User {self.selected_user.display_name} is already in jail.', ephemeral=True)
                    return
                
            case _:
                await interaction.followup.send(f'Something went wrong, please contact a staff member.', ephemeral=True)
                return
        
        amount = self.selected_amount
        cost = self.item.get_cost() * amount
        
        self.event_manager.dispatch_beans_event(
            datetime.datetime.now(), 
            guild_id,
            BeansEventType.SHOP_PURCHASE, 
            member_id,
            -cost
        )
        
        await jail_cog.announce(interaction.guild, jail_announcement)
        await self.finish_transaction(interaction)
