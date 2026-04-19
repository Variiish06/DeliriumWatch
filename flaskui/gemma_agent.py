import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Use Gemma 3 4B via Gemini Developer API
GEMMA_MODEL = "models/gemma-3-4b-it"


def run_triage_agent(features: dict, shap_dict: dict, 
                     risk_level: str, probability: float) -> dict:
    """
    Gemma-powered clinical triage agent.
    
    Runs a structured chain-of-thought reasoning loop over the 
    patient's full clinical profile. Returns a dict with:
      - steps: list of reasoning step strings
      - interventions: prioritized list of recommended actions
      - urgency: ROUTINE / URGENT / IMMEDIATE
      - summary: one-line agent conclusion
    
    Falls back gracefully if Vertex AI is unavailable.
    """
    try:
        model = genai.GenerativeModel(GEMMA_MODEL)

        # ── Step 1: Vitals Assessment ──────────────────────────
        vitals = {k: v for k, v in features.items() 
                  if any(x in k.lower() for x in 
                  ['hr', 'rr', 'spo2', 'sbp', 'dbp', 'temp'])}
        
        step1_prompt = f"""You are a clinical triage agent assessing 
ICU delirium risk. This is Step 1 of 4.

STEP 1 — ASSESS VITAL SIGNS
Patient vitals: {vitals}
Normal ICU ranges: HR 60-100, RR 12-20, SpO2 >94%, SBP 90-140

In 2 sentences: Are vitals contributing to delirium risk? 
State which specific vitals are abnormal and why they matter."""

        step1 = model.generate_content(step1_prompt).text.strip()

        # ── Step 2: Sedation & Medications ────────────────────
        sedation = {k: v for k, v in features.items() 
                    if any(x in k.lower() for x in 
                    ['sedation', 'propofol', 'benzo', 
                     'midazolam', 'lorazepam', 'opioid'])}
        
        step2_prompt = f"""You are a clinical triage agent. This is 
Step 2 of 4.

STEP 2 — ASSESS SEDATION PROFILE
Sedation features: {sedation}
Previous finding (Step 1): {step1}

In 2 sentences: Is sedation burden contributing to delirium risk?
Heavy sedation is a major modifiable delirium risk factor."""

        step2 = model.generate_content(step2_prompt).text.strip()

        # ── Step 3: Sleep Disruption (NID) ────────────────────
        nid = features.get('nid_score', features.get('NID', 
              features.get('nighttime_intervention_density', None)))
        
        step3_prompt = f"""You are a clinical triage agent. This is 
Step 3 of 4.

STEP 3 — ASSESS SLEEP DISRUPTION
Nighttime Intervention Density (NID) score: {nid}
Context: NID measures nursing interventions during 22:00-06:00.
Average NID in non-delirious patients: ~3-4 interventions/night.
NID > 6 is associated with significantly elevated delirium risk.

Previous findings:
- Vitals: {step1}
- Sedation: {step2}

In 2 sentences: Is sleep fragmentation a primary driver here?
What does this NID value tell us about overnight care intensity?"""

        step3 = model.generate_content(step3_prompt).text.strip()

        # ── Step 4: Synthesize + Action Plan ──────────────────
        top_shap = sorted(shap_dict.items(), 
                          key=lambda x: abs(x[1]), 
                          reverse=True)[:5]
        shap_readable = ", ".join([
            f"{k.replace('_',' ')} ({v:+.3f})" 
            for k, v in top_shap
        ])

        step4_prompt = f"""You are a clinical triage agent completing 
your final assessment. This is Step 4 of 4.

STEP 4 — SYNTHESIZE AND PRODUCE ACTION PLAN
Overall delirium risk: {risk_level} ({probability:.1%})
Top model drivers: {shap_readable}

Your step-by-step findings:
1. Vitals: {step1}
2. Sedation: {step2}  
3. Sleep disruption: {step3}

Produce a structured action plan in this exact format:

URGENCY: [ROUTINE / URGENT / IMMEDIATE]

INTERVENTIONS (ranked by priority):
1. [Most important action — be specific, e.g. 
   "Reduce overnight nursing checks to every 2h if stable"]
2. [Second action]
3. [Third action]

AGENT CONCLUSION: [One sentence summarising the clinical picture 
and the single most impactful thing staff can do right now]

Do not use SHAP or ML jargon. Write for a bedside nurse."""

        step4 = model.generate_content(step4_prompt).text.strip()

        # ── Parse the structured output ───────────────────────
        urgency = "ROUTINE"
        if "URGENT" in step4.upper():
            urgency = "URGENT"
        if "IMMEDIATE" in step4.upper():
            urgency = "IMMEDIATE"

        # Extract interventions block
        interventions = []
        lines = step4.split('\n')
        for line in lines:
            line = line.strip()
            if (line.startswith('1.') or 
                line.startswith('2.') or 
                line.startswith('3.')):
                interventions.append(line[2:].strip())

        # Extract conclusion
        conclusion = ""
        for line in lines:
            if "AGENT CONCLUSION:" in line:
                conclusion = line.replace(
                    "AGENT CONCLUSION:", ""
                ).strip()

        return {
            "steps": [
                {"title": "Vital Signs Assessment", 
                 "content": step1},
                {"title": "Sedation Profile", 
                 "content": step2},
                {"title": "Sleep Disruption (NID)", 
                 "content": step3},
                {"title": "Synthesis & Action Plan", 
                 "content": step4},
            ],
            "interventions": interventions if interventions 
                             else ["Review full clinical picture",
                                   "Consult senior clinician",
                                   "Reassess in 2 hours"],
            "urgency": urgency,
            "summary": conclusion if conclusion 
                       else f"{risk_level} delirium risk — "
                            f"agent assessment complete.",
            "error": None
        }

    except Exception as e:
        return {
            "steps": [],
            "interventions": [
                "Agent unavailable — review SHAP chart manually",
                "Consult clinical team for intervention planning"
            ],
            "urgency": risk_level if risk_level in 
                       ["ROUTINE","URGENT","IMMEDIATE"] 
                       else "ROUTINE",
            "summary": (
                f"Agent assessment unavailable. "
                f"Model risk: {risk_level} ({probability:.1%}). "
                f"Error: {str(e)}"
            ),
            "error": str(e)
        }
