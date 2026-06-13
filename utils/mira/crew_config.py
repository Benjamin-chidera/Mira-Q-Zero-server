import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool
from langchain_community.tools import TavilySearchResults

load_dotenv()

# Set NVIDIA_NIM_API_KEY for CrewAI/litellm compatibility if not already set
if os.getenv("NVIDIA_API_KEY") and not os.getenv("NVIDIA_NIM_API_KEY"):
    os.environ["NVIDIA_NIM_API_KEY"] = os.getenv("NVIDIA_API_KEY")

# Initialize the underlying Tavily search instance
tavily_search_instance = TavilySearchResults(max_results=3)

@tool("Search clinical guidelines and trials")
def search_clinical_guidelines(query: str) -> str:
    """Searches the internet for clinical guidelines, medications, trials, NICE/ESC protocols, and general medical references using Tavily."""
    try:
        return str(tavily_search_instance.run(query))
    except Exception as e:
        return f"Error searching: {str(e)}"

def get_mira_crew() -> Crew:
    """
    Assembles the CrewAI team for clinical research.
    Uses NVIDIA Llama 3.1 405B for all agents.
    """
    # Initialize LLM
    llm = LLM(
        model="nvidia_nim/meta/llama-3.3-70b-instruct",
        api_key=os.getenv("NVIDIA_NIM_API_KEY"),
        temperature=0.2
    )

    # 1. Literature Researcher Agent
    literature_researcher = Agent(
        role="Medical Literature Researcher",
        goal="Search the web and databases for clinical guidelines, drug information, and trial data.",
        backstory=(
            "You are a clinical librarian and research specialist. You excel at searching "
            "reputable sources like NICE, ESC, CDC, and PubMed to locate verified clinical evidence."
        ),
        llm=llm,
        tools=[search_clinical_guidelines],
        verbose=True,
        allow_delegation=False
    )

    # 2. Drug Interaction & Allergy Checker Agent
    interaction_checker = Agent(
        role="Drug Interaction & Allergy Specialist",
        goal="Analyze patient medication plans for contraindications, drug-drug interactions, and allergies.",
        backstory=(
            "You are a clinical pharmacist. You cross-reference current medications, new proposed drugs, "
            "allergies, and medical history (like GFR / renal function) to detect safety risks."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False
    )

    # 3. Clinical Analyst Agent
    clinical_analyst = Agent(
        role="Clinical Case Analyst",
        goal="Synthesize extracted patient data (lab results, scans, reports) with medical literature.",
        backstory=(
            "You are an expert diagnostician and consulting clinician. You interpret lab values, "
            "imaging reports, and doctor notes to formulate clinical options based on patient facts."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False
    )

    # 4. Summarizer Agent
    summarizer = Agent(
        role="Clinical Communication Specialist",
        goal="Synthesize inputs from all specialists into a unified, actionable, and structured response.",
        backstory=(
            "You translate complex findings into concise, readable clinical summaries. You ensure "
            "conclusions are direct, highlight warning signs, list sources clearly, and format using "
            "bold guidelines-compliant markdown for immediate use."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False
    )

    # Define Tasks
    research_task = Task(
        description=(
            "Perform search for the user's clinical question: '{user_query}'\n"
            "Search for current guidelines, standard practices, or drug indications.\n"
            "Rely on extracted context if provided: '{extracted_context}'"
        ),
        expected_output="A list of relevant clinical findings, drug details, and guidelines.",
        agent=literature_researcher
    )

    safety_task = Task(
        description=(
            "Review the patient's case and query: '{user_query}'\n"
            "With context: '{extracted_context}'\n"
            "Check for any drug-drug interactions, contraindications, dose adjustments "
            "(e.g., renal dosing based on GFR), or allergy conflicts. Highlight safety alerts clearly."
        ),
        expected_output="A list of safety concerns, contraindications, and dosing precautions.",
        agent=interaction_checker
    )

    analysis_task = Task(
        description=(
            "Analyze the user query: '{user_query}' using the extracted data: '{extracted_context}'\n"
            "Combine this with the findings from the research task and safety task. "
            "Provide clinical reasoning and options for management."
        ),
        expected_output="An analysis of clinical options, interpreting patient parameters against guidelines.",
        agent=clinical_analyst
    )

    summary_task = Task(
        description=(
            "Compile the research, safety reviews, and clinical analysis into a final summary.\n"
            "Format the output using standard ATX-style markdown headings (e.g., ### Heading, #### Subheading). "
            "Never use Setext-style headings (underlining text with === or ---). "
            "Use bullet points and bold inline styling for readability.\n"
            "Ensure the output includes:\n"
            "1. ### Clinical Recommendation: Bold, clear, and direct advice.\n"
            "2. ### Safety & Interactions Check: A summary of interactions, allergies, or contraindications.\n"
            "3. ### Supporting Evidence: Brief synthesis of guidelines used.\n"
            "4. ### Sources & References: List of publications or URLs checked. All references must contain clickable links in standard markdown format, e.g. [HealthyChildren.org](https://...)."
        ),
        expected_output="A structured markdown report for the practitioner.",
        agent=summarizer
    )

    # Assemble Crew (Sequential processing)
    return Crew(
        agents=[literature_researcher, interaction_checker, clinical_analyst, summarizer],
        tasks=[research_task, safety_task, analysis_task, summary_task],
        process=Process.sequential,
        verbose=True
    )
