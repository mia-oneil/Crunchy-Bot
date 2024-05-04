import datetime
import random

import discord
from bot_util import BotUtil
from datalayer.database import Database
from datalayer.prediction import Prediction
from discord.ext import commands
from events.bat_event import BatEvent
from events.beans_event import BeansEvent
from events.inventory_event import InventoryEvent
from events.jail_event import JailEvent
from events.prediction_event import PredictionEvent
from events.types import BeansEventType, JailEventType, PredictionEventType, UIEventType
from events.ui_event import UIEvent
from items.types import ItemType
from view.shop_response_view import ShopResponseData
from view.types import EmojiType

from control.controller import Controller
from control.event_manager import EventManager
from control.jail_manager import JailManager
from control.logger import BotLogger
from control.view.view_controller import ViewController


class ShopResponseViewController(ViewController):
        
    def __init__(
        self,
        bot: commands.Bot,
        logger: BotLogger,
        database: Database,
        controller: Controller,
    ):
        super().__init__(
            bot, logger, database, 
        )
        self.controller = controller
        self.event_manager: EventManager = controller.get_service(EventManager)
        self.jail_manager: JailManager = self.controller.get_service(JailManager)
        
    async def listen_for_ui_event(self, event: UIEvent):
        match event.type:
            case UIEventType.REACTION_SELECTED:
                interaction = event.payload[0]
                message = event.payload[1]
                await self.submit_reaction_selection(interaction, message, event.view_id)
            case UIEventType.SHOP_RESPONSE_CONFIRM_SUBMIT:
                interaction = event.payload[0]
                shop_data = event.payload[1]
                await self.submit_confirm_view(interaction, shop_data, event.view_id)
            case UIEventType.SHOP_RESPONSE_USER_SUBMIT:
                interaction = event.payload[0]
                shop_data = event.payload[1]
                await self.submit_user_view(interaction, shop_data, event.view_id)
            case UIEventType.SHOP_RESPONSE_COLOR_SUBMIT | UIEventType.SHOP_RESPONSE_REACTION_SUBMIT:
                interaction = event.payload[0]
                shop_data = event.payload[1]
                await self.submit_generic_view(interaction, shop_data, event.view_id)
            case UIEventType.SHOP_RESPONSE_PREDICTION_SUBMIT:
                await self.submit_prediction(event.payload)
                
    async def start_transaction(self, interaction: discord.Interaction, shop_data: ShopResponseData) -> bool:
        
        guild_id = interaction.guild_id
        member_id = interaction.user.id
        
        if shop_data.item is not None:
            user_balance = self.database.get_member_beans(guild_id, member_id)
            
            amount = shop_data.selected_amount
            cost = shop_data.item.cost * amount
            
            if user_balance < cost:
                await interaction.followup.send('You dont have enough beans to buy that.', ephemeral=True)
                return False
        
        if shop_data.selected_user is not None and shop_data.selected_user.bot:
            await interaction.followup.send("You cannot select bot users.", ephemeral=True)
            return False

        if shop_data.user_select is not None and shop_data.selected_user is None:
            await interaction.followup.send('Please select a user first.', ephemeral=True)
            return False
        
        if shop_data.reaction_input_button is not None and shop_data.selected_emoji is None:
            await interaction.followup.send('Please select a reaction emoji first.', ephemeral=True)
            return False
        
        if shop_data.color_input_button is not None and shop_data.selected_color is None:
            await interaction.followup.send('Please select a color first.', ephemeral=True)
            return False
        
        return True
    
    async def finish_transaction(self, interaction: discord.Interaction, shop_data: ShopResponseData, view_id: int):
        amount = shop_data.selected_amount
        cost = shop_data.item.cost * amount
        guild_id = interaction.guild_id
        member_id = interaction.user.id
        
        log_message = f'{interaction.user.display_name} bought {amount} {shop_data.item.name} for {cost} beans.'
        
        arguments = []
        
        if shop_data.selected_user is not None:
            arguments.append(f'selected_user: {shop_data.selected_user.display_name}')
        
        if shop_data.selected_color is not None:
            arguments.append(f'selected_color: {shop_data.selected_color}')
            
        if shop_data.selected_emoji is not None:
            arguments.append(f'selected_emoji: {str(shop_data.selected_emoji)}')
        
        if len(arguments) > 0:
            log_message += ' arguments[' + ', '.join(arguments) + ']'
        
        self.logger.log(interaction.guild_id, log_message, cog='Shop')
        
        new_user_balance = self.database.get_member_beans(guild_id, member_id)
        success_message = f'You successfully bought {amount} **{shop_data.item.name}** for `🅱️{cost}` beans.\n Remaining balance: `🅱️{new_user_balance}`'
        
        await interaction.followup.send(success_message, ephemeral=True)
        
        user_items = self.database.get_item_counts_by_user(guild_id, member_id)
        event = UIEvent(
            UIEventType.SHOP_REFRESH, (new_user_balance, user_items), view_id
        )
        await self.controller.dispatch_ui_event(event)
        
        message = await interaction.original_response()
        await message.delete()
    
    async def submit_reaction_selection(self, interaction: discord.Interaction, message: discord.Message, view_id: int):
        await interaction.response.defer()
        
        user_emoji = None
        emoji_type = None
        
        message = await interaction.channel.fetch_message(message.id)
        
        for reaction in message.reactions:
            reactors = [user async for user in reaction.users()]
            if interaction.user in reactors:
                if user_emoji is not None:
                    await interaction.followup.send('Please react with a single emoji.', ephemeral=True)
                    return
                
                user_emoji = reaction.emoji
                emoji_type = EmojiType.CUSTOM if reaction.is_custom_emoji() else EmojiType.DEFAULT
        
        if user_emoji is None:
            await interaction.followup.send('Please react with any emoji.', ephemeral=True)
            return
        
        if emoji_type == EmojiType.CUSTOM:
            emoji_obj = discord.utils.get(self.bot.emojis, name=user_emoji.name)
            if emoji_obj is None:                      
                await interaction.followup.send('I do not have access to this emoji. I can only see the emojis of the servers i am a member of.', ephemeral=True)
                return
        
        event = UIEvent( UIEventType.SHOP_RESPONSE_EMOJI_UPDATE, (user_emoji, emoji_type), view_id)
        await self.controller.dispatch_ui_event(event)
        
        await interaction.followup.delete_message(message.id)
    
    async def submit_confirm_view(self, interaction: discord.Interaction, shop_data: ShopResponseData, view_id: int):
        if not await self.start_transaction(interaction, shop_data):
            return
        
        match shop_data.type:
            case ItemType.BAILOUT:
                await self.jail_interaction(interaction, shop_data, view_id)
            case ItemType.JAIL_REDUCTION:
                await self.jail_interaction(interaction, shop_data, view_id)
            case ItemType.EXPLOSIVE_FART:
                await self.random_jailing(interaction, shop_data, view_id)
    
    async def submit_user_view(self, interaction: discord.Interaction, shop_data: ShopResponseData, view_id: int):
        if not await self.start_transaction(interaction, shop_data):
            return
        
        match shop_data.type:
            case ItemType.ARREST:
                await self.jail_interaction(interaction, shop_data, view_id)
            case ItemType.RELEASE:
                await self.jail_interaction(interaction, shop_data, view_id)
            case ItemType.ROULETTE_FART:
                await self.jail_interaction(interaction, shop_data, view_id)
            case ItemType.BAT:
                await self.bat_attack(interaction, shop_data, view_id)
    
    async def jail_interaction(self, interaction: discord.Interaction, shop_data: ShopResponseData, view_id: int):
        guild_id = interaction.guild_id
        member_id = interaction.user.id
        amount = shop_data.selected_amount
        cost = shop_data.item.cost * amount

        match shop_data.item.type:
            case ItemType.ARREST:
                duration = 30
                success = await self.jail_manager.jail_user(guild_id, member_id, shop_data.selected_user, duration)
                
                if not success:
                    await interaction.followup.send(f'User {shop_data.selected_user.display_name} is already in jail.', ephemeral=True)
                    return
                
                timestamp_now = int(datetime.datetime.now().timestamp())
                release = timestamp_now + (duration*60)
                jail_announcement = f'<@{shop_data.selected_user.id}> was sentenced to Jail by <@{member_id}> using a **{shop_data.item.name}**. They will be released <t:{release}:R>.'
                
            case ItemType.RELEASE:
                affected_jails = self.database.get_active_jails_by_member(guild_id, member_id)
                if len(affected_jails) > 0:
                    await interaction.followup.send('You cannot use this while you are in jail.', ephemeral=True)
                    return
                
                if shop_data.selected_user.id == interaction.user.id:
                    await interaction.followup.send('You cannot free yourself using this item.', ephemeral=True)
                    return
                
                response = await self.jail_manager.release_user(guild_id, member_id, shop_data.selected_user)

                if not response:
                    await interaction.followup.send(f'User {shop_data.selected_user.display_name} is currently not in jail.', ephemeral=True)
                    return
                
                jail_announcement = f'<@{shop_data.selected_user.id}> was generously released from Jail by <@{interaction.user.id}> using a **{shop_data.item.name}**. ' + response
                
            case ItemType.ROULETTE_FART:
                duration = 30
                
                member = interaction.user
                selected = shop_data.selected_user
                
                timestamp_now = int(datetime.datetime.now().timestamp())
                release = timestamp_now + (duration*60)
                target = selected
                jail_announcement = f'<@{selected.id}> was sentenced to Jail by <@{member_id}> using a **{shop_data.item.name}**. They will be released <t:{release}:R>.'
                
                if random.choice([True, False]):
                    jail_announcement = f'<@{member_id}> shit themselves in an attempt to jail <@{selected.id}> using a **{shop_data.item.name}**, going to jail in their place. They will be released <t:{release}:R>.'
                    target = member
                
                success = await self.jail_manager.jail_user(guild_id, member_id, target, duration)
                
                if not success:
                    await interaction.followup.send(f'User {shop_data.selected_user.display_name} is already in jail.', ephemeral=True)
                    return
            case ItemType.BAILOUT:
                response = await self.jail_manager.release_user(guild_id, member_id, interaction.user)
        
                if not response:
                    await interaction.followup.send('You are currently not in jail.', ephemeral=True)
                    return
                
                jail_announcement = f'<@{member_id}> was released from Jail by bribing the mods with beans. ' + response
            case ItemType.JAIL_REDUCTION:
                
                affected_jails = self.database.get_active_jails_by_member(guild_id, member_id)
                
                if len(affected_jails) == 0:
                    await interaction.followup.send('You are currently not in jail.', ephemeral=True)
                    return
                    
                jail = affected_jails[0]
                
                remaining = int(self.jail_manager.get_jail_remaining(jail))
                
                total_value = shop_data.item.value * amount
                
                if remaining - total_value <= 0:
                    await interaction.followup.send('You cannot reduce your jail sentence by this much.', ephemeral=True)
                    return
                
                if remaining - total_value <= 30:
                    total_value -= (30 - (remaining - total_value))
                    
                event = JailEvent(datetime.datetime.now(), guild_id, JailEventType.REDUCE, member_id, -total_value, jail.id)
                await self.controller.dispatch_event(event)
                
                jail_announcement = f'<@{member_id}> reduced their own sentence by `{total_value}` minutes by spending `🅱️{cost}` beans.'
                new_remaining = self.jail_manager.get_jail_remaining(jail)
                jail_announcement += f'\n `{BotUtil.strfdelta(new_remaining, inputtype='minutes')}` still remain.'
                
            case _:
                await interaction.followup.send('Something went wrong, please contact a staff member.', ephemeral=True)
                return
        
        event = BeansEvent(datetime.datetime.now(), guild_id, BeansEventType.SHOP_PURCHASE, member_id, -cost)
        await self.controller.dispatch_event(event)
        
        await self.jail_manager.announce(interaction.guild, jail_announcement)
        await self.finish_transaction(interaction, shop_data, view_id)
       
    async def bat_attack(self, interaction: discord.Interaction, shop_data: ShopResponseData, view_id: int):
        guild_id = interaction.guild_id
        member_id = interaction.user.id
        target = shop_data.selected_user
        last_bat_event = self.database.get_last_bat_event_by_target(guild_id, target.id)
        
        last_bat_time = datetime.datetime.min
        if last_bat_event is not None:
            last_bat_time = last_bat_event.datetime
        
        diff = datetime.datetime.now() - last_bat_time
        if int(diff.total_seconds()/60) <= shop_data.item.value:
            await interaction.followup.send("Targeted user is already stunned by a previous bat attack.", ephemeral=True)
            return
        
        event = BatEvent(datetime.datetime.now(), guild_id, member_id, target.id, shop_data.item.value)
        await self.controller.dispatch_event(event)
        
        amount = shop_data.selected_amount
        cost = shop_data.item.cost * amount
        
        event = BeansEvent(datetime.datetime.now(), guild_id, BeansEventType.SHOP_PURCHASE, member_id, -cost)
        await self.controller.dispatch_event(event)
        
        await self.finish_transaction(interaction, shop_data, view_id)
        
    async def random_jailing(self, interaction: discord.Interaction, shop_data: ShopResponseData, view_id: int):
        guild_id = interaction.guild_id
        member_id = interaction.user.id
        amount = shop_data.selected_amount
        cost = shop_data.item.cost * amount
        
        bean_data = self.database.get_guild_beans(guild_id)
        users = []
        
        for user_id, amount in bean_data.items():
            if amount >= 100:
                users.append(user_id)
        
        jails = self.database.get_active_jails_by_guild(guild_id)
        
        for jail in jails:
            jailed_member_id = jail.member_id
            if jailed_member_id in users:
                users.remove(jailed_member_id)
        
        victims = random.sample(users, min(5, len(users)))
        
        jail_announcement = f'After committing unspeakable atrocities, <@{member_id}> caused innocent bystanders to be banished into the abyss.'
        await self.jail_manager.announce(interaction.guild, jail_announcement)
        
        for victim in victims:
            duration = random.randint(5*60, 10*60)
            member = interaction.guild.get_member(victim)
            
            if member is None:
                continue
            
            success = await self.jail_manager.jail_user(guild_id, member_id, member, duration)

            if not success:
                continue
            
            timestamp_now = int(datetime.datetime.now().timestamp())
            release = timestamp_now + (duration*60)
            jail_announcement = f'<@{victim}> was sentenced to Jail. They will be released <t:{release}:R>.'
            await self.jail_manager.announce(interaction.guild, jail_announcement)
        
        event = BeansEvent(datetime.datetime.now(), guild_id, BeansEventType.SHOP_PURCHASE, member_id, -cost)
        await self.controller.dispatch_event(event)

        await self.finish_transaction(interaction, shop_data, view_id)

    async def submit_generic_view(self, interaction: discord.Interaction, shop_data: ShopResponseData, view_id: int):
        if not await self.start_transaction(interaction, shop_data):
            return
        
        guild_id = interaction.guild_id
        member_id = interaction.user.id
        amount = shop_data.selected_amount
        cost = shop_data.item.cost * amount

        event = BeansEvent(datetime.datetime.now(), guild_id, BeansEventType.SHOP_PURCHASE, member_id, -cost)
        await self.controller.dispatch_event(event)
        
        match shop_data.type:
            case ItemType.NAME_COLOR:
                self.database.log_custom_color(guild_id, member_id, shop_data.selected_color)
                event = InventoryEvent(datetime.datetime.now(), guild_id, member_id, shop_data.type, shop_data.item.base_amount*amount)
                await self.controller.dispatch_event(event)
            case ItemType.REACTION_SPAM:
                self.database.log_bully_react(guild_id, member_id, shop_data.selected_user.id, shop_data.selected_emoji_type, shop_data.selected_emoji)
                event = InventoryEvent(datetime.datetime.now(), guild_id, member_id, shop_data.type, shop_data.item.base_amount*amount)
                await self.controller.dispatch_event(event)
            case _:
                await interaction.followup.send('Something went wrong, please contact a staff member.', ephemeral=True)
                return
        
        await self.finish_transaction(interaction, shop_data, view_id)

    async def submit_prediction(self, prediction: Prediction):
        prediction_id = self.database.log_prediction(prediction)
        event = PredictionEvent(datetime.datetime.now(), prediction.guild_id, prediction_id, prediction.author_id, PredictionEventType.SUBMIT)
        await self.controller.dispatch_event(event)
