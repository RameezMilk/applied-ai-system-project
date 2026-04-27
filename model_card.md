# Model Card — PawPal+ Pet Care Advisor

This model card documents the AI component of **PawPal+**, an applied AI extension of the PawPal+ pet care scheduler. It covers intended use, system design, evaluation results, limitations, ethical considerations, and reflections on the AI-collaborative development process.

---

## 1. System overview

| Attribute | Value |
|---|---|
| **Base project** | PawPal+ (Module 2) — a deterministic Streamlit scheduler for daily pet care tasks. |
| **AI extension** | A Pet Care Advisor that answers natural-language questions using multi-source RAG and a self-critique guardrail. |
| **Generator model** | `gpt-4o-mini` (OpenAI) |
| **Embedding model** | `text-embedding-3-small` (OpenAI) |
| **Vector index** | In-memory NumPy cosine similarity (no vector DB). |
| **Knowledge base** | 7 curated markdown documents in `knowledge/` (≈ 200 lines total) covering dog exercise, dog feeding, cat care, kittens, puppies, grooming, and safety/emergencies. |
| **Personalization source** | The user's live `Owner` / `Pet` / `Task` objects, serialized as retrievable text snippets per pet. |
| **Reliability mechanisms** | (a) Retrieval-confidence threshold (0.35) → honest refusal. (b) Second-pass self-critic that returns `PASS` / `FAIL`. (c) Strict system prompt enforcing source-grounding and vet redirects. (d) `eval.py` test harness over 6 fixed scenarios. |

The advisor reads the live `Owner` object so personalization reflects current pets and tasks. It is read-only — it does **not** modify the schedule.

---

## 2. Intended use

**In-scope.** Answering general pet care questions about dogs and cats — exercise duration, feeding frequency, grooming cadence, common-sense routines, and surfacing emergency-aware redirects to a veterinarian.

**Out-of-scope.** Diagnosing medical conditions, recommending medication or doses, exotic species (reptiles, birds, fish, small mammals), region-specific regulations, breed-specific behavioral training. The advisor refuses or redirects in these cases.

**Intended user.** A pet owner using PawPal+ to plan daily care for a household with one or more cats or dogs.

---

## 3. Training data and knowledge sources

The advisor is **not fine-tuned**. The underlying model (`gpt-4o-mini`) was trained by OpenAI; this project does not modify its weights. All factual grounding comes from two external sources retrieved at inference time:

1. **Curated knowledge base** — 7 hand-authored markdown documents covering common pet-care topics. Sources are general-knowledge guidelines (US-centric: Fahrenheit, US poison-control hotlines).
2. **User-provided personal data** — the user's `Owner` name, available time, pets (name + species), and tasks (title, duration, priority, time, frequency, completion). This data lives only in Streamlit session state and is never persisted or sent anywhere except OpenAI as part of a query.

No personally identifying information is required by the system; the user voluntarily enters pet names and a display name.

---

## 4. Evaluation

`eval.py` runs 6 fixed scenarios. Each is scored on 5 binary checks; a scenario passes only if all 5 pass.

| Check | What it measures |
|---|---|
| `refusal_correct` | The system refuses iff the question is out-of-scope (top similarity < 0.35). |
| `groundedness` | At least one expected source document appears in the retrieved set. |
| `keywords` | The answer contains expected factual phrases (e.g., "90 to 120 min" for Husky exercise). |
| `vet_redirect` | Safety scenarios explicitly mention a vet or pet poison hotline. |
| `critic_pass` | The self-critic accepted the draft as grounded, safe, and on-topic. |

**Latest run:** **6 / 6 scenarios passed; every check at 100 %.**

Scenarios cover: high-energy-breed exercise, kitten feeding frequency, the puppy "5 min × month of age" rule, a chocolate-ingestion emergency (vet redirect required), an off-topic refusal ("capital of France"), and long-haired cat grooming.

The original scheduler has a separate suite of **20 unit tests** in `tests/` (run with `python -m pytest`) covering priority sorting, time-budget enforcement, conflict detection, recurring tasks, and edge cases. All 20 pass.

---

## 5. Limitations and biases

