from agents import Runner, function_tool, trace, gen_trace_id, Agent
from agents.exceptions import OutputGuardrailTripwireTriggered
from openai import APIConnectionError
from clarifying_agent import Questions, clarifying_agent
from search_agent import search_agent
from planner_agent import planner_agent, WebSearchItem, WebSearchPlan
from writer_agent import writer_agent, ReportData
from email_agent import email_agent
import asyncio
import os

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4-mini")

RESEARCH_AGENT_INSTRUCTIONS = """
You are the Research Orchestrator for a deep-research workflow.

Your job is to coordinate the full research process for the user’s original query by using the available tools in the correct order.

Follow this exact workflow:
1. First, call the search_planner tool with the original user query in this exact format:
   Query: {query}
   This tool produces a WebSearchPlan with the search tasks to run.
2. Next, call perform_searches with the WebSearchPlan returned by search_planner.
   This tool executes the planned searches and returns a list of search results.
3. After that, call write_report with:
   - the original user query
   - the list of search results returned by perform_searches
   This tool writes a final report object and returns a ReportData value.
4. Finally, call send_email with the ReportData returned by write_report.
   This is the last step in the workflow and must be called only after the report has been created.
5. Once send_email returns successfully, stop immediately and return the markdown_report value from that tool as the final output.
   Do not call any additional tools after send_email returns.
   Do not repeat the workflow after email has been sent.

Important rules:
- Do not skip steps.
- Do not call write_report before perform_searches.
- Do not call send_email before write_report.
- Use the original user query, not a derived or rewritten version, as the input to planner and report writing.
- The workflow terminates immediately after send_email succeeds.
- The final output of the workflow is the markdown_report returned by send_email.
- If email has already been sent and a result was returned, do not continue the loop or call any more tools.
"""

