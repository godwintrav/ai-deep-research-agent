import gradio as gr
from dotenv import load_dotenv
from research_manager import ResearchManager
from styles import CSS, JS, EXAMPLES, HEADER_HTML

load_dotenv(override=True)


async def clarify_question(query: str):
    if not query or not query.strip():
        return gr.update(choices=[], value=None, visible=False), "Please enter a research question first."

    manager = ResearchManager()
    async for clarifying_questions in manager.clarify_question(query):
        if not clarifying_questions or not clarifying_questions.clarified_questions:
            return gr.update(choices=[], value=None, visible=False), "No clarifying options were generated."

        options = [item.clarified_question for item in clarifying_questions.clarified_questions]
        return (
            gr.update(choices=options, value=None, visible=True),
            "Choose the option that best matches what you want to research.",
        )


async def run_selected_question(selected_question: str):
    if not selected_question:
        yield "Please choose a clarifying question before starting the research."
        return

    manager = ResearchManager()
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
            scale=5,
        )
        run_button = gr.Button("Clarify", variant="primary", elem_id="dr-run", scale=1)

    clarification_options = gr.Radio(
        label="Choose the best clarification",
        choices=[],
        visible=False,
        interactive=True,
    )

    gr.HTML('<div class="dr-examples-label">Try one</div>')
    gr.Examples(examples=EXAMPLES, inputs=query_textbox, elem_id="dr-examples")

    report = gr.Markdown(elem_id="dr-report")

    run_button.click(clarify_question, inputs=query_textbox, outputs=[clarification_options, report])
    query_textbox.submit(clarify_question, inputs=query_textbox, outputs=[clarification_options, report])
    clarification_options.change(run_selected_question, inputs=clarification_options, outputs=report)


if __name__ == "__main__":
    ui.launch(css=CSS, js=JS, theme=gr.themes.Base())
