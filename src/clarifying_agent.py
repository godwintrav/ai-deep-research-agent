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

Return the result as a list of {NUM_OF_CLARIFYING_QUESTIONS} clarifying questions. For each item, include:
- a short reason explaining why this option is clearer than the original query
- the refined question text the user can select

Do not output raw search terms or keyword lists. Output only the clarifying options the user can choose from.
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
        "If all questions are good, set is_clarified_correctly to true and unclarified_questions to an empty list."
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