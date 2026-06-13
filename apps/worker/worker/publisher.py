from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from worker.config import settings


@dataclass
class PublishResult:
    status: str
    screenshot_path: str | None = None
    result_url: str | None = None
    failure_reason: str | None = None


@dataclass
class ActiveBrowserSession:
    context: BrowserContext
    page: Page
    job: dict[str, Any]
    stage: str


def _log(job_id: str, message: str) -> None:
    print(f"publish_job {job_id}: {message}", flush=True)


def _png_dimensions(image: bytes) -> tuple[int | None, int | None]:
    if len(image) >= 24 and image.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", image[16:24])
    return None, None


class XiaohongshuPublisher:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._active_sessions: dict[str, ActiveBrowserSession] = {}

    async def publish(self, job: dict[str, Any]) -> PublishResult:
        job_id = job.get("job_id", "unknown-job")
        account_id = job.get("account_id", "default")
        profile_path = Path(settings.browser_profiles_dir) / account_id
        profile_path.mkdir(parents=True, exist_ok=True)
        Path(settings.screenshots_dir).mkdir(parents=True, exist_ok=True)

        playwright = await self._get_playwright()
        _log(job_id, "launch_browser")
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=settings.headless,
            args=["--start-maximized", "--window-size=1920,1080"],
            viewport={"width": 1920, "height": 1080},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await self._reset_browser_view(page)
        try:
            _log(job_id, "open_xhs_creator")
            await page.goto(settings.xhs_creator_url, wait_until="domcontentloaded", timeout=60000)
            await self._reset_browser_view(page)
            await page.wait_for_timeout(1500)
            _log(job_id, "check_login_or_risk_control")
            if await self._needs_human(page):
                _log(job_id, "requires_human_intervention")
                return await self._human_required(context, page, job, "login_or_risk_control_required")

            _log(job_id, "fill_note")
            await self._fill_note(page, job)
            if job.get("publish_mode") == "auto_publish":
                _log(job_id, "auto_publish")
                result = await self._auto_publish(context, page, job)
                if result:
                    _log(job_id, f"auto_publish_result {result.status}")
                    return result

            _log(job_id, "await_manual_approval")
            screenshot = await self._screenshot(page, job["job_id"])
            self._active_sessions[job["job_id"]] = ActiveBrowserSession(
                context=context,
                page=page,
                job=job,
                stage="awaiting_manual_approval",
            )
            return PublishResult(status="awaiting_manual_approval", screenshot_path=screenshot)
        except BaseException:
            await context.close()
            raise

    async def handle_browser_event(self, job_id: str, event: dict[str, Any]) -> dict[str, Any]:
        session = self._active_sessions.get(job_id)
        if not session:
            return {"type": "browser_frame", "job_id": job_id, "error": "session_not_found"}
        context = session.context
        page = session.page
        event_type = event.get("type")
        last_click: dict[str, Any] | None = None
        if event_type == "click":
            viewport = page.viewport_size or {"width": 1920, "height": 1080}
            screenshot_size = page.context.__dict__.get("remote_screenshot_size") or {}
            metrics = await page.evaluate(
                """
                () => {
                  const visual = window.visualViewport;
                  const htmlStyle = window.getComputedStyle(document.documentElement);
                  return {
                    inner_width: window.innerWidth,
                    inner_height: window.innerHeight,
                    outer_width: window.outerWidth,
                    outer_height: window.outerHeight,
                    device_pixel_ratio: window.devicePixelRatio,
                    visual_width: visual ? visual.width : null,
                    visual_height: visual ? visual.height : null,
                    visual_scale: visual ? visual.scale : null,
                    visual_offset_left: visual ? visual.offsetLeft : 0,
                    visual_offset_top: visual ? visual.offsetTop : 0,
                    html_zoom: htmlStyle.zoom || '',
                  };
                }
                """
            )
            page_width = float(metrics.get("inner_width") or viewport["width"])
            page_height = float(metrics.get("inner_height") or viewport["height"])
            source_width = float(
                event.get("natural_width")
                or screenshot_size.get("width")
                or event.get("display_width")
                or page_width
            )
            source_height = float(
                event.get("natural_height")
                or screenshot_size.get("height")
                or event.get("display_height")
                or page_height
            )
            basis_width = float(
                metrics.get("visual_width")
                or page_width
            )
            basis_height = float(
                metrics.get("visual_height")
                or page_height
            )
            offset_x = float(metrics.get("visual_offset_left") or 0)
            offset_y = float(metrics.get("visual_offset_top") or 0)
            if "rx" in event and "ry" in event:
                rx = max(0.0, min(1.0, float(event.get("rx", 0))))
                ry = max(0.0, min(1.0, float(event.get("ry", 0))))
                x = offset_x + rx * basis_width
                y = offset_y + ry * basis_height
            else:
                source_x = float(event.get("x", 0))
                source_y = float(event.get("y", 0))
                rx = source_x / source_width
                ry = source_y / source_height
                x = offset_x + rx * basis_width
                y = offset_y + ry * basis_height
            x = max(0.0, min(float(viewport["width"]) - 1, x))
            y = max(0.0, min(float(viewport["height"]) - 1, y))
            last_click = {
                "x": x,
                "y": y,
                "rx": rx,
                "ry": ry,
                "basis_width": basis_width,
                "basis_height": basis_height,
                "source_width": source_width,
                "source_height": source_height,
                "viewport_width": viewport["width"],
                "viewport_height": viewport["height"],
                "page_width": page_width,
                "page_height": page_height,
                "visual_scale": metrics.get("visual_scale"),
                "html_zoom": metrics.get("html_zoom"),
                "display_width": event.get("display_width"),
                "display_height": event.get("display_height"),
                "natural_width": event.get("natural_width"),
                "natural_height": event.get("natural_height"),
            }
            await page.mouse.click(x, y)
        elif event_type == "type":
            await page.keyboard.type(str(event.get("text", "")))
        elif event_type == "backspace":
            count = max(1, min(100, int(event.get("count", 1))))
            for _ in range(count):
                await page.keyboard.press("Backspace")
        elif event_type == "press":
            await page.keyboard.press(str(event.get("key", "Enter")))
        elif event_type == "scroll":
            await page.mouse.wheel(float(event.get("dx", 0)), float(event.get("dy", 0)))
        elif event_type == "scroll_top":
            await page.keyboard.press("Home")
            await page.evaluate("window.scrollTo(0, 0)")
        elif event_type == "scroll_bottom":
            await page.keyboard.press("End")
            await page.evaluate(
                """
                () => {
                  const root = document.scrollingElement || document.documentElement || document.body;
                  root.scrollTop = root.scrollHeight;
                  window.scrollTo(0, root.scrollHeight);
                }
                """
            )
        elif event_type == "screenshot":
            pass
        elif event_type == "reset_zoom":
            await self._reset_browser_view(page)
        elif event_type == "zoom_out":
            await self._browser_zoom(page, int(event.get("steps", 2)))
        elif event_type == "zoom_in":
            await self._browser_zoom(page, -int(event.get("steps", 2)))
        elif event_type == "close":
            await context.close()
            self._active_sessions.pop(job_id, None)
            return self._job_status(job_id, "failed", failure_reason="remote_session_closed")
        elif event_type == "continue":
            return await self._continue_session(job_id, session)
        screenshot = await page.screenshot(full_page=False, scale="css")
        screenshot_width, screenshot_height = _png_dimensions(screenshot)
        page.context.__dict__["remote_screenshot_size"] = {
            "width": screenshot_width,
            "height": screenshot_height,
        }
        encoded = base64.b64encode(screenshot).decode("ascii")
        viewport = page.viewport_size or {}
        return {
            "type": "browser_frame",
            "job_id": job_id,
            "image": f"data:image/png;base64,{encoded}",
            "width": screenshot_width or viewport.get("width"),
            "height": screenshot_height or viewport.get("height"),
            "viewport_width": viewport.get("width"),
            "viewport_height": viewport.get("height"),
            "url": page.url,
            "event": event_type,
            "zoom": page.context.__dict__.get("remote_zoom_factor", 1.0),
            "last_click": last_click,
        }

    async def _continue_session(self, job_id: str, session: ActiveBrowserSession) -> dict[str, Any]:
        context = session.context
        page = session.page
        if session.stage == "requires_human_intervention":
            if await self._needs_human(page):
                screenshot = await page.screenshot(full_page=False)
                encoded = base64.b64encode(screenshot).decode("ascii")
                return {
                    "type": "browser_frame",
                    "job_id": job_id,
                    "image": f"data:image/png;base64,{encoded}",
                    "error": "human_intervention_still_required",
                }
            try:
                await self._fill_note(page, session.job)
                if session.job.get("publish_mode") == "auto_publish":
                    result = await self._auto_publish(context, page, session.job)
                    if result and result.status == "published":
                        self._active_sessions.pop(job_id, None)
                        return self._job_status(job_id, "published", result_url=result.result_url)
                    return self._job_status(
                        job_id,
                        result.status if result else "awaiting_manual_approval",
                        failure_reason=result.failure_reason if result else "auto_publish_failed",
                        screenshot_path=result.screenshot_path if result else None,
                    )
                session.stage = "awaiting_manual_approval"
                screenshot = await self._screenshot(page, job_id)
                return self._job_status(job_id, "awaiting_manual_approval", screenshot_path=screenshot)
            except Exception as exc:  # noqa: BLE001 - report resume failures to the API.
                await context.close()
                self._active_sessions.pop(job_id, None)
                return self._job_status(job_id, "failed", failure_reason=str(exc))

        if await self._is_publish_success(page):
            await context.close()
            self._active_sessions.pop(job_id, None)
            return self._job_status(job_id, "published", result_url=page.url)

        if session.job.get("publish_mode") == "auto_publish":
            try:
                result = await self._auto_publish(context, page, session.job)
            except Exception as exc:  # noqa: BLE001 - surface retry failures.
                return self._job_status(job_id, "awaiting_manual_approval", failure_reason=str(exc))
            if result and result.status == "published":
                self._active_sessions.pop(job_id, None)
                return self._job_status(job_id, "published", result_url=result.result_url)
            return self._job_status(
                job_id,
                result.status if result else "awaiting_manual_approval",
                failure_reason=result.failure_reason if result else "auto_publish_failed",
                screenshot_path=result.screenshot_path if result else None,
            )

        screenshot = await self._screenshot(page, job_id)
        return self._job_status(
            job_id,
            "awaiting_manual_approval",
            failure_reason="manual_publish_not_confirmed",
            screenshot_path=screenshot,
        )

    def _job_status(
        self,
        job_id: str,
        status: str,
        failure_reason: str | None = None,
        result_url: str | None = None,
        screenshot_path: str | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "job_status",
            "job_id": job_id,
            "status": status,
            "failure_reason": failure_reason,
            "result_url": result_url,
            "screenshot_url": screenshot_to_data_url(screenshot_path),
        }

    async def _fill_note(self, page: Page, job: dict[str, Any]) -> None:
        job_id = job.get("job_id", "unknown-job")
        draft = job.get("draft", {})
        title = str(draft.get("selected_title", ""))[:20]
        body = draft.get("body", "")
        hashtags = " ".join(f"#{tag}" for tag in draft.get("hashtags", []))
        text = f"{body}\n\n{hashtags}".strip()

        _log(job_id, "select_image_publish_tab")
        await self._select_image_publish_tab(page)
        _log(job_id, "prepare_images")
        images = await self._prepare_images(draft.get("images", []), job.get("job_id", "job"), page)
        if not images:
            raise RuntimeError("draft_images_missing")
        _log(job_id, f"upload_images count={len(images)}")
        await self._upload_images(page, images)
        _log(job_id, "fill_title_and_body")
        await self._try_fill(page, ["input[placeholder*='标题']", "textarea[placeholder*='标题']"], title)
        await self._try_fill(
            page,
            ["textarea[placeholder*='正文']", "[contenteditable='true']", "textarea"],
            text,
        )

    async def _select_image_publish_tab(self, page: Page) -> None:
        current = await self._first_file_input_accept(page)
        if _accepts_images(current):
            return

        clicked = await page.evaluate(
            """
            () => {
              const labels = ['上传图文', '图文'];
              const elements = [...document.querySelectorAll('button, [role="tab"], span, div, a')];
              const target = elements.find((element) => {
                const text = (element.textContent || '').trim();
                return labels.includes(text);
              });
              if (!target) return false;
              target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
              target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
              target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
              return true;
            }
            """
        )
        if not clicked:
            raise RuntimeError("image_publish_tab_not_found")

        for _ in range(20):
            await page.wait_for_timeout(250)
            if await self._find_image_upload_input(page):
                return
        raise RuntimeError("image_publish_tab_did_not_activate")

    async def _upload_images(self, page: Page, images: list[str]) -> None:
        if not images:
            return
        upload_input = await self._find_image_upload_input(page)
        if not upload_input:
            raise RuntimeError("image_upload_input_not_found")

        multiple = await upload_input.get_attribute("multiple")
        await upload_input.set_input_files(images if multiple is not None or len(images) == 1 else images[0])
        for _ in range(60):
            await page.wait_for_timeout(1000)
            if await page.locator("input[placeholder*='标题'], textarea[placeholder*='标题']").count() > 0:
                return
        raise RuntimeError("image_upload_editor_not_ready")

    async def _find_image_upload_input(self, page: Page):
        inputs = page.locator("input[type='file']")
        count = await inputs.count()
        for index in range(count):
            candidate = inputs.nth(index)
            accept = (await candidate.get_attribute("accept") or "").lower()
            multiple = await candidate.get_attribute("multiple")
            if _accepts_images(accept) or multiple is not None:
                return candidate
        return None

    async def _first_file_input_accept(self, page: Page) -> str:
        inputs = page.locator("input[type='file']")
        if await inputs.count() == 0:
            return ""
        return (await inputs.first.get_attribute("accept") or "").lower()

    async def _try_fill(self, page: Page, selectors: list[str], value: str) -> bool:
        for selector in selectors:
            locator = page.locator(selector).first
            if await locator.count() > 0:
                await locator.fill(value)
                return True
        return False

    async def _auto_publish(
        self, context: BrowserContext, page: Page, job: dict[str, Any]
    ) -> PublishResult | None:
        job_id = job.get("job_id", "unknown-job")
        _log(job_id, "click_publish_button")
        clicked = await self._click_publish(page)
        if not clicked:
            _log(job_id, "publish_button_not_found")
            return await self._manual_publish_required(
                context, page, job, "publish_button_not_found"
            )

        _log(job_id, "click_publish_confirmation")
        await self._click_publish_confirmation(page)
        _log(job_id, "wait_for_publish_result")
        if await self._wait_for_publish_success(page):
            _log(job_id, "published")
            await context.close()
            return PublishResult(status="published", result_url=page.url)

        _log(job_id, "auto_publish_success_not_detected")
        return await self._manual_publish_required(
            context, page, job, "auto_publish_success_not_detected"
        )

    async def _manual_publish_required(
        self, context: BrowserContext, page: Page, job: dict[str, Any], reason: str
    ) -> PublishResult:
        job_id = job["job_id"]
        _log(job_id, f"manual_publish_required reason={reason}")
        screenshot = await self._screenshot(page, job_id)
        self._active_sessions[job_id] = ActiveBrowserSession(
            context=context,
            page=page,
            job=job,
            stage="awaiting_manual_approval",
        )
        return PublishResult(
            status="awaiting_manual_approval",
            screenshot_path=screenshot,
            failure_reason=reason,
        )

    async def _scroll_publish_controls_into_view(self, page: Page) -> None:
        await page.keyboard.press("Escape")
        await self._reset_browser_view(page)
        await page.evaluate(
            """
            () => {
              document.documentElement.style.zoom = '0.8';
              document.body.style.zoom = '';
              document.documentElement.focus();
            }
            """
        )
        await page.keyboard.press("End")
        await page.mouse.wheel(0, 6000)
        await page.wait_for_timeout(300)
        await page.evaluate(
            """
            () => {
              const scrollBottom = () => {
                const root = document.scrollingElement || document.documentElement || document.body;
                root.scrollTop = root.scrollHeight;
                window.scrollTo(0, root.scrollHeight);
                const elements = [...document.querySelectorAll('*')];
                for (const element of elements) {
                  if (element.scrollHeight > element.clientHeight + 8) {
                    element.scrollTop = element.scrollHeight;
                  }
                  if (element.scrollWidth > element.clientWidth + 8) {
                    element.scrollLeft = 0;
                  }
                }
              };
              scrollBottom();
              document.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', code: 'End', bubbles: true }));
              requestAnimationFrame(scrollBottom);
            }
            """
        )
        await page.keyboard.press("PageDown")
        await page.mouse.wheel(0, 4000)
        size = page.viewport_size or {"width": 1920, "height": 1080}
        await page.mouse.move(float(size["width"] - 8), float(size["height"] * 0.55))
        await page.mouse.down()
        await page.mouse.move(float(size["width"] - 8), float(size["height"] - 20), steps=12)
        await page.mouse.up()
        await page.wait_for_timeout(600)

    async def _nudge_publish_controls(self, page: Page) -> None:
        await page.keyboard.press("End")
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(300)

    async def _reset_browser_view(self, page: Page) -> None:
        page.context.__dict__["remote_zoom_factor"] = 1.0
        await page.keyboard.down("Control")
        try:
            await page.keyboard.press("0")
        finally:
            await page.keyboard.up("Control")
        try:
            client = await page.context.new_cdp_session(page)
            await client.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
            await client.detach()
        except Exception:
            pass
        await page.evaluate(
            """
            () => {
              document.documentElement.style.zoom = '';
              document.body.style.zoom = '';
            }
            """
        )
        await page.wait_for_timeout(200)

    async def _browser_zoom(self, page: Page, steps: int, reset: bool = False) -> None:
        if reset:
            await self._reset_browser_view(page)
        if steps == 0:
            return
        current = float(page.context.__dict__.get("remote_zoom_factor", 1.0))
        factor = 0.9 ** steps if steps > 0 else 1.1 ** abs(steps)
        next_zoom = max(0.45, min(1.8, current * factor))
        page.context.__dict__["remote_zoom_factor"] = next_zoom
        try:
            client = await page.context.new_cdp_session(page)
            await client.send(
                "Emulation.setPageScaleFactor",
                {"pageScaleFactor": next_zoom},
            )
            await client.detach()
        except Exception:
            pass
        await page.evaluate(
            """
            (zoom) => {
              document.documentElement.style.zoom = String(zoom);
              document.body.style.zoom = '';
            }
            """,
            next_zoom,
        )
        await page.wait_for_timeout(300)

    async def _click_publish(self, page: Page) -> bool:
        await self._scroll_publish_controls_into_view(page)
        await page.bring_to_front()

        for _ in range(3):
            info = await page.evaluate(
                """
                () => {
                  const forceBottom = () => {
                    const root = document.scrollingElement || document.documentElement || document.body;
                    root.scrollTop = root.scrollHeight;
                    window.scrollTo(0, root.scrollHeight);
                    for (const element of document.querySelectorAll('*')) {
                      if (element.scrollHeight > element.clientHeight + 8) {
                        element.scrollTop = element.scrollHeight;
                      }
                    }
                  };
                  forceBottom();

                  const hostRows = Array.from(document.querySelectorAll('xhs-publish-btn'))
                    .map((host, hostIndex) => {
                      const rect = host.getBoundingClientRect();
                      const style = window.getComputedStyle(host);
                      const shadowButton = host.shadowRoot
                        ? host.shadowRoot.querySelector('button.bg-red, button[class*="bg-red"], button:last-of-type')
                        : null;
                      if (shadowButton) {
                        shadowButton.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
                        const buttonRect = shadowButton.getBoundingClientRect();
                        return {
                          element: host,
                          shadowButton,
                          strategy: 'xhs-publish-btn-shadow',
                          hostIndex,
                          text: shadowButton.innerText || host.getAttribute('submit-text') || '',
                          tag: host.tagName,
                          className: String(host.className || ''),
                          disabled: shadowButton.disabled || host.getAttribute('submit-disabled') === 'true',
                          ariaDisabled: shadowButton.getAttribute('aria-disabled'),
                          rect: {
                            x: buttonRect.left,
                            y: buttonRect.top,
                            width: buttonRect.width,
                            height: buttonRect.height,
                            centerX: buttonRect.left + buttonRect.width / 2,
                            centerY: buttonRect.top + buttonRect.height / 2,
                          },
                          hostRect: {
                            x: rect.left,
                            y: rect.top,
                            width: rect.width,
                            height: rect.height,
                          },
                        };
                      }

                      const buttonWidth = 96;
                      const buttonHeight = 32;
                      const buttonGap = 24;
                      return {
                        element: host,
                        shadowButton: null,
                        strategy: 'xhs-publish-btn-host-geometry',
                        hostIndex,
                        text: host.getAttribute('submit-text') || '',
                        tag: host.tagName,
                        className: String(host.className || ''),
                        disabled: host.getAttribute('submit-disabled') === 'true',
                        ariaDisabled: host.getAttribute('aria-disabled'),
                        rect: {
                          x: rect.left + rect.width / 2 + buttonGap / 2,
                          y: rect.top + Math.max(0, (rect.height - buttonHeight) / 2),
                          width: buttonWidth,
                          height: buttonHeight,
                          centerX: rect.left + rect.width / 2 + buttonGap / 2 + buttonWidth / 2,
                          centerY: rect.top + rect.height / 2,
                        },
                        hostRect: {
                          x: rect.left,
                          y: rect.top,
                          width: rect.width,
                          height: rect.height,
                        },
                      };
                    })
                    .filter((row) => {
                      return row.text === '\\u53d1\\u5e03'
                        && !row.disabled
                        && row.hostRect.width > 0
                        && row.hostRect.height > 0
                        && row.rect.centerX > 0
                        && row.rect.centerX < window.innerWidth
                        && row.rect.centerY > window.innerHeight * 0.60
                        && row.rect.centerY < window.innerHeight;
                    })
                    .sort((left, right) => right.hostRect.y - left.hostRect.y);
                  if (hostRows[0]) {
                    const target = hostRows[0];
                    const top = document.elementFromPoint(target.rect.centerX, target.rect.centerY);
                    return {
                      ok: true,
                      target: {
                        x: target.rect.centerX,
                        y: target.rect.centerY,
                        text: target.text,
                        tag: target.tag,
                        className: target.className,
                        rect: target.rect,
                        hostRect: target.hostRect,
                        topTag: top ? top.tagName : null,
                        topText: top ? ((top.innerText || top.textContent || '').replace(/\\s+/g, ' ').trim()).slice(0, 80) : null,
                        topClassName: top ? String(top.className || '') : null,
                        isTopSelf: top === target.element || target.element.contains(top),
                        strategy: target.strategy,
                        hostIndex: target.hostIndex,
                      },
                      candidates: hostRows.slice(0, 3).map((row) => ({
                        strategy: row.strategy,
                        hostIndex: row.hostIndex,
                        text: row.text,
                        tag: row.tag,
                        className: row.className,
                        disabled: row.disabled,
                        ariaDisabled: row.ariaDisabled,
                        rect: row.rect,
                        hostRect: row.hostRect,
                      })),
                    };
                  }

                  const parseColor = (value) => {
                    const match = String(value).match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                    if (!match) return null;
                    return { r: Number(match[1]), g: Number(match[2]), b: Number(match[3]) };
                  };
                  const isRed = (color) => color && color.r >= 190 && color.g <= 115 && color.b <= 145;
                  const textOf = (element) => {
                    return (element.innerText || element.textContent || '').replace(/\\s+/g, ' ').trim();
                  };
                  const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0
                      && rect.height > 0
                      && rect.left >= 0
                      && rect.top >= 0
                      && rect.right <= window.innerWidth
                      && rect.bottom <= window.innerHeight
                      && style.display !== 'none'
                      && style.visibility !== 'hidden'
                      && style.opacity !== '0';
                  };
                  const clickableFor = (element) => {
                    let current = element;
                    for (let i = 0; i < 6 && current; i += 1) {
                      const style = window.getComputedStyle(current);
                      const role = current.getAttribute('role');
                      const tag = current.tagName.toLowerCase();
                      const className = String(current.className || '');
                      if (
                        tag === 'button'
                        || role === 'button'
                        || style.cursor === 'pointer'
                        || className.includes('button')
                        || className.includes('btn')
                      ) {
                        return current;
                      }
                      current = current.parentElement;
                    }
                    return element;
                  };
                  const rowFor = (element, strategy) => {
                    const target = clickableFor(element);
                    const rect = target.getBoundingClientRect();
                    const centerX = rect.left + rect.width / 2;
                    const centerY = rect.top + rect.height / 2;
                    const top = document.elementFromPoint(centerX, centerY);
                    return {
                      element: target,
                      strategy,
                      text: textOf(target),
                      tag: target.tagName,
                      className: String(target.className || ''),
                      disabled: Boolean(target.disabled),
                      ariaDisabled: target.getAttribute('aria-disabled'),
                      rect: {
                        x: rect.left,
                        y: rect.top,
                        width: rect.width,
                        height: rect.height,
                        centerX,
                        centerY,
                      },
                      topTag: top ? top.tagName : null,
                      topText: top ? textOf(top).slice(0, 80) : null,
                      topClassName: top ? String(top.className || '') : null,
                      isTopSelf: top === target || target.contains(top),
                    };
                  };
                  const inPublishZone = (row) => {
                    const centerX = row.rect.centerX;
                    const centerY = row.rect.centerY;
                    return row.rect.width >= 36
                      && row.rect.width <= 220
                      && row.rect.height >= 18
                      && row.rect.height <= 80
                      && !row.disabled
                      && row.ariaDisabled !== 'true'
                      && centerX > window.innerWidth * 0.30
                      && centerX < window.innerWidth * 0.70
                      && centerY > window.innerHeight * 0.66
                      && centerY < window.innerHeight * 0.98;
                  };
                  const allElements = Array.from(document.querySelectorAll('*'));
                  const textRows = allElements
                    .filter((element) => textOf(element) === '\\u53d1\\u5e03')
                    .filter(visible)
                    .map((element) => rowFor(element, 'exact-text'))
                    .filter(inPublishZone)
                    .sort((left, right) => right.rect.y - left.rect.y);

                  const visualRows = allElements
                    .filter(visible)
                    .map((element) => rowFor(element, 'red-visual'))
                    .filter((row) => {
                      const style = window.getComputedStyle(row.element);
                      const color = parseColor(style.backgroundColor);
                      const text = row.text;
                      return inPublishZone(row)
                        && isRed(color)
                        && row.rect.width >= 56
                        && row.rect.height >= 24
                        && !text.includes('\\u53d1\\u5e03\\u7b14\\u8bb0')
                        && !text.includes('\\u4e0a\\u4f20\\u89c6\\u9891')
                        && !text.includes('\\u5173\\u6ce8');
                    })
                    .sort((left, right) => {
                      const preferredX = window.innerWidth * 0.49;
                      return (right.rect.y - left.rect.y)
                        || (Math.abs(left.rect.centerX - preferredX) - Math.abs(right.rect.centerX - preferredX));
                    });

                  const pointRows = [];
                  const xFactors = [0.49, 0.50, 0.48, 0.52, 0.46, 0.54, 0.44, 0.56];
                  for (let y = window.innerHeight * 0.96; y >= window.innerHeight * 0.66; y -= 8) {
                    for (const factor of xFactors) {
                      const x = window.innerWidth * factor;
                      for (const element of document.elementsFromPoint(x, y)) {
                        if (!visible(element)) continue;
                        const row = rowFor(element, 'point-red-scan');
                        const color = parseColor(window.getComputedStyle(row.element).backgroundColor);
                        if (!inPublishZone(row) || !isRed(color) || row.rect.width < 56 || row.rect.height < 24) continue;
                        if (row.text.includes('\\u53d1\\u5e03\\u7b14\\u8bb0') || row.text.includes('\\u4e0a\\u4f20\\u89c6\\u9891') || row.text.includes('\\u5173\\u6ce8')) continue;
                        pointRows.push(row);
                        break;
                      }
                      if (pointRows.length) break;
                    }
                    if (pointRows.length) break;
                  }

                  const rows = [...textRows, ...pointRows, ...visualRows];
                  const seen = new Set();
                  const uniqueRows = rows.filter((row) => {
                    const key = [Math.round(row.rect.x), Math.round(row.rect.y), Math.round(row.rect.width), Math.round(row.rect.height)].join(':');
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                  });
                  const target = uniqueRows[0];
                  return {
                    ok: Boolean(target),
                    target: target ? {
                      x: target.rect.centerX,
                      y: target.rect.centerY,
                      text: target.text,
                      tag: target.tag,
                      className: target.className,
                      rect: target.rect,
                      topTag: target.topTag,
                      topText: target.topText,
                      topClassName: target.topClassName,
                      isTopSelf: target.isTopSelf,
                      strategy: target.strategy,
                    } : null,
                    candidates: uniqueRows.slice(0, 8).map((row) => ({
                      strategy: row.strategy,
                      text: row.text,
                      tag: row.tag,
                      className: row.className,
                      disabled: row.disabled,
                      ariaDisabled: row.ariaDisabled,
                      rect: row.rect,
                      topTag: row.topTag,
                      topText: row.topText,
                      topClassName: row.topClassName,
                      isTopSelf: row.isTopSelf,
                    })),
                  };
                }
                """
            )
            print("publish_button_diagnostic:", json.dumps(info, ensure_ascii=False))
            target = info.get("target") if isinstance(info, dict) else None
            if target:
                before_url = page.url
                if str(target.get("tag", "")).upper() == "XHS-PUBLISH-BTN":
                    try:
                        host_rect = target.get("hostRect") or target.get("rect") or {}
                        position = {
                            "x": float(target["x"]) - float(host_rect.get("x", 0)),
                            "y": float(target["y"]) - float(host_rect.get("y", 0)),
                        }
                        await page.locator("xhs-publish-btn").nth(int(target.get("hostIndex", 0))).click(
                            position=position,
                            force=True,
                            timeout=3000,
                        )
                        await page.wait_for_timeout(1000)
                        if page.url != before_url and ("from=menu" in page.url or "target=video" in page.url):
                            return False
                        if page.url != before_url:
                            return True
                        if await self._has_publish_confirmation(page) or await self._is_publish_success(page):
                            return True
                    except Exception as exc:
                        print(f"publish_button_host_click_failed: {exc}", flush=True)
                await page.mouse.move(float(target["x"]), float(target["y"]))
                await page.wait_for_timeout(150)
                await page.mouse.click(float(target["x"]), float(target["y"]), delay=120)
                await page.wait_for_timeout(1000)
                if page.url != before_url and ("from=menu" in page.url or "target=video" in page.url):
                    return False
                if page.url != before_url:
                    return True
                if await self._has_publish_confirmation(page) or await self._is_publish_success(page):
                    return True

                clicked = await page.evaluate(
                    """
                    ([x, y]) => {
                      const publishHost = document.querySelector('xhs-publish-btn[submit-text="发布"], xhs-publish-btn[is-publish="true"], xhs-publish-btn');
                      const shadowButton = publishHost && publishHost.shadowRoot
                        ? publishHost.shadowRoot.querySelector('button.bg-red, button[class*="bg-red"], button:last-of-type')
                        : null;
                      if (shadowButton && !shadowButton.disabled) {
                        shadowButton.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
                        shadowButton.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
                        shadowButton.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                        return true;
                      }
                      const clickableFor = (element) => {
                        let current = element;
                        for (let i = 0; i < 6 && current; i += 1) {
                          const style = window.getComputedStyle(current);
                          const role = current.getAttribute('role');
                          const tag = current.tagName.toLowerCase();
                          const className = String(current.className || '');
                          if (tag === 'button' || role === 'button' || style.cursor === 'pointer' || className.includes('button') || className.includes('btn')) {
                            return current;
                          }
                          current = current.parentElement;
                        }
                        return element;
                      };
                      const stack = document.elementsFromPoint(x, y);
                      if (!stack.length) return false;
                      const target = clickableFor(stack[0]);
                      target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
                      target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
                      target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                      return true;
                    }
                    """,
                    [float(target["x"]), float(target["y"])],
                )
                await page.wait_for_timeout(1000)
                if clicked:
                    if page.url != before_url and ("from=menu" in page.url or "target=video" in page.url):
                        return False
                    if page.url != before_url:
                        return True
                    if await self._has_publish_confirmation(page) or await self._is_publish_success(page):
                        return True

            await self._nudge_publish_controls(page)

        fallback = await page.evaluate(
            """
            () => {
              return {
                x: window.innerWidth * 0.49,
                y: window.innerHeight * 0.92,
              };
            }
            """
        )
        before_url = page.url
        await page.mouse.click(float(fallback["x"]), float(fallback["y"]))
        await page.wait_for_timeout(1000)
        if page.url != before_url and ("from=menu" in page.url or "target=video" in page.url):
            return False
        if page.url != before_url:
            return True
        return await self._has_publish_confirmation(page) or await self._is_publish_success(page)

    async def _has_publish_confirmation(self, page: Page) -> bool:
        return bool(
            await page.evaluate(
                """
                () => {
                  const labels = [
                    '\\u786e\\u8ba4\\u53d1\\u5e03',
                    '\\u786e\\u5b9a\\u53d1\\u5e03',
                    '\\u786e\\u8ba4',
                    '\\u786e\\u5b9a',
                  ];
                  return Array.from(document.querySelectorAll('button, [role="button"]'))
                    .some((element) => {
                      const text = (element.innerText || element.textContent || '').trim();
                      const rect = element.getBoundingClientRect();
                      const style = window.getComputedStyle(element);
                      return labels.includes(text)
                        && rect.width > 0
                        && rect.height > 0
                        && rect.left > window.innerWidth * 0.20
                        && rect.right < window.innerWidth * 0.80
                        && rect.top > window.innerHeight * 0.20
                        && rect.bottom < window.innerHeight * 0.92
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                    });
                }
                """
            )
        )

    async def _click_publish_confirmation(self, page: Page) -> None:
        await page.wait_for_timeout(800)
        clicked = await page.evaluate(
            """
            () => {
              const labels = [
                '\\u786e\\u8ba4\\u53d1\\u5e03',
                '\\u786e\\u5b9a\\u53d1\\u5e03',
                '\\u786e\\u8ba4',
                '\\u786e\\u5b9a',
              ];
              const elements = [...document.querySelectorAll('button, [role="button"]')];
              const target = elements.find((element) => {
                const text = (element.textContent || '').trim();
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return labels.includes(text)
                  && rect.width > 0
                  && rect.height > 0
                  && rect.left > window.innerWidth * 0.20
                  && rect.right < window.innerWidth * 0.80
                  && rect.top > window.innerHeight * 0.20
                  && rect.bottom < window.innerHeight * 0.92
                  && style.visibility !== 'hidden'
                  && style.display !== 'none';
              });
              if (!target) return false;
              target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
              target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
              target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
              return true;
            }
            """
        )
        if clicked:
            await page.wait_for_timeout(800)
            return

    async def _wait_for_publish_success(self, page: Page) -> bool:
        for _ in range(40):
            await page.wait_for_timeout(1000)
            if await self._is_publish_success(page):
                return True
        return False

    async def _is_publish_success(self, page: Page) -> bool:
        if "success" in page.url.lower():
            return True
        try:
            text = await page.locator("body").inner_text(timeout=5000)
        except Exception:
            return False
        return "发布成功" in text

    async def _needs_human(self, page: Page) -> bool:
        if "/login" in page.url or "redirectReason=401" in page.url:
            return True
        text = await page.locator("body").inner_text(timeout=10000)
        markers = ["扫码", "验证码", "登录", "安全验证", "风险", "请完成验证"]
        return any(marker in text for marker in markers)

    async def _prepare_images(
        self, images: list[dict[str, Any]], job_id: str, page: Page | None = None
    ) -> list[str]:
        prepared: list[str] = []
        image_dir = Path(settings.screenshots_dir) / "publish-assets" / job_id
        image_dir.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=60) as client:
            for index, image in enumerate(images):
                local_path = image.get("local_path")
                if local_path:
                    prepared.append(local_path)
                    continue
                url = image.get("image_url")
                if not url or url.startswith("data:"):
                    continue
                response = await client.get(url)
                response.raise_for_status()
                suffix = ".png"
                content_type = response.headers.get("content-type", "")
                path = image_dir / f"{index}{suffix}"
                if "svg" in content_type and page is not None:
                    await self._render_svg_as_png(page, response.content, path)
                else:
                    path.write_bytes(response.content)
                prepared.append(str(path))
        return prepared

    async def _render_svg_as_png(self, page: Page, svg: bytes, output_path: Path) -> None:
        renderer = await page.context.new_page()
        encoded = base64.b64encode(svg).decode("ascii")
        try:
            await renderer.set_content(
                f"""
                <html>
                  <body style="margin:0;background:white">
                    <img id="asset" src="data:image/svg+xml;base64,{encoded}" />
                  </body>
                </html>
                """
            )
            asset = renderer.locator("#asset")
            await asset.screenshot(path=str(output_path))
        finally:
            await renderer.close()

    async def _human_required(
        self, context: BrowserContext, page: Page, job: dict[str, Any], reason: str
    ) -> PublishResult:
        job_id = job["job_id"]
        _log(job_id, f"human_required reason={reason}")
        screenshot = await self._screenshot(page, job_id)
        self._active_sessions[job_id] = ActiveBrowserSession(
            context=context,
            page=page,
            job=job,
            stage="requires_human_intervention",
        )
        return PublishResult(
            status="requires_human_intervention",
            screenshot_path=screenshot,
            failure_reason=reason,
        )

    async def _screenshot(self, page: Page, job_id: str) -> str:
        path = Path(settings.screenshots_dir) / f"{job_id}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)

    async def _get_playwright(self) -> Playwright:
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        return self._playwright


def screenshot_to_data_url(path: str | None) -> str | None:
    if not path:
        return None
    data = Path(path).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _accepts_images(accept: str) -> bool:
    if not accept:
        return False
    image_markers = ["image", ".png", ".jpg", ".jpeg", ".webp"]
    video_markers = [".mp4", ".mov", ".flv", ".mkv", ".mpeg", ".mpg"]
    return any(marker in accept for marker in image_markers) and not any(
        marker in accept for marker in video_markers
    )
