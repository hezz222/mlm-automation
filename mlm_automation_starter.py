"""
MLM / direct sales content automation starter

What this script does
- Stores product / audience / compliance settings
- Generates platform-specific content prompts
- Builds a weekly content queue
- Creates lead magnets and CTA variants
- Simulates publishing to YouTube, Facebook, and Instagram
- Captures leads into SQLite
- Schedules follow-up messages
- Scores leads for simple prioritization

What this script does NOT do yet
- It does not directly call OpenAI or social APIs until you add keys and endpoint logic.
- It does not auto-post to Meta/YouTube out of the box.
- It is designed as a clean starter architecture you can extend.

How to run
1. pip install fastapi uvicorn pydantic python-dotenv
2. uvicorn mlm_automation_starter:app --reload
3. Open http://127.0.0.1:8000/docs

You can later split this into modules once your workflow is stable.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel, Field


# =========================
# CONFIGURATION
# =========================

APP_NAME = "MLM Content Automation Starter"
DB_PATH = os.getenv("MLM_AUTOMATION_DB", "mlm_automation.db")
TIMEZONE = os.getenv("TIMEZONE", "America/Phoenix")
BRAND_NAME = os.getenv("BRAND_NAME", "Choose Your Hard")
COMPANY_NAME = os.getenv("COMPANY_NAME", "Melaleuca")
DEFAULT_EMAIL_FROM = os.getenv("DEFAULT_EMAIL_FROM", "noreply@example.com")


# =========================
# DATABASE SETUP
# =========================

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            phone TEXT,
            platform TEXT,
            interest TEXT,
            source TEXT,
            score INTEGER DEFAULT 0,
            status TEXT DEFAULT 'new',
            created_at TEXT NOT NULL,
            last_contacted_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS content_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            title TEXT NOT NULL,
            hook TEXT,
            body TEXT,
            cta TEXT,
            status TEXT DEFAULT 'draft',
            scheduled_for TEXT,
            published_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS follow_ups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            message TEXT NOT NULL,
            send_at TEXT NOT NULL,
            sent_at TEXT,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


init_db()


# =========================
# ENUMS AND MODELS
# =========================

class Platform(str, Enum):
    youtube = "youtube"
    facebook = "facebook"
    instagram = "instagram"


class LeadStatus(str, Enum):
    new = "new"
    contacted = "contacted"
    nurtured = "nurtured"
    qualified = "qualified"
    customer = "customer"
    inactive = "inactive"


class AudienceProfile(BaseModel):
    niche: str = Field(..., examples=["busy moms wanting cleaner products"])
    pain_points: List[str]
    desired_outcomes: List[str]
    beliefs: List[str] = []
    objections: List[str] = []


class ProductTheme(BaseModel):
    name: str
    key_benefits: List[str]
    ingredients_to_avoid: List[str] = []
    compliance_notes: List[str] = []


class ContentRequest(BaseModel):
    platform: Platform
    topic: str
    audience: AudienceProfile
    product: ProductTheme
    call_to_action: str
    tone: str = "encouraging, clear, non-hype"


class LeadCreate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    platform: str
    interest: Optional[str] = None
    source: Optional[str] = None


class FollowUpRequest(BaseModel):
    lead_id: int
    days_from_now: int = 1
    channel: str = "email"
    message: str


class WeeklyPlanRequest(BaseModel):
    audience: AudienceProfile
    product: ProductTheme
    weekly_theme: str
    days: int = 7


class PublishRequest(BaseModel):
    content_id: int


# =========================
# CORE DOMAIN LOGIC
# =========================

@dataclass
class ContentPiece:
    platform: str
    title: str
    hook: str
    body: str
    cta: str
    scheduled_for: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class ComplianceGuard:
    """Simple compliance helper for direct sales / wellness messaging.

    This is intentionally conservative.
    Extend based on your company's current policy.
    """

    RED_FLAG_TERMS = [
        "cure",
        "treat",
        "heal disease",
        "guaranteed income",
        "get rich",
        "medical claim",
        "replace your doctor",
    ]

    @classmethod
    def validate(cls, text: str) -> List[str]:
        issues: List[str] = []
        lowered = text.lower()
        for term in cls.RED_FLAG_TERMS:
            if term in lowered:
                issues.append(f"Potential compliance issue: '{term}'")
        return issues


class PromptBuilder:
    @staticmethod
    def build(request: ContentRequest) -> Dict[str, str]:
        base_context = (
            f"Brand: {BRAND_NAME}. Company: {COMPANY_NAME}. "
            f"Audience niche: {request.audience.niche}. "
            f"Pain points: {', '.join(request.audience.pain_points)}. "
            f"Desired outcomes: {', '.join(request.audience.desired_outcomes)}. "
            f"Objections: {', '.join(request.audience.objections) if request.audience.objections else 'none listed'}. "
            f"Product theme: {request.product.name}. "
            f"Benefits: {', '.join(request.product.key_benefits)}. "
            f"Avoid ingredients: {', '.join(request.product.ingredients_to_avoid) if request.product.ingredients_to_avoid else 'n/a'}. "
            f"CTA: {request.call_to_action}. Tone: {request.tone}."
        )

        platform_rules = {
            "youtube": "Create a YouTube short script with hook, 3 value beats, and a CTA. Add video caption and title.",
            "facebook": "Create a Facebook post with a strong opening, short story, authority without hype, and a CTA.",
            "instagram": "Create an Instagram reel caption with a short hook, emotional connection, line breaks, and CTA. Include 8 hashtags.",
        }

        system_prompt = (
            "You are a content strategist for a values-based direct sales brand. "
            "Write content that is helpful, compliant, human, specific, and never spammy."
        )

        user_prompt = f"{base_context} {platform_rules[request.platform.value]} Topic: {request.topic}."

        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }


class ContentGenerator:
    """Stub generator.

    Replace generate() with an LLM API call if desired.
    """

    @staticmethod
    def generate(request: ContentRequest) -> ContentPiece:
        prompts = PromptBuilder.build(request)

        title = f"{request.topic.title()} | {request.platform.value.title()}"
        hook = f"What if the products in your home are making healthy living harder, not easier?"
        body = (
            f"Today we are talking about {request.topic}. "
            f"For {request.audience.niche}, this matters because {request.audience.pain_points[0]} can feel overwhelming. "
            f"One reason people explore {request.product.name} is {request.product.key_benefits[0]}. "
            f"This is about making better choices one step at a time, not perfection. "
            f"Prompt basis: {prompts['user_prompt']}"
        )
        cta = request.call_to_action

        issues = ComplianceGuard.validate(" ".join([title, hook, body, cta]))
        if issues:
            body += "\n\nCOMPLIANCE REVIEW NEEDED:\n- " + "\n- ".join(issues)

        return ContentPiece(
            platform=request.platform.value,
            title=title,
            hook=hook,
            body=body,
            cta=cta,
        )


class QueueService:
    @staticmethod
    def add_content(item: ContentPiece) -> int:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO content_queue (platform, title, hook, body, cta, status, scheduled_for, created_at)
            VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                item.platform,
                item.title,
                item.hook,
                item.body,
                item.cta,
                item.scheduled_for,
                item.created_at,
            ),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()
        return int(row_id)

    @staticmethod
    def list_content(status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_conn()
        cur = conn.cursor()
        if status:
            rows = cur.execute(
                "SELECT * FROM content_queue WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT * FROM content_queue ORDER BY created_at DESC"
            ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def schedule_content(content_id: int, scheduled_for: str) -> None:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE content_queue SET scheduled_for = ?, status = 'scheduled' WHERE id = ?",
            (scheduled_for, content_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Content item not found")
        conn.close()

    @staticmethod
    def publish_content(content_id: int) -> Dict[str, Any]:
        conn = get_conn()
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM content_queue WHERE id = ?", (content_id,)
        ).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Content item not found")

        now = datetime.utcnow().isoformat()
        cur.execute(
            "UPDATE content_queue SET status = 'published', published_at = ? WHERE id = ?",
            (now, content_id),
        )
        conn.commit()
        conn.close()

        payload = dict(row)
        payload["published_at"] = now
        payload["simulated_api_result"] = SocialPublisher.publish(payload)
        return payload


class SocialPublisher:
    """Simulated publish layer.

    Replace these methods with real API calls:
    - YouTube Data API
    - Meta Graph API for Facebook/Instagram
    - Or a scheduler like Make/Zapier/n8n
    """

    @staticmethod
    def publish(content: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "platform": content["platform"],
            "message": f"Simulated publish to {content['platform']}",
            "title": content["title"],
        }


class LeadScoring:
    @staticmethod
    def score(lead: LeadCreate) -> int:
        score = 0
        if lead.email:
            score += 25
        if lead.phone:
            score += 20
        if lead.interest:
            score += 25
        if lead.source and lead.source.lower() in {"lead magnet", "webinar", "dm", "quiz"}:
            score += 20
        if lead.platform.lower() in {"instagram", "facebook", "youtube"}:
            score += 10
        return min(score, 100)


class LeadService:
    @staticmethod
    def create(lead: LeadCreate) -> Dict[str, Any]:
        score = LeadScoring.score(lead)
        now = datetime.utcnow().isoformat()

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO leads (name, email, phone, platform, interest, source, score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lead.name,
                lead.email,
                lead.phone,
                lead.platform,
                lead.interest,
                lead.source,
                score,
                now,
            ),
        )
        conn.commit()
        lead_id = cur.lastrowid
        row = cur.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        conn.close()
        return dict(row)

    @staticmethod
    def list_all() -> List[Dict[str, Any]]:
        conn = get_conn()
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM leads ORDER BY score DESC, created_at DESC").fetchall()
        conn.close()
        return [dict(row) for row in rows]


class FollowUpService:
    @staticmethod
    def schedule(req: FollowUpRequest) -> Dict[str, Any]:
        conn = get_conn()
        cur = conn.cursor()

        lead = cur.execute("SELECT * FROM leads WHERE id = ?", (req.lead_id,)).fetchone()
        if not lead:
            conn.close()
            raise HTTPException(status_code=404, detail="Lead not found")

        send_at = (datetime.utcnow() + timedelta(days=req.days_from_now)).isoformat()
        cur.execute(
            """
            INSERT INTO follow_ups (lead_id, channel, message, send_at, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (req.lead_id, req.channel, req.message, send_at),
        )
        conn.commit()
        follow_up_id = cur.lastrowid
        row = cur.execute("SELECT * FROM follow_ups WHERE id = ?", (follow_up_id,)).fetchone()
        conn.close()
        return dict(row)

    @staticmethod
    def run_pending() -> List[Dict[str, Any]]:
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()

        rows = cur.execute(
            "SELECT * FROM follow_ups WHERE status = 'pending' AND send_at <= ? ORDER BY send_at ASC",
            (now,),
        ).fetchall()

        processed: List[Dict[str, Any]] = []
        for row in rows:
            result = MessageSender.send(channel=row["channel"], message=row["message"])
            cur.execute(
                "UPDATE follow_ups SET status = 'sent', sent_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), row["id"]),
            )
            processed.append({**dict(row), "result": result})

        conn.commit()
        conn.close()
        return processed


