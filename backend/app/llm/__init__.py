"""LLM access: one router over Groq and Gemini with caching, budgets, failover and a call log.
The model is only used for free text and ambiguous judgments; it has no tools and no side effects.
"""
