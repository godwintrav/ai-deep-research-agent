from agents import Agent, function_tool, ModelSettings
from messenger import send_email, push
import os
from dotenv import load_dotenv
load_dotenv(override=True)

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4-mini")
USE_EMAIL = os.getenv("USE_EMAIL", "true").lower() == "true"

settings = ModelSettings(tool_choice="required")

@function_tool
def send_email_tool(subject: str, text_body: str, html_body: str, recipient_email: str) -> str:
    """
    Send a research report to the user via email.

    Args:
        subject: The email subject line.
        text_body: The plain-text version of the email body.
        html_body: The HTML version of the email body.
        recipient_email: The exact recipient email address provided in the workflow input.
            This value must be included and must not be guessed or invented.
    """
    if USE_EMAIL:
        print(f"sending email tool to {recipient_email}")
        send_email(subject, text_body, html_body, recipient_email)
    else:
        push(f"To: {recipient_email}\nSubject: {subject}\n\n{text_body}")
    return "Email sent successfully"


INSTRUCTIONS = """
You are provided with a detailed research report and the exact recipient_email value in the input.

Your job is to send the email using the send_email_tool function.

Strict requirements:
- Use the exact recipient_email value supplied in the input.
- Do not invent, ignore, or change the recipient_email.
- Build a clean subject line and a polished email body.
- Include both text_body and html_body in the tool call.
- Always include recipient_email when calling send_email_tool.
- The only valid email delivery is through send_email_tool.
"""

email_agent = Agent(name="Email Agent", instructions=INSTRUCTIONS, tools=[send_email_tool], model=MODEL_NAME, model_settings=settings)