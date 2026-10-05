# main.py
import os
import asyncio
import threading
from flask import Flask
from pyrogram import Client
from motor.motor_asyncio import AsyncIOMotorClient

# --- MONKEY PATCH: Fix for pytgcalls + pyrogram version mismatch ---
import pyrogram.errors
import pyrogram.raw.types

if not hasattr(pyrogram.errors, "GroupcallForbidden"):
    pyrogram.errors.GroupcallForbidden = type("GroupcallForbidden", (Exception,), {})
if not hasattr(pyrogram.errors, "GroupcallInvalid"):
    pyrogram.errors.GroupcallInvalid = getattr(pyrogram.errors, "GroupCallInvalid", type("GroupcallInvalid", (Exception,), {}))
if not hasattr(pyrogram.raw.types, "InputGroupCallSlug"):
    class InputGroupCallSlug:
        def __init__(self, slug=None):
            self.slug = slug
    pyrogram.raw.types.InputGroupCallSlug = InputGroupCallSlug
if not hasattr(pyrogram.raw.types, "PhoneCallDiscardReasonMigrateConferenceCall"):
    class PhoneCallDiscardReasonMigrateConferenceCall:
        pass
    pyrogram.raw.types.PhoneCallDiscardReasonMigrateConferenceCall = PhoneCallDiscardReasonMigrateConferenceCall
# --- END MONKEY PATCH ---

from pytgcalls import PyTgCalls
# ... बाकी imports और code
