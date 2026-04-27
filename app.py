import streamlit as st
from datetime import date
from pawpal_system import Pet, Task, Owner, Schedule
from rag import PetCareAdvisor

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

# --- Session state: keep the Owner alive across reruns ---
if "owner" not in st.session_state:
    st.session_state.owner = Owner(name="Owner")

owner = st.session_state.owner

st.title("🐾 PawPal+")
st.caption("A smart pet care planning assistant")

# ── Owner info ──────────────────────────────────────────
with st.expander("Owner Settings", expanded=False):
    new_name = st.text_input("Your name", value=owner.name)
    available = st.number_input(
        "Available minutes today", min_value=10, max_value=480, value=owner.available_minutes
    )
    owner.name = new_name
    owner.available_minutes = available

# ── Add a Pet ───────────────────────────────────────────
st.subheader("🐶 Pets")

with st.form("add_pet_form"):
    col1, col2 = st.columns(2)
    with col1:
        pet_name = st.text_input("Pet name", value="Mochi")
    with col2:
        species = st.selectbox("Species", ["dog", "cat", "other"])
    add_pet = st.form_submit_button("Add pet")

if add_pet and pet_name:
    pet = Pet(name=pet_name, species=species)
    owner.add_pet(pet)
    st.success(f"Added {pet_name} the {species}!")

if owner.pets:
    for p in owner.pets:
        st.write(f"- **{p.name}** ({p.species}) — {len(p.tasks)} task(s)")
else:
    st.info("No pets yet. Add one above.")

st.divider()

# ── Add a Task ──────────────────────────────────────────
st.subheader("📋 Tasks")

if not owner.pets:
    st.info("Add a pet first before creating tasks.")
else:
    with st.form("add_task_form"):
        task_title = st.text_input("Task title", value="Morning walk")
        col1, col2 = st.columns(2)
        with col1:
            duration = st.number_input("Duration (min)", min_value=1, max_value=240, value=20)
        with col2:
            priority = st.selectbox("Priority", ["high", "medium", "low"])
        col3, col4, col5 = st.columns(3)
        with col3:
            pet_choice = st.selectbox("For which pet?", [p.name for p in owner.pets])
        with col4:
            scheduled = st.date_input("Date", value=date.today())
        with col5:
            scheduled_time = st.text_input("Time (HH:MM)", value="09:00")
        frequency = st.selectbox("Frequency", ["once", "daily", "weekly"])
        add_task = st.form_submit_button("Add task")

    if add_task and task_title:
        task = Task(
            title=task_title,
            duration_minutes=int(duration),
            priority=priority,
            scheduled_date=scheduled,
            scheduled_time=scheduled_time,
            frequency=frequency,
        )
        target_pet = next(p for p in owner.pets if p.name == pet_choice)
        target_pet.add_task(task)
        st.success(f"Added '{task_title}' for {pet_choice}!")

    # ── Task list with filtering ────────────────────────
    all_tasks = owner.get_all_tasks()
    if all_tasks:
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            filter_pet = st.selectbox(
                "Filter by pet", ["All"] + [p.name for p in owner.pets], key="filter_pet"
            )
        with filter_col2:
            filter_status = st.selectbox(
                "Filter by status", ["All", "Pending", "Completed"], key="filter_status"
            )

        # Apply filters using Schedule methods
        schedule_helper = Schedule(date=date.today(), owner=owner)
        filtered = all_tasks

        if filter_pet != "All":
            filtered = schedule_helper.filter_by_pet(filter_pet)

        if filter_status == "Pending":
            filtered = [t for t in filtered if not t.completed]
        elif filter_status == "Completed":
            filtered = [t for t in filtered if t.completed]

        # Build table data
        task_rows = []
        for t in filtered:
            pet_label = next((p.name for p in owner.pets if t in p.tasks), "?")
            task_rows.append({
                "Status": "✅" if t.completed else "⬜",
                "Task": t.title,
                "Time": t.scheduled_time,
                "Duration": f"{t.duration_minutes} min",
                "Priority": t.priority,
                "Pet": pet_label,
                "Date": str(t.scheduled_date),
                "Freq": t.frequency,
            })

        if task_rows:
            st.table(task_rows)
        else:
            st.info("No tasks match your filters.")

        # ── Mark complete / recurring ───────────────────
        incomplete = [t for t in all_tasks if not t.completed]
        if incomplete:
            task_to_complete = st.selectbox(
                "Mark a task complete",
                incomplete,
                format_func=lambda t: f"{t.title} ({t.scheduled_time})",
                key="complete_select",
            )
            if st.button("Mark complete"):
                next_task = task_to_complete.mark_complete()
                if next_task:
                    # Add the recurring follow-up to the same pet
                    for p in owner.pets:
                        if task_to_complete in p.tasks:
                            p.add_task(next_task)
                            st.success(
                                f"Completed '{task_to_complete.title}'! "
                                f"Next occurrence created for {next_task.scheduled_date}."
                            )
                            break
                else:
                    st.success(f"Completed '{task_to_complete.title}'!")
                st.rerun()
    else:
        st.info("No tasks yet.")

