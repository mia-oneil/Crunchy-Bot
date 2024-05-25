import datetime

import discord
from combat.gear.gear import Gear
from combat.gear.types import GearSlot
from datalayer.database import Database
from discord.ext import commands
from events.bot_event import BotEvent
from events.inventory_event import InventoryEvent
from events.types import EventType, UIEventType
from events.ui_event import UIEvent
from items.types import ItemType
from view.combat.embed import EquipmentHeadEmbed, SelectGearHeadEmbed
from view.combat.equipment_select_view import EquipmentSelectView
from view.combat.equipment_view import EquipmentView

from control.combat.combat_actor_manager import CombatActorManager
from control.combat.combat_embed_manager import CombatEmbedManager
from control.combat.combat_gear_manager import CombatGearManager
from control.combat.encounter_manager import EncounterManager
from control.controller import Controller
from control.event_manager import EventManager
from control.logger import BotLogger
from control.view.view_controller import ViewController


class EquipmentViewController(ViewController):

    def __init__(
        self,
        bot: commands.Bot,
        logger: BotLogger,
        database: Database,
        controller: Controller,
    ):
        super().__init__(bot, logger, database)
        self.controller = controller
        self.event_manager: EventManager = controller.get_service(EventManager)
        self.actor_manager: CombatActorManager = controller.get_service(
            CombatActorManager
        )
        self.encounter_manager: EncounterManager = controller.get_service(
            EncounterManager
        )
        self.embed_manager: CombatEmbedManager = controller.get_service(
            CombatEmbedManager
        )
        self.gear_manager: CombatGearManager = self.controller.get_service(
            CombatGearManager
        )

    async def listen_for_event(self, event: BotEvent) -> None:
        member_id = None
        guild_id = None
        match event.type:
            case EventType.INVENTORY:
                event: InventoryEvent = event
                guild_id = event.guild_id
                member_id = event.member_id

        if (
            member_id is not None
            and guild_id is not None
            and event.item_type == ItemType.SCRAP
        ):
            user_items = await self.database.get_item_counts_by_user(
                guild_id, member_id, item_types=[ItemType.SCRAP]
            )
            scrap_balance = 0
            if ItemType.SCRAP in user_items:
                scrap_balance = user_items[ItemType.SCRAP]

            event = UIEvent(
                UIEventType.SCRAP_BALANCE_CHANGED, (guild_id, member_id, scrap_balance)
            )
            await self.controller.dispatch_ui_event(event)

    async def listen_for_ui_event(self, event: UIEvent):
        match event.type:
            case UIEventType.GEAR_OPEN_SECELT:
                interaction = event.payload[0]
                slot = event.payload[1]
                await self.open_gear_select(interaction, slot, event.view_id)
            case UIEventType.GEAR_OPEN_OVERVIEW:
                interaction = event.payload
                await self.open_gear_overview(interaction, event.view_id)
            case UIEventType.GEAR_EQUIP:
                interaction = event.payload[0]
                selected = event.payload[1]
                await self.equip_gear(interaction, selected, event.view_id)
            case UIEventType.GEAR_DISMANTLE:
                interaction = event.payload[0]
                selected = event.payload[1]
                await self.dismantle_gear(interaction, selected, event.view_id)

    async def open_gear_select(
        self, interaction: discord.Interaction, slot: GearSlot, view_id: int
    ):
        guild_id = interaction.guild.id
        member_id = interaction.user.id

        encounters = await self.database.get_active_encounter_participants(guild_id)

        for _, participants in encounters.items():
            if member_id in participants:
                await interaction.followup.send(
                    "You cannot change your gear while you are involved in an active combat.",
                    ephemeral=True,
                )
                return

        gear_inventory = await self.database.get_user_armory(guild_id, member_id)
        default_gear = await self.gear_manager.get_default_gear()
        gear_inventory.extend(default_gear)

        currently_equipped = await self.database.get_user_equipment_slot(
            guild_id, member_id, slot
        )

        user_items = await self.database.get_item_counts_by_user(
            guild_id, member_id, item_types=[ItemType.SCRAP]
        )
        scrap_balance = 0
        if ItemType.SCRAP in user_items:
            scrap_balance = user_items[ItemType.SCRAP]

        view = EquipmentSelectView(
            self.controller,
            interaction,
            gear_inventory,
            currently_equipped,
            scrap_balance,
            slot,
        )

        embeds = []
        embeds.append(SelectGearHeadEmbed(interaction.user))

        loading_embed = discord.Embed(
            title="Loadin Gear", color=discord.Colour.light_grey()
        )
        self.embed_manager.add_text_bar(loading_embed, "", "Please Wait...")
        loading_embed.set_thumbnail(url=self.bot.user.display_avatar)
        embeds.append(loading_embed)

        message = await interaction.original_response()
        await message.edit(embeds=embeds, view=view, attachments=[])
        view.set_message(message)
        await view.refresh_ui()
        self.controller.detach_view_by_id(view_id)

    async def open_gear_overview(self, interaction: discord.Interaction, view_id: int):
        guild_id = interaction.guild_id
        member_id = interaction.user.id

        character = await self.actor_manager.get_character(interaction.user)

        user_items = await self.database.get_item_counts_by_user(
            guild_id, member_id, item_types=[ItemType.SCRAP]
        )
        scrap_balance = 0
        if ItemType.SCRAP in user_items:
            scrap_balance = user_items[ItemType.SCRAP]

        view = EquipmentView(self.controller, interaction, character, scrap_balance)

        embeds = []
        embeds.append(EquipmentHeadEmbed(interaction.user))

        loading_embed = discord.Embed(
            title="Loadin Gear", color=discord.Colour.light_grey()
        )
        self.embed_manager.add_text_bar(loading_embed, "", "Please Wait...")
        loading_embed.set_thumbnail(url=self.bot.user.display_avatar)
        embeds.append(loading_embed)

        message = await interaction.original_response()
        await message.edit(embeds=embeds, view=view, attachments=[])
        view.set_message(message)
        await view.refresh_ui()
        self.controller.detach_view_by_id(view_id)

    async def equip_gear(
        self, interaction: discord.Interaction, selected: list[Gear], view_id: int
    ):
        guild_id = interaction.guild_id
        member_id = interaction.user.id

        if selected is None or len(selected) <= 0:
            return

        if len(selected) > 2:
            return

        if len(selected) == 1:
            await self.database.update_user_equipment(guild_id, member_id, selected[0])
            if selected[0].base.slot == GearSlot.ACCESSORY:
                await self.database.update_user_equipment(
                    guild_id, member_id, None, acc_slot_2=True
                )

        if len(selected) == 2:
            # Accessory
            await self.database.update_user_equipment(guild_id, member_id, selected[0])
            await self.database.update_user_equipment(
                guild_id, member_id, selected[1], acc_slot_2=True
            )

        await self.open_gear_overview(interaction, view_id)

    async def dismantle_gear(
        self, interaction: discord.Interaction, selected: list[Gear], view_id: int
    ):
        guild_id = interaction.guild_id
        member_id = interaction.user.id

        now = datetime.datetime.now()
        gear_slot = None

        for gear in selected:
            if gear_slot is None:
                gear_slot = gear.base.slot
            gear_score = await self.gear_manager.get_gear_score(gear)

            event = InventoryEvent(
                now,
                guild_id,
                member_id,
                ItemType.SCRAP,
                gear_score,
            )
            await self.controller.dispatch_event(event)

            await self.database.delete_gear_by_id(gear.id)
            self.logger.log(
                guild_id,
                f"Gear piece was scrapped: lvl.{gear.level} {gear.rarity.value} {gear.name}",
                cog="Equipment",
            )

        if gear_slot is None:
            await self.open_gear_overview(interaction, view_id)
            return

        await self.open_gear_select(interaction, gear_slot, view_id)
