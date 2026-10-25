"""Canonical /api/v1 routes keep their previous paths as deprecated aliases."""

from fastapi import APIRouter


def with_legacy_prefix(routes: APIRouter, *, canonical: str, legacy: str) -> APIRouter:
    mounted = APIRouter()
    mounted.include_router(routes, prefix=canonical)
    mounted.include_router(routes, prefix=legacy, deprecated=True)
    return mounted
