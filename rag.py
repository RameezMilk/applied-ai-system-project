"""Pet Care Advisor — multi-source RAG with self-critique guardrail.

Sources:
  1. Curated knowledge base in knowledge/*.md
  2. The user's own Owner/Pet/Task data (personalized retrieval)

Pipeline: question -> embed -> retrieve top-k from each source -> generate
answer with retrieved context -> self-critique pass -> return answer + sources
+ critique flag.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

from pawpal_system import Owner

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("pawpal.rag")

EMBED_MODEL = "models/gemini-embedding-001"
GEN_MODEL = "gemini-2.5-flash"
KB_DIR = Path(__file__).parent / "knowledge"
TOP_K_KB = 3
TOP_K_USER = 2
LOW_SIMILARITY_THRESHOLD = 0.55  # below this we treat retrieval as weak

SYSTEM_PROMPT = """You are PawPal+, a warm, vet-informed pet care assistant embedded in a daily-care scheduling app.

Rules:
- Answer ONLY using the provided context. If the context does not cover the question, say so plainly and suggest the user consult a licensed veterinarian.
- Never give emergency medical advice. For any sign of medical distress, direct the user to a vet or pet poison hotline.
- Be concise (3-6 sentences). When you cite a fact, mention which source supports it (e.g., "per the dog exercise guide").
- If the user has pets on file, tailor the answer to those pets when relevant.
- Tone: warm, practical, never alarmist, never replacing professional care."""

CRITIC_PROMPT = """You are a strict reviewer of pet care advice. Given a user question, the retrieved context, and a draft answer, decide if the draft is:
1. GROUNDED — every factual claim is supported by the retrieved context.
2. SAFE — does not give medical/emergency advice that should come from a vet.
3. ON-TOPIC — actually addresses the user's question.

