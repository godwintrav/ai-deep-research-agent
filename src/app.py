import os

import gradio as gr
from dotenv import load_dotenv
from research_manager import ResearchManager
from styles import CSS, JS, EXAMPLES, HEADER_HTML

load_dotenv(override=True)


async def clarify_question(query: str, email: str):
    if not query or not query.strip():
        return gr.update(choices=[], value=None, visible=False), "Please enter a research question first.", None

    if not email or not email.strip():
        return gr.update(choices=[], value=None, visible=False), "Please enter your email address before continuing.", None

    manager = ResearchManager()
    manager.set_recipient_email(email.strip())

    async for clarifying_questions in manager.clarify_question(query):
        if not clarifying_questions or not clarifying_questions.clarified_questions:
            return gr.update(choices=[], value=None, visible=False), "No clarifying options were generated.", email.strip()

        options = [item.clarified_question for item in clarifying_questions.clarified_questions]
        return (
            gr.update(choices=options, value=None, visible=True),
            "Choose the option that best matches what you want to research.",
            email.strip(),
        )


async def run_selected_question(selected_question: str, recipient_email: str):
    if not selected_question:
        yield "Please choose a clarifying question before starting the research."
        return

    if not recipient_email:
        yield "Please provide your email address before starting the research."
        return

    manager = ResearchManager()
    manager.set_recipient_email(recipient_email)

    async for status_update in manager.run_research_agent(selected_question):
        yield status_update


with gr.Blocks(title="Deep Research") as ui:
    gr.HTML(HEADER_HTML)

    with gr.Row(elem_classes="dr-query-row"):
        query_textbox = gr.Textbox(
            placeholder="Type a research question...",
            show_label=False,
            container=False,
            autofocus=True,
            elem_id="dr-query",
            scale=4,
        )
        email_textbox = gr.Textbox(
            label="Your email",
            placeholder="you@example.com",
            type="email",
            container=False,
            elem_id="dr-email",
            scale=2,
        )
        run_button = gr.Button("Clarify", variant="primary", elem_id="dr-run", scale=1)

    recipient_email_state = gr.State(value=None)

    clarification_options = gr.Radio(
        label="Choose the best clarification",
        choices=[],
        visible=False,
        interactive=True,
    )

    gr.HTML('<div class="dr-examples-label">Try one</div>')
    gr.Examples(examples=EXAMPLES, inputs=query_textbox, elem_id="dr-examples")

    report = gr.Markdown(elem_id="dr-report")

    run_button.click(
        clarify_question,
        inputs=[query_textbox, email_textbox],
        outputs=[clarification_options, report, recipient_email_state],
    )
    query_textbox.submit(
        clarify_question,
        inputs=[query_textbox, email_textbox],
        outputs=[clarification_options, report, recipient_email_state],
    )
    clarification_options.change(
        run_selected_question,
        inputs=[clarification_options, recipient_email_state],
        outputs=report,
    )


def main():
    ui.launch(css=CSS, js=JS, theme=gr.themes.Base())


if __name__ == "__main__":
    main()
