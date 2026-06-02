"""Claude-powered quiz engine: generate questions from a PDF and grade answers.

Uses the Anthropic Messages API (model claude-opus-4-8) with:
  - a base64 PDF document block as input,
  - structured outputs so we get clean JSON back,
  - prompt caching on the system prompt + PDF so repeated grading calls are cheap.
"""

import base64
import json

from dotenv import load_dotenv
from anthropic import Anthropic

# Load ANTHROPIC_API_KEY from the .env file once, at import time.
load_dotenv()

MODEL = "claude-opus-4-8"

# Tuned for ages 9-12: simple language, encouraging tone, questions drawn
# strictly from the uploaded pages.
QUESTION_SYSTEM_PROMPT = (
    "You are a friendly teacher who writes fun practice questions for a child "
    "aged 9 to 12. Write questions STRICTLY based on the textbook pages provided "
    "in the document. Mix multiple-choice and short-answer questions. Use simple, "
    "clear, encouraging language. For multiple-choice questions, give exactly 4 "
    "plausible options and make 'correct_answer' the exact text of the right option. "
    "For short-answer questions, leave 'options' empty and put a model answer in "
    "'correct_answer'. Always include a short, kid-friendly 'explanation' of why the "
    "answer is right. For every question, also include a short 'topic' label (1-3 "
    "words, e.g. 'Fractions', 'Water Cycle') naming the specific concept it tests, so "
    "a parent can see which topics were covered."
)

CONCEPTS_SYSTEM_PROMPT = (
    "You are a friendly teacher helping a child aged 9 to 12 revise before a quiz. "
    "From the textbook pages provided in the document, pull out the key concepts the "
    "child needs to understand. For each one give a short, clear 'title' and a simple, "
    "encouraging 'explanation' (2-4 sentences) in kid-friendly language, with a tiny "
    "everyday example where it helps. Cover only what's on the pages."
)

GRADE_SYSTEM_PROMPT = (
    "You are a warm, encouraging teacher grading a short answer from a child aged "
    "9 to 12. Be lenient: accept answers that show the right idea even if spelling, "
    "capitalization, or phrasing differ from the model answer. Mark it correct if the "
    "core idea is right. Always reply kindly. If the answer is wrong, give one gentle, "
    "encouraging hint that nudges them toward the right idea (do not just give away the "
    "full answer)."
)

# Schema for the generated quiz. Structured outputs disallow min/maxLength,
# numeric bounds, and recursion, so we keep it flat and simple.
QUESTIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["questions"],
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "type",
                    "topic",
                    "question",
                    "options",
                    "correct_answer",
                    "explanation",
                ],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["multiple_choice", "short_answer"],
                    },
                    "topic": {"type": "string"},
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "correct_answer": {"type": "string"},
                    "explanation": {"type": "string"},
                },
            },
        }
    },
}

CONCEPTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["concepts"],
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "explanation"],
                "properties": {
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                },
            },
        }
    },
}

GRADE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_correct", "feedback"],
    "properties": {
        "is_correct": {"type": "boolean"},
        "feedback": {"type": "string"},
    },
}


def _pdf_document_block(pdf_bytes: bytes) -> dict:
    """Build a cached base64 PDF document content block."""
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(pdf_bytes).decode("utf-8"),
        },
        "cache_control": {"type": "ephemeral"},
    }


def load_client() -> Anthropic:
    """Return an Anthropic client (API key resolved from the environment)."""
    return Anthropic()


def _first_text(response) -> str:
    """Pull the first text block out of a Messages API response."""
    return next(b.text for b in response.content if b.type == "text")


def generate_questions(pdf_bytes: bytes, num_questions: int = 8) -> list[dict]:
    """Generate a mixed quiz from the uploaded textbook PDF.

    Returns a list of question dicts matching QUESTIONS_SCHEMA's item shape.
    """
    client = load_client()

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=[
            {
                "type": "text",
                "text": QUESTION_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    _pdf_document_block(pdf_bytes),
                    {
                        "type": "text",
                        "text": (
                            f"Create {num_questions} practice questions based on these "
                            "pages. Use a mix of multiple-choice and short-answer "
                            "questions."
                        ),
                    },
                ],
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": QUESTIONS_SCHEMA}},
    )

    data = json.loads(_first_text(response))
    return data["questions"]


def explain_concepts(pdf_bytes: bytes) -> list[dict]:
    """Explain the key concepts in the uploaded pages for a quick revision.

    Returns a list of {"title", "explanation"} dicts.
    """
    client = load_client()

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=[
            {
                "type": "text",
                "text": CONCEPTS_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    _pdf_document_block(pdf_bytes),
                    {
                        "type": "text",
                        "text": "Explain the key concepts in these pages for revision.",
                    },
                ],
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": CONCEPTS_SCHEMA}},
    )

    return json.loads(_first_text(response))["concepts"]


def grade_short_answer(question: str, correct_answer: str, child_answer: str) -> dict:
    """Grade a child's short answer leniently and return {is_correct, feedback}."""
    client = load_client()

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=GRADE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n"
                    f"Model answer: {correct_answer}\n"
                    f"Child's answer: {child_answer}\n\n"
                    "Decide if the child's answer is correct, and write friendly feedback."
                ),
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": GRADE_SCHEMA}},
    )

    return json.loads(_first_text(response))
