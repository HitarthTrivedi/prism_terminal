"""Experimental cinematic motion system for Prism Studio.

This package is intentionally not wired into GUI routing. It is a small,
reviewable lab for developing motion-film primitives against the same
deterministic Chromium capture layer used by Studio.
"""

from .project import CinematicTheme, build_demo_spec
from .render import render, render_previews, render_transition_previews

__all__ = ["CinematicTheme", "build_demo_spec", "render", "render_previews",
           "render_transition_previews"]
