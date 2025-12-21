# backend/main.py
from dotenv import load_dotenv
load_dotenv()

from typing import List, Optional, Literal
from fastapi import FastAPI
from pydantic import BaseModel, Field
import os
import json
import sys

from google import genai
types = genai.types  # alias for convenience

<<<<<<< Updated upstream
app = FastAPI()
=======
# ----------------------------
# Retry config (tune here)
# ----------------------------
RETRY_INITIAL_DELAY_SEC = float(os.getenv("GEMINI_RETRY_INITIAL_DELAY", "0.35"))
RETRY_MAX_DELAY_SEC = float(os.getenv("GEMINI_RETRY_MAX_DELAY", "2.0"))
RETRY_MAX_ATTEMPTS = int(os.getenv("GEMINI_RETRY_MAX_ATTEMPTS", "12"))
RETRY_JITTER_SEC = float(os.getenv("GEMINI_RETRY_JITTER_SEC", "0.10"))
>>>>>>> Stashed changes


# ----------------------------
# Payload models
# ----------------------------
class FileInfo(BaseModel):
    filename: str
    status: Optional[str] = None
    additions: Optional[int] = None
    deletions: Optional[int] = None
    changes: Optional[int] = None
    patch: Optional[str] = None  # unified diff string


class ReviewCommentInfo(BaseModel):
    id: int
    body: str
    path: Optional[str] = None
    diff_hunk: Optional[str] = None
    position: Optional[int] = None
    line: Optional[int] = None
    original_line: Optional[int] = None
    user_login: Optional[str] = None


class ProjectContextDoc(BaseModel):
    path: str
    url: Optional[str] = None
    kind: Optional[str] = None  # "style_guide" | "architecture" | etc.
    excerpt: Optional[str] = None


class ReviewPayload(BaseModel):
    # "review" | "review_comment" | "issue_comment" | "wizard_review_command"
    kind: str

    # review-level fields
    review_body: Optional[str] = None
    review_state: Optional[str] = None

    # comment-level fields
    comment_body: Optional[str] = None
    comment_path: Optional[str] = None
    comment_diff_hunk: Optional[str] = None
    comment_position: Optional[int] = None
    comment_id: Optional[int] = None

    reviewer_login: Optional[str] = None
    pr_number: int
    pr_title: Optional[str] = None
    pr_body: Optional[str] = None
    pr_author_login: Optional[str] = None
    repo_full_name: str
    repo_owner: Optional[str] = None
    repo_name: Optional[str] = None
    repo_default_branch: Optional[str] = None

    files: Optional[List[FileInfo]] = None

    # all inline comments that belong to this finished review
    review_comments: Optional[List[ReviewCommentInfo]] = None

    # Optional project context docs (FR2.3)
    project_context_docs: Optional[List[ProjectContextDoc]] = None


class BackendResponse(BaseModel):
    comment: str


# ----------------------------
# Gemini structured output model
# ----------------------------
Category = Literal[
    "PRAISE",
    "GOOD_CHANGE",
    "BAD_CHANGE",
    "GOOD_QUESTION",
    "BAD_QUESTION",
    "UNKNOWN",  # safety fallback
]


class Classification(BaseModel):
    category: Category
    needs_reply: bool = Field(..., description="True only for GOOD_CHANGE, BAD_CHANGE, BAD_QUESTION.")
    needs_clarification: bool = Field(..., description="True only for BAD_CHANGE or BAD_QUESTION.")
    confidence: float = Field(..., ge=0.0, le=1.0)
    short_reason: str = Field(..., description="One short sentence. No chain-of-thought.")


<<<<<<< Updated upstream
=======
class ClarifiedQuestion(BaseModel):
    clarified_question: str = Field(..., description="A rewritten, clarified version of the original question.")
    confidence: float = Field(..., ge=0.0, le=1.0)
    short_reason: str = Field(..., description="One short sentence on what was ambiguous / what you clarified.")
    reference_urls: List[str] = Field(default_factory=list, description="0-3 links to relevant project conventions, if any.")