Reply in this exact format:
VERDICT: PASS | FAIL
REASON: <one short sentence>"""


@dataclass
class RetrievedChunk:
    source: str        # filename or "user_data"
    text: str
    score: float


class PetCareAdvisor:
    """Multi-source RAG advisor with embedded knowledge base and self-critique."""

    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Add it to .env or pass api_key=..."
            )
        genai.configure(api_key=key)
        self._kb_chunks: list[tuple[str, str]] = []   # (source_name, text)
        self._kb_embeddings: np.ndarray | None = None
        self._load_kb()

    def _load_kb(self) -> None:
        """Load and embed all markdown files in knowledge/."""
        if not KB_DIR.exists():
            log.warning("KB directory %s missing; advisor will be empty", KB_DIR)
            return

        for path in sorted(KB_DIR.glob("*.md")):
            text = path.read_text().strip()
            if text:
                self._kb_chunks.append((path.stem, text))

        log.info("Loaded %d KB documents", len(self._kb_chunks))

        if not self._kb_chunks:
            return

        texts = [c[1] for c in self._kb_chunks]
        self._kb_embeddings = self._embed(texts, task="retrieval_document")
        log.info("Embedded %d KB documents", len(texts))

    def _embed(self, texts: list[str], task: str) -> np.ndarray:
        """Embed a list of texts. task is 'retrieval_document' or 'retrieval_query'."""
        vectors = []
        for t in texts:
            resp = genai.embed_content(
                model=EMBED_MODEL,
                content=t,
                task_type=task,
            )
            vectors.append(resp["embedding"])
        return np.array(vectors, dtype=np.float32)

    @staticmethod
    def _cosine(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        q = query / (np.linalg.norm(query) + 1e-9)
        m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
        return m @ q

    def _serialize_user_corpus(self, owner: Owner | None) -> list[tuple[str, str]]:
        """Turn the user's pets and tasks into retrievable text snippets."""
        if owner is None or not owner.pets:
            return []
        snippets = []
        for pet in owner.pets:
            lines = [f"Pet on file: {pet.name}, a {pet.species}."]
            if pet.tasks:
                lines.append(f"{pet.name}'s scheduled care tasks:")
                for t in pet.tasks:
                    status = "completed" if t.completed else "pending"
                    lines.append(
                        f"- {t.title} ({t.duration_minutes} min, {t.priority} priority, "
                        f"{t.frequency}, at {t.scheduled_time}, {status})"
                    )
            else:
                lines.append(f"{pet.name} has no scheduled tasks yet.")
            snippets.append((f"user_data:{pet.name}", "\n".join(lines)))
        return snippets

    def retrieve(
        self, question: str, owner: Owner | None = None
    ) -> list[RetrievedChunk]:
        """Retrieve top chunks from KB + user corpus."""
        if self._kb_embeddings is None or not self._kb_chunks:
            return []

        q_embed = self._embed([question], task="retrieval_query")[0]

        # KB retrieval
        kb_scores = self._cosine(q_embed, self._kb_embeddings)
        kb_top_idx = np.argsort(-kb_scores)[:TOP_K_KB]
        results = [
            RetrievedChunk(
                source=self._kb_chunks[i][0],
                text=self._kb_chunks[i][1],
                score=float(kb_scores[i]),
            )
            for i in kb_top_idx
        ]

        # User corpus retrieval (re-embedded each call — small N, fine)
        user_snippets = self._serialize_user_corpus(owner)
        if user_snippets:
            user_embeds = self._embed(
                [s[1] for s in user_snippets], task="retrieval_document"
            )
            user_scores = self._cosine(q_embed, user_embeds)
            user_top_idx = np.argsort(-user_scores)[:TOP_K_USER]
            for i in user_top_idx:
                results.append(
                    RetrievedChunk(
                        source=user_snippets[i][0],
                        text=user_snippets[i][1],
                        score=float(user_scores[i]),
                    )
                )

        results.sort(key=lambda r: -r.score)
        log.info(
            "Retrieved %d chunks (top score %.3f)",
            len(results),
            results[0].score if results else 0.0,
        )
        return results

    def _format_context(self, chunks: list[RetrievedChunk]) -> str:
        return "\n\n".join(
            f"[Source: {c.source} | similarity={c.score:.2f}]\n{c.text}"
            for c in chunks
        )

    def _call_with_retry(self, model: "genai.GenerativeModel", prompt: str) -> str:
        """Call generate_content with one automatic retry on rate-limit."""
        try:
            return model.generate_content(prompt).text.strip()
        except ResourceExhausted as e:
            wait = 35
            m = re.search(r"retry in ([\d.]+)s", str(e))
            if m:
                wait = min(int(float(m.group(1))) + 2, 60)
            log.warning("Rate-limited; sleeping %ds before retry", wait)
            time.sleep(wait)
            return model.generate_content(prompt).text.strip()

    def _generate(self, question: str, context: str) -> str:
        model = genai.GenerativeModel(GEN_MODEL, system_instruction=SYSTEM_PROMPT)
        prompt = f"Context:\n{context}\n\nUser question: {question}\n\nAnswer:"
        return self._call_with_retry(model, prompt)

    def _critique(self, question: str, context: str, draft: str) -> tuple[bool, str]:
        """Second-pass self-critique. Returns (passed, reason)."""
        model = genai.GenerativeModel(GEN_MODEL, system_instruction=CRITIC_PROMPT)
        prompt = (
            f"User question:\n{question}\n\n"
            f"Retrieved context:\n{context}\n\n"
            f"Draft answer:\n{draft}\n"
        )
        resp = self._call_with_retry(model, prompt)
        passed = "VERDICT: PASS" in resp.upper()
        reason = ""
        for line in resp.splitlines():
            if line.upper().startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()
                break
        log.info("Critic verdict: %s — %s", "PASS" if passed else "FAIL", reason)
        return passed, reason

    def ask(
        self, question: str, owner: Owner | None = None
    ) -> dict:
        """End-to-end: retrieve -> generate -> critique. Returns structured result."""
        if not question or not question.strip():
            return {
                "answer": "Please enter a question.",
                "sources": [],
                "critique_passed": True,
                "critique_reason": "empty input rejected",
                "low_confidence": False,
            }

        log.info("Question: %s", question)
        chunks = self.retrieve(question, owner=owner)

        if not chunks:
            return {
                "answer": "I don't have any reference material loaded. Please check the knowledge/ directory.",
                "sources": [],
                "critique_passed": False,
                "critique_reason": "empty knowledge base",
                "low_confidence": True,
            }

        top_score = chunks[0].score
        low_confidence = top_score < LOW_SIMILARITY_THRESHOLD

        context = self._format_context(chunks)

        if low_confidence:
            log.info("Low retrieval confidence (%.2f) — short-circuiting", top_score)
            return {
                "answer": (
                    "I don't have reliable information on that in my pet care guides. "
                    "I'd recommend asking a licensed veterinarian for guidance specific to your pet."
                ),
                "sources": [c.source for c in chunks],
                "critique_passed": True,
                "critique_reason": "honest refusal due to low retrieval similarity",
                "low_confidence": True,
            }

        try:
            draft = self._generate(question, context)
        except Exception as e:
            log.exception("Generation failed")
            return {
                "answer": f"Sorry, I hit an error generating an answer: {e}",
                "sources": [c.source for c in chunks],
                "critique_passed": False,
                "critique_reason": "generation error",
                "low_confidence": False,
            }

        try:
            passed, reason = self._critique(question, context, draft)
        except Exception as e:
            log.exception("Critique failed")
            passed, reason = True, f"critic unavailable: {e}"

        return {
            "answer": draft,
            "sources": [c.source for c in chunks],
            "critique_passed": passed,
            "critique_reason": reason,
            "low_confidence": False,
        }
