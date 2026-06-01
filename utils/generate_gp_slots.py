import hashlib
import random
from datetime import datetime, date, timedelta, time as dt_time, timezone
from sqlmodel import Session, select
from database import engine
from models import GPSlot

_FIRST_NAMES = ["James", "Sarah", "Michael", "Emma", "David", "Rachel", "John", "Claire", "Robert", "Helen"]
_LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis", "Miller", "Wilson", "Moore", "Taylor"]


def get_mock_gp_name(ods_code: str) -> str:
    h = int(hashlib.md5(ods_code.encode()).hexdigest(), 16)
    first = _FIRST_NAMES[h % len(_FIRST_NAMES)]
    last = _LAST_NAMES[(h // len(_FIRST_NAMES)) % len(_LAST_NAMES)]
    return f"Dr. {first} {last}"


def _is_future(d: str, t: str, now: datetime) -> bool:
    try:
        # slot_dt is parsed as a naive datetime representing local time
        slot_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
        return slot_dt > now
    except ValueError:
        return False


def generate_slots_for_gp(
    ods_code: str,
    start_date_str: str,
    end_date_str: str,
    start_time_str: str,
    end_time_str: str,
) -> list[dict]:
    practitioner_name = get_mock_gp_name(ods_code)
    # Use naive local datetime so it matches the practice/user local time directly
    now = datetime.now()

    try:
        s_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        e_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        s_date = date.today()
        e_date = s_date + timedelta(days=7)

    try:
        s_time = datetime.strptime(start_time_str, "%H:%M").time()
        e_time = datetime.strptime(end_time_str, "%H:%M").time()
    except (ValueError, TypeError):
        s_time = dt_time(9, 0)
        e_time = dt_time(17, 0)

    # Build only future 30-minute candidate slots across the date/time range.
    # If the requested date range has already passed or has no slots left,
    # we automatically roll over and search up to 7 days into the future.
    candidates: list[tuple[str, str]] = []
    current_day = s_date
    max_search_date = max(e_date, s_date + timedelta(days=7))

    while current_day <= max_search_date:
        current_dt = datetime.combine(current_day, s_time)
        end_dt = datetime.combine(current_day, e_time)
        while current_dt < end_dt:
            d_str = current_day.strftime("%Y-%m-%d")
            t_str = current_dt.strftime("%H:%M")
            if _is_future(d_str, t_str, now):
                candidates.append((d_str, t_str))
            current_dt += timedelta(minutes=30)
        
        # Stop if we have at least 4 future candidates and we have covered at least the requested e_date
        if len(candidates) >= 4 and current_day >= e_date:
            break
        current_day += timedelta(days=1)

    with Session(engine) as session:
        all_unbooked = session.exec(
            select(GPSlot).where(GPSlot.gp_ods_code == ods_code, GPSlot.is_booked == False)
        ).all()

        # Only keep slots that are still in the future, and sort them chronologically
        existing = [s for s in all_unbooked if _is_future(s.date, s.time, now)]
        existing.sort(key=lambda s: (s.date, s.time))

        if len(existing) >= 4:
            return [
                {"id": s.id, "date": s.date, "time": s.time, "practitioner_name": s.practitioner_name}
                for s in existing[:4]
            ]

        existing_pairs = {(s.date, s.time) for s in existing}
        new_candidates = [(d, t) for d, t in candidates if (d, t) not in existing_pairs]

        needed = 4 - len(existing)
        if new_candidates:
            # Pick the chronologically next slots instead of random scattering
            picked = new_candidates[:needed]
            for d, t in picked:
                session.add(GPSlot(gp_ods_code=ods_code, practitioner_name=practitioner_name, date=d, time=t))
            session.commit()

        all_slots = session.exec(
            select(GPSlot).where(GPSlot.gp_ods_code == ods_code, GPSlot.is_booked == False)
        ).all()

        future_slots = [s for s in all_slots if _is_future(s.date, s.time, now)]
        future_slots.sort(key=lambda s: (s.date, s.time))
        return [
            {"id": s.id, "date": s.date, "time": s.time, "practitioner_name": s.practitioner_name}
            for s in future_slots[:4]
        ]