class ResearchManager:
    def __init__(self):
        self.trace_id = gen_trace_id()
        self.plan_search_tool = planner_agent.as_tool(
            tool_name="search_planner",
            tool_description=(
                "Creates a structured web-search plan for the original user query. "
                "This tool should be called first with the initial user question, and the input must be formatted exactly as: "
                "Query: {query}. "
                "It takes the original user query as input and returns a WebSearchPlan containing the specific searches to run."
            ),
        )
        self.perform_searches_tool = function_tool(self._perform_searches)
        self.write_report_tool = function_tool(self._write_report)
        self.send_email_tool = function_tool(self._send_email)

        self.tools = [
            self.plan_search_tool,
            self.perform_searches_tool,
            self.write_report_tool,
            self.send_email_tool,
        ]
        self.research_agent = Agent(
            name="Research Manager Agent",
            instructions=RESEARCH_AGENT_INSTRUCTIONS,
            tools=self.tools,
            model=MODEL_NAME,
        )

    async def clarify_question(self, initial_query):
        """ Run the Clarify agent and clarify the user initil question"""
        with trace("Research trace", trace_id=self.trace_id):
            clarifying_questions = await self.get_clarifying_questions(initial_query)
            yield clarifying_questions
        

    async def run(self, query: str):
        """ Run the deep research process, yielding the status updates and the final report"""
        
        with trace("Research trace", trace_id=self.trace_id):
            yield f"Starting research. Trace: https://platform.openai.com/traces/trace?trace_id={self.trace_id}"
            search_plan = await self.plan_searches(query)
            yield f"Searches planned, starting {len(search_plan.searches)} searches..."     
            search_results = await self.perform_searches(search_plan)
            yield "Searches complete, writing report..."
            report = await self.write_report(query, search_results)
            yield "Report written, sending email..."
            await self.send_email(report)
            yield "Email sent, research complete"
            yield report.markdown_report

    async def run_research_agent(self, query: str):
        task = f"""
Follow these steps exactly once in order:

1. Use the search_planner tool first to generate a search plan for the original user query.
   Input format must be exactly:
   Query: {query}
   Do not skip this step.

2. Once the search plan is ready, call perform_searches with the WebSearchPlan returned by search_planner.
   This tool executes the planned searches and returns the aggregated search results.

3. After the search results are ready, call write_report with:
   - the original user query
   - the list of search results returned by perform_searches
   This tool creates the final ReportData object.

4. Only after the report is ready, call send_email with the ReportData returned by write_report.
   This is the final tool call in the workflow and should only be used once.

5. Once send_email returns successfully, stop immediately and return the markdown_report value from the tool as the final output.
   Do not call any more tools after step 4 succeeds.
   Do not repeat any part of the workflow after the email step.
"""
        with trace("Research trace", trace_id=self.trace_id):
            yield f"Starting research. Trace: https://platform.openai.com/traces/trace?trace_id={self.trace_id}"
            result = await Runner.run(self.research_agent, task)
            yield result.final_output

    async def plan_searches(self, query: str) -> WebSearchPlan:
        """ Plan the searches to perform for the query """
        result = await Runner.run(planner_agent, f"Query: {query}")
        return result.final_output

    async def get_clarifying_questions(self, query: str) -> Questions:
        """ Returns three clarifying questions that best clarify the initial query for the user to select from """
        context = {"original_query": query}
        max_retries = 3
        last_output = None
        last_failure_reason = "The clarifying questions were not specific enough or did not reduce the ambiguity in the original query."

        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    result = await Runner.run(clarifying_agent, f"Query: {query}", context=context)
                else:
                    retry_prompt = (
                        f"Original query: {query}\n"
                        f"The previous clarifying attempt failed because: {last_failure_reason}\n"
                        "Please generate a better set of clarifying questions that fixes the issue above and keeps the options distinct, actionable, and useful."
                    )
                    result = await Runner.run(clarifying_agent, retry_prompt, context=context)

                last_output = result.final_output
                return last_output
            except OutputGuardrailTripwireTriggered as exc:
                guardrail_review = exc.guardrail_result.output.output_info.get("review")
                last_failure_reason = getattr(guardrail_review, "reason", str(guardrail_review))

                if attempt == max_retries - 1:
                    if last_output is not None:
                        return last_output
                    return exc.guardrail_result.agent_output
            except APIConnectionError:
                if last_output is not None:
                    return last_output
                return Questions(clarified_questions=[])
            except Exception:
                if last_output is not None:
                    return last_output
                return Questions(clarified_questions=[])

        if last_output is not None:
            return last_output

        return Questions(clarified_questions=[])

    async def _perform_searches(self, search_plan: WebSearchPlan) -> list[str]:
        """Execute the search plan generated by the search_planner tool.

        This tool should only be called with the WebSearchPlan returned by the search_planner tool.
        It iterates through each planned search, executes the underlying web searches, and returns
        the aggregated list of search results that will be used as input to the write_report tool.

        Args:
            search_plan: The search plan object returned by the search_planner tool.

        Returns:
            A list of search result strings that summarize the findings for each planned query.
        """
        tasks = [self.search(item) for item in search_plan.searches]
        return await asyncio.gather(*tasks)

    async def search(self, item: WebSearchItem) -> str | None:
        """ Perform a search for the query """
        input_message = f"Search term: {item.query}\nReason for searching: {item.reason}"
        result = await Runner.run(search_agent, input_message)
        return result.final_output

    async def _write_report(self, query: str, search_results: list[str]) -> ReportData:
        """Write a final report for the user query using the search results returned by the perform_searches tool.

        Args:
            query: The initial user query exactly as provided by the user.
            search_results: The list of search results returned by the perform_searches tool, which should be used as the source material for the report.
        """
        input_message = f"Original query: {query}\nSummarized search results: {search_results}"
        result = await Runner.run(writer_agent, input_message)
        return result.final_output

    async def _send_email(self, report: ReportData) -> str:
        """Send the final research report to the user by email.

        This is the last tool in the workflow and should only be called with the ReportData returned by the write_report tool.

        Args:
            report: The final report object returned by write_report, containing the markdown report content.

        Returns:
            The markdown_report field from the report so it can be used as the final output of the workflow.
        """
        print("sending email")
        await Runner.run(email_agent, report.markdown_report)
        return report.markdown_report