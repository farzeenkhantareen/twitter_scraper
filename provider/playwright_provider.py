"""
provider/playwright_provider.py
================================
Concrete ``DataProvider`` implementation backed by Playwright + Chromium.

This module is the **only** place in the entire codebase that knows about
Playwright, browser automation, DOM selectors, or X (Twitter) HTML structure.
All other modules interact exclusively through the ``DataProvider`` interface
defined in ``provider/base.py``.

Architecture:
    PlaywrightProvider
        ├── _SessionManager  (internal — manages browser / context lifecycle)
        ├── fetch_posts()    (public — orchestrates page navigation & collection)
        ├── _check_page_errors()
        ├── _locate_boundary()
        ├── _collect_batch()
        └── _parse_article()
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
)

import config
from models import Post
from provider.base import (
    AccountProtectedError,
    AccountSuspendedError,
    AuthenticationError,
    DataProvider,
    ProgressCallback,
    ProviderError,
    RateLimitExceededError,
    UserNotFoundError,
)

logger = logging.getLogger("twitter_scraper.provider.playwright")


# ---------------------------------------------------------------------------
# Internal Browser Session Manager
# ---------------------------------------------------------------------------

class _BrowserSession:
    """
    Manages the lifecycle of a single long-lived Playwright browser context.

    Keeping the context alive across requests avoids the overhead of
    launching a new browser for every scrape operation.
    """

    def __init__(self, auth_path: Path) -> None:
        self._auth_path = auth_path
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    def _verify_auth(self) -> None:
        """
        Verify that the session auth file exists and contains a valid login session.

        Raises:
            AuthenticationError: If the file is missing or doesn't contain an active login token.
        """
        if not self._auth_path.exists():
            raise AuthenticationError(
                f"Authentication file not found: {self._auth_path}. "
                "Run: playwright codegen --save-storage=sessions/auth.json x.com"
            )

        try:
            import json
            with open(self._auth_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            
            cookies = data.get("cookies", [])
            has_auth_token = any(c.get("name") == "auth_token" for c in cookies)
            
            if not has_auth_token:
                raise AuthenticationError(
                    "The session file 'sessions/auth.json' does not contain an active login session "
                    "(missing the 'auth_token' cookie). Please regenerate it: "
                    "playwright codegen --save-storage=sessions/auth.json x.com "
                    "and log in to your X account before closing the browser."
                )
        except json.JSONDecodeError:
            raise AuthenticationError(
                f"The session file '{self._auth_path}' is corrupted or empty. "
                "Please regenerate it: playwright codegen --save-storage=sessions/auth.json x.com"
            )
        except AuthenticationError:
            raise
        except Exception as exc:
            logger.warning("Could not read auth.json during verification: %s", exc)


    async def get_context(self) -> BrowserContext:
        """
        Return the active ``BrowserContext``, initialising it if necessary.

        Performs a lightweight liveness check before returning a cached
        context to catch crashed or disconnected browsers early.

        Returns:
            An active, authenticated Playwright BrowserContext.

        Raises:
            AuthenticationError: auth.json file is missing.
            RuntimeError: Browser failed to launch or context creation failed.
        """
        self._verify_auth()

        # Fast path: reuse if the browser is still connected.
        if self._context and self._browser and self._browser.is_connected():
            try:
                probe = await self._context.new_page()
                await probe.close()
                return self._context
            except Exception as exc:
                logger.warning("Browser context liveness check failed (%s). Reinitialising.", exc)
                await self.close()

        # Slow path: launch a fresh browser and context.
        try:
            if self._playwright is None:
                self._playwright = await async_playwright().start()

            if self._browser is None:
                self._browser = await self._playwright.chromium.launch(
                    headless=config.BROWSER_HEADLESS,
                    args=config.BROWSER_LAUNCH_ARGS,
                )

            logger.info("Creating BrowserContext from saved auth state: %s", self._auth_path)
            self._context = await self._browser.new_context(
                storage_state=str(self._auth_path),
                user_agent=config.BROWSER_USER_AGENT,
                viewport={
                    "width": config.BROWSER_VIEWPORT_WIDTH,
                    "height": config.BROWSER_VIEWPORT_HEIGHT,
                },
            )
            # Mask the WebDriver flag to reduce bot-detection signals.
            await self._context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            return self._context

        except AuthenticationError:
            raise
        except Exception as exc:
            logger.error("Failed to create browser context: %s", exc, exc_info=True)
            await self.close()
            raise RuntimeError(f"Browser initialisation failed: {exc}") from exc

    async def close(self) -> None:
        """Close all browser resources. Safe to call multiple times."""
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        finally:
            self._context = None

        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        finally:
            self._browser = None

        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        finally:
            self._playwright = None

        logger.info("Browser session closed.")


# ---------------------------------------------------------------------------
# Playwright Data Provider
# ---------------------------------------------------------------------------

class PlaywrightProvider(DataProvider):
    """
    Playwright-based implementation of ``DataProvider``.

    Navigates X (Twitter) profiles using a pre-authenticated Chromium
    browser session, scrolls the timeline, parses tweet articles, and
    returns normalised ``Post`` objects.

    Configuration is sourced entirely from ``config.py``.
    """

    def __init__(self) -> None:
        self._session = _BrowserSession(auth_path=config.AUTH_SESSION_PATH)

    # ------------------------------------------------------------------
    # DataProvider lifecycle
    # ------------------------------------------------------------------

    async def initialise(self) -> None:
        """
        Eagerly verify that auth.json exists.

        The browser context itself is lazy — it starts only on first fetch.
        """
        if not config.AUTH_SESSION_PATH.exists():
            raise AuthenticationError(
                "sessions/auth.json not found. "
                "Generate it with: playwright codegen --save-storage=sessions/auth.json x.com"
            )
        logger.info("PlaywrightProvider initialised. Auth file present.")

    async def shutdown(self) -> None:
        """Close the browser and Playwright instance gracefully."""
        logger.info("PlaywrightProvider shutting down.")
        await self._session.close()

    # ------------------------------------------------------------------
    # Public fetch interface
    # ------------------------------------------------------------------

    async def fetch_posts(
        self,
        username: str,
        batch_number: int,
        last_post_id: Optional[str] = None,
        progress_callback: ProgressCallback = None,
    ) -> List[Post]:
        """
        Scrape exactly ``config.BATCH_SIZE`` posts from @username's timeline.

        Implements the ``DataProvider`` contract. Handles boundary location
        (scrolling to the last-seen post), deduplication, and collection.

        Args:
            username: Target handle (no '@').
            batch_number: 1-based batch index (used only for logging).
            last_post_id: ID of the final post from the previous batch.
            progress_callback: Optional async callable for live UI updates.

        Returns:
            Up to ``config.BATCH_SIZE`` unique ``Post`` objects. An empty
            list means the timeline has been exhausted.

        Raises:
            UserNotFoundError, AccountSuspendedError, AccountProtectedError,
            RateLimitExceededError, AuthenticationError, ProviderError
        """
        logger.info(
            "fetch_posts: @%s batch=%d last_post_id=%s",
            username, batch_number, last_post_id,
        )

        async def _report(msg: str) -> None:
            if progress_callback:
                await progress_callback(msg)
            logger.info("[Progress] @%s Batch%d: %s", username, batch_number, msg)

        await _report("Accessing browser session…")
        context = await self._session.get_context()
        page = await context.new_page()

        try:
            # ----------------------------------------------------------
            # 1. Navigate to the profile
            # ----------------------------------------------------------
            target_url = f"https://x.com/{username}"
            await _report(f"Navigating to profile @{username}…")
            logger.info("Navigating to %s", target_url)

            await page.goto(target_url, wait_until="domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT_MS)
            await _report("Checking profile status…")
            await self._check_page_errors(page, username)

            # Wait for at least one tweet article to appear.
            try:
                await page.wait_for_selector(
                    "article[data-testid='tweet']",
                    timeout=config.TWEET_SELECTOR_TIMEOUT_MS,
                )
            except Exception:
                await self._check_page_errors(page, username)
                raise ProviderError("Tweets failed to load — timeline may be empty or blocked.")

            # ----------------------------------------------------------
            # 2. Locate boundary: scroll to last_post_id
            # ----------------------------------------------------------
            if last_post_id:
                await _report(f"Locating last saved post ({last_post_id})…")
                found = await self._locate_boundary(page, last_post_id, _report)
                if not found:
                    logger.warning(
                        "Boundary post %s not found after %d scrolls. Proceeding from current view.",
                        last_post_id, config.MAX_SEARCH_SCROLLS,
                    )

            # ----------------------------------------------------------
            # 3. Collect the next batch
            # ----------------------------------------------------------
            await _report(f"Collecting up to {config.BATCH_SIZE} posts…")
            posts = await self._collect_batch(page, username, last_post_id, _report)

            await _report(f"Batch complete — {len(posts)} posts collected.")
            return posts

        except (UserNotFoundError, AccountSuspendedError, AccountProtectedError,
                RateLimitExceededError, AuthenticationError, ProviderError):
            raise
        except Exception as exc:
            # Capture a screenshot to help diagnose unexpected failures.
            await self._capture_crash_screenshot(page, username, batch_number)
            logger.error("Unexpected provider error: %s", exc, exc_info=True)
            raise ProviderError(f"Provider encountered an unexpected error: {exc}") from exc
        finally:
            await page.close()
            logger.debug("Page closed.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _check_page_errors(self, page: Page, username: str) -> None:
        """
        Inspect the loaded page for common error conditions.

        Raises the appropriate domain exception when a known error state
        is detected. Called after navigation and after selector timeout.

        Args:
            page: The active Playwright page.
            username: Used in error message strings.

        Raises:
            AuthenticationError, UserNotFoundError, AccountSuspendedError,
            AccountProtectedError, RateLimitExceededError, ProviderError
        """
        url = page.url

        # Login redirect → auth session expired or invalid.
        if "/i/flow/login" in url or "/login" in url:
            raise AuthenticationError(
                "Session expired or invalid — redirected to login. "
                "Regenerate sessions/auth.json."
            )

        # Allow dynamic elements a moment to settle.
        await page.wait_for_timeout(config.PAGE_SETTLE_DELAY_MS)

        body_text = await page.locator("body").inner_text()

        # Account not found.
        empty_state = page.locator("[data-testid='emptyState']")
        if await empty_state.count() > 0:
            inner = await empty_state.inner_text()
            if "doesn't exist" in inner or "Try searching" in inner:
                raise UserNotFoundError(f"Username '{username}' does not exist on X.")

        # Account suspended.
        if "Account suspended" in body_text:
            raise AccountSuspendedError(f"The account '@{username}' has been suspended.")

        # Protected / private timeline.
        protected_el = page.locator("text=These posts are protected")
        if await protected_el.count() > 0:
            raise AccountProtectedError(
                f"The account '@{username}' is protected. Only followers can view posts."
            )

        # Rate limit or platform error.
        if "Rate limit exceeded" in body_text or "Something went wrong" in body_text:
            tweet_count = await page.locator("article[data-testid='tweet']").count()
            if tweet_count == 0:
                raise RateLimitExceededError(
                    "X (Twitter) rate limit exceeded or platform error. Please try again later."
                )

    async def _locate_boundary(
        self,
        page: Page,
        last_post_id: str,
        report: ProgressCallback,
    ) -> bool:
        """
        Scroll the page until ``last_post_id`` is visible in the DOM.

        Args:
            page: Active Playwright page.
            last_post_id: The post ID to search for.
            report: Progress callback.

        Returns:
            True if the boundary post was found, False otherwise.
        """
        for attempt in range(config.MAX_SEARCH_SCROLLS):
            if report:
                await report(f"Scrolling to boundary post… (attempt {attempt + 1})")

            articles = page.locator("article[data-testid='tweet']")
            count = await articles.count()

            for idx in range(count):
                article = articles.nth(idx)
                if await self._article_contains_post_id(article, last_post_id):
                    logger.info("Boundary post %s found after %d scrolls.", last_post_id, attempt)
                    return True

            # Scroll down and wait.
            await page.evaluate("window.scrollBy(0, 800)")
            delay = config.SCROLL_DELAY_SECONDS * 0.75 + config.SCROLL_JITTER_FACTOR * (attempt % 3)
            await asyncio.sleep(delay)

        return False

    async def _article_contains_post_id(self, article: Locator, post_id: str) -> bool:
        """Return True if the given article element's status link matches ``post_id``."""
        try:
            time_el = article.locator("time")
            if await time_el.count() > 0:
                link_el = article.locator("time").locator("xpath=ancestor::a")
                if await link_el.count() > 0:
                    href = await link_el.first.get_attribute("href") or ""
                    if post_id in href:
                        return True
        except Exception:
            pass
        return False

    async def _collect_batch(
        self,
        page: Page,
        username: str,
        last_post_id: Optional[str],
        report: ProgressCallback,
    ) -> List[Post]:
        """
        Collect up to ``config.BATCH_SIZE`` unique posts from the current page position.

        Handles deduplication and skips posts at or before ``last_post_id``.

        Args:
            page: Active Playwright page scrolled to the boundary position.
            username: Target handle for author filtering.
            last_post_id: Boundary post ID; all posts up to and including
                this ID are skipped.
            report: Progress callback.

        Returns:
            List of unique ``Post`` objects.
        """
        collected: List[Post] = []
        seen_ids: Set[str] = set()
        skipped_boundary = (last_post_id is None)  # Skip nothing if no boundary.
        scroll_count = 0

        while len(collected) < config.BATCH_SIZE and scroll_count < config.MAX_COLLECTION_SCROLLS:
            if report:
                await report(f"Gathering posts… ({len(collected)}/{config.BATCH_SIZE} found)")

            articles = page.locator("article[data-testid='tweet']")
            count = await articles.count()

            for idx in range(count):
                article = articles.nth(idx)
                post = await self._parse_article(article, username)

                if post is None:
                    continue

                # Skip until we pass the boundary post.
                if not skipped_boundary:
                    if post.post_id == last_post_id:
                        skipped_boundary = True
                    continue  # Skip this post (boundary or before it).

                # Deduplicate within current batch.
                if post.post_id in seen_ids:
                    continue

                seen_ids.add(post.post_id)
                collected.append(post)
                logger.debug("Collected post %s (%d/%d)", post.post_id, len(collected), config.BATCH_SIZE)

                if len(collected) >= config.BATCH_SIZE:
                    break

            if len(collected) < config.BATCH_SIZE:
                logger.debug("Need more posts. Scrolling… (%d collected)", len(collected))
                await page.evaluate("window.scrollBy(0, 1000)")
                scroll_count += 1
                await asyncio.sleep(config.SCROLL_DELAY_SECONDS)

        if len(collected) < config.BATCH_SIZE:
            logger.warning(
                "Only %d/%d posts collected after %d scrolls.",
                len(collected), config.BATCH_SIZE, scroll_count,
            )

        return collected[: config.BATCH_SIZE]

    async def _parse_article(self, article: Locator, target_username: str) -> Optional[Post]:
        """
        Parse a single tweet article DOM element into a ``Post`` object.

        Returns ``None`` if the post ID cannot be resolved or a parse error
        prevents building a valid Post.

        Args:
            article: Playwright Locator pointing to an ``<article>`` element.
            target_username: Fallback author name when author block is absent.

        Returns:
            A populated ``Post`` or ``None`` on failure.
        """
        try:
            # ── 1. Post ID and URL ────────────────────────────────────────
            post_id = ""
            post_url = ""
            created_at = ""

            time_el = article.locator("time")
            if await time_el.count() > 0:
                created_at = await time_el.first.get_attribute("datetime") or ""
                link_el = article.locator("time").locator("xpath=ancestor::a")
                if await link_el.count() > 0:
                    href = await link_el.first.get_attribute("href") or ""
                    match = re.search(r"/status/(\d+)", href)
                    if match:
                        post_id = match.group(1)
                        post_url = f"https://x.com{href}" if href.startswith("/") else href

            # Fallback: scan all status links in the article.
            if not post_id:
                status_links = article.locator("a[href*='/status/']")
                for i in range(await status_links.count()):
                    href = await status_links.nth(i).get_attribute("href") or ""
                    match = re.search(r"/status/(\d+)", href)
                    if match:
                        post_id = match.group(1)
                        post_url = f"https://x.com{href}" if href.startswith("/") else href
                        break

            if not post_id:
                return None  # Cannot track or deduplicate without an ID.

            # ── 2. Author ─────────────────────────────────────────────────
            display_name = target_username
            author_handle = target_username

            user_el = article.locator("[data-testid='User-Name']")
            if await user_el.count() > 0:
                raw = await user_el.first.inner_text()
                parts = raw.split("\n")
                if len(parts) >= 1:
                    display_name = parts[0].strip()
                if len(parts) >= 2:
                    author_handle = parts[1].replace("@", "").strip()

            # ── 3. Text, hashtags, mentions, external links ───────────────
            text = ""
            hashtags: List[str] = []
            mentions: List[str] = []
            external_links: List[str] = []

            text_el = article.locator("[data-testid='tweetText']")
            if await text_el.count() > 0:
                text = await text_el.first.inner_text()
                anchors = text_el.locator("a")
                for i in range(await anchors.count()):
                    anchor = anchors.nth(i)
                    href = await anchor.get_attribute("href") or ""
                    anchor_text = (await anchor.inner_text()).strip()

                    if href.startswith("/hashtag/") or "q=%23" in href:
                        tag = anchor_text.lstrip("#")
                        if tag and tag not in hashtags:
                            hashtags.append(tag)
                    elif anchor_text.startswith("@"):
                        handle = anchor_text.lstrip("@")
                        if handle and handle not in mentions:
                            mentions.append(handle)
                    elif href.startswith("http") or href.startswith("t.co"):
                        if href not in external_links:
                            external_links.append(href)

            # ── 4. Engagement counts ──────────────────────────────────────
            reply_count = await self._get_count(article.locator("[data-testid='reply']"))
            repost_count = await self._get_count(article.locator("[data-testid='retweet']"))
            like_count = await self._get_count(article.locator("[data-testid='like']"))

            view_count = 0
            view_el = article.locator("a[href*='/analytics']")
            if await view_el.count() == 0:
                view_el = article.locator("[data-testid='app-bar-view-count']")
            if await view_el.count() > 0:
                raw_view = await view_el.first.inner_text()
                view_count = self._parse_number(raw_view.replace("Views", "").strip())

            # ── 5. Media URLs ─────────────────────────────────────────────
            media_urls: List[str] = []
            photos = article.locator("[data-testid='tweetPhoto'] img")
            for i in range(await photos.count()):
                src = await photos.nth(i).get_attribute("src")
                if src:
                    media_urls.append(src)

            videos = article.locator("video")
            for i in range(await videos.count()):
                src = await videos.nth(i).get_attribute("src")
                poster = await videos.nth(i).get_attribute("poster")
                if src:
                    media_urls.append(src)
                elif poster:
                    media_urls.append(poster)

            # ── 6. Assemble Post ──────────────────────────────────────────
            return Post(
                post_id=post_id,
                username=author_handle,
                display_name=display_name,
                created_at=created_at or datetime.now(tz=timezone.utc).isoformat(),
                text=text,
                url=post_url,
                reply_count=reply_count,
                repost_count=repost_count,
                like_count=like_count,
                view_count=view_count,
                hashtags=hashtags,
                mentions=mentions,
                media_urls=media_urls,
                external_links=external_links,
            )

        except Exception as exc:
            logger.warning("Failed to parse article element: %s", exc, exc_info=False)
            return None

    async def _get_count(self, locator: Locator) -> int:
        """
        Safely extract the numeric engagement count from a tweet action element.

        Tries inner text first, then falls back to the ``aria-label`` attribute.

        Args:
            locator: Playwright Locator for a tweet action button element.

        Returns:
            Parsed integer count, or 0 if unavailable.
        """
        try:
            if await locator.count() > 0:
                text = (await locator.first.inner_text()).strip()
                if text:
                    return self._parse_number(text)
                # Fallback: parse from aria-label (e.g. "1,234 Likes").
                aria = await locator.first.get_attribute("aria-label") or ""
                if aria:
                    match = re.search(r"([\d,]+\.?\d*[KMB]?)", aria, re.IGNORECASE)
                    if match:
                        return self._parse_number(match.group(1))
        except Exception:
            pass
        return 0

    @staticmethod
    def _parse_number(text: str) -> int:
        """
        Convert Twitter's abbreviated stat strings to integers.

        Examples:
            ``"1.2K"`` → ``1200``
            ``"5.4M"`` → ``5400000``
            ``"450"``  → ``450``

        Args:
            text: Raw stat string from the DOM.

        Returns:
            Integer representation, or 0 if parsing fails.
        """
        if not text:
            return 0
        cleaned = text.strip().upper().replace(",", "")
        try:
            if "M" in cleaned:
                return int(float(cleaned.replace("M", "")) * 1_000_000)
            if "K" in cleaned:
                return int(float(cleaned.replace("K", "")) * 1_000)
            if "B" in cleaned:
                return int(float(cleaned.replace("B", "")) * 1_000_000_000)
            return int(float(cleaned))
        except (ValueError, TypeError):
            match = re.search(r"(\d+)", cleaned)
            return int(match.group(1)) if match else 0

    async def _capture_crash_screenshot(
        self, page: Page, username: str, batch_number: int
    ) -> None:
        """
        Save a viewport screenshot to the logs directory for post-mortem debugging.

        Args:
            page: The Playwright page at the time of failure.
            username: Used to generate a descriptive filename.
            batch_number: Used to generate a descriptive filename.
        """
        ts = int(datetime.now(tz=timezone.utc).timestamp())
        path = config.LOGS_DIR / f"crash_{username}_{batch_number}_{ts}.png"
        try:
            config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(path))
            logger.info("Crash screenshot saved to %s", path)
        except Exception as exc:
            logger.error("Failed to save crash screenshot: %s", exc)

    async def fetch_latest_post(
        self,
        username: str,
        progress_callback: ProgressCallback = None,
    ) -> Optional[Post]:
        """
        Retrieve the single newest post on the user's timeline (excluding pinned posts).
        """
        async def _report(msg: str) -> None:
            if progress_callback:
                await progress_callback(msg)
            logger.info("[Progress] @%s Latest Post: %s", username, msg)

        await _report("Accessing browser session…")
        context = await self._session.get_context()
        page = await context.new_page()

        try:
            target_url = f"https://x.com/{username}"
            await _report(f"Navigating to profile @{username}…")
            await page.goto(target_url, wait_until="domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT_MS)
            await _report("Checking profile status…")
            await self._check_page_errors(page, username)

            # Wait for at least one tweet article to appear.
            await page.wait_for_selector(
                "article[data-testid='tweet']",
                timeout=config.TWEET_SELECTOR_TIMEOUT_MS,
            )

            # Find all tweet articles on the page.
            articles = page.locator("article[data-testid='tweet']")
            count = await articles.count()
            
            for idx in range(count):
                article = articles.nth(idx)
                # Check if it has a pinned badge
                social_context = article.locator("[data-testid='socialContext']")
                is_pinned = False
                if await social_context.count() > 0:
                    context_text = await social_context.first.inner_text()
                    if "Pinned" in context_text:
                        is_pinned = True
                
                if is_pinned:
                    logger.info("Skipping pinned tweet at index %d", idx)
                    continue

                post = await self._parse_article(article, username)
                if post:
                    await _report("Latest post fetched successfully.")
                    return post

            # Fallback to the first post regardless of pinned state
            if count > 0:
                post = await self._parse_article(articles.first, username)
                if post:
                    return post

            raise ProviderError("Failed to extract any posts from the timeline.")

        except Exception as exc:
            await self._capture_crash_screenshot(page, username, 999)
            raise ProviderError(f"Failed to fetch latest post: {exc}") from exc
        finally:
            await page.close()
