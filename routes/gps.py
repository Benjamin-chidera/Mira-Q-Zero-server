from fastapi import APIRouter
from typing import Optional
from utils.router import get_target_country
from utils.fetch_english_gps import fetch_english_gps
from utils.fetch_scottish_gps import fetch_scottish_gps
from utils.generate_gp_slots import generate_slots_for_gp
from datetime import datetime, timezone, timedelta

router = APIRouter()

@router.get("/gps")
async def get_nearby_gps(
    postcode: str,
    radius: Optional[int] = 5,
    startTime: Optional[str] = None,
    endTime: Optional[str] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
):
    country = get_target_country(postcode)

    if country == "SCOTLAND":
        scotlandGps = await fetch_scottish_gps(postcode)
        if "result" in scotlandGps and "records" in scotlandGps.get("result", {}):
            # Use local datetime to avoid UTC date mismatch/rollover issues
            today = datetime.now()
            s_date = startDate if startDate else today.strftime("%Y-%m-%d")
            e_date = endDate if endDate else (today + timedelta(days=7)).strftime("%Y-%m-%d")
            s_time = startTime if startTime else "09:00"
            e_time = endTime if endTime else "17:00"
            for record in scotlandGps["result"]["records"]:
                # PracticeCode comes back as an integer from the Scottish API (e.g. 11166).
                # We convert it to a string here because generate_slots_for_gp
                # expects a string (it calls .encode() on it internally).
                practice_code = str(record.get("PracticeCode", ""))
                if practice_code:
                    record["generated_slots"] = generate_slots_for_gp(
                        practice_code, s_date, e_date, s_time, e_time
                    )
        return scotlandGps

    englishGps = await fetch_english_gps(postcode)

    if "entry" in englishGps:
        # Use local datetime to avoid UTC date mismatch/rollover issues
        today = datetime.now() 
        s_date = startDate if startDate else today.strftime("%Y-%m-%d")
        e_date = endDate if endDate else (today + timedelta(days=7)).strftime("%Y-%m-%d")
        s_time = startTime if startTime else "09:00"
        e_time = endTime if endTime else "17:00"

        for item in englishGps["entry"]:
            ods_code = item["resource"]["id"]
            generated = generate_slots_for_gp(ods_code, s_date, e_date, s_time, e_time)
            item["resource"]["generated_slots"] = generated

    return englishGps
    