st.divider()

# ── Generate Schedule ───────────────────────────────────
st.subheader("📅 Daily Schedule")

schedule_date = st.date_input("Plan for date", value=date.today(), key="schedule_date")

if st.button("Generate schedule"):
    schedule = Schedule(date=schedule_date, owner=owner)
    plan = schedule.generate_plan()

    if plan:
        # Conflict warnings
        if schedule.warnings:
            for w in schedule.warnings:
                st.warning(f"⚠️ {w}")

        # Schedule table sorted by time
        sorted_plan = schedule.sort_by_time()
        total = sum(t.duration_minutes for t in sorted_plan)

        st.info(
            f"**{owner.name}'s plan for {schedule_date}** — "
            f"{total} min used / {owner.available_minutes} min available"
        )

        plan_rows = []
        for i, t in enumerate(sorted_plan, 1):
            pet_label = schedule._find_pet_for_task(t)
            freq_label = f" 🔁 {t.frequency}" if t.frequency != "once" else ""
            plan_rows.append({
                "#": i,
                "Time": t.scheduled_time,
                "Task": t.title,
                "Duration": f"{t.duration_minutes} min",
                "Priority": t.priority.upper(),
                "Pet": pet_label,
                "Recurrence": t.frequency,
            })
        st.table(plan_rows)

        # Skipped tasks
        all_for_date = [
            t for t in owner.get_tasks_for_date(schedule_date) if not t.completed
        ]
        skipped = [t for t in all_for_date if t not in plan]
        if skipped:
            with st.expander("Skipped tasks (not enough time)"):
                for t in skipped:
                    st.write(f"- **{t.title}** ({t.duration_minutes} min, {t.priority})")

        # Explanation
        with st.expander("Why this plan?"):
            st.markdown(
                "Tasks are sorted by **priority** (high first), then by **scheduled time**. "
                "The scheduler fits as many tasks as possible within your available time budget, "
                "starting with the most important ones."
            )
    else:
        st.warning("No incomplete tasks found for this date.")

st.divider()

# ── Pet Care Advisor (RAG) ──────────────────────────────
st.subheader("🤖 Pet Care Advisor")
st.caption(
    "Ask a question about pet care. The advisor retrieves from a curated knowledge "
    "base **and** your own pet/task data, then a second-pass critic reviews the answer "
    "for groundedness and safety before it's shown."
)


@st.cache_resource(show_spinner="Loading pet care knowledge base…")
def _get_advisor() -> PetCareAdvisor:
    return PetCareAdvisor()


try:
    advisor = _get_advisor()
    advisor_ready = True
except Exception as e:
    advisor = None
    advisor_ready = False
    st.error(f"Advisor unavailable: {e}")

question = st.text_input(
    "Your question",
    value="",
    placeholder="e.g., How long should I walk a Husky puppy?",
    key="advisor_question",
)

if st.button("Ask the advisor", disabled=not advisor_ready):
    if not question.strip():
        st.warning("Please type a question first.")
    else:
        with st.spinner("Retrieving and reasoning…"):
            result = advisor.ask(question, owner=owner)

        st.markdown(f"**Answer:** {result['answer']}")

        if result["sources"]:
            st.caption("📚 Retrieved sources: " + ", ".join(f"`{s}`" for s in result["sources"]))

        if result["low_confidence"]:
            st.warning(
                "⚠️ Low retrieval confidence — the question may be outside this assistant's scope."
            )
        elif result["critique_passed"]:
            st.success(f"✅ Critic passed: {result['critique_reason']}")
        else:
            st.error(f"❌ Critic flagged this answer: {result['critique_reason']}")
