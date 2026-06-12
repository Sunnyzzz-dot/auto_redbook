from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent_core import AgentEvent, AgentRuntime, AgentStep, Tool, ToolCall, ToolRegistry
from app.core.security import decrypt_secret
from app.models import AgentRun, AgentStepRecord, DraftImage, DraftNote, ModelKey
from app.services.model_clients import ImageModelClient, TextModelClient
from app.services.safety import rule_check


class AgentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_run(self, user_id: str, instruction: str, config: dict[str, Any]) -> AgentRun:
        run = AgentRun(user_id=user_id, instruction=instruction, config=config, status="running")
        self.db.add(run)
        await self.db.flush()
        await self._execute(run)
        await self.db.commit()
        return await self.get_run(user_id, run.id)

    async def create_run_record(self, user_id: str, instruction: str, config: dict[str, Any]) -> AgentRun:
        run = AgentRun(user_id=user_id, instruction=instruction, config=config, status="running")
        self.db.add(run)
        await self.db.commit()
        return await self.get_run(user_id, run.id)

    async def execute_existing_run(self, user_id: str, run_id: str) -> AgentRun:
        run = await self.get_run(user_id, run_id)
        run.status = "running"
        run.failure_reason = None
        await self.db.flush()
        await self._execute(run)
        await self.db.commit()
        return await self.get_run(user_id, run.id)

    async def get_run(self, user_id: str, run_id: str) -> AgentRun:
        result = await self.db.execute(
            select(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.user_id == user_id)
            .options(
                selectinload(AgentRun.steps),
                selectinload(AgentRun.draft).selectinload(DraftNote.images),
            )
            .execution_options(populate_existing=True)
        )
        run = result.scalar_one()
        run.steps.sort(key=lambda item: item.created_at)
        if run.draft:
            run.draft.images.sort(key=lambda item: item.sort_order)
        return run

    async def regenerate(
        self,
        user_id: str,
        run_id: str,
        target: str,
        image_count: int | None = None,
        instruction_override: str | None = None,
    ) -> AgentRun:
        run = await self.get_run(user_id, run_id)
        if instruction_override:
            run.instruction = instruction_override
        config = dict(run.config)
        if image_count:
            config["image_count"] = image_count
        run.config = config
        run.status = "running"
        run.failure_reason = None
        await self.db.execute(delete(AgentStepRecord).where(AgentStepRecord.run_id == run.id))
        await self.db.flush()
        await self._execute(run, only=target)
        await self.db.commit()
        return await self.get_run(user_id, run.id)

    async def _execute(self, run: AgentRun, only: str | None = None) -> None:
        api_key = await self._get_api_key(run.user_id)
        text_client = TextModelClient(api_key)
        image_client = ImageModelClient(api_key)
        registry = ToolRegistry()

        async def identify_intent(payload: dict[str, Any]) -> dict[str, Any]:
            fallback = {
                "theme": run.instruction,
                "target_audience": run.config.get("target_audience_hint") or "小红书泛生活方式用户",
                "style": run.config.get("style_hint") or "真诚、具体、轻种草",
                "goal": "生成可发布的小红书图文笔记",
                "constraints": ["避免夸大承诺", "避免站外引流"],
            }
            return await text_client.chat_json(
                "你是小红书内容策略专家。只返回 JSON。",
                f"根据一句话指令识别主题、目标人群、风格、目的和限制：{run.instruction}",
                fallback,
            )

        async def refine_prompt(payload: dict[str, Any]) -> dict[str, Any]:
            intent = payload["memory"].get("identify_intent", {})
            fallback = {
                "content_prompt": (
                    f"围绕“{intent.get('theme', run.instruction)}”，面向"
                    f"{intent.get('target_audience', '小红书用户')}，用"
                    f"{intent.get('style', '真诚实用')}风格写一篇小红书笔记。"
                )
            }
            return await text_client.chat_json(
                "你是提示词工程师。只返回 JSON。",
                f"将内容需求改写成更精准的创作提示词：{intent}",
                fallback,
                temperature=0.4,
            )

        async def generate_titles(payload: dict[str, Any]) -> dict[str, Any]:
            prompt = payload["memory"].get("refine_prompt", {}).get("content_prompt", run.instruction)
            fallback = {
                "titles": [
                    _limit_title(f"{run.instruction[:12]}，这样写"),
                    _limit_title(f"收藏级{run.instruction[:10]}"),
                    _limit_title(f"把{run.instruction[:10]}讲清楚"),
                ]
            }
            result = await text_client.chat_json(
                "你是小红书标题编辑。只返回 JSON，字段 titles 为 3 个标题，每个标题必须不超过 20 个汉字或字符。",
                prompt,
                fallback,
                temperature=0.8,
            )
            result["titles"] = [_limit_title(title) for title in result.get("titles", [])][:3]
            return result

        async def generate_body(payload: dict[str, Any]) -> dict[str, Any]:
            prompt = payload["memory"].get("refine_prompt", {}).get("content_prompt", run.instruction)
            fallback = {
                "body": (
                    f"今天想认真聊聊：{run.instruction}\n\n"
                    "我会先抓住最核心的场景，再把可执行的方法拆开讲。"
                    "这篇笔记适合正在做内容规划、想提高发布效率的人收藏。\n\n"
                    "1. 先明确这篇笔记解决谁的问题。\n"
                    "2. 再把标题、正文、标签和图片统一到同一个风格。\n"
                    "3. 发布前做一次风险检查，避免夸张承诺和站外引流。\n\n"
                    "如果你也在搭建自己的内容工作流，可以从一个小主题开始试跑。"
                )
            }
            return await text_client.chat_json(
                "你是小红书正文作者。只返回 JSON，字段 body 为正文。",
                prompt,
                fallback,
                temperature=0.75,
            )

        async def generate_hashtags(payload: dict[str, Any]) -> dict[str, Any]:
            fallback = {"hashtags": ["小红书运营", "AI工具", "内容创作", "自动化", "效率工具"]}
            return await text_client.chat_json(
                "你是小红书标签运营。只返回 JSON，字段 hashtags 为 5-10 个标签，不带 #。",
                str(payload["memory"]),
                fallback,
                temperature=0.5,
            )

        async def generate_image_prompts(payload: dict[str, Any]) -> dict[str, Any]:
            count = int(run.config.get("image_count", 3))
            image_size = run.config.get("image_ratio", "2K")
            fallback = {
                "image_prompts": [
                    f"小红书封面图，主题：{run.instruction}，清爽真实，中文留白排版，图片规格 {image_size}"
                    for _ in range(count)
                ]
            }
            result = await text_client.chat_json(
                "你是商业插画和小红书封面提示词专家。只返回 JSON。",
                f"生成 {count} 个图片提示词，固定图片规格 {image_size}，上下文：{payload['memory']}",
                fallback,
                temperature=0.7,
            )
            result["image_prompts"] = _ensure_image_prompts(
                _normalize_prompt_list(result.get("image_prompts", []), count),
                run.instruction,
                image_size,
                count,
            )
            return result

        async def generate_images(payload: dict[str, Any]) -> dict[str, Any]:
            prompts = payload["memory"].get("generate_image_prompts", {}).get("image_prompts", [])
            prompts = _normalize_prompt_list(prompts, int(run.config.get("image_count", 3)))
            prompts = _ensure_image_prompts(
                prompts,
                run.instruction,
                run.config.get("image_ratio", "2K"),
                int(run.config.get("image_count", 3)),
            )
            images = await image_client.generate_images(
                prompts,
                run.config.get("image_ratio", "2K"),
                run.id,
            )
            return {"images": images}

        async def safety_review(payload: dict[str, Any]) -> dict[str, Any]:
            titles = payload["memory"].get("generate_titles", {}).get("titles", [])
            body = payload["memory"].get("generate_body", {}).get("body", "")
            hashtags = payload["memory"].get("generate_hashtags", {}).get("hashtags", [])
            selected_title = titles[0] if titles else ""
            rule_report = rule_check(selected_title, body, hashtags)
            fallback = {
                "level": rule_report["level"],
                "reasons": [hit["word"] for hit in rule_report["hits"]],
                "suggestions": ["发布前人工复核涉及承诺、联系方式和敏感内容的表达。"],
            }
            model_report = await text_client.chat_json(
                "你是内容安全审核员。只返回 JSON。",
                f"检查这篇小红书笔记是否有违规或平台风险：标题 {selected_title} 正文 {body} 标签 {hashtags}",
                fallback,
                temperature=0,
            )
            return {"rule_report": rule_report, "model_report": model_report}

        async def save_draft(payload: dict[str, Any]) -> dict[str, Any]:
            memory = payload["memory"]
            titles = memory.get("generate_titles", {}).get("titles", [])
            body = memory.get("generate_body", {}).get("body", "")
            hashtags = memory.get("generate_hashtags", {}).get("hashtags", [])
            intent = memory.get("identify_intent", {})
            safety = memory.get("safety_review", {})
            images = memory.get("generate_images", {}).get("images", [])

            result = await self.db.execute(select(DraftNote).where(DraftNote.run_id == run.id))
            draft = result.scalar_one_or_none()
            if not draft:
                draft = DraftNote(run_id=run.id, user_id=run.user_id)
            if "generate_titles" in memory:
                draft.title_candidates = titles
                draft.title_candidates = [_limit_title(title) for title in titles]
                draft.selected_title = _limit_title(titles[0]) if titles else _limit_title(draft.selected_title)
            if "generate_body" in memory:
                draft.body = body
            if "generate_hashtags" in memory:
                draft.hashtags = hashtags
            if "identify_intent" in memory:
                draft.style = _limit_text(intent.get("style", ""), 120)
                draft.target_audience = _limit_text(intent.get("target_audience", ""), 255)
            if "safety_review" in memory:
                draft.safety_report = safety
            self.db.add(draft)
            await self.db.flush()

            if "generate_images" in memory:
                await self.db.execute(delete(DraftImage).where(DraftImage.draft_id == draft.id))
                for image in images:
                    self.db.add(DraftImage(draft_id=draft.id, **image))
                self.db.expire(draft, ["images"])
            run.status = "draft_ready"
            await self.db.flush()
            return {"draft_id": draft.id}

        registry.register(Tool("intent.identify", "Extract note intent", identify_intent))
        registry.register(Tool("prompt.refine", "Refine content prompt", refine_prompt))
        registry.register(Tool("llm.generate_titles", "Generate title candidates", generate_titles))
        registry.register(Tool("llm.generate_body", "Generate note body", generate_body))
        registry.register(Tool("llm.generate_hashtags", "Generate hashtags", generate_hashtags))
        registry.register(Tool("llm.generate_image_prompts", "Generate image prompts", generate_image_prompts))
        registry.register(Tool("image.generate", "Generate images", generate_images))
        registry.register(Tool("safety.review", "Review content risks", safety_review))
        registry.register(Tool("draft.save", "Persist draft", save_draft))

        async def sink(event: AgentEvent) -> None:
            if event.type not in {"step_succeeded", "step_failed"}:
                return
            step = event.step
            self.db.add(
                AgentStepRecord(
                    id=str(step.id),
                    run_id=str(step.run_id),
                    step=step.step,
                    thought_summary=step.thought_summary,
                    action=step.action,
                    action_input=step.action_input,
                    observation=step.observation,
                    status=step.status.value,
                    error=step.error,
                    created_at=step.created_at,
                    completed_at=step.completed_at,
                )
            )
            await self.db.flush()

        runtime = AgentRuntime(registry, event_sink=sink)
        plan = self._plan(only)
        steps = await runtime.run_plan(UUID(run.id), plan)
        if steps and steps[-1].status.value == "failed":
            await self._save_partial_draft(run, steps)
            run.status = "failed"
            run.failure_reason = steps[-1].error
        await self.db.flush()

    async def _save_partial_draft(self, run: AgentRun, steps: list[AgentStep]) -> None:
        memory = {step.step: step.observation for step in steps if step.status.value == "succeeded"}
        if not any(key in memory for key in ("generate_titles", "generate_body", "generate_hashtags")):
            return

        result = await self.db.execute(select(DraftNote).where(DraftNote.run_id == run.id))
        draft = result.scalar_one_or_none()
        if not draft:
            draft = DraftNote(run_id=run.id, user_id=run.user_id)

        titles = memory.get("generate_titles", {}).get("titles", [])
        if titles:
            draft.title_candidates = [_limit_title(title) for title in titles]
            draft.selected_title = _limit_title(titles[0])

        body = memory.get("generate_body", {}).get("body")
        if body:
            draft.body = str(body)

        hashtags = memory.get("generate_hashtags", {}).get("hashtags")
        if isinstance(hashtags, list):
            draft.hashtags = [str(tag).strip().lstrip("#") for tag in hashtags if str(tag).strip()]

        intent = memory.get("identify_intent", {})
        if intent:
            draft.style = _limit_text(intent.get("style", draft.style), 120)
            draft.target_audience = _limit_text(intent.get("target_audience", draft.target_audience), 255)

        self.db.add(draft)
        await self.db.flush()

    def _plan(self, only: str | None) -> list[tuple[str, str, ToolCall]]:
        full = [
            ("identify_intent", "识别主题、目标人群、风格和限制。", ToolCall(name="intent.identify")),
            ("refine_prompt", "将一句话指令改写为更精准的生成提示词。", ToolCall(name="prompt.refine")),
            ("generate_titles", "生成 3 个适合小红书点击和收藏的标题。", ToolCall(name="llm.generate_titles")),
            ("generate_body", "生成正文并保持真实、可执行和平台友好。", ToolCall(name="llm.generate_body")),
            ("generate_hashtags", "生成和主题匹配的话题标签。", ToolCall(name="llm.generate_hashtags")),
            ("generate_image_prompts", "把内容需求转成图片模型提示词。", ToolCall(name="llm.generate_image_prompts")),
            ("generate_images", "调用图片模型生成笔记配图。", ToolCall(name="image.generate")),
            ("safety_review", "发布前执行规则检查和模型自检。", ToolCall(name="safety.review")),
            ("save_draft", "保存草稿、图片和审核结果。", ToolCall(name="draft.save")),
        ]
        if not only:
            return full
        target_map = {
            "titles": ["identify_intent", "refine_prompt", "generate_titles", "save_draft"],
            "body": ["identify_intent", "refine_prompt", "generate_titles", "generate_body", "save_draft"],
            "hashtags": ["identify_intent", "generate_hashtags", "save_draft"],
            "images": ["identify_intent", "refine_prompt", "generate_image_prompts", "generate_images", "save_draft"],
            "safety": ["generate_titles", "generate_body", "generate_hashtags", "safety_review", "save_draft"],
        }
        allowed = set(target_map.get(only, []))
        return [item for item in full if item[0] in allowed]

    async def _get_api_key(self, user_id: str) -> str | None:
        result = await self.db.execute(
            select(ModelKey).where(ModelKey.user_id == user_id, ModelKey.status == "active")
        )
        key = result.scalars().first()
        if not key:
            return None
        return decrypt_secret(key.encrypted_api_key)


def _limit_text(value: Any, max_length: int) -> str:
    text = "" if value is None else str(value)
    return text[:max_length]


def _limit_title(value: Any) -> str:
    text = " ".join(_limit_text(value, 80).split())
    return text[:20]


def _normalize_prompt_list(values: Any, count: int) -> list[str]:
    if not isinstance(values, list):
        values = [values]
    prompts: list[str] = []
    for item in values:
        if isinstance(item, dict):
            text = item.get("prompt") or item.get("text") or item.get("description") or item.get("content") or ""
        else:
            text = item
        prompt = _clean_image_prompt(text)
        if prompt:
            prompts.append(prompt)
        if len(prompts) >= count:
            break
    return prompts


def _clean_image_prompt(value: Any) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.replace("\u0000", " ").split())
    return text[:800]


def _ensure_image_prompts(prompts: list[str], instruction: str, image_size: str, count: int) -> list[str]:
    result = list(prompts[:count])
    while len(result) < count:
        index = len(result) + 1
        result.append(
            f"小红书图文笔记配图 {index}，主题：{instruction}。清爽真实，中文留白排版，适合收藏，图片规格 {image_size}"
        )
    return result
