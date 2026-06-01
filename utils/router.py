import re

# A simple lookup for Scottish Outcode Areas
SCOTLAND_AREAS = {"AB", "DD", "DG", "EH", "FK", "G", "HS", "IV", "KA", "KW", "KY", "ML", "PA", "PH", "ZE", "TD"}

def get_target_country(postcode: str) -> str:
    """
    Determines if a postcode belongs to Scotland or England/Wales.
    """
    clean_pc = postcode.strip().upper()
    # Extract the Area (letters at the start)
    match = re.match(r"^([A-Z]{1,2})", clean_pc)
    
    if match:
        area = match.group(1)
        if area in SCOTLAND_AREAS:
            return "SCOTLAND"
    
    return "ENGLAND_WALES"
