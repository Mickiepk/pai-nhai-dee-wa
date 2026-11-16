"""Load secrets from SSM Parameter Store at cold start (AWS only)."""

from __future__ import annotations

import os

import boto3

from config import Settings, load_settings

_SECRETS = {
    "LINE_CHANNEL_SECRET_PARAM": "line_channel_secret",
    "LINE_CHANNEL_ACCESS_TOKEN_PARAM": "line_channel_access_token",
    "GEMINI_API_KEY_PARAM": "gemini_api_key",
    "GOOGLE_PLACES_API_KEY_PARAM": "google_places_api_key",
}


def settings_from_ssm() -> Settings:
    settings = load_settings()
    names = {env: os.environ[env] for env in _SECRETS if os.environ.get(env)}
    if not names:
        return settings
    resp = boto3.client("ssm").get_parameters(Names=list(names.values()), WithDecryption=True)
    values = {p["Name"]: p["Value"] for p in resp["Parameters"]}
    updates = {_SECRETS[env]: values[name] for env, name in names.items() if name in values}
    return settings.model_copy(update=updates)
