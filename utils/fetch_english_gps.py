import httpx

async def fetch_english_gps(postcode: str):
    async with httpx.AsyncClient() as client:
        # We assume postcode here is the outcode or we just pass the full postcode
        # NHS FHIR API expects outcode for broader searches
        outcode = postcode.split()[0] if ' ' in postcode else postcode[:4].strip()
        url = f"https://sandbox.api.service.nhs.uk/organisation-data-terminology-api/fhir/Organization?address-postalcode={outcode}&roleCode=RO177&_count=50"
        response = await client.get(url)
        return response.json()
