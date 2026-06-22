import os
import threading
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool
from langchain_community.tools import TavilySearchResults

load_dotenv()

# Set NVIDIA_NIM_API_KEY for CrewAI/litellm compatibility if not already set
if os.getenv("NVIDIA_API_KEY") and not os.getenv("NVIDIA_NIM_API_KEY"):
    os.environ["NVIDIA_NIM_API_KEY"] = os.getenv("NVIDIA_API_KEY")

# Thread-local storage to accumulate searched sources
thread_local_sources = threading.local()

# Initialize the underlying Tavily search instance
tavily_search_instance = TavilySearchResults(max_results=3)

@tool("Search clinical guidelines and trials")
def search_clinical_guidelines(query: str) -> str:
    """Searches the internet for clinical guidelines, medications, trials, NICE/ESC protocols, and general medical references using Tavily."""
    try:
        results = tavily_search_instance.invoke(query)
        if hasattr(thread_local_sources, "sources"):
            for r in results:
                if isinstance(r, dict) and "url" in r:
                    thread_local_sources.sources.append({
                        "label": r.get("title") or "Web Search Result",
                        "url": r["url"],
                        "type": "url"
                    })
        return str(results)
    except Exception as e:
        return f"Error searching: {str(e)}"

def get_mira_crew() -> Crew:
    """
    Assembles the CrewAI team for clinical research.
    Uses meta/llama-3.3-70b-instruct.
    """
    # Initialize LLM
    llm = LLM(
        model="nvidia_nim/meta/llama-3.3-70b-instruct",
        api_key=os.getenv("NVIDIA_NIM_API_KEY"),
        temperature=0.2
    )

    # 1. Clinical Intake Agent (The Context Parser)
    intake_agent = Agent(
        role="Clinical Intake Agent",
        goal=(
            "Read and synthesize all user inputs, PDF documents, and image descriptions to build a "
            "structured Research Target Matrix. CRITICAL: When the query involves a rare combination "
            "of conditions and procedures, you MUST decompose it into separate clinical entities — "
            "never leave them as a single merged topic."
        ),
        backstory=(
            "You are a clinical intake and triage specialist. You excel at parsing complex patient queries, "
            "extracting parameters from lab results or medical biopsy PDFs, and utilizing descriptions of "
            "medical scans/clinical photos to define the exact clinical parameters and anatomical conditions.\n\n"

            "MEDICAL DECOMPOSITION RULE:\n"
            "When a query involves a rare combination (e.g., 'Condition A + Surgery B'), you MUST decompose "
            "it into a Research Target Matrix with SEPARATE rows for:\n"
            "  1. Each underlying medical CONDITION (e.g., Class IV Lupus Nephritis, renal insufficiency).\n"
            "  2. Each PROCEDURE or SURGERY (e.g., total thyroidectomy, its physiological consequences).\n"
            "  3. Every ACTIVE MEDICATION or THERAPY the patient is on (e.g., chronic prednisone, "
            "mycophenolate, rituximab) — these MUST be flagged for interaction and perioperative risk analysis.\n\n"

            "NEVER combine these into a single search string like 'Lupus Nephritis thyroidectomy'. "
            "Each entity is a separate research axis. Your matrix must make each axis explicit so the "
            "Search Agent can query them independently."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False
    )

    # 2. Medical Search Agent (The Global Researcher)
    search_agent = Agent(
        role="Medical Search Agent",
        goal=(
            "Autonomous medical librarian combing global archives using web search tools to resolve "
            "rare clinical case questions. You MUST execute multiple independent sub-searches — "
            "NEVER search for the exact combined string of a rare pairing."
        ),
        backstory=(
            "You are an expert global clinical searcher. You translate the Research Target Matrix into "
            "optimized search parameters and query high-authority medical databases (PubMed, clinicaltrials.gov, "
            "the Lancet, NICE, ESC, or global registries).\n\n"

            "MEDICAL DECOMPOSITION RULE — MANDATORY SEARCH PROTOCOL:\n"
            "When the Research Target Matrix contains a rare combination of Condition + Procedure, "
            "you MUST execute THREE separate sub-searches:\n\n"

            "SUB-SEARCH 1 — CONDITION AXIS: Perioperative and anesthetic management and risks for "
            "the patient's underlying condition(s). Example: 'perioperative management lupus nephritis "
            "surgery anesthesia' or 'renal insufficiency surgical risk anesthesia guidelines'.\n\n"

            "SUB-SEARCH 2 — PROCEDURE AXIS: Critical physiological complications specific to the surgery "
            "itself, independent of the patient's condition. Example: 'total thyroidectomy complications "
            "parathyroid injury hypocalcemia' or 'thyroidectomy metabolic risks recurrent laryngeal nerve'.\n\n"

            "SUB-SEARCH 3 — MEDICATION/THERAPY AXIS: Drug interactions, perioperative contraindications, "
            "and required dose adjustments for every active medication in the patient profile. "
            "Example: 'chronic corticosteroid perioperative adrenal crisis stress dose protocol' or "
            "'mycophenolate perioperative immunosuppression surgical infection risk'.\n\n"

            "After completing all three sub-searches, ALSO search for the combined case if possible: "
            "'[Condition] [Procedure] case report'. But this is SUPPLEMENTARY — the three independent "
            "axes are the primary research. If the combined search returns nothing, that is expected "
            "and acceptable. The independent axis results are what matter.\n\n"

            "You specifically answer the 4 critical emergency questions from each axis:\n"
            "1. Has this procedure/treatment/surgical combination been done before?\n"
            "2. In what country/hospital was it performed?\n"
            "3. Who was the lead clinician or surgeon?\n"
            "4. How did they modify the treatment (steroids, immunosuppressants, etc.) and manage complications?"
        ),
        llm=llm,
        tools=[search_clinical_guidelines],
        verbose=True,
        allow_delegation=False
    )

    # 3. Clinical Evaluator & Writer Agent (The Quality Controller & Publisher)
    writer_agent = Agent(
        role="Clinical Evaluator & Writer Agent",
        goal=(
            "Verify safety of medical data, filter out noise/hallucinations, synthesize cross-domain "
            "clinical implications, and structure findings into the exact Emergency Research Brief format. "
            "You MUST connect the dots between independent search results using established clinical logic. "
            "NEVER output 'No information found' — synthesize from the available evidence."
        ),
        backstory=(
            "You are a senior clinical case publisher, auditor, and synthesis expert. You cross-reference "
            "search findings against patient parameters to filter out unreliable precedents and AI "
            "hallucinations. You organize the final verified clinical data into a clear report featuring "
            "direct references and citations.\n\n"

            "CLINICAL SYNTHESIS MANDATE — YOUR MOST CRITICAL RESPONSIBILITY:\n"
            "You receive findings from THREE independent sub-searches (Condition, Procedure, Medication). "
            "Your job is to CONNECT THE DOTS between them using established clinical logic. You must "
            "actively infer physiological chain-reactions that the search results may not explicitly state "
            "together.\n\n"

            "EXAMPLES OF REQUIRED SYNTHESIS:\n"
            "- If the patient has RENAL INSUFFICIENCY and is undergoing THYROIDECTOMY: you MUST flag the "
            "calcium metabolism trap. Renal insufficiency impairs Vitamin D hydroxylation + thyroidectomy "
            "risks parathyroid trauma = HYPOCALCEMIC CRISIS. The patient will need aggressive calcium "
            "and calcitriol supplementation perioperatively.\n"
            "- If the patient is on CHRONIC CORTICOSTEROIDS (e.g., prednisone for lupus) and is undergoing "
            "ANY major surgery: you MUST highlight the adrenal suppression risk. Chronic exogenous steroids "
            "suppress the HPA axis. Without an IV stress-dose of hydrocortisone (100mg bolus + 50mg q8h), "
            "the patient faces ADRENAL CRISIS during surgical stress.\n"
            "- If the patient is on IMMUNOSUPPRESSANTS (mycophenolate, rituximab, cyclophosphamide) and "
            "undergoing surgery: you MUST flag elevated infection risk, impaired wound healing, and "
            "whether to hold/reduce the immunosuppressant perioperatively.\n\n"

            "ABSOLUTE RULE: If no EXACT case report exists for the specific combination, you MUST still "
            "produce a clinically useful brief by synthesizing the individual axis findings. A doctor in "
            "an emergency needs actionable guidance from first principles — not a blank screen. "
            "Synthesize related cases, established physiological principles, and published guidelines "
            "to construct the best available clinical picture. Clearly label synthesized conclusions as "
            "'Clinical Inference (synthesized from related evidence)' vs direct case precedents."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False
    )

    # Define Tasks
    intake_task = Task(
        description=(
            "Synthesize the user's clinical question: '{user_query}'\n"
            "and any extracted context from attached files/images: '{extracted_context}'\n\n"
            "Build a Research Target Matrix with SEPARATE rows for:\n"
            "- Each underlying CONDITION (with severity, stage, relevant organ dysfunction)\n"
            "- Each PROCEDURE/SURGERY (with specific anatomical and physiological risks)\n"
            "- Each ACTIVE MEDICATION/THERAPY (with drug class, duration of use, and perioperative relevance)\n\n"
            "CRITICAL: Do NOT merge conditions and procedures into a single topic. Each must be its own "
            "research axis. If the patient is on chronic steroids, flag 'Adrenal Suppression Risk' as a "
            "mandatory research target. If the patient has renal dysfunction, flag 'Altered Drug Metabolism "
            "and Electrolyte Risks' as a mandatory research target."
        ),
        expected_output=(
            "A structured Research Target Matrix with clearly separated rows for each condition, procedure, "
            "and active medication. Each row should include: the clinical entity, its relevance to the case, "
            "and specific parameters requiring research."
        ),
        agent=intake_agent
    )

    search_task = Task(
        description=(
            "Using the Research Target Matrix, execute THREE mandatory independent sub-searches:\n\n"
            "SUB-SEARCH 1 — CONDITION AXIS:\n"
            "Search for perioperative/anesthetic management and risks for EACH underlying condition in the matrix. "
            "Use queries like '[Condition] perioperative management guidelines' and '[Condition] anesthesia risks'.\n\n"
            "SUB-SEARCH 2 — PROCEDURE AXIS:\n"
            "Search for critical physiological complications of the planned surgery/procedure, independent of "
            "the patient's conditions. Include metabolic traps, hormonal shifts, and anatomical risks. "
            "Use queries like '[Surgery] complications' and '[Surgery] metabolic risks postoperative'.\n\n"
            "SUB-SEARCH 3 — MEDICATION/THERAPY AXIS:\n"
            "Search for drug interactions, perioperative dose adjustments, and contraindications for EACH "
            "active medication. Use queries like '[Drug] perioperative management' and '[Drug] surgical risk "
            "dose adjustment protocol'.\n\n"
            "SUPPLEMENTARY — COMBINED CASE SEARCH:\n"
            "After the three independent searches, attempt ONE combined search for the rare pairing: "
            "'[Condition] [Procedure] case report'. If it returns nothing, that is expected — move on.\n\n"
            "For ALL results, answer these 4 questions where evidence exists:\n"
            "1. Has this combination been documented before?\n"
            "2. What country or hospital performed it?\n"
            "3. Who was the lead clinician?\n"
            "4. How did they modify treatment and manage complications?"
        ),
        expected_output=(
            "Raw text extracts, clinical case abstracts, and direct source links organized by search axis: "
            "Condition findings, Procedure findings, Medication findings, and any Combined case findings."
        ),
        agent=search_agent
    )

    writer_task = Task(
        description=(
            "Evaluate the research findings from ALL THREE sub-searches (Condition, Procedure, Medication) "
            "and the supplementary combined search. Filter out unreliable data or noise.\n\n"

            "CLINICAL SYNTHESIS MANDATE:\n"
            "Before writing, cross-reference findings across all three axes. Identify and explicitly document "
            "any physiological chain-reactions or compounding risks that emerge when combining the individual "
            "findings. For example:\n"
            "- Renal dysfunction + thyroidectomy = calcium metabolism trap (impaired Vitamin D activation "
            "+ parathyroid trauma risk = hypocalcemic crisis)\n"
            "- Chronic steroids + any major surgery = adrenal crisis risk (HPA axis suppression requires "
            "IV hydrocortisone stress-dose protocol)\n"
            "- Immunosuppressants + surgery = infection risk, impaired wound healing, hold/reduce decisions\n\n"

            "If no exact case precedent exists for the specific combination, you MUST synthesize from related "
            "evidence and first-principles clinical reasoning. Label these as 'Clinical Inference (synthesized "
            "from related evidence)'. NEVER output 'No information found' or leave sections empty.\n\n"

            "FORMAT THE OUTPUT IN EXACTLY THIS STRUCTURE:\n\n"

            "## 🚨 Emergency Research Brief: [Concise Topic Description]\n\n"

            "### 1. Precedent Status & Global Manifestations\n"
            "Summarize whether this exact combination has been documented. If not, synthesize the closest "
            "related case reports and note the gap. Include country, institution, and lead clinician if known.\n\n"

            "### 2. Surgical & Anesthetic Technique Considerations\n"
            "Detail procedure-specific risks, recommended anesthetic approaches, intraoperative monitoring "
            "requirements, and anatomical considerations relevant to the patient's conditions.\n\n"

            "### 3. Critical Treatment Alterations (Perioperative Protocol Changes)\n"
            "List ALL required medication adjustments: stress-dose steroids, immunosuppressant holds, "
            "electrolyte supplementation protocols, anticoagulation bridging, etc. Be specific with dosing "
            "where evidence supports it.\n\n"

            "### 4. Safety & Interaction Checks\n"
            "Drug-drug interactions, drug-condition contraindications, anesthesia-specific warnings, and "
            "any physiological chain-reactions identified through cross-axis synthesis. Use bullet points "
            "with severity indicators (⚠️ Warning, 🔴 Critical).\n\n"

            "### Sources & References\n"
            "List all publications, guidelines, and URLs consulted. All references MUST contain clickable "
            "links in standard markdown format: [Label](https://...). Prioritize high-authority sources: "
            "NICE, ESC, AHA, KDIGO, ASA, Lancet, NEJM, BMJ."
        ),
        expected_output=(
            "A complete Emergency Research Brief in the exact format specified, with all 4 numbered sections "
            "plus Sources & References. Every section must contain substantive clinical content — no empty "
            "sections or 'no information found' placeholders. Synthesized inferences must be clearly labeled."
        ),
        agent=writer_agent
    )

    # Assemble Crew (Sequential processing)
    return Crew(
        agents=[intake_agent, search_agent, writer_agent],
        tasks=[intake_task, search_task, writer_task],
        process=Process.sequential,
        verbose=True
    )