class ClarifiedChange(BaseModel):
    clarified_request: str = Field(
        ...,
        description="A rewritten, clarified change request. Must be actionable but may contain placeholders like <which function?>.",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    short_reason: str = Field(..., description="One short sentence on what was unclear / what you clarified.")
    reference_urls: List[str] = Field(default_factory=list, description="0-3 links to relevant project conventions, if any.")


class DiscussionReply(BaseModel):
    needs_reply: bool
    reply_markdown: str = Field(..., description="A short PR discussion reply. No code review unless /wizard-review.")
    reference_urls: List[str] = Field(default_factory=list, description="0-3 links to relevant project conventions, if any.")
    short_reason: str = Field(..., description="One short sentence. No chain-of-thought.")


class CandidateReviewComment(BaseModel):
    title: str = Field(..., description="Short title (max ~8 words).")
    description: str = Field(..., description="1-3 sentences describing the issue and why it matters.")
    file_path: Optional[str] = None
    reference_urls: List[str] = Field(default_factory=list, description="0-3 links to relevant project conventions, if any.")


class CandidateReviewOutput(BaseModel):
    comments: List[CandidateReviewComment] = Field(default_factory=list)


>>>>>>> Stashed changes
# ----------------------------
# Helpers
# ----------------------------
def get_client() -> genai.Client:
    """Returns the synchronous Gemini client."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=api_key)


def clip(s: Optional[str], n: int) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[:n] + "\n…(truncated)…"


def build_llm_context(payload: ReviewPayload) -> str:
    """
    Compact, high-signal context for classification and suggestion.
    """
    pr_title = payload.pr_title or ""
    pr_body = clip(payload.pr_body, 1200)

    base = f"""
Repo: {payload.repo_full_name}
PR: #{payload.pr_number} — {pr_title}
PR author: {payload.pr_author_login}

PR description (truncated):
{pr_body}
""".strip()

    # Event-specific context
    if payload.kind == "review_comment":
        comment_text = payload.comment_body or ""
        path = payload.comment_path or ""
        hunk = clip(payload.comment_diff_hunk, 1200)

        base += f"""

Event: inline review comment
Reviewer: {payload.reviewer_login}
File path: {path}
Original comment:
{clip(comment_text, 1500)}

Diff hunk (truncated):
{hunk}
""".rstrip()

<<<<<<< Updated upstream
=======
    elif payload.kind == "issue_comment":
        comment_text = payload.comment_body or ""
        base += f"""

Event: PR discussion comment (not a review)
Author: {payload.reviewer_login}
Comment:
{clip(comment_text, 2000)}
""".rstrip()

    elif payload.kind == "wizard_review_command":
        comment_text = payload.comment_body or payload.review_body or ""
        path = payload.comment_path or ""
        hunk = clip(payload.comment_diff_hunk, 1200)

        base += f"""

Event: /wizard-review command
Author: {payload.reviewer_login}
Command comment:
{clip(comment_text, 1200)}
""".rstrip()

        if path:
            base += f"\n\nTriggered near file path: {path}\n"
        if hunk.strip():
            base += f"\nDiff hunk (truncated):\n{hunk}\n"

>>>>>>> Stashed changes
    else:
        review_text = payload.review_body or ""
        base += f"""

Event: review submitted
Reviewer: {payload.reviewer_login}
State: {payload.review_state}
Review body:
{clip(review_text, 2000)}
""".rstrip()

        if payload.review_comments:
            base += "\n\nInline comments in this review (showing up to 5):\n"
            for c in payload.review_comments[:5]:
                base += (
                    f"- id={c.id} file={c.path} line={c.line or c.position} "
                    f"by {c.user_login}: {clip(c.body, 400)}\n"
                )

<<<<<<< Updated upstream
    # Include changed files + patches (truncated)
=======
    # Diff context
>>>>>>> Stashed changes
    files = payload.files or []
    if files:
        base += f"\n\nChanged files: {len(files)} (showing up to 6 patches, truncated)\n"
        for f in files[:6]:
            base += (
                f"\n---\nFILE: {f.filename}\nSTATUS: {f.status} "
                f"(+{f.additions}/-{f.deletions}, changes={f.changes})\n"
                f"PATCH:\n{clip(f.patch, 1200)}\n"
            )

    # Project docs context (FR2.3)
    docs = payload.project_context_docs or []
    if docs:
        base += "\n\nProject context docs (configured):\n"
        for d in docs[:6]:
            label = f"[{d.kind}] " if d.kind else ""
            base += (
                f"\n---\nDOC: {label}{d.path}\n"
                f"URL: {d.url or '(no url)'}\n"
                f"EXCERPT:\n{clip(d.excerpt, 1400)}\n"
            )

    return base.strip()

<<<<<<< Updated upstream
# NOTE: This function is SYNCHRONOUS (no 'async')
=======

def extract_first_fenced_code_block(text: str) -> str:
    """
    Return ONLY the first fenced code block (```...```).
    If none found, wrap whole text in a plain ``` block as a fallback.
    """
    if not text:
        return "```diff\n```"

    m = re.search(r"```[a-zA-Z0-9_-]*\n.*?\n```", text, flags=re.DOTALL)
    if m:
        return m.group(0).strip()

    if "```" in text:
        first = text.find("```")
        return text[first:].strip()

    return f"```\n{text.strip()}\n```"


# ----------------------------
# Gemini retry wrapper (sync)
# ----------------------------
T = TypeVar("T")


def _is_transient_gemini_error(exc: Exception) -> bool:
    msg = (str(exc) or "").lower()
    transient_markers = [
        "503",
        "overloaded",
        "unavailable",
        "resource exhausted",
        "rate limit",
        "quota",
        "429",
        "timeout",
        "timed out",
        "deadline exceeded",
        "connection reset",
        "connection aborted",
        "bad gateway",
        "502",
        "gateway timeout",
        "504",
        "internal error",
        "500",
        "temporarily",
        "try again",
    ]
    return any(m in msg for m in transient_markers)


def gemini_call_with_retry(
    call_name: str,
    fn: Callable[[], T],
    *,
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    initial_delay: float = RETRY_INITIAL_DELAY_SEC,
    max_delay: float = RETRY_MAX_DELAY_SEC,
    jitter: float = RETRY_JITTER_SEC,
) -> T:
    attempt = 1
    delay = max(0.0, initial_delay)

    while True:
        try:
            print(f"[gemini] {call_name}: attempt {attempt}/{max_attempts}", file=sys.stderr)
            return fn()
        except Exception as e:
            transient = _is_transient_gemini_error(e)
            print(
                f"[gemini] {call_name}: attempt {attempt} failed "
                f"(transient={transient}) -> {type(e).__name__}: {str(e)[:220]}",
                file=sys.stderr,
            )

            if not transient:
                raise
            if attempt >= max_attempts:
                raise

            sleep_for = min(max_delay, delay) + random.uniform(0.0, max(0.0, jitter))
            print(f"[gemini] {call_name}: sleeping {sleep_for:.2f}s before retry", file=sys.stderr)
            time.sleep(sleep_for)

            delay = min(max_delay, max(delay, 0.05) * 1.5)
            attempt += 1


# ----------------------------
# Gemini calls (sync)
# ----------------------------
>>>>>>> Stashed changes
def classify_with_gemini(payload: ReviewPayload) -> Classification:
    client = get_client() # Get synchronous client
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # The system instructions string for classification
    system_instructions = """
You are a code review assistant that classifies a GitHub PR inline review comment
into exactly ONE category.

Decision priority:
1) First determine the INTENT of the comment:
    - praise
    - question
    - request to change code
2) Then determine whether the intent is CLEAR (good) or UNCLEAR (bad).

Categories:
1) PRAISE:
    - Only positive reaction.
    - No actionable request.

2) GOOD_CHANGE:
    - Clear, actionable request to change code.

3) BAD_CHANGE:
    - A request to change code, but unclear, underspecified, or poorly explained.
    - Needs clarification before code can be suggested.

4) GOOD_QUESTION:
    - A clear question.
    - No action required by the bot.

5) BAD_QUESTION:
    - A question, but unclear, ambiguous, or underspecified.
    - Bot should ask clarifying questions.

Important notes:
- "bad" means unclear, ambiguous, or underspecified — NOT rude or toxic.
- Informal language, slang, sarcasm, emojis, or non-English text
    does NOT automatically make a comment bad.
- Short comments are allowed to be GOOD if intent is still clear.
- needs_reply must be true ONLY for:
    GOOD_CHANGE, BAD_CHANGE, BAD_QUESTION.
- needs_clarification must be true ONLY for:
    BAD_CHANGE, BAD_QUESTION.
- If intent cannot be determined, use category=UNKNOWN with low confidence.

Return ONLY valid JSON that matches the provided schema.
""".strip()

    ctx = build_llm_context(payload)    

    # NOTE: No 'await' keyword here.
    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=f"{system_instructions}\n\nCONTEXT:\n{ctx}"
                    )
                ],
            )
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Classification,
            temperature=0.2,
        ),
    )

