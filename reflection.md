# PawPal+ Project Reflection

## 1. System Design

Three core actions a user should be able to perform in natural language:

1. The user should be able to see the tasks for that particular day
2. Be able to add a task or edit from an existing set of tasks
3. Add a pet with a designated owner

**a. Initial design**

UML should have a user with an arrow to a frontend component,
which represents the app's UI, and leaving that frontend component are
a series of arrows, each of which correspond to an action invoked
from different elements on the frontend. For example, clicking "add pet"
should call the Pet Management Service and enable adding a pet with
a designated owner, etc. (assuming service-oriented architecture)

Four classes, each with a clear responsibility:
- **Pet** — holds a name and species. Kept simple since the owner manages the relationship.
- **Task** — represents a single care task (title, duration, priority, scheduled date) and
  points to the Pet it's for. Uses a dataclass so we don't need boilerplate.
- **Owner** — the central hub. Holds a list of pets and tasks, and exposes add_pet(),
  add_task(), and get_tasks_for_date(). Also tracks available_minutes so the scheduler
  knows how much time the owner actually has in a day.
- **Schedule** — takes an owner and a date, then generate_plan() filters and orders
  the tasks by priority while staying within the owner's available time.
  explain_plan() gives a human-readable breakdown of why tasks were chosen and ordered.

**b. Design changes**

After reviewing the skeleton with AI, one overlap stood out: Owner had a
get_tasks_for_today() method, but Schedule.generate_plan() would also need
to filter tasks by date. Having both do the same filtering is redundant and
could lead to inconsistencies. So I removed get_tasks_for_today() and replaced
it with a more flexible get_tasks_for_date(target_date) on Owner — this way
Owner just does the lookup, and Schedule is the one that actually orders and
constrains the plan. Cleaner separation of concerns.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

The scheduler considers three constraints: priority (high/medium/low), scheduled time
(HH:MM), and the owner's available minutes for the day. Priority matters most because
a busy pet owner needs to make sure the critical stuff (meds, feeding) happens even if
there's not enough time for everything. Time is the secondary sort so that tasks with
the same priority land in a natural chronological order. The available_minutes budget
keeps the plan realistic — no point scheduling 3 hours of tasks if the owner only has 90
minutes.

**b. Tradeoffs**

The conflict detection only checks for exact time matches — if two tasks are both at
"07:00" it flags a warning, but it doesn't check if a 30-minute task at 07:00 overlaps
with a task at 07:15. This is a reasonable tradeoff because for a pet care app, most
owners think in rough time blocks ("morning walk", "evening feeding") rather than
minute-level precision. Checking for exact collisions catches the most common mistake
(double-booking a slot) without overcomplicating the logic.

---

## 3. AI Collaboration

**a. How you used AI**

AI was used at every phase — brainstorming the initial class design, generating the Mermaid
UML diagram, scaffolding the dataclass skeletons, implementing the scheduling algorithm,
writing tests, and wiring the Streamlit UI. The most helpful prompts were the specific ones:
"based on my skeletons, how should the Scheduler retrieve tasks from the Owner's pets?" got
a much better answer than a vague "help me build a scheduler." Giving the AI the actual file
as context made a huge difference.

**b. Judgment and verification**

The AI initially put a get_tasks_for_today() method on Owner, but Schedule.generate_plan()
would also need to filter by date — so that was duplicate logic. I rejected the overlap and
replaced it with get_tasks_for_date(target_date) on Owner, keeping Schedule as the only class
that orders and constrains the plan. I verified by thinking through what happens when both
classes filter: if one gets updated and the other doesn't, you get inconsistent results.
Cleaner to have one path for filtering and one for planning.

---

## 4. Testing and Verification

**a. What you tested**

20 tests total, covering happy paths and edge cases:
- Task completion and recurring task generation (daily creates tomorrow, weekly creates next week, one-time returns nothing)
- Adding tasks to a pet actually increases its task count
- Scheduler sorts by priority then time, stays within the time budget, and excludes completed tasks
- Filtering by pet name and completion status
- Conflict detection flags same-time tasks (within a pet and across different pets), and doesn't false-positive when times differ
- Edge cases: empty pets, empty owners, tasks on the wrong date, all tasks too big to fit

These tests matter because the scheduler has multiple interacting constraints — priority, time, budget, completion status. Without tests it would be easy to break one thing while fixing another.

**b. Confidence**

4 out of 5. The core logic is solid and the edge cases I can think of are covered. If I had more time I'd test overlap-based conflicts (a 30-min task at 07:00 vs a task at 07:15), what happens when two pets have the exact same name, and stress-testing with a large number of tasks to make sure sorting doesn't degrade.

---

## 5. Reflection

**a. What went well**

The CLI-first workflow — building and verifying everything in main.py before touching
Streamlit. By the time I wired up the UI, the logic was already solid and tested. The
scheduler's generate_plan() method came together cleanly because each class had a single
clear responsibility from the UML stage.

