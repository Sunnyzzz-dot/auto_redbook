from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from agent_core.json_utils import parse_json_object
from app.core.config import get_settings
from app.services.storage import ObjectStorage, stable_asset_key


class TextModelClient:
    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key
        self.settings = get_settings()

    async def chat_json(
        self,
        system: str,
        user: str,
        fallback: dict[str, Any],
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        if not self.api_key:
            if self.settings.allow_mock_models:
                return fallback
            raise RuntimeError("model_api_key_missing")

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.settings.doubao_text_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(base_url=self.settings.ark_base_url, timeout=60) as client:
            response = await client.post("/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            try:
                return parse_json_object(content)
            except Exception:
                repair_payload = {
                    **payload,
                    "messages": [
                        {"role": "system", "content": "Return only valid compact JSON."},
                        {"role": "user", "content": content},
                    ],
                    "temperature": 0,
                }
                repaired = await client.post("/chat/completions", headers=headers, json=repair_payload)
                repaired.raise_for_status()
                fixed = repaired.json()["choices"][0]["message"]["content"]
                return parse_json_object(fixed)


class ImageModelClient:
    def __init__(self, api_key: str | None, storage: ObjectStorage | None = None) -> None:
        self.api_key = api_key
        self.settings = get_settings()
        self.storage = storage or ObjectStorage()

    async def generate_images(
        self,
        prompts: list[str],
        ratio: str,
        run_id: str,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            if self.settings.allow_mock_models:
                return [self._mock_image(prompt, ratio, run_id, index) for index, prompt in enumerate(prompts)]
            raise RuntimeError("model_api_key_missing")

        results: list[dict[str, Any]] = []
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(base_url=self.settings.ark_base_url, timeout=120) as client:
            for index, prompt in enumerate(prompts):
                payload = {
                    "model": self.settings.doubao_image_model,
                    "prompt": prompt,
                    "response_format": "b64_json",
                    "size": self._ratio_to_size(ratio),
                }
                response = await client.post("/images/generations", headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
                data, content_type, extension = await self._image_bytes_from_response(client, body)
                key = stable_asset_key(f"generated/{run_id}", data, extension)
                url = self.storage.put_bytes(key, data, content_type)
                results.append(
                    {
                        "image_url": url,
                        "prompt": prompt,
                        "ratio": ratio,
                        "sort_order": index,
                        "provider_response": {"model": self.settings.doubao_image_model},
                    }
                )
        return results

    async def _image_bytes_from_response(
        self, client: httpx.AsyncClient, body: dict[str, Any]
    ) -> tuple[bytes, str, str]:
        data_items = body.get("data") or []
        if not data_items:
            raise RuntimeError("image_model_response_empty")
        item = data_items[0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"]), "image/png", "png"
        if item.get("url"):
            response = await client.get(item["url"])
            response.raise_for_status()
            content_type = response.headers.get("content-type", "image/png").split(";")[0].strip()
            extension = {
                "image/jpeg": "jpg",
                "image/jpg": "jpg",
                "image/png": "png",
                "image/webp": "webp",
            }.get(content_type, "png")
            return response.content, content_type, extension
        raise RuntimeError("image_model_response_missing_image")

    def _mock_image(self, prompt: str, ratio: str, run_id: str, index: int) -> dict[str, Any]:
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1200">
<rect width="100%" height="100%" fill="#f6f1e8"/>
<rect x="60" y="60" width="780" height="1080" rx="28" fill="#ffffff"/>
<text x="100" y="170" font-size="54" font-family="Arial" fill="#28323c">Red Book Agent</text>
<text x="100" y="260" font-size="34" font-family="Arial" fill="#c43b4d">Mock image {index + 1}</text>
<foreignObject x="100" y="330" width="700" height="650">
<div xmlns="http://www.w3.org/1999/xhtml" style="font:32px Arial;color:#28323c;line-height:1.35">{prompt[:180]}</div>
</foreignObject>
</svg>"""
        data = svg.encode("utf-8")
        key = stable_asset_key(f"generated/{run_id}", data, "svg")
        url = self.storage.put_bytes(key, data, "image/svg+xml")
        return {
            "image_url": url,
            "prompt": prompt,
            "ratio": ratio,
            "sort_order": index,
            "provider_response": {"mock": True},
        }

    def _ratio_to_size(self, ratio: str) -> str:
        return {
            "1:1": "1024x1024",
            "3:4": "864x1152",
            "4:3": "1152x864",
            "9:16": "720x1280",
        }.get(ratio, "864x1152")