<<<<<<< Updated upstream
    # Structured output parsing (safe fallback)
    data = getattr(resp, "parsed", None)
    if data is None:
        data = json.loads(resp.text)
=======
        data = getattr(resp, "parsed", None)
        if data is None:
            data = json.loads(resp.text)
>>>>>>> Stashed changes

    return Classification.model_validate(data)

<<<<<<< Updated upstream
# NOTE: This function is SYNCHRONOUS (no 'async')
def generate_code_suggestion(payload: ReviewPayload, cls: Classification) -> str:
    client = get_client() # Get synchronous client
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash") # Use a powerful model for code
=======
    return gemini_call_with_retry("classify_with_gemini", _call)


def clarify_bad_question(payload: ReviewPayload, cls: Classification) -> ClarifiedQuestion:
    client = get_client()
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    system_instructions = """
Rewrite an unclear PR question into a clarified question.

Rules:
- Output must match the JSON schema.
- 1–2 short sentences max, end with "?".
- Do NOT answer. Do NOT invent facts.
- Use placeholders if missing: "<which file?>", "<which function?>", "<expected behavior?>"
- If project conventions are relevant (naming/architecture), include up to 3 `reference_urls`
  that point to the most relevant provided project docs.
""".strip()

    ctx = build_llm_context(payload)

    def _call():
        resp = client.models.generate_content(
            model=model,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"{system_instructions}\n\nCONTEXT:\n{ctx}")],
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ClarifiedQuestion,
                temperature=0.2,
            ),
        )

        data = getattr(resp, "parsed", None)
        if data is None:
            data = json.loads(resp.text)

        return ClarifiedQuestion.model_validate(data)

    return gemini_call_with_retry("clarify_bad_question", _call)


