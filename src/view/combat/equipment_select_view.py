import contextlib

import discord
from combat.gear.gear import Gear
from combat.gear.types import EquipmentSlot, GearModifierType
from control.combat.combat_embed_manager import CombatEmbedManager
from control.controller import Controller
from control.types import ControllerType
from events.types import UIEventType
from events.ui_event import UIEvent
from view.combat.elements import (
    BackButton,
    CurrentPageButton,
    ImplementsBack,
    ImplementsLocking,
    ImplementsPages,
    ImplementsScrapping,
    LockButton,
    PageButton,
    ScrapBalanceButton,
    ScrapSelectedButton,
    UnlockButton,
)
from view.combat.embed import SelectGearHeadEmbed
from view.combat.equipment_view import EquipmentViewState, SelectGearSlot
from view.view_menu import ViewMenu


class EquipmentSelectView(
    ViewMenu, ImplementsPages, ImplementsBack, ImplementsLocking, ImplementsScrapping
):

    def __init__(
        self,
        controller: Controller,
        interaction: discord.Interaction,
        gear_inventory: list[Gear],
        currently_equipped: list[Gear],
        scrap_balance: int,
        slot: EquipmentSlot,
    ):
        super().__init__(timeout=300)
        self.controller = controller
        self.guild_name = interaction.guild.name
        self.member_id = interaction.user.id
        self.member = interaction.user
        self.guild_id = interaction.guild_id
        self.gear = gear_inventory
        self.current = currently_equipped
        self.scrap_balance = scrap_balance

        self.current_page = 0
        self.selected: list[Gear] = []

        self.filter = slot
        self.filtered_items = []
        self.display_items = []
        self.item_count = 0
        self.page_count = 1
        self.filter_items()
        self.message = None
        self.loaded = False

        self.controller_type = ControllerType.EQUIPMENT
        self.controller.register_view(self)
        self.refresh_elements()
        self.embed_manager: CombatEmbedManager = controller.get_service(
            CombatEmbedManager
        )

    async def listen_for_ui_event(self, event: UIEvent):
        match event.type:
            case UIEventType.SCRAP_BALANCE_CHANGED:
                guild_id = event.payload[0]
                member_id = event.payload[1]
                balance = event.payload[2]
                if member_id != self.member_id or guild_id != self.guild_id:
                    return
                await self.refresh_ui(scrap_balance=balance)
                return

        if event.view_id != self.id:
            return

    def filter_items(self):
        self.filtered_items = [
            gear for gear in self.gear if gear.base.slot == self.filter
        ]
        self.item_count = len(self.filtered_items)
        self.page_count = int(self.item_count / SelectGearHeadEmbed.ITEMS_PER_PAGE) + (
            self.item_count % SelectGearHeadEmbed.ITEMS_PER_PAGE > 0
        )
        self.page_count = max(self.page_count, 1)

        self.filtered_items = sorted(
            self.filtered_items,
            key=lambda x: (
                (x.id in [gear.id for gear in self.current]),
                # x.locked,
                x.level,
                Gear.RARITY_SORT_MAP[x.rarity],
            ),
            reverse=True,
        )

    async def flip_page(self, interaction: discord.Interaction, right: bool = False):
        await interaction.response.defer()
        self.current_page = (self.current_page + (1 if right else -1)) % self.page_count
        self.selected = []
        await self.refresh_ui()

    async def select_gear(self, interaction: discord.Interaction):
        await interaction.response.defer()
        event = UIEvent(
            UIEventType.GEAR_EQUIP,
            (interaction, self.selected),
            self.id,
        )
        await self.controller.dispatch_ui_event(event)

    async def scrap_selected(
        self, interaction: discord.Interaction, scrap_all: bool = False
    ):
        await interaction.response.defer()

        scrappable = [item for item in self.selected if not item.locked]

        event = UIEvent(
            UIEventType.GEAR_DISMANTLE,
            (interaction, scrappable, scrap_all, self.filter),
            self.id,
        )
        await self.controller.dispatch_ui_event(event)

    async def lock_selected(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer()
        event = UIEvent(
            UIEventType.GEAR_LOCK,
            (interaction, self.selected),
            self.id,
        )
        await self.controller.dispatch_ui_event(event)

    async def unlock_selected(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer()
        items = [
            item
            for item in self.selected
            if item.id not in [item.id for item in self.current]
        ]
        event = UIEvent(
            UIEventType.GEAR_UNLOCK,
            (interaction, items),
            self.id,
        )
        await self.controller.dispatch_ui_event(event)

    async def go_back(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer()
        event = UIEvent(
            UIEventType.GEAR_OPEN_OVERVIEW,
            (interaction, EquipmentViewState.GEAR),
            self.id,
        )
        await self.controller.dispatch_ui_event(event)

    async def change_gear(self, interaction: discord.Interaction, slot: EquipmentSlot):
        await interaction.response.defer()
        event = UIEvent(
            UIEventType.GEAR_OPEN_SECELT,
            (interaction, slot),
            self.id,
        )
        await self.controller.dispatch_ui_event(event)

    def refresh_elements(self, disabled: bool = False):
        page_display = f"Page {self.current_page + 1}/{self.page_count}"

        if not self.loaded:
            disabled = True

        max_values = 1
        if self.filter == EquipmentSlot.ACCESSORY:
            max_values = 2

        disable_equip = disabled
        if len(self.selected) > max_values:
            disable_equip = True

        disable_dismantle = disabled
        for selected_gear in self.selected:
            if selected_gear.id in [gear.id for gear in self.current]:
                disable_dismantle = True

            if selected_gear.id < 0:
                # Default Gear
                disable_dismantle = True

        equipped = [gear.id for gear in self.current if gear.base.slot == self.filter]

        self.clear_items()
        if len(self.display_items) > 0:
            self.add_item(
                Dropdown(self.display_items, self.selected, equipped, disabled=disabled)
            )
        self.add_item(PageButton("<", False, disabled=disabled))
        self.add_item(SelectButton(disabled=disable_equip))
        self.add_item(PageButton(">", True, disabled=disabled))
        self.add_item(CurrentPageButton(page_display))
        self.add_item(ScrapBalanceButton(self.scrap_balance))
        self.add_item(ScrapSelectedButton(disabled=disable_dismantle))
        self.add_item(LockButton(disabled=disabled))
        self.add_item(UnlockButton(disabled=disabled))
        self.add_item(BackButton(disabled=disabled))
        self.add_item(
            SelectGearSlot(
                EquipmentSlot.WEAPON,
                row=0,
                disabled=(self.filter == EquipmentSlot.WEAPON or disabled),
            )
        )
        self.add_item(
            SelectGearSlot(
                EquipmentSlot.HEAD,
                row=0,
                disabled=(self.filter == EquipmentSlot.HEAD or disabled),
            )
        )
        self.add_item(
            SelectGearSlot(
                EquipmentSlot.BODY,
                row=0,
                disabled=(self.filter == EquipmentSlot.BODY or disabled),
            )
        )
        self.add_item(
            SelectGearSlot(
                EquipmentSlot.LEGS,
                row=0,
                disabled=(self.filter == EquipmentSlot.LEGS or disabled),
            )
        )
        self.add_item(
            SelectGearSlot(
                EquipmentSlot.ACCESSORY,
                row=0,
                disabled=(self.filter == EquipmentSlot.ACCESSORY or disabled),
            )
        )

    async def refresh_ui(
        self,
        gear_inventory: list[Gear] = None,
        currently_equipped: list[Gear] = None,
        scrap_balance: int = None,
        disabled: bool = False,
    ):
        if self.message is None:
            return

        if scrap_balance is not None:
            self.scrap_balance = scrap_balance

        if gear_inventory is not None:
            self.gear = gear_inventory

        if currently_equipped is not None:
            self.current = currently_equipped

        if None not in [self.scrap_balance, self.gear, self.current]:
            self.loaded = True

        self.filter_items()
        self.current_page = min(self.current_page, (self.page_count - 1))

        start_offset = SelectGearHeadEmbed.ITEMS_PER_PAGE * self.current_page
        end_offset = min(
            (start_offset + SelectGearHeadEmbed.ITEMS_PER_PAGE),
            len(self.filtered_items),
        )
        self.display_items = self.filtered_items[start_offset:end_offset]

        self.selected = [
            item
            for item in self.display_items
            if item.id in [selected.id for selected in self.selected]
        ]

        self.refresh_elements(disabled)

        embeds = []
        files = {}
        embeds.append(SelectGearHeadEmbed(self.member))

        if len(self.display_items) <= 0:
            empty_embed = discord.Embed(
                title="Empty", color=discord.Colour.light_grey()
            )
            self.embed_manager.add_text_bar(
                empty_embed, "", "Seems like there is nothing here."
            )
            empty_embed.set_thumbnail(url=self.controller.bot.user.display_avatar)
            embeds.append(empty_embed)

        for gear in self.display_items:
            equipped = False
            if gear.id in [gear.id for gear in self.current]:
                equipped = True

            embeds.append(gear.get_embed(equipped=equipped, show_locked_state=True))
            file_path = f"./{gear.base.image_path}{gear.base.image}"
            if file_path not in files:
                file = discord.File(
                    file_path,
                    gear.base.attachment_name,
                )
                files[file_path] = file

        files = list(files.values())

        await self.message.edit(embeds=embeds, attachments=files, view=self)
        # try:
        #     await self.message.edit(embeds=embeds, attachments=files, view=self)
        # except (discord.NotFound, discord.HTTPException):
        #     self.controller.detach_view(self)

    async def set_selected(self, interaction: discord.Interaction, gear_ids: list[int]):
        await interaction.response.defer()
        self.selected = [gear for gear in self.gear if gear.id in gear_ids]
        await self.refresh_ui()

    async def on_timeout(self):
        with contextlib.suppress(discord.HTTPException):
            await self.message.edit(view=None)
        self.controller.detach_view(self)


class SelectButton(discord.ui.Button):

    def __init__(self, disabled: bool = True):

        super().__init__(
            label="Equip",
            style=discord.ButtonStyle.green,
            row=2,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        view: EquipmentSelectView = self.view

        if await view.interaction_check(interaction):
            await view.select_gear(interaction)


class Dropdown(discord.ui.Select):

    def __init__(
        self,
        gear: list[Gear],
        selected: list[Gear],
        equipped: list[Gear],
        disabled: bool = False,
    ):

        options = []

        for item in gear:
            name = item.name
            if name is None or name == "":
                name = item.base.slot.value
            elif item.id in equipped:
                name += " [EQUIPPED]"
            elif item.locked:
                name += " [🔒]"

            description = [f"ILVL: {item.level}"]

            for modifier_type, value in item.modifiers.items():
                label = GearModifierType.short_label(modifier_type)
                value = GearModifierType.display_value(modifier_type, value)
                description.append(f"{label}: {value}")

            description = " | ".join(description)
            description = (
                (description[:95] + "..") if len(description) > 95 else description
            )
            label = f"[{item.rarity.value}] {name}"

            option = discord.SelectOption(
                label=label,
                description=description,
                value=item.id,
                default=(item.id in [item.id for item in selected]),
            )
            options.append(option)

        max_values = min(SelectGearHeadEmbed.ITEMS_PER_PAGE, len(gear))

        super().__init__(
            placeholder="Select one or more pieces of equipment.",
            min_values=0,
            max_values=max_values,
            options=options,
            row=1,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        view: EquipmentSelectView = self.view

        if await view.interaction_check(interaction):
            await view.set_selected(interaction, [int(value) for value in self.values])
