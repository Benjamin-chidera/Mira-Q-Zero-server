import httpx

# The NHS Scotland Open Data portal resource ID for GP Practice Contact Details.
# If this stops working, visit https://www.opendata.nhs.scot/dataset/gp-practice-contact-details-and-list-sizes
# and copy the resource_id from the latest dataset.
SCOTTISH_GP_RESOURCE_ID = "e572d9fd-c82d-4f22-8623-1353018843f8"

BASE_URL = "https://www.opendata.nhs.scot/api/3/action/datastore_search"


def extract_outcode(postcode: str) -> str:
    """
    Extract the outward code (first part) from a postcode.
    
    Examples:
      "DD3 9AT" -> "DD3"
      "DD3"     -> "DD3"
      "EH12 5EA" -> "EH12"
    """
    # Strip any extra whitespace first
    cleaned = postcode.strip()

    # If there's a space, the outcode is everything before the first space
    if " " in cleaned:
        return cleaned.split(" ")[0]

    # If no space, assume the whole thing is the outcode (e.g. user typed "DD3")
    return cleaned


async def fetch_scottish_gps(postcode: str): 
    """
    Fetch GP practices from the NHS Scotland Open Data API.
    Searches by outward code (e.g. "DD3") to find practices in that area.
    
    Returns the raw JSON from the API, or an error dict if something goes wrong.
    """
    outcode = extract_outcode(postcode)

    params = {
        "resource_id": SCOTTISH_GP_RESOURCE_ID,
        "q": outcode,
        "limit": 50,  # Limit results to a reasonable number
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(BASE_URL, params=params)

            # Raise an exception for 4xx/5xx HTTP status codes
            response.raise_for_status()

            data = response.json()

            # The NHS Scotland API wraps results in a "result" key with a "success" flag
            if not data.get("success"):
                print(f"[Scottish GP API] API returned success=false for outcode: {outcode}")
                print(f"[Scottish GP API] Response: {data}")
                return {"result": {"records": []}, "error": "Scottish GP API returned an unsuccessful response"}

            return data

    except httpx.HTTPStatusError as e:
        # The external API returned a 4xx or 5xx error
        print(f"[Scottish GP API] HTTP error fetching GPs for {outcode}: {e.response.status_code} - {e.response.text}")
        return {"result": {"records": []}, "error": f"Scottish GP API returned HTTP {e.response.status_code}"}

    except httpx.TimeoutException:
        print(f"[Scottish GP API] Request timed out for outcode: {outcode}")
        return {"result": {"records": []}, "error": "Scottish GP API request timed out"}

    except Exception as e:
        print(f"[Scottish GP API] Unexpected error for outcode {outcode}: {e}")
        return {"result": {"records": []}, "error": str(e)}