def clarify_bad_change(payload: ReviewPayload, cls: Classification) -> ClarifiedChange:
    client = get_client()
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    system_instructions = """
Rewrite an unclear PR change request into a clarified, actionable request.

Rules:
- Output must match the JSON schema.
- Do NOT propose code. Do NOT invent facts.
- "clarified_request" must be 1–2 short sentences max.
- Use placeholders if missing: "<which file?>", "<which function?>", "<acceptance criteria?>"
- If project conventions are relevant (naming/architecture), include up to 3 `reference_urls`
  that point to the most relevant provided project docs.
""".strip()

    ctx = build_llm_context(payload)

    def _call():
        resp = client.models.generate_content(
            model=model,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"{system_instructions}\n\nCONTEXT:\n{ctx}")],
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ClarifiedChange,
                temperature=0.2,
            ),
        )

        data = getattr(resp, "parsed", None)
        if data is None:
            data = json.loads(resp.text)

        return ClarifiedChange.model_validate(data)

    return gemini_call_with_retry("clarify_bad_change", _call)


def generate_code_suggestion(
    payload: ReviewPayload,
    cls: Classification,
    reviewer_comment_override: Optional[str] = None,
) -> str:
    client = get_client()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    reviewer_comment = (reviewer_comment_override or payload.comment_body or payload.review_body or "").strip()
    ctx = build_llm_context(payload)