class MessageSender:
    @staticmethod
    def send(channel: str, message: str) -> Dict[str, Any]:
        return {
            "success": True,
            "channel": channel,
            "message_preview": message[:120],
        }


class WeeklyPlanner:
    """Generates a simple weekly cross-platform content plan."""

    @staticmethod
    def build(req: WeeklyPlanRequest) -> List[ContentPiece]:
        themes = [
            f"{req.weekly_theme}: ingredient awareness",
            f"{req.weekly_theme}: healthier swaps",
            f"{req.weekly_theme}: common objections",
            f"{req.weekly_theme}: family routines",
            f"{req.weekly_theme}: behind the brand",
            f"{req.weekly_theme}: testimony/story",
            f"{req.weekly_theme}: invitation/CTA",
        ]

        platforms = [Platform.youtube, Platform.facebook, Platform.instagram]
        queue: List[ContentPiece] = []

        for day in range(min(req.days, len(themes))):
            platform = platforms[day % len(platforms)]
            content_req = ContentRequest(
                platform=platform,
                topic=themes[day],
                audience=req.audience,
                product=req.product,
                call_to_action="Comment CLEAN and I will send you the guide.",
            )
            piece = ContentGenerator.generate(content_req)
            piece.scheduled_for = (datetime.utcnow() + timedelta(days=day)).isoformat()
            queue.append(piece)

        return queue


