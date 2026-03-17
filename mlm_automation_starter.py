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
    uvicorn.run(app, host="127.0.0.1", port=8000)
