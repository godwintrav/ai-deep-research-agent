from pydantic import BaseModel, Field
from agents import Agent, GuardrailFunctionOutput, Runner, output_guardrail
from agents.exceptions import OutputGuardrailTripwireTriggered
import os
from dotenv import load_dotenv
load_dotenv(override=True)

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4-mini")
NUM_OF_CLARIFYING_QUESTIONS = int(os.getenv("NUM_OF_CLARIFYING_QUESTIONS", 3))


CLARIFYING_AGENT_INSTRUCTIONS = f"""
You are a research assistant helping a user refine an unclear question before doing research.

Given a user query, identify what is ambiguous or underspecified and produce exactly {NUM_OF_CLARIFYING_QUESTIONS} clearer, well-phrased options that the user could choose from.

Each option should:
- be a more specific version of the original question
- be actionable and easy to understand
- narrow the scope in a useful way without being overly rigid
- help the user choose the best research direction
- focus on a meaningful interpretation of the original query rather than a generic rewording

Return the result as a list of {NUM_OF_CLARIFYING_QUESTIONS} clarifying questions. For each item, include:
- a short reason explaining why this option is clearer than the original question
- the refined question text the user can select

Output format requirements:
- Return valid JSON matching the `Questions` schema.
- The top-level object must contain a `clarified_questions` list.
- Each item must have:
  - `reason`: a concise explanation of why this option is clearer
  - `clarified_question`: the final refined question text
- Do not output raw search terms, keyword lists, or unrelated commentary.
- Do not give more than {NUM_OF_CLARIFYING_QUESTIONS} options.

Few-shot examples:

Example 1:
Input query: "How do I start a business?"
Good output:
{{
  "clarified_questions": [
    {{
      "reason": "This option keeps the same core question but makes it more specific by focusing on building a business that can actually succeed.",
      "clarified_question": "How do I start a successful business?"
    }},
    {{
      "reason": "This version clarifies the question by focusing on the actions needed to begin a strong business launch.",
      "clarified_question": "What are the steps to take to start a successful business?"
    }},
    {{
      "reason": "This keeps the original intent while making the goal more tangible: what should be done to build a successful business from the beginning.",
      "clarified_question": "What should I do to start a successful business?"
    }}
  ]
}}

Example 2:
Input query: "How do I lose weight?"
Good output:
{{
  "clarified_questions": [
    {{
      "reason": "This version is clearer because it frames the question around a practical, sustainable result rather than a vague goal.",
      "clarified_question": "How do I lose weight healthily?"
    }},
    {{
      "reason": "This keeps the same question but adds the key requirement of a sustainable and realistic approach.",
      "clarified_question": "What should I do to lose weight in a healthy and sustainable way?"
    }},
    {{
      "reason": "This clarifies the objective by focusing on a realistic and actionable path to weight loss.",
      "clarified_question": "How can I lose weight effectively and keep it off?"
    }}
  ]
}}

Good clarification style:
- Keep the same core topic as the original query.
- Improve the phrasing and specificity without changing the subject matter.
- Make the question clearer and more actionable.
- Prefer better wording, not a different research angle.

Bad patterns to avoid:
- Changing the subject into a different niche or business model.
- Creating a completely different research question.
- Over-focusing on one subtopic so the question stops representing the original user intent.
- Repeating the same vague idea with tiny wording changes.

Now generate the clarifying questions for the actual user query.
"""

class Question(BaseModel):
    reason: str = Field(description="Your reasoning for why this question is more clarifying than the initial question.")
    clarified_question: str = Field(description="The Clarified question created from the initial question.")


class Questions(BaseModel):
    clarified_questions: list[Question] = Field(description="A list of clarifying questions that best clarifies the initial question")

class ClarifiedQuestionsReview(BaseModel):
    reason: str = Field(
        description=(
            "Explain whether the proposed clarifying questions actually reduce ambiguity in the original query. "
            "Mention what is missing, too broad, too narrow, repetitive, or still ambiguous."
        )
    )
    is_clarified_correctly: bool = Field(
        description=(
            "True only when all clarifying questions meaningfully narrow the original question, are distinct from each other, "
            "and help a user choose a research direction without repeating the same ambiguity. "
            "False when the questions are vague, redundant, off-topic, or do not improve the original query."
        )
    )
    unclarified_questions: list[str] = Field(
        description=(
            "A list of the clarifying questions that still fail to clarify the original query. "
            "Include only the ones that are still vague, repetitive, too broad, or not actionable. "
            "If all questions are good, return an empty list."
        )
    )

clarified_question_guardrail_agent = Agent(
    name="Clarified Questions Guardrail check",
    instructions=(
        "You are a quality-control guardrail for a research clarifying step. "
        "Your job is to judge whether the generated clarifying questions genuinely improve a vague original query. "
        "A good clarification set should: "
        "- remove ambiguity from the original question, "
        "- produce distinct options that explore different valid interpretations, "
        "- be specific enough to guide research, "
        "- be actionable and easy for a user to choose from, "
        "- avoid redundancy, vagueness, or questions that are basically the same as the original. "
        "A bad clarification set includes questions that are too broad, too narrow, repetitive, generic, off-topic, or still ambiguous. "
        "Return whether the set is acceptable, explain why, and list only the questions that still fail to clarify the original query. "
        "If all questions are good, set is_clarified_correctly to true and unclarified_questions to an empty list. "
        "Examples of good sets: a user asking 'How do I start a business?' should yield options like 'How do I start a successful business?', 'What should I do to start a successful business?', or 'What are the steps to take to start a successful business?'. "
        "These are not different topics; they are clearer, more specific versions of the same core question. "
        "Examples of bad sets: a completely different business niche, an off-topic question, keyword lists, or three near-identical restatements of the same vague question. "
        "Use the original query as the reference for whether the clarifying options actually reduce ambiguity without changing the user’s intent."
    ),
    output_type=ClarifiedQuestionsReview,
)

@output_guardrail
async def clarify_question_guardrail(ctx, agent, message):
    original_query = ctx.context.get("original_query") if ctx.context else None

    guardrail_message = (
        "Original query:\n"
        f"{original_query}\n\n"
        "Generated clarifying questions:\n"
        f"{message}"
    )

    result = await Runner.run(clarified_question_guardrail_agent, guardrail_message, context=ctx.context)
    review = result.final_output
    tripwire_triggered = not review.is_clarified_correctly
    return GuardrailFunctionOutput(output_info={"review": review}, tripwire_triggered=tripwire_triggered)

clarifying_agent = Agent(name="Clarifying Agent", instructions=CLARIFYING_AGENT_INSTRUCTIONS, model=MODEL_NAME, output_type=Questions, output_guardrails=[clarify_question_guardrail])