>>>>>>> Stashed changes

    # The system instructions string for code suggestion
    system_instructions = f"""
You are an expert GitHub code review assistant. Your task is to provide a helpful, actionable code suggestion in response to a peer review comment.

Constraints:
1. **Analyze the original comment** (provided below) and the surrounding **diff hunk**.
2. **Focus ONLY on the requested change.**
3. **If possible, provide the entire suggested file content or a complete function/class block that includes the fix.**
4. **Your final output MUST be a clean, direct Markdown code block.** Do not include any introductory or explanatory text outside the code block.

<<<<<<< Updated upstream
Reviewer's Intent (from Classification): {cls.category} - {cls.short_reason}
=======
Hard rules:
- Output MUST be ONLY ONE fenced code block and NOTHING else.
- The code block language MUST be either:
  1) ```diff  (preferred)
  2) ```suggestion  (only if diff isn't possible)
- Keep it minimal: change ONLY the smallest relevant lines.
- Do NOT rewrite whole files. Do NOT include unrelated context.
- If unsure, output a SMALL diff that adds TODOs/placeholders rather than guessing.
- If project conventions/style guides are included in CONTEXT, follow them.

Comment to satisfy (source of truth):
{reviewer_comment}
>>>>>>> Stashed changes
""".strip()

    # Reuse the context builder, but focus the prompt on the necessary fix
    ctx = build_llm_context(payload)

    # The full prompt string for code suggestion
    prompt = f"""
{system_instructions}

CONTEXT:
---
{ctx}
---

Your task: Based on the "Original comment" and the "Diff hunk" in the context above, provide the corrected/suggested code.

Return ONLY the code block in Markdown format.
"""

    # NOTE: No 'await' keyword here.
    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part(text=prompt)
                ],
            )
        ],
        config=types.GenerateContentConfig(
            temperature=0.3,
        ),
    )
    
    # Strip any potential leading/trailing text outside the code block
    # and return the generated text.
    return resp.text.strip()


<<<<<<< Updated upstream
=======
def generate_pr_discussion_reply(payload: ReviewPayload) -> str:
    client = get_client()
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    ctx = build_llm_context(payload)

    system_instructions = """
You are a helpful assistant participating in a PR conversation thread (NOT a formal code review).

Rules:
- If the comment is simple acknowledgement (e.g., "thanks", "LGTM", emoji), set needs_reply=false and reply_markdown="".
- Answer questions briefly and concretely based on the provided PR context.
- Do NOT produce code diffs/suggestions unless the user explicitly requests /wizard-review.
- If the user asks for an automated review, tell them to comment "/wizard-review".
- If project conventions/docs are relevant, include up to 3 `reference_urls` to the provided doc links.

Return ONLY valid JSON for the schema.
""".strip()

    def _call():
        resp = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part(text=f"{system_instructions}\n\nCONTEXT:\n{ctx}")])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DiscussionReply,
                temperature=0.3,
            ),
        )
        data = getattr(resp, "parsed", None) or json.loads(resp.text)
        out = DiscussionReply.model_validate(data)

        if not out.needs_reply:
            return ""

        md = (out.reply_markdown or "").strip()
        if out.reference_urls:
            md += "\n\n**References:**\n" + "\n".join([f"- {u}" for u in out.reference_urls[:3]])
        return md

    return gemini_call_with_retry("generate_pr_discussion_reply", _call)


def run_wizard_candidate_comments(payload: ReviewPayload) -> str:
    client = get_client()
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    ctx = build_llm_context(payload)

    system_instructions = """
You are the 'ContextWizard' AI Reviewer.
Upon request, scan the PR diff and generate candidate review comments.

Rules:
- Output must match the JSON schema.
- Produce 0-8 comments.
- Each comment MUST have:
  - title (short)
  - description (1-3 sentences)
- Include file_path when you can infer it from context.
- If a comment relates to naming/architecture/conventions and relevant docs are provided,
  include up to 3 reference_urls (links) to those docs.
- Be concise and professional.
""".strip()

    def _call():
        resp = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part(text=f"{system_instructions}\n\nCONTEXT:\n{ctx}")])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CandidateReviewOutput,
                temperature=0.3,
            ),
        )
        data = getattr(resp, "parsed", None) or json.loads(resp.text)
        out = CandidateReviewOutput.model_validate(data)

        if not out.comments:
            return "_No significant issues found in the provided diff context._"

        lines: List[str] = []
        for i, c in enumerate(out.comments[:8], start=1):
            lines.append(f"### {i}) {c.title.strip()}")
            if c.file_path:
                lines.append(f"**File:** `{c.file_path}`")
            lines.append(f"**Description:** {c.description.strip()}")
            if c.reference_urls:
                lines.append("**References:**")
                for u in c.reference_urls[:3]:
                    lines.append(f"- {u}")
            lines.append("")
        return "\n".join(lines).strip()

    return gemini_call_with_retry("wizard_review_candidates", _call)


