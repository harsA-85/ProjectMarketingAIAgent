"""
Team Roles — each editorial team member is an AI with a specialized system prompt.
Follows the same pattern as BaseAgent: wraps a DB row + LLMProvider.
"""
import json
import logging
from typing import Dict, Any, Optional
from src.database.db import get_db
from src.database.models import TeamMember
from src.api.llm_provider import LLMProvider

log = logging.getLogger(__name__)


class TeamRole:
    """Base class for all editorial team AI roles."""

    def __init__(self, role_key: str, db=None):
        self.db = db or get_db()
        self.member = self._load_member(role_key)
        self.llm = LLMProvider(provider=self.member.llm_provider or 'claude')

    def _load_member(self, role_key: str) -> TeamMember:
        member = self.db.query(TeamMember).filter(
            TeamMember.role_key == role_key
        ).first()
        if not member:
            raise ValueError(f"Team member '{role_key}' not found in DB")
        return member

    def call_llm(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call LLM with this role's system prompt."""
        return self.llm.generate_content(
            prompt=prompt,
            system_prompt=self.member.system_prompt,
            max_tokens=max_tokens,
            temperature=self.member.temperature
        )

    def call_llm_json(self, prompt: str, max_tokens: int = 2000) -> Dict[str, Any]:
        """Call LLM and parse the response as JSON."""
        import re
        raw = self.call_llm(prompt, max_tokens)

        # ── Strategy 1: extract content inside ```...``` fences ──────────
        fence_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', raw)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # ── Strategy 2: strip ALL fence markers and try full string ──────
        cleaned = re.sub(r'```(?:json)?', '', raw).strip().strip('`').strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # ── Strategy 3: bracket-matching for outermost { } ───────────────
        def extract_by_bracket(s, open_c, close_c):
            start = s.find(open_c)
            if start == -1:
                return None
            depth = 0
            in_string = False
            escape = False
            for i, ch in enumerate(s[start:], start):
                if escape:
                    escape = False
                    continue
                if ch == '\\' and in_string:
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                if not in_string:
                    if ch == open_c:
                        depth += 1
                    elif ch == close_c:
                        depth -= 1
                        if depth == 0:
                            return s[start:i + 1]
            return None

        for opener, closer in [('{', '}'), ('[', ']')]:
            chunk = extract_by_bracket(cleaned, opener, closer)
            if chunk:
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    pass

        log.warning(f"[{self.member.role_key}] Failed to parse JSON, returning raw text")
        return {"raw_response": raw}

    def call_llm_with_search(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call LLM with live Google Search grounding (Gemini) for real-world intel."""
        return self.llm.generate_with_search(
            prompt=prompt,
            system_prompt=self.member.system_prompt,
            max_tokens=max_tokens,
            temperature=self.member.temperature
        )

    def execute(self, input_data: dict) -> dict:
        """Override in subclasses to perform role-specific work."""
        raise NotImplementedError


# ─── Role Subclasses ───────────────────────────────────────

class HeadOfIntelligence(TeamRole):
    def __init__(self, db=None):
        super().__init__('head_intelligence', db)

    def execute(self, input_data: dict) -> dict:
        topics = input_data.get('topics', [])
        topic_str = ', '.join(topics) if topics else 'real estate, PropTech, housing market, investment'

        # Step 1: Search the web for live intelligence
        search_prompt = (
            f"Search for the latest breaking news, data, and trends about: {topic_str}.\n\n"
            "Find: recent regulatory changes, new market data with specific numbers, "
            "viral social media discussions, technology launches, and emerging consumer patterns. "
            "Include publication names, dates, and specific statistics where available."
        )
        web_intel = self.call_llm_with_search(search_prompt, max_tokens=2000)

        # Step 2: Synthesize into structured trend report
        prompt = (
            f"You have just gathered this live intelligence from the web:\n\n{web_intel}\n\n"
            f"Focus areas: {topic_str}.\n\n"
            "Using ONLY verified, real data from the above intel, produce a Trend Report.\n"
            "Deliver exactly 3 anchor points with real data. "
            "Each anchor point: topic, summary, data_points (real specific numbers/stats), "
            "relevance_score (1-10), content_angle_suggestion.\n\n"
            "Respond in JSON: {anchor_points: [...], market_context: '...', raw_signals: [...]}"
        )
        return self.call_llm_json(prompt, max_tokens=2500)


class EditorInChief(TeamRole):
    def __init__(self, db=None):
        super().__init__('eic', db)

    def execute(self, input_data: dict) -> dict:
        trend_report = json.dumps(input_data.get('trend_report', {}), indent=2)
        prompt = (
            f"Here is today's Trend Report from Intelligence:\n\n{trend_report}\n\n"
            "Choose THE angle for our master content piece. "
            "Don't just report the news — sublimate it. Make it a story worth telling.\n\n"
            "Produce: headline (punchy, under 80 chars), angle (the editorial thesis), "
            "narrative_hook (the opening that makes people stop), emotional_arc (how the reader should feel), "
            "target_audience, tone_notes.\n\n"
            "Respond in JSON."
        )
        return self.call_llm_json(prompt, max_tokens=1500)


class CreativeDirector(TeamRole):
    def __init__(self, db=None):
        super().__init__('creative_director', db)

    def execute(self, input_data: dict) -> dict:
        brief = json.dumps(input_data.get('editorial_brief', {}), indent=2)
        prompt = (
            f"The Editor-in-Chief has chosen this angle:\n\n{brief}\n\n"
            "Produce the visual direction for this piece. "
            "We need images that look Vogue/Wallpaper*-quality, NOT generic AI. "
            "Specify: visual_mood, color_palette, composition_notes, "
            "image_prompt_guidelines (what to include), avoid_list (what to never include), "
            "reference_style (name real photographers/magazines as reference).\n\n"
            "Respond in JSON."
        )
        return self.call_llm_json(prompt, max_tokens=1500)


class SeniorCopywriterInvestigations(TeamRole):
    def __init__(self, db=None):
        super().__init__('copywriter_1', db)

    def execute(self, input_data: dict) -> dict:
        brief = json.dumps(input_data.get('content_brief', {}), indent=2)
        prompt = (
            f"Content Brief:\n\n{brief}\n\n"
            "Write the master content piece. This is the long-form narrative that will be "
            "atomized into multiple platform formats.\n\n"
            "Structure: Hook (2 lines) → Context → Data Revelation → Implication → Call to Action.\n"
            "Target: 600-1200 words. Every paragraph must earn its place.\n\n"
            "Respond in JSON: {body: '...', key_points: [...], hook_line: '...', cta: '...'}"
        )
        return self.call_llm_json(prompt, max_tokens=3000)


class SeniorCopywriterSocial(TeamRole):
    def __init__(self, db=None):
        super().__init__('copywriter_2', db)

    def execute(self, input_data: dict) -> dict:
        brief = json.dumps(input_data.get('content_brief', {}), indent=2)
        master_body = input_data.get('master_body', '')
        prompt = (
            f"Content Brief:\n\n{brief}\n\n"
            f"Master Content Body:\n\n{master_body[:2000]}\n\n"
            "Create social-first versions:\n"
            "1. hooks — 3 alternative opening hooks (controversial but data-backed)\n"
            "2. social_body — punchy version, max 300 words\n"
            "3. thread_version — array of tweet-sized chunks for a Twitter/X thread. "
            "CRITICAL: Each tweet chunk MUST be under 260 characters (emojis count as 2). Aim for 240 chars max per tweet.\n"
            "4. carousel_slides — 5-7 slide texts for an Instagram carousel\n\n"
            "Respond in JSON."
        )
        return self.call_llm_json(prompt, max_tokens=2500)


class PromptEngineerPhoto(TeamRole):
    def __init__(self, db=None):
        super().__init__('prompt_engineer_1', db)

    def execute(self, input_data: dict) -> dict:
        visual_direction = json.dumps(input_data.get('visual_direction', {}), indent=2)
        topic = input_data.get('topic', 'real estate')
        prompt = (
            f"Visual Direction from Creative Director:\n\n{visual_direction}\n\n"
            f"Topic: {topic}\n\n"
            "Craft 3-4 photorealistic image generation prompts. "
            "Each must be highly detailed: subject, lighting, lens, composition, color grading. "
            "ALWAYS include: 'photorealistic, editorial photography, no text, no words, no letters, no watermarks.'\n\n"
            "Respond in JSON: {prompts: ['...', '...', '...'], style_notes: '...'}"
        )
        return self.call_llm_json(prompt, max_tokens=1500)


class PromptEngineerDesign(TeamRole):
    def __init__(self, db=None):
        super().__init__('prompt_engineer_2', db)

    def execute(self, input_data: dict) -> dict:
        visual_direction = json.dumps(input_data.get('visual_direction', {}), indent=2)
        topic = input_data.get('topic', 'real estate')
        prompt = (
            f"Visual Direction from Creative Director:\n\n{visual_direction}\n\n"
            f"Topic: {topic}\n\n"
            "Craft 2-3 design/graphic-style image prompts. "
            "Think: abstract architecture, minimal data visualization aesthetics, Swiss design. "
            "ALWAYS include: 'no text, no words, no letters, no watermarks.'\n\n"
            "Respond in JSON: {prompts: ['...', '...'], style_notes: '...'}"
        )
        return self.call_llm_json(prompt, max_tokens=1200)


class ProductionManager(TeamRole):
    def __init__(self, db=None):
        super().__init__('production_manager', db)

    def execute(self, input_data: dict) -> dict:
        brief = json.dumps(input_data.get('content_brief', {}), indent=2)
        copy_output = json.dumps(input_data.get('copywriter_output', {}), indent=2)
        prompt = (
            f"Content Brief:\n\n{brief}\n\n"
            f"Copywriter Output:\n\n{copy_output}\n\n"
            "Assemble and validate the master content. Check:\n"
            "- Does the headline match the brief's angle?\n"
            "- Is the body well-structured (hook → context → data → implication → CTA)?\n"
            "- Word count appropriate (600-1200)?\n"
            "- Key points are clear and data-backed?\n\n"
            "Produce the final assembled master content.\n"
            "Respond in JSON: {headline, body, key_points, validation_status (pass/warn/fail), "
            "validation_notes, word_count}"
        )
        return self.call_llm_json(prompt, max_tokens=3000)


class DistributionSpecialist(TeamRole):
    def __init__(self, db=None):
        super().__init__('distribution_specialist', db)

    def execute(self, input_data: dict) -> dict:
        master = input_data.get('master_content', {})
        agent_info = input_data.get('agent_info', {})
        prompt = (
            f"Master Content:\n"
            f"Headline: {master.get('headline', '')}\n"
            f"Body: {master.get('body', '')[:2000]}\n"
            f"Key Points: {json.dumps(master.get('key_points', []))}\n\n"
            f"Target Influencer:\n"
            f"Name: {agent_info.get('name', 'Unknown')}\n"
            f"Persona: {agent_info.get('persona', '')}\n"
            f"Tone: {agent_info.get('tone', '')}\n"
            f"Fields: {json.dumps(agent_info.get('fields', []))}\n\n"
            "CRITICAL ROLE CONSTRAINT: This person is an INFLUENCER who comments on real estate — "
            "NOT a real estate agent, broker, or realtor. They do NOT have clients, buyers, sellers, "
            "listings, deals, or commissions. NEVER write first-person broker language: no 'my client', "
            "'my buyer', 'my seller', 'I just closed', 'I just sold', 'my listing', 'my latest deal', "
            "'DM me to buy/sell', 'let me help you find a home'. They observe, analyze, and tell stories "
            "about real estate — they don't transact in it.\n\n"
            "Atomize this content into platform-specific formats FOR THIS INFLUENCER's voice:\n"
            "1. ig_post — Instagram caption (max 2200 chars) with 20-30 hashtags\n"
            "2. twitter_post — ONE single standalone tweet. MUST be under 260 characters total "
            "(emojis count as 2 chars each). Aim for 230-250 chars max. "
            "Do NOT write a thread. Do NOT use 1/, 2/ numbering. Just ONE punchy tweet.\n"
            "3. linkedin_post — Professional (600-1000 words)\n"
            "4. tiktok_script — 30-60 second video script\n\n"
            "CRITICAL: Adapt the tone/voice to match this specific agent's persona.\n"
            "CRITICAL: The twitter_post body field MUST be a single tweet under 260 characters. Not a thread.\n\n"
            "Respond in JSON: {agent_name: '...', formats: [{format_type, platform, body, hashtags}, ...]}"
        )
        return self.call_llm_json(prompt, max_tokens=4000)


# ─── Factory ────────────────────────────────────────────────

ROLE_CLASSES = {
    'eic': EditorInChief,
    'creative_director': CreativeDirector,
    'head_intelligence': HeadOfIntelligence,
    'production_manager': ProductionManager,
    'prompt_engineer_1': PromptEngineerPhoto,
    'prompt_engineer_2': PromptEngineerDesign,
    'copywriter_1': SeniorCopywriterInvestigations,
    'copywriter_2': SeniorCopywriterSocial,
    'distribution_specialist': DistributionSpecialist,
}


def get_role(role_key: str, db=None) -> TeamRole:
    """Factory: get the right TeamRole subclass by role_key."""
    cls = ROLE_CLASSES.get(role_key)
    if not cls:
        raise ValueError(f"Unknown role: {role_key}")
    return cls(db=db)