**b. What you would improve**

The conflict detection is pretty basic — it only catches exact time matches, not overlapping
durations. If I had another iteration I'd add real time-range overlap checking and maybe let
the user resolve conflicts from the UI (pick which task to keep in the slot). I'd also add
persistence so your pets and tasks don't disappear when you close the browser.

**c. Key takeaway**

AI is great at generating code fast, but you still need to be the architect. The AI doesn't
know your design intent — it'll happily put the same logic in two places or add complexity
you don't need. The most valuable skill was knowing when to say "no, that's redundant" and
keeping the design clean. Using separate phases for design, implementation, and testing made
it way easier to stay organized and catch bad suggestions before they became real problems.

---

## 6. Applied AI Extension — Pet Care Advisor (RAG)

### a. What was added

A retrieval-augmented Pet Care Advisor was integrated into the existing Streamlit app. It uses Gemini for embedding and generation, retrieves from two sources (a curated markdown knowledge base **and** the user's live pet/task data), and routes every draft answer through a second-pass self-critic before showing it to the user. A retrieval-confidence floor short-circuits low-similarity questions to an honest "ask a vet" refusal, and an evaluation harness scores the system on six fixed scenarios.

### b. Limitations and biases

- **The KB is small and US-centric.** It uses Fahrenheit, US poison-control phone numbers, and reflects the author's choices about which breeds to highlight. Owners outside the US and people with breeds not represented in the KB (e.g., reptiles, birds, exotics) will get refusals or shallow answers.
- **Self-critique uses the same model family.** Gemini reviewing Gemini can share blind spots — a confidently-wrong draft may pass review. The retrieval-confidence threshold is a second line of defense, but it cannot catch a wrong answer that *is* well-supported by the retrieved chunks.
- **The personalized corpus is shallow.** It currently encodes pet name, species, and tasks. It does not know the pet's age, weight, breed, or medical history, so personalization is limited.
- **No persistence.** Pets and tasks live only in Streamlit session state, so personalized retrieval resets when the browser tab closes.

### c. Misuse and prevention

The advisor could be misused by an owner trying to substitute it for veterinary care — for example, asking it to diagnose symptoms or recommend medication doses. The system has two guardrails for this:

1. The system prompt tells the model never to give emergency medical advice and to redirect any sign of distress to a licensed veterinarian.
2. The `safety_emergencies` KB document explicitly enumerates the scenarios that demand a vet call, which the retriever surfaces for any safety-related query.

If this were a real product, additional steps would be a stronger safety classifier ahead of retrieval, rate-limiting per user, and an explicit disclaimer the user must accept on first use.

### d. What surprised me

How much of the work was **gating**, not generation. The fluent answers were the easy part — Gemini produces those out of the box. The harder problem was deciding when *not* to answer: tuning the cosine-similarity threshold so a question about French capitals refuses while a question about a Maine Coon retrieves cleanly, designing the critic prompt so it is willing to disagree with its own draft, and writing eval scenarios that distinguish "right for the right reasons" from "right by accident." The system became more trustworthy when I added more places where it could refuse, not more places where it could speak.

### e. AI collaboration on this extension — one helpful, one flawed

**Helpful:** when designing the advisor I asked the AI for a multi-source retrieval pattern. It suggested embedding the user's pets/tasks as natural-language snippets so they could be ranked alongside KB documents in a single cosine similarity call, rather than maintaining two separate retrieval paths and merging results. This was a clean simplification I had not thought of, and it made the personalized retrieval almost free to add.

**Flawed:** the AI initially proposed `models/text-embedding-004` as the embedding model when we were using Gemini. The Gemini API rejected it (404 — that ID was not available on the v1beta endpoint the Python SDK targets), forcing a switch to `gemini-embedding-001`. A second flawed assumption surfaced when we later swapped to OpenAI: the AI carried over the `0.55` cosine-similarity threshold I had tuned for Gemini's embedder, but `text-embedding-3-small` produces lower-magnitude scores, and a literal port would have caused the system to refuse every legitimate question. I had to re-tune the threshold to `0.35` against real embeddings. The lesson is that model IDs *and* numerical thresholds in AI-generated code are tied to a specific model family and must be re-verified when the underlying model changes.

### f. Future improvements

- Replace the in-memory NumPy index with a persistent vector store so the KB does not have to be re-embedded on every cold start.
- Expand the `Pet` model with age, breed, and weight, which would meaningfully improve personalization (e.g., "for *your* 4-month-old puppy, that means roughly 20 minutes twice a day").
- Add a small adversarial eval set that constructs plausible-but-ungrounded answers and verifies the critic catches them — the current eval shows the critic passing every good answer but does not yet prove it can reject bad ones.
- Let the advisor *propose* tasks back to the schedule (e.g., "I can add a 20-minute morning walk for Mochi at 7:00 — confirm?"), turning the read-only advisor into an opt-in agent with a human approval step.
