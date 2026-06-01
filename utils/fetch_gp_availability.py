import httpx
from datetime import datetime

async def get_gp_availability(ods_code: str, start_time: str, end_time: str):
    # # Sandbox Base URL
    # url = "https://sandbox.api.service.nhs.uk/gp-connect/patient-facing/appointment-management/fhir/STU3/Slot"
    url = "https://sandbox.api.service.nhs.uk/gp-connect/appointment-management/fhir/STU3/Slot"
    
    # headers = {
    #     "Ssp-From": "200000000359", # Standard Sandbox ASID
    #     "Ssp-To": "918999198999",   # Mock Target ASID
    #     "Ssp-InteractionID": "urn:nhs:names:services:gpconnect:fhir:rest:search:slot-1",
    #     "Accept": "application/fhir+json"
    # }

    headers = {
        "Ssp-From": "200000000359",
        "Ssp-To": "918999198999",
        "Ssp-InteractionID": "urn:nhs:names:services:gpconnect:fhir:rest:search:slot-1", # Keep this
        "Accept": "application/fhir+json"
    }
    
    # query for 'free' slots within the user's window


    # params = {
    #    "schedule.actor:healthcareservice": f"Organization/{ods_code}", 
    #     "start": [f"ge{start_time}", f"le{end_time}"], 
    #     "status": "free",
    #     "_format": "json",
    #     "_include": "Slot:schedule",
    #     "_include:iterate": "Schedule:actor:Practitioner"
    # }

    params = {
        # Try removing the ':healthcareservice' suffix if the URL fix alone doesn't work
        "schedule.actor": f"Organization/{ods_code}", 
        "start": [f"ge{start_time}", f"le{end_time}"], 
        "status": "free",
        "_format": "json",
        "_include": "Slot:schedule",
        "_include:iterate": "Schedule:actor:Practitioner"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                bundle = response.json()
                
                # Extract the Slots
                slots = [item['resource'] for item in bundle.get('entry', []) if item['resource']['resourceType'] == 'Slot']
                
                # Extract the Practitioners (The Doctors)
                practitioners = [item['resource'] for item in bundle.get('entry', []) if item['resource']['resourceType'] == 'Practitioner']
                
                if not slots:
                    print(f"\n--- EMPTY RESPONSE FOR {ods_code} ---")
                    print(f"URL: {response.url}")
                    print(f"HEADERS: {headers}")
                    print(f"PARAMS: {params}")
                    print(f"RESPONSE JSON: {bundle}")
                    print("--------------------------------------\n")
                
                return {"slots": slots, "practitioners": practitioners}
            else:
                print(f"\n--- ERROR STATUS {response.status_code} FOR {ods_code} ---")
                print(f"URL: {response.url}")
                print(f"HEADERS: {headers}")
                print(f"PARAMS: {params}")
                print(f"RESPONSE TEXT: {response.text}")
                print("--------------------------------------\n")
                return {"slots": [], "practitioners": []}
        except Exception as e:
            print(f"Error fetching slots for {ods_code}: {e}")
            return {"slots": [], "practitioners": []}
