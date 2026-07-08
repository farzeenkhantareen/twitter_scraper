import re
import logging
import asyncio
from datetime import datetime
from typing import List, Optional, Tuple, Set
from playwright.async_api import BrowserContext, Page, Locator
from models import Tweet, ScraperState
from session import SessionManager

logger = logging.getLogger("twitter_scraper.scraper")

class ScrapeError(Exception):
    """Base exception for scraping operations."""
    pass

class UserNotFoundError(ScrapeError):
    """Raised when the target user profile does not exist."""
    pass

class AccountSuspendedError(ScrapeError):
    """Raised when the target account has been suspended."""
    pass

class AccountProtectedError(ScrapeError):
    """Raised when the target account is private/protected."""
    pass

class RateLimitExceededError(ScrapeError):
    """Raised when X rate limits are encountered."""
    pass

class TwitterScraper:
    """Handles the navigation, scrolling, and parsing of tweets from public X profiles."""

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager

    def _parse_number(self, text: str) -> int:
        """Converts Twitter's abbreviated stat numbers (e.g. '1.2K', '5.4M') into integers."""
        if not text:
            return 0
        
        # Clean text
        text = text.strip().upper().replace(",", "")
        try:
            if "M" in text:
                return int(float(text.replace("M", "")) * 1_000_000)
            elif "K" in text:
                return int(float(text.replace("K", "")) * 1_000)
            return int(text)
        except Exception:
            # Fallback regex search for any digits if parsing failed
            match = re.search(r'(\d+)', text)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    return 0
            return 0

    async def _check_page_errors(self, page: Page, username: str) -> None:
        """Checks the page for common account or network level errors."""
        url = page.url
        
        # 1. Check for Login Redirection
        if "/i/flow/login" in url or "/login" in url:
            logger.error("Session has expired or is invalid. Redirected to login flow.")
            raise ScrapeError("Authentication session expired. Please update sessions/auth.json.")

        # Give dynamic elements a brief moment to settle
        await page.wait_for_timeout(1000)

        # 2. Check User Not Found
        empty_state = page.locator("[data-testid='emptyState']")
        if await empty_state.count() > 0:
            text = await empty_state.inner_text()
            if "This account doesn’t exist" in text or "Try searching for another" in text:
                logger.error(f"User profile '{username}' does not exist.")
                raise UserNotFoundError(f"Username '{username}' does not exist on X.")

        # 3. Check Account Suspended
        body_text = await page.locator("body").inner_text()
        if "Account suspended" in body_text:
            logger.error(f"User profile '{username}' is suspended.")
            raise AccountSuspendedError(f"The account '{username}' has been suspended.")

        # 4. Check Protected Profile
        if "These posts are protected" in body_text or "lock" in body_text.lower() and "protected" in body_text:
            # Check specifically for lock graphic or protected text
            protected_el = page.locator("text=These posts are protected")
            if await protected_el.count() > 0:
                logger.error(f"User profile '{username}' is private/protected.")
                raise AccountProtectedError(f"The account '{username}' is protected. Cannot scrape posts.")

        # 5. Check Rate Limits
        if "Rate limit exceeded" in body_text or "Something went wrong. Try reloading." in body_text:
            # Double check if tweets are rendering despite warning
            tweets_count = await page.locator("article[data-testid='tweet']").count()
            if tweets_count == 0:
                logger.error("Rate limit encountered or general error loading page content.")
                raise RateLimitExceededError("X (Twitter) rate limit exceeded or connection issue. Try again later.")

    async def _extract_tweet_data(self, article: Locator, target_username: str) -> Optional[Tweet]:
        """Parses a single tweet article locator and returns a Tweet object."""
        try:
            # 1. Identify Tweet ID and URL
            # The timestamp is nested inside a link that points directly to the tweet status
            time_el = article.locator("time")
            tweet_id = ""
            tweet_url = ""
            tweet_date = ""

            if await time_el.count() > 0:
                tweet_date = await time_el.first.get_attribute("datetime") or ""
                # Find the ancestor <a> tag of the <time> tag
                link_el = article.locator("time").locator("xpath=ancestor::a")
                if await link_el.count() > 0:
                    href = await link_el.first.get_attribute("href") or ""
                    # Path is usually: /username/status/1234567890
                    match = re.search(r'/status/(\d+)', href)
                    if match:
                        tweet_id = match.group(1)
                        tweet_url = f"https://x.com{href}" if href.startswith("/") else href
            
            # If we couldn't resolve the Tweet ID, we cannot track it. Skip.
            if not tweet_id:
                # Try finding any status link as fallback
                status_links = article.locator("a[href*='/status/']")
                count = await status_links.count()
                for i in range(count):
                    href = await status_links.nth(i).get_attribute("href") or ""
                    match = re.search(r'/status/(\d+)', href)
                    if match:
                        tweet_id = match.group(1)
                        tweet_url = f"https://x.com{href}" if href.startswith("/") else href
                        break
            
            if not tweet_id:
                return None

            # 2. Extract Author Username and Display Name
            user_name_el = article.locator("[data-testid='User-Name']")
            display_name = target_username
            author_username = target_username
            
            if await user_name_el.count() > 0:
                user_text = await user_name_el.first.inner_text()
                # Text formatted as: "DisplayName\n@username\n·\nDate"
                parts = user_text.split('\n')
                if len(parts) > 0:
                    display_name = parts[0]
                if len(parts) > 1:
                    author_username = parts[1].replace("@", "")

            # 3. Extract Tweet Text
            text_el = article.locator("[data-testid='tweetText']")
            tweet_text = ""
            hashtags: Set[str] = set()
            mentions: Set[str] = set()
            links: Set[str] = set()

            if await text_el.count() > 0:
                tweet_text = await text_el.first.inner_text()
                
                # Parse links, hashtags, and mentions from anchor tags inside the text block
                anchors = text_el.locator("a")
                anchor_count = await anchors.count()
                for idx in range(anchor_count):
                    anchor = anchors.nth(idx)
                    href = await anchor.get_attribute("href") or ""
                    text_content = await anchor.inner_text()
                    
                    if href.startswith("/hashtag/") or "q=%23" in href:
                        hashtags.add(text_content.strip())
                    elif text_content.startswith("@") or (href.startswith("/") and not href.startswith("/search") and len(href) > 1):
                        mentions.add(text_content.strip())
                    elif href.startswith("http") or href.startswith("t.co"):
                        links.add(href)

            # 4. Extract Stats (likes, retweets, replies, bookmarks)
            reply_el = article.locator("[data-testid='reply']")
            repost_el = article.locator("[data-testid='retweet']")
            like_el = article.locator("[data-testid='like']")
            bookmark_el = article.locator("[data-testid='bookmark']")
            
            # Views are sometimes linked inside analytics or specific containers
            view_el = article.locator("a[href*='/analytics']")
            if await view_el.count() == 0:
                view_el = article.locator("[data-testid='app-bar-view-count']")
            
            # Fetch stats values
            reply_count = await self._get_stat_value(reply_el)
            repost_count = await self._get_stat_value(repost_el)
            like_count = await self._get_stat_value(like_el)
            bookmark_count = await self._get_stat_value(bookmark_el)
            
            view_str = None
            if await view_el.count() > 0:
                raw_view = await view_el.first.inner_text()
                if raw_view:
                    view_str = raw_view.replace("Views", "").strip()

            # 5. Extract Media Elements
            media_list = []
            
            # Photos
            photo_els = article.locator("[data-testid='tweetPhoto'] img")
            photo_count = await photo_els.count()
            for idx in range(photo_count):
                src = await photo_els.nth(idx).get_attribute("src")
                if src:
                    media_list.append(src)
                    
            # Videos (check for video tags)
            video_els = article.locator("video")
            video_count = await video_els.count()
            for idx in range(video_count):
                src = await video_els.nth(idx).get_attribute("src")
                if src:
                    media_list.append(src)
                else:
                    # Video sometimes uses a poster URL if stream source is dynamic blob
                    poster = await video_els.nth(idx).get_attribute("poster")
                    if poster:
                        media_list.append(poster)

            return Tweet(
                tweet_id=tweet_id,
                username=author_username,
                display_name=display_name,
                text=tweet_text,
                date=tweet_date or datetime.utcnow().isoformat(),
                url=tweet_url,
                reply_count=reply_count,
                repost_count=repost_count,
                like_count=like_count,
                bookmark_count=bookmark_count,
                view_count=view_str,
                hashtags=list(hashtags),
                mentions=list(mentions),
                media=media_list,
                links=list(links)
            )
            
        except Exception as e:
            logger.warning(f"Error parsing tweet element: {e}", exc_info=True)
            return None

    async def _get_stat_value(self, locator: Locator) -> int:
        """Helper to safely retrieve the numeric value of a tweet action icon."""
        try:
            if await locator.count() > 0:
                text = await locator.first.inner_text()
                if not text:
                    # Try label text
                    aria = await locator.first.get_attribute("aria-label")
                    if aria:
                        # Extract digits/metrics
                        match = re.search(r'(\d+[\d,.]*[KMB]?)', aria)
                        if match:
                            text = match.group(1)
                return self._parse_number(text)
        except Exception:
            pass
        return 0

    async def scrape_batch(self, username: str, batch_number: int, last_tweet_id: Optional[str] = None, progress_callback = None) -> List[Tweet]:
        """
        Scrapes a batch of 10 unique tweets from the target profile.
        
        Args:
            username: Target user profile handle.
            batch_number: The index of the current batch.
            last_tweet_id: The ID of the last tweet scraped in previous batches.
            progress_callback: Async callable that takes a string progress message.
            
        Returns:
            A list of 10 parsed unique Tweet objects.
        """
        logger.info(f"Starting scrape for '{username}' (Batch {batch_number}, last_tweet_id={last_tweet_id})")
        if progress_callback:
            await progress_callback("Accessing browser session context...")
            
        context = await self.session_manager.get_context()
        page = await context.new_page()
        
        # Implement dynamic delays and human-like scroll behavior
        try:
            # Navigate to target profile
            target_url = f"https://x.com/{username}"
            logger.info(f"Navigating to {target_url}")
            if progress_callback:
                await progress_callback(f"Navigating to profile @{username}...")
            
            # Wait for main page load
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            
            if progress_callback:
                await progress_callback("Checking profile status...")
            # Check for critical errors (suspended, profile missing, login required, etc.)
            await self._check_page_errors(page, username)
            
            # Wait for at least one tweet to be loaded
            try:
                await page.wait_for_selector("article[data-testid='tweet']", timeout=15000)
            except Exception:
                # Recheck page level errors in case selector timed out due to page redirection/block
                await self._check_page_errors(page, username)
                raise ScrapeError("Tweets failed to load. The timeline may be empty or blocked.")

            scraped_tweets: List[Tweet] = []
            scraped_ids: Set[str] = set()
            
            # If last_tweet_id exists, scroll down until finding it
            found_last_tweet = False
            if last_tweet_id:
                logger.info(f"Searching for last scraped tweet ID: {last_tweet_id}")
                if progress_callback:
                    await progress_callback(f"Searching for last scraped tweet ({last_tweet_id})...")
                scroll_attempts = 0
                max_scrolls = 35  # Cap the scroll to avoid infinite loops if tweet was deleted
                
                while not found_last_tweet and scroll_attempts < max_scrolls:
                    if progress_callback:
                        await progress_callback(f"Scrolling to locate starting tweet (attempt {scroll_attempts + 1})...")
                        
                    # Fetch visible articles
                    articles = page.locator("article[data-testid='tweet']")
                    count = await articles.count()
                    
                    for idx in range(count):
                        art = articles.nth(idx)
                        time_el = art.locator("time")
                        if await time_el.count() > 0:
                            link_el = art.locator("time").locator("xpath=ancestor::a")
                            if await link_el.count() > 0:
                                href = await link_el.first.get_attribute("href") or ""
                                if last_tweet_id in href:
                                    found_last_tweet = True
                                    logger.info(f"Found last scraped tweet {last_tweet_id} in DOM after {scroll_attempts} scrolls.")
                                    break
                    
                    if not found_last_tweet:
                        # Scroll down by 800px to fetch older elements
                        await page.evaluate("window.scrollBy(0, 800)")
                        scroll_attempts += 1
                        # Human-like delay
                        await asyncio.sleep(1.5 + (0.5 * (scroll_attempts % 3)))
                
                if not found_last_tweet:
                    logger.warning(
                        f"Could not find last tweet ID '{last_tweet_id}' after {max_scrolls} scrolls. "
                        "It might have been deleted, or is too far back. Continuing from current view."
                    )
                    # We proceed anyway rather than crashing, to avoid getting stuck forever
                    found_last_tweet = True

            # Collection loop: collect exactly 10 unique tweets
            collecting = True
            scroll_count = 0
            max_collection_scrolls = 50
            
            # Use a list to check for the position of the last tweet to skip duplicates
            # If we just found the last tweet, we want to only collect tweets *below* it in the DOM order.
            # When found_last_tweet was completed, we are scrolled to its position.
            skipped_prior = not last_tweet_id  # If no last_tweet_id, nothing to skip
            
            while len(scraped_tweets) < 10 and scroll_count < max_collection_scrolls:
                if progress_callback:
                    await progress_callback(f"Gathering tweets... (Found {len(scraped_tweets)}/10 unique)")
                    
                articles = page.locator("article[data-testid='tweet']")
                count = await articles.count()
                
                for idx in range(count):
                    art = articles.nth(idx)
                    
                    # Ensure element is valid and not empty before processing
                    tweet_data = await self._extract_tweet_data(art, username)
                    if not tweet_data:
                        continue
                        
                    # Skip logic if we are searching for the last tweet's boundary
                    if last_tweet_id and not skipped_prior:
                        if tweet_data.tweet_id == last_tweet_id:
                            skipped_prior = True
                        continue  # Skip this and all elements preceding it
                        
                    # Deduplicate in the current batch
                    if tweet_data.tweet_id not in scraped_ids:
                        scraped_tweets.append(tweet_data)
                        scraped_ids.add(tweet_data.tweet_id)
                        
                        logger.debug(f"Collected tweet: {tweet_data.tweet_id} | Total: {len(scraped_tweets)}")
                        
                        if len(scraped_tweets) == 10:
                            break
                
                if len(scraped_tweets) < 10:
                    # Scroll down to fetch more tweets
                    logger.debug("Need more tweets. Scrolling down...")
                    if progress_callback:
                        await progress_callback(f"Scrolling for more content... (Collected {len(scraped_tweets)}/10)")
                    await page.evaluate("window.scrollBy(0, 1000)")
                    scroll_count += 1
                    await asyncio.sleep(2.0)
            
            if len(scraped_tweets) < 10:
                logger.warning(f"Only managed to scrape {len(scraped_tweets)} tweets after {scroll_count} scrolls.")
            
            if progress_callback:
                await progress_callback(f"Completed batch of {len(scraped_tweets)} tweets.")
            return scraped_tweets[:10]
            
        except (UserNotFoundError, AccountSuspendedError, AccountProtectedError, RateLimitExceededError) as e:
            # Re-raise known exceptions directly
            raise e
        except Exception as e:
            # Capture screenshot to logs directory for debugging if browser crash / captcha occurred
            screenshot_path = Path(__file__).resolve().parent / "logs" / f"crash_{username}_{batch_number}_{int(datetime.utcnow().timestamp())}.png"
            try:
                await page.screenshot(path=str(screenshot_path))
                logger.info(f"Saved crash screenshot to {screenshot_path}")
            except Exception as se:
                logger.error(f"Failed to capture crash screenshot: {se}")
            
            logger.error(f"Unexpected scraping error: {e}", exc_info=True)
            raise ScrapeError(f"Scraper encountered an issue: {e}")
        finally:
            # Always close page to clean up resources, keeping the context alive
            await page.close()
            logger.debug("Closed browser page.")
