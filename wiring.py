"""Build the SessionEngine from Settings. The only place that picks real vs fake providers."""

from __future__ import annotations

from adapters.line import FakeLine, LineGateway, RealLine
from adapters.llm import Extractor, GeminiExtractor, RuleExtractor
from adapters.places import FakePlaces, GooglePlaces, Places
from config import Settings
from session.engine import SessionEngine
from store.base import Store
from store.memory import MemoryStore


def build_engine(settings: Settings, *, store: Store | None = None, line: LineGateway | None = None,
                 llm: Extractor | None = None, places: Places | None = None) -> SessionEngine:
    if store is None:
        if settings.store_provider == "dynamo":
            from store.dynamo import DynamoStore

            store = DynamoStore(settings.table_name)
        elif settings.store_provider == "postgres":
            from store.postgres import PostgresStore

            store = PostgresStore(settings.database_url)
        else:
            store = MemoryStore()
    if line is None:
        line = RealLine(settings.line_channel_access_token) if settings.line_provider == "real" else FakeLine()
    if llm is None:
        rules = RuleExtractor()
        llm = (GeminiExtractor(settings.gemini_api_key, settings.gemini_model, rules)
               if settings.llm_provider == "gemini" else rules)
    if places is None:
        places = (GooglePlaces(settings.google_places_api_key)
                  if settings.places_provider == "google" else FakePlaces())
    return SessionEngine(settings, store, line, llm, places)
