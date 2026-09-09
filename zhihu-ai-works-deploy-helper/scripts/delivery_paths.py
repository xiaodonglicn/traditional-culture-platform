#!/usr/bin/env python3
"""Normalize names shared by deployment descriptors and project archives."""

from __future__ import annotations


def delivery_directory_name(value: str) -> str:
    if not value or value in {".", ".."} or any(ord(character) < 32 for character in value):
        raise ValueError("project directory name cannot form a safe delivery directory")
    normalized = "".join("_" if character.isspace() else character for character in value)
    if not normalized or any(character.isspace() for character in normalized):
        raise ValueError("project directory name cannot form a space-free delivery directory")
    return normalized