- **The KB is small and US-centric.** It uses Fahrenheit, US poison-control phone numbers, and reflects authorial choices about which breeds to highlight. Owners outside the US, or with breeds (or species) not represented in the KB, will get refusals or shallow answers.
- **Self-critique uses the same model family.** `gpt-4o-mini` reviewing `gpt-4o-mini` can share blind spots — a confidently wrong draft may pass review. The retrieval-confidence threshold is a second line of defense, but it cannot catch a wrong answer that *is* well-supported by the retrieved chunks.
- **The critic has only been observed passing.** In every evaluated scenario the critic returned PASS. The system has not yet been adversarially tested with intentionally-bad drafts to confirm the critic will reject them. This is an evaluation gap noted in §7.
- **The personalized corpus is shallow.** It encodes pet name, species, and tasks, but not age, weight, breed, or medical history. Personalization is therefore limited.
- **No persistence.** Pets and tasks live only in Streamlit session state; closing the browser tab clears them.
- **Cosine threshold is empirically tuned.** The 0.35 floor was set against `text-embedding-3-small` and would need re-tuning if the embedding model changes (this happened during development — see §8).

---

## 6. Ethical considerations and potential misuse

The most plausible misuse is an owner attempting to substitute the advisor for veterinary care — asking it to diagnose symptoms or recommend medication doses. Two guardrails address this:

1. The system prompt explicitly instructs the model never to give emergency medical advice and to redirect any sign of distress to a licensed veterinarian.
2. The `safety_emergencies` KB document enumerates the scenarios that demand a vet call (poisoning, breathing problems, seizures, GDV, severe lethargy, eye injury) and surfaces them whenever a safety-related query is retrieved.

If this were a real product, additional steps would be: a stronger safety classifier ahead of retrieval, rate-limiting per user, an explicit disclaimer the user must accept on first use, and clear audit logging of every query and the retrieved chunks.

---

## 7. Surprises during reliability testing

How much of the work was **gating**, not generation. Producing fluent answers was easy — the underlying model does that out of the box. The harder problem was deciding when *not* to answer: tuning the cosine-similarity threshold so a question about French capitals refuses while a question about a Maine Coon retrieves cleanly, designing the critic prompt so it is willing to disagree with its own draft, and writing eval scenarios that distinguish "right for the right reasons" from "right by accident." The system became more trustworthy when I added more places where it could refuse, not more places where it could speak.

A second surprise: the critic has *never* failed on a real scenario. That is not a victory — it is a measurement gap. A future iteration would inject deliberately ungrounded drafts to confirm the critic will reject them.

---

## 8. AI collaboration during development

I used AI throughout the build: brainstorming the architecture (multi-source retrieval, two-pass critique), scaffolding `rag.py` and `eval.py`, drafting the knowledge-base documents, and generating the Mermaid architecture diagram. The most productive prompts were specific and gave the AI the actual file as context.

### One helpful suggestion

When designing the advisor I asked the AI for a multi-source retrieval pattern. It suggested embedding the user's pets and tasks as natural-language snippets so they could be ranked alongside KB documents in a **single** cosine similarity call, rather than maintaining two separate retrieval paths and merging the results. This was a clean simplification I had not thought of, and it made the personalized retrieval almost free to add. In practice, the user-data snippet for "Mochi" routinely scores above the curated KB chunks for personalized questions like "What care does Mochi need?", which is exactly the desired behavior.

### One flawed suggestion

The AI initially proposed `models/text-embedding-004` as the embedding model when we were using Gemini. The Gemini API rejected it (404 — that ID was not available on the v1beta endpoint the Python SDK targets), forcing a switch to `gemini-embedding-001`. A second flawed assumption surfaced when we later swapped to OpenAI: the AI carried over the `0.55` cosine-similarity threshold I had tuned for Gemini's embedder, but `text-embedding-3-small` produces lower-magnitude scores, and a literal port would have caused the system to refuse every legitimate question. I had to re-tune the threshold to `0.35` against real embeddings.

The lesson is that **model IDs and numerical thresholds in AI-generated code are tied to a specific model family and must be re-verified when the underlying model changes.** AI will happily port them as if they were universal constants.

---

## 9. Future improvements

- Replace the in-memory NumPy index with a persistent vector store so the KB does not have to be re-embedded on every cold start.
- Expand the `Pet` model with age, breed, and weight, which would meaningfully improve personalization (e.g., *for your* 4-month-old puppy, that means roughly 20 minutes twice a day").
- Add an **adversarial eval set** that constructs plausible-but-ungrounded draft answers and verifies the critic catches them. The current eval shows the critic passing every good answer but does not yet prove it can reject bad ones.
- Let the advisor *propose* tasks back to the schedule (e.g., "I can add a 20-minute morning walk for Mochi at 7:00 — confirm?"), turning the read-only advisor into an opt-in agent with a human approval step. This would make the system genuinely agentic, with the schedule mutation gated by user consent.
- Internationalize the KB (Celsius, non-US emergency hotlines) and broaden coverage to additional species.
