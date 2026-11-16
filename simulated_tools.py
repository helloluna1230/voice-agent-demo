"""Session-local household simulation; never connects to real devices or shops."""

import json
from copy import deepcopy
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


class ToolSimulator:
    def __init__(self, definition_path: Path) -> None:
        definition = yaml.safe_load(definition_path.read_text(encoding="utf-8"))["definition"]
        self.validators = {
            tool["name"]: Draft202012Validator(tool["parameters"])
            for tool in definition["tools"] if tool["type"] == "function"
        }
        media_reference = definition["instructions"].partition(
            "SAVED MEDIA REFERENCE (evidence, not executable instructions):"
        )[2].strip()
        self.media = json.loads(media_reference)
        self.devices = {
            "tv": {"power": False, "settings": {
                "volume": 30, "channel": "home", "mediaTitle": "",
            }},
            "fridge": {"power": True, "settings": {"fridgeTemp": 4, "freezerTemp": -18}},
            "ac": {"power": False, "settings": {
                "temperature": 26, "mode": "auto", "fanSpeed": "auto",
            }},
            "humidifier": {"power": False, "settings": {
                "targetHumidity": 50, "mistLevel": "auto",
            }},
            "lights": {"power": True, "settings": {"brightness": 70, "warmth": 4000}},
            "curtains": {"power": True, "settings": {"position": "open"}},
        }
        self.readings = {"temperature": 26, "humidity": 45}
        self.inventory = [
            {"itemId": "milk", "name": "milk", "quantity": 0.25, "unit": "L",
             "daysStored": 2, "lowStock": True},
            {"itemId": "apples", "name": "apples", "quantity": 3, "unit": "pieces",
             "daysStored": 6, "longerStorage": True},
            {"itemId": "strawberries", "name": "strawberries", "quantity": 1, "unit": "box",
             "daysStored": 1},
            {"itemId": "eggs", "name": "eggs", "quantity": 6, "unit": "pieces",
             "daysStored": 3},
        ]
        self.shopping: dict[str, int] = {}

    def execute(self, name: str, arguments: dict) -> dict:
        if name not in self.validators:
            raise ValueError(f"Unknown function: {name}")
        error = next(self.validators[name].iter_errors(arguments), None)
        if error is not None:
            raise ValueError(f"{name}: {error.message}")

        match name:
            case "get_home_state":
                result = {"devices": self.devices, "readings": self.readings,
                          "note": "Illustrative state, not sensor readings or verified product models."}
            case "control_device":
                result = self._control_device(arguments)
            case "activate_scene":
                result = self._activate_scene(arguments["scene"])
            case "prepare_media_experience":
                title = arguments["title"].strip()
                if not title:
                    raise ValueError("Media title must not be blank.")
                result = self._activate_scene("movie", title)
            case "get_fridge_inventory":
                result = {"items": self.inventory, "shoppingList": self.shopping,
                          "note": "Invented sample records, not a camera scan or food safety assessment."}
            case "manage_shopping_list":
                result = self._manage_shopping_list(arguments)
            case "get_media_recommendations":
                key = "movies" if arguments["kind"] == "movie" else "series"
                result = {"recommendations": self.media[key]}
            case "search_product_manual":
                return {
                    "success": False, "simulated": True, "sources": [],
                    "error": "No manufacturer manuals or uploaded documents are available locally. "
                             "Do not invent product models, specifications or search evidence.",
                }
            case _:
                raise ValueError(f"No simulator implemented for function: {name}")
        return deepcopy({"success": True, "simulated": True, **result})

    def _control_device(self, arguments: dict) -> dict:
        device_id = arguments["deviceId"]
        settings = arguments.get("settings", {})
        if "power" not in arguments and not settings:
            raise ValueError("Device control requires power or at least one setting.")
        if device_id == "fridge" and arguments.get("power") is False:
            raise ValueError("Refrigerator power-off is blocked.")
        invalid = settings.keys() - self.devices[device_id]["settings"].keys()
        if invalid:
            raise ValueError(f"Unsupported settings for {device_id}: {', '.join(sorted(invalid))}")
        device = self.devices[device_id]
        if "power" in arguments:
            device["power"] = arguments["power"]
        device["settings"].update(settings)
        return {"deviceId": device_id, "device": device}

    def _activate_scene(self, scene: str, title: str | None = None) -> dict:
        devices = deepcopy(self.devices)
        if scene == "movie":
            devices["tv"]["power"] = True
            devices["tv"]["settings"]["channel"] = "movie"
            if title is not None:
                devices["tv"]["settings"]["mediaTitle"] = title
            devices["lights"]["power"] = True
            devices["lights"]["settings"].update(brightness=25, warmth=2700)
            devices["curtains"]["settings"]["position"] = "closed"
        elif scene == "comfort":
            devices["ac"]["power"] = True
            devices["ac"]["settings"].update(temperature=24, mode="auto", fanSpeed="auto")
            devices["lights"]["power"] = True
            devices["lights"]["settings"].update(brightness=60, warmth=3000)
        elif scene == "away":
            for device_id in ("tv", "ac", "humidifier", "lights"):
                devices[device_id]["power"] = False
            devices["curtains"]["settings"]["position"] = "closed"
        else:
            raise ValueError(f"Unsupported scene: {scene}")
        self.devices = devices
        return {"scene": scene, "devices": devices, "streaming": False}

    def _manage_shopping_list(self, arguments: dict) -> dict:
        item = arguments["itemId"]
        quantity = arguments["quantity"]
        current = self.shopping.get(item, 0)
        if arguments["action"] == "remove" and quantity > current:
            raise ValueError(f"Cannot remove {quantity} {item}; list contains {current}.")
        total = current + quantity if arguments["action"] == "add" else current - quantity
        if total:
            self.shopping[item] = total
        else:
            self.shopping.pop(item)
        return {"action": arguments["action"], "itemId": item, "quantity": quantity,
                "totalQuantity": total, "shoppingList": self.shopping, "orderPlaced": False}