# =========================
# SYSTEME.IO WEBHOOK HELPERS
# =========================

SYSTEME_WEBHOOK_SECRET = os.getenv("SYSTEME_WEBHOOK_SECRET", "change-me")


def log_event(event_type: str, payload: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO automation_logs (event_type, payload, created_at) VALUES (?, ?, ?)",
        (event_type, payload, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def upsert_lead_from_systeme(payload: Dict[str, Any]) -> Dict[str, Any]:
    contact = payload.get("contact") or payload.get("data", {}).get("contact") or payload.get("data", {}).get("customer") or {}

    raw_fields = contact.get("fields") or []
    field_map: Dict[str, Any] = {}

    if isinstance(raw_fields, list):
        for item in raw_fields:
            if isinstance(item, dict) and item.get("slug"):
                field_map[item["slug"]] = item.get("value")
    elif isinstance(raw_fields, dict):
        field_map = raw_fields

    first_name = field_map.get("first_name")
    last_name = field_map.get("surname")
    full_name = " ".join([p for p in [first_name, last_name] if p]) or None

    lead = LeadCreate(
        name=full_name,
        email=contact.get("email"),
        phone=field_map.get("phone_number"),
        platform="systeme",
        interest=payload.get("type") or "contact.created",
        source="systeme.io webhook",
    )
    return LeadService.create(lead)


# =========================
# FASTAPI APP
# =========================

app = FastAPI(title=APP_NAME)


@app.get("/")
def healthcheck() -> Dict[str, str]:
    return {
        "app": APP_NAME,
        "status": "ok",
        "brand": BRAND_NAME,
        "company": COMPANY_NAME,
        "timezone": TIMEZONE,
    }


@app.post("/webhooks/systeme")
async def systeme_webhook(
    request: Request,
    x_systeme_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    try:
        payload = await request.json()
        print("SYSTEME PAYLOAD:", payload, flush=True)
        event_type = payload.get("type", "unknown")

        if x_systeme_secret and x_systeme_secret != SYSTEME_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

        log_event(event_type=event_type, payload=str(payload))

        created_lead: Optional[Dict[str, Any]] = None
        if payload.get("contact") or payload.get("data", {}).get("contact") or payload.get("data", {}).get("customer"):
            try:
                created_lead = upsert_lead_from_systeme(payload)
            except Exception as exc:
                log_event(event_type="systeme_webhook_error", payload=str(exc))
                return {
                    "ok": False,
                    "received_type": event_type,
                    "error": str(exc),
                }

        return {
            "ok": True,
            "received_type": event_type,
            "lead_created": created_lead,
        }
    except HTTPException:
        raise
    except Exception as exc:
        log_event(event_type="systeme_webhook_fatal", payload=str(exc))
        return {
            "ok": False,
            "received_type": "unknown",
            "error": str(exc),
        }
    except HTTPException:
        raise
    except Exception as exc:
        log_event(event_type="systeme_webhook_fatal", payload=str(exc))
        return {
            "ok": False,
            "received_type": "unknown",
            "error": str(exc),
        }


@app.post("/content/generate")
def generate_content(req: ContentRequest) -> Dict[str, Any]:
    piece = ContentGenerator.generate(req)
    content_id = QueueService.add_content(piece)
    return {
        "content_id": content_id,
        "platform": piece.platform,
        "title": piece.title,
        "hook": piece.hook,
        "body": piece.body,
        "cta": piece.cta,
    }


@app.get("/content")
def list_content(status: Optional[str] = None) -> List[Dict[str, Any]]:
    return QueueService.list_content(status=status)


@app.post("/content/{content_id}/schedule")
def schedule_content(content_id: int, when_iso: str) -> Dict[str, Any]:
    QueueService.schedule_content(content_id, when_iso)
    return {"success": True, "content_id": content_id, "scheduled_for": when_iso}


@app.post("/content/publish")
def publish_content(req: PublishRequest) -> Dict[str, Any]:
    return QueueService.publish_content(req.content_id)


@app.post("/planner/weekly")
def build_weekly_plan(req: WeeklyPlanRequest) -> Dict[str, Any]:
    queue = WeeklyPlanner.build(req)
    ids: List[int] = []
    for item in queue:
        ids.append(QueueService.add_content(item))
    return {
        "created": len(ids),
        "content_ids": ids,
        "message": "Weekly content plan added to queue",
    }


@app.post("/leads")
def create_lead(req: LeadCreate) -> Dict[str, Any]:
    return LeadService.create(req)


@app.get("/leads")
def list_leads() -> List[Dict[str, Any]]:
    return LeadService.list_all()


@app.post("/followups")
def schedule_followup(req: FollowUpRequest) -> Dict[str, Any]:
    return FollowUpService.schedule(req)


@app.post("/followups/run")
def run_pending_followups() -> List[Dict[str, Any]]:
    return FollowUpService.run_pending()


# =========================
# OPTIONAL: SAMPLE PAYLOADS
# =========================

SAMPLE_AUDIENCE = {
    "niche": "busy moms wanting cleaner products and healthier homes",
    "pain_points": [
        "confusion about ingredients",
        "lack of time to research products",
        "feeling overwhelmed by unhealthy options",
    ],
    "desired_outcomes": [
        "simpler swaps",
        "cleaner home routines",
        "more confidence in product choices",
    ],
    "beliefs": [
        "small changes matter",
        "what we bring into the home matters",
    ],
    "objections": [
        "it seems expensive",
        "I do not have time",
        "I need proof before switching",
    ],
}

SAMPLE_PRODUCT = {
    "name": "clean home essentials",
    "key_benefits": [
        "simpler ingredient-conscious options",
        "helps families make better household swaps",
        "supports a cleaner-home lifestyle",
    ],
    "ingredients_to_avoid": [
        "chlorine bleach",
        "phthalates",
        "formaldehyde-releasing preservatives",
    ],
    "compliance_notes": [
        "avoid disease claims",
        "avoid guaranteed income claims",
    ],
}


@app.get("/samples")
def get_samples() -> Dict[str, Any]:
    return {
        "audience": SAMPLE_AUDIENCE,
        "product": SAMPLE_PRODUCT,
        "example_generate_content_payload": {
            "platform": "instagram",
            "topic": "3 cleaner swaps for busy moms",
            "audience": SAMPLE_AUDIENCE,
            "product": SAMPLE_PRODUCT,
            "call_to_action": "DM me CLEAN for the guide.",
            "tone": "encouraging, trustworthy, practical",
        },
        "example_weekly_plan_payload": {
            "audience": SAMPLE_AUDIENCE,
            "product": SAMPLE_PRODUCT,
            "weekly_theme": "clean living made simple",
            "days": 7,
        },
    }


# =========================
# FUTURE INTEGRATIONS
# =========================

"""
NEXT STEPS YOU CAN ADD:

1. OPENAI CONTENT GENERATION
   - Replace ContentGenerator.generate() with an OpenAI API call.
   - Return structured JSON for title, hook, caption, CTA, hashtags.

2. META + YOUTUBE POSTING
   - Add real publish methods in SocialPublisher.
   - Use environment variables for API tokens.

3. LEAD CAPTURE FORM
   - Build a landing page or connect Typeform / Tally / ConvertKit.
   - POST new leads into /leads.

4. EMAIL / SMS NURTURE
   - Connect SendGrid, MailerLite, ConvertKit, Twilio, or HighLevel.
   - Replace MessageSender.send().

5. DASHBOARD
   - Add a frontend in React or use Streamlit for easy internal use.

6. COMPLIANCE WORKFLOW
   - Add required disclaimer blocks.
   - Add a manual approval state before publishing.
"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