# ----------------------------
# Formatting helpers
# ----------------------------
>>>>>>> Stashed changes
def format_debug_comment(payload: ReviewPayload, cls: Classification) -> str:
    where = "review" if payload.kind == "review" else "inline comment"
    original_text = payload.review_body if payload.kind == "review" else payload.comment_body
    original_text = (original_text or "").strip()

    lines = [
        "🧠 **ContextWizard (debug: classification only)**",
        f"- event: `{where}`",
        f"- category: **{cls.category}**",
        f"- confidence: `{cls.confidence:.2f}`",
        f"- needs_reply: `{cls.needs_reply}`",
        f"- needs_clarification: `{cls.needs_clarification}`",
        f"- reason: {cls.short_reason}",
        "",
        "**Original text:**",
        f"> {(original_text[:500] + '…') if len(original_text) > 500 else original_text}".replace("\n", "\n> "),
        "",
        "_(classification only; no follow-up action taken)_",
    ]
    return "\n".join(lines).strip()


<<<<<<< Updated upstream
=======
def format_clarification_question_comment(payload: ReviewPayload, cls: Classification, cq: ClarifiedQuestion) -> str:
    original_text = (payload.comment_body or payload.review_body or "").strip()

    lines = [
        "❓ **ContextWizard (clarified question)**",
        f"- category: **{cls.category}**",
        f"- classification_confidence: `{cls.confidence:.2f}`",
        f"- rewrite_confidence: `{cq.confidence:.2f}`",
        f"- reason: {cls.short_reason}",
        f"- rewrite_note: {cq.short_reason}",
        "",
        "**Original question:**",
        f"> {(original_text[:800] + '…') if len(original_text) > 800 else original_text}".replace("\n", "\n> "),
        "",
        "**Proposed clarified version:**",
        f"> {cq.clarified_question}".replace("\n", "\n> "),
    ]

    if cq.reference_urls:
        lines += ["", "**References:**"] + [f"- {u}" for u in cq.reference_urls[:3]]

    return "\n".join(lines).strip()


def format_bad_change_with_suggestion_comment(
    cls: Classification,
    clarified_request: str,
    suggestion_block: str,
    reference_urls: Optional[List[str]] = None,
) -> str:
    out = "\n".join(
        [
            f"1- **clarified version:** {clarified_request}",
            "2- **suggested code change:**",
            suggestion_block.strip(),
        ]
    ).strip()

    refs = reference_urls or []
    if refs:
        out += "\n\n**References:**\n" + "\n".join([f"- {u}" for u in refs[:3]])

    return out


>>>>>>> Stashed changes
# ----------------------------
# FastAPI route
# ----------------------------
@app.post("/analyze-review", response_model=BackendResponse)
async def analyze_review(payload: ReviewPayload):
<<<<<<< Updated upstream
    # Print payload for debug (keep this)
=======
    print(f"Processing kind: {payload.kind} for PR #{payload.pr_number}", file=sys.stderr)

    # 0) Wizard command: generate candidate review comments (FR5.2)
    if payload.kind == "wizard_review_command":
        try:
            suggestions = await anyio.to_thread.run_sync(run_wizard_candidate_comments, payload)
            return BackendResponse(comment=f"🧙‍♂️ **Wizard Candidate Review Comments**\n\n{suggestions}")
        except Exception as e:
            return BackendResponse(comment=f"❌ Error during Wizard Review: {str(e)[:180]}")

    # 0b) Normal PR discussion comments should be replied to WITHOUT reviewing
    if payload.kind == "issue_comment":
        try:
            reply_md = await anyio.to_thread.run_sync(generate_pr_discussion_reply, payload)
            return BackendResponse(comment=reply_md)
        except Exception as e:
            return BackendResponse(comment=f"❌ Error generating discussion reply: {type(e).__name__}: {str(e)[:180]}")

>>>>>>> Stashed changes
    print("==== Incoming payload ====", file=sys.stderr)
    try:
        print(json.dumps(payload.model_dump(), indent=2), file=sys.stderr)
    except Exception:
        print(json.dumps(payload.dict(), indent=2), file=sys.stderr) 
    print("==========================", file=sys.stderr)

<<<<<<< Updated upstream
    # 1. Classify the comment/review
=======
    # 1) Classify (only for review/review_comment)
    print("Classifying with Gemini...", file=sys.stderr)
