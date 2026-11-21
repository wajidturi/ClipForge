"""AI providers behind one small interface.

Every provider answers with JSON that must validate against a Pydantic schema; the
caller never parses free text. Transcript and chat text are data, never
instructions (see prompts.py for the delimiting rules).
"""
