"""
routes/ai.py
============
Endpoints for AI Analyst Mode using Groq API.
"""

import asyncio
import json
import logging
import urllib.request
from pathlib import Path
from fastapi import APIRouter, HTTPException
import os
from pydantic import BaseModel

import config

logger = logging.getLogger("twitter_scraper.routes.ai")

router = APIRouter()

# Read the Groq API key from environment variables for security.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"


class ChatRequest(BaseModel):
    message: str


class MessageItem(BaseModel):
    role: str
    content: str


class SaveChatRequest(BaseModel):
    history: list[MessageItem]


def _get_downloaded_posts() -> list[dict]:
    """Helper to scan downloaded_json folder and load unique posts."""
    downloaded_dir = config.BASE_DIR / "downloaded_json"
    if not downloaded_dir.exists() or not downloaded_dir.is_dir():
        return []

    posts = []
    seen_ids = set()

    for file_path in downloaded_dir.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                
            # Single post objects vs List of post objects
            if isinstance(data, dict):
                items = [data]
            elif isinstance(data, list):
                items = data
            else:
                continue

            for item in items:
                post_id = item.get("post_id")
                if post_id and post_id not in seen_ids:
                    seen_ids.add(post_id)
                    posts.append(item)
        except Exception as exc:
            logger.error("Failed to parse JSON file %s: %s", file_path.name, exc)
            
    return posts


def _call_groq_api(messages: list[dict]) -> str:
    """Synchronous function to perform the Groq API HTTP request."""
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.3
    }
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GROQ_API_URL,
        data=req_data,
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_body = response.read().decode("utf-8")
            res_data = json.loads(res_body)
            return res_data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8")
            logger.error("Groq API returned HTTP error %d: %s", exc.code, err_body)
            err_data = json.loads(err_body)
            msg = err_data.get("error", {}).get("message", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(
            status_code=502,
            detail=f"Error communicating with AI service (Groq): {msg}"
        )
    except Exception as exc:
        logger.error("Groq API request failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Error communicating with AI service (Groq): {exc}"
        )


@router.get("/ai/status", summary="Get status of downloaded context files")
async def ai_status() -> dict:
    """Scan downloaded_json directory and return counts of files and posts."""
    downloaded_dir = config.BASE_DIR / "downloaded_json"
    file_count = 0
    if downloaded_dir.exists() and downloaded_dir.is_dir():
        file_count = len(list(downloaded_dir.glob("*.json")))
        
    try:
        posts = _get_downloaded_posts()
        return {
            "file_count": file_count,
            "tweet_count": len(posts)
        }
    except Exception as exc:
        logger.error("Failed to compile AI context status: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to scan AI folder: {exc}")


@router.post("/ai/chat", summary="Query the AI assistant with scraped posts context")
async def ai_chat(req: ChatRequest) -> dict:
    """
    Load scraped posts, format context, and query Groq LLM.
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")

    # 1. Load context
    try:
        posts = _get_downloaded_posts()
    except Exception as exc:
        logger.error("Failed to load posts for AI context: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to load scraped posts: {exc}")

    # Sort posts by created_at descending (newest first) to ensure the AI gets the most recent data
    posts.sort(key=lambda p: str(p.get("created_at") or ""), reverse=True)
    
    # Limit context to the latest 20 unique posts to prevent exceeding Groq payload/token limits (HTTP 413 / 429)
    posts = posts[:20]

    # 2. Format context
    formatted_posts = []
    for post in posts:
        formatted_posts.append(
            f"Tweet ID: {post.get('post_id')}\n"
            f"Author: {post.get('display_name')} (@{post.get('username')})\n"
            f"Date: {post.get('created_at')}\n"
            f"Content: {post.get('text', '')}\n"
            f"Metrics: Likes: {post.get('like_count', 0)}, Reposts: {post.get('repost_count', 0)}, "
            f"Replies: {post.get('reply_count', 0)}, Views: {post.get('view_count', 0)}\n"
            f"Hashtags: {', '.join(post.get('hashtags', []))}\n"
            f"Mentions: {', '.join(post.get('mentions', []))}\n"
            f"Link: {post.get('url', '')}\n"
            f"---"
        )
    
    context_str = "\n".join(formatted_posts) if formatted_posts else "No posts have been scraped or downloaded yet."

    # 3. Create prompt
    system_prompt = (
        "You are a helpful AI analyst designed to answer questions based on a dataset of scraped X (Twitter) posts.\n\n"
        "Here is the context of scraped posts:\n"
        "<scraped_posts>\n"
        f"{context_str}\n"
        "</scraped_posts>\n\n"
        "GUIDELINES:\n"
        "1. If the user's question can be answered using the provided scraped posts, answer the question accurately based on the data. Mention specific posts, handles, dates, or metrics where appropriate.\n"
        "2. If the user's question is NOT related to the scraped posts or is out of context:\n"
        "   - First, explicitly write: \"This question is out of the context of the scraped posts, but here is the answer: \"\n"
        "   - Then, provide a helpful and accurate answer to their question using your general knowledge.\n"
        "3. Be detailed, comprehensive, and thorough in your responses. Format your responses beautifully using Markdown, utilizing headers, bold text, lists, and tables where appropriate to present information clearly.\n"
        "4. Elaborate on the background, implications, metrics, or analytical significance of the tweets to make your answers as rich and informative as possible."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": req.message}
    ]

    # 4. Invoke API asynchronously in a separate thread to prevent blocking
    try:
        response_content = await asyncio.to_thread(_call_groq_api, messages)
        return {"response": response_content}
    except HTTPException as http_exc:
        raise http_exc
    except Exception as exc:
        logger.error("AI service error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"AI query failed: {exc}")


@router.post("/ai/save", summary="Save chat history to ai_saved_chat directory")
async def save_chat(req: SaveChatRequest) -> dict:
    """Save the chat history to a JSON file inside ai_saved_chat/."""
    if not req.history:
        raise HTTPException(status_code=400, detail="Cannot save empty chat history.")

    import datetime
    
    # Resolve and ensure directory exists
    save_dir = config.BASE_DIR / "ai_saved_chat"
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.error("Failed to create ai_saved_chat directory: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create save directory on server.")

    # Format filename with current timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"chat_{timestamp}.json"
    filepath = save_dir / filename

    try:
        data = [item.model_dump() for item in req.history]
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=4)
        
        logger.info("Saved chat history to %s", filepath)
        return {"message": "Success", "filename": filename}
    except Exception as exc:
        logger.error("Failed to save chat file %s: %s", filepath, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to write chat file: {exc}")