>>>>>>> Stashed changes
    try:
        # MUST use 'await' here to run the synchronous helper in a thread pool
        cls = classify_with_gemini(payload)
    except Exception as e:
        # Fallback debug comment on classification failure
        cls = Classification(
            category="UNKNOWN",
            needs_reply=True,
            needs_clarification=False,
            confidence=0.0,
            short_reason=f"Gemini classification failed: {type(e).__name__}: {str(e)[:160]}",
        )
        # If classification fails, return the error immediately
        final_comment_body = format_debug_comment(payload, cls)
        return BackendResponse(comment=final_comment_body.strip())

<<<<<<< Updated upstream
    final_comment_body = ""

    # 2. Check if a code suggestion is warranted
    # Only attempt code suggestion for inline comments, NOT full reviews.
    if payload.kind == "review_comment" and cls.category == "GOOD_CHANGE" and cls.confidence >= 0.7:
=======
    if payload.kind not in ("review_comment", "review"):
        return BackendResponse(comment=format_debug_comment(payload, cls))

    # 2) GOOD_CHANGE -> strict code suggestion only
    if cls.category == "GOOD_CHANGE" and cls.confidence >= 0.7:
        print("Generating good change with Gemini...", file=sys.stderr)
>>>>>>> Stashed changes
        try:
            # MUST use 'await' here to run the synchronous helper in a thread pool
            suggestion = generate_code_suggestion(payload, cls)
            
            # Format the final comment body for GitHub
            final_comment_body = f"""
**🤖 Code Suggestion ({cls.category} - {cls.confidence:.2f})**

_Reviewer intent: {cls.short_reason}_

Here is a suggested implementation for the requested change:

{suggestion}

---
_(Generated by Gemini)_
"""
        except Exception as e:
<<<<<<< Updated upstream
            # Fallback if code generation fails
            final_comment_body = format_debug_comment(
                payload, 
                Classification(
                    category="UNKNOWN",
                    needs_reply=True,
                    needs_clarification=False,
                    confidence=0.0,
                    short_reason=f"Suggestion generation failed: {type(e).__name__}: {str(e)[:160]}",
                )
            )
    else:
        # For full reviews, or other categories/low confidence inline comments, return the classification debug comment
        final_comment_body = format_debug_comment(payload, cls)


    return BackendResponse(comment=final_comment_body.strip())
=======
            fallback = Classification(
                category="UNKNOWN",
                needs_reply=True,
                needs_clarification=False,
                confidence=0.0,
                short_reason=f"Suggestion generation failed: {type(e).__name__}: {str(e)[:160]}",
            )
            return BackendResponse(comment=format_debug_comment(payload, fallback))

    # 3) BAD_QUESTION -> clarified question + refs (FR3.2)
    if cls.category == "BAD_QUESTION" and cls.confidence >= 0.55:
        print("Clarifying bad question with Gemini...", file=sys.stderr)
        try:
            cq = await anyio.to_thread.run_sync(clarify_bad_question, payload, cls)
            return BackendResponse(comment=format_clarification_question_comment(payload, cls, cq))
        except Exception as e:
            fallback = Classification(
                category="UNKNOWN",
                needs_reply=True,
                needs_clarification=False,
                confidence=0.0,
                short_reason=f"Question clarification failed: {type(e).__name__}: {str(e)[:160]}",
            )
            return BackendResponse(comment=format_debug_comment(payload, fallback))

    # 4) BAD_CHANGE -> clarify -> suggestion + refs (FR3.2)
    if cls.category == "BAD_CHANGE" and cls.confidence >= 0.55:
        print("Clarifying bad change and generating suggestion with Gemini...", file=sys.stderr)
        try:
            cc = await anyio.to_thread.run_sync(clarify_bad_change, payload, cls)
            suggestion_block = await anyio.to_thread.run_sync(
                generate_code_suggestion,
                payload,
                cls,
                cc.clarified_request,
            )
            body = format_bad_change_with_suggestion_comment(cls, cc.clarified_request, suggestion_block, cc.reference_urls)
            return BackendResponse(comment=body)
        except Exception as e:
            fallback = Classification(
                category="UNKNOWN",
                needs_reply=True,
                needs_clarification=False,
                confidence=0.0,
                short_reason=f"BAD_CHANGE clarification/suggestion failed: {type(e).__name__}: {str(e)[:160]}",
            )
            return BackendResponse(comment=format_debug_comment(payload, fallback))

    # 5) Default: classification debug comment
    return BackendResponse(comment=format_debug_comment(payload, cls))
>>>>>>> Stashed changes
