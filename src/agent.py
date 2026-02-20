"""
Static Site Agent Logic - Using LangChain
"""
import os
import re
import json
import logging
from typing import List, Dict, Any, Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain.callbacks.base import BaseCallbackHandler

from tools import (
    analyze_reference_site,
    generate_static_site,
    containerize_site,
    deploy_to_spaces,
    list_spaces_buckets,
    download_site_from_spaces,
    delete_site_from_spaces,
    read_file,
    write_file,
)

# Setup logger
logger = logging.getLogger("static-site-agent")


def _extract_first_json(s: str) -> Optional[str]:
    """Extract the first complete JSON object (balanced braces) from a string."""
    s = s.strip()
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


class DetailedLoggingCallback(BaseCallbackHandler):
    """Custom callback handler for detailed logging"""
    
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """Log when LLM starts"""
        logger.info(f"\n{'='*80}\nLLM REQUEST STARTED\n{'='*80}")
        if prompts:
            logger.info(f"Prompt: {prompts[0][:500]}...")
    
    def on_llm_end(self, response, **kwargs) -> None:
        """Log when LLM ends"""
        logger.info(f"\n{'='*80}\nLLM RESPONSE RECEIVED\n{'='*80}")
        if hasattr(response, 'generations') and response.generations:
            content = response.generations[0][0].text[:500] if hasattr(response.generations[0][0], 'text') else str(response.generations[0][0])[:500]
            logger.info(f"Response: {content}...")
        if hasattr(response, 'llm_output') and response.llm_output:
            usage = response.llm_output.get('token_usage', {})
            if usage:
                logger.info(f"Token Usage: {usage}")
    
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """Log when tool starts"""
        tool_name = serialized.get('name', 'unknown')
        logger.info(f"\n{'='*80}\nTOOL EXECUTION: {tool_name}\n{'='*80}")
        logger.info(f"Tool Input: {input_str}")
    
    def on_tool_end(self, output: str, **kwargs) -> None:
        """Log when tool ends"""
        logger.info(f"Tool Output: {output[:500]}...")
        logger.info(f"{'='*80}\n")
    
    def on_tool_error(self, error: Exception, **kwargs) -> None:
        """Log tool errors"""
        logger.error(f"Tool Error: {str(error)}")


class Agent:
    def __init__(self):
        self.name = "Static Site Agent"
        self.spaces_configured = bool(
            os.getenv('SPACES_ACCESS_KEY_ID') or os.getenv('SPACES_KEY')
        ) and bool(
            os.getenv('SPACES_SECRET_ACCESS_KEY') or os.getenv('SPACES_SECRET')
        )
        self.chat_history = []
        
        # 1. Define Tools
        self.tools = [
            analyze_reference_site,
            generate_static_site,
            containerize_site,
            deploy_to_spaces,
            list_spaces_buckets,
            download_site_from_spaces,
            delete_site_from_spaces,
            read_file,
            write_file,
        ]
        
        # 2. Setup LLM
        openai_key = os.getenv('OPENAI_API_KEY')
        do_gradient_key = os.getenv('DO_GRADIENT_API_KEY')
        
        self.use_gradient_tool_loop = bool(do_gradient_key)
        if openai_key:
            self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
        elif do_gradient_key:
            self.llm = ChatOpenAI(
                model="claude-sonnet-4-5-20250929",
                temperature=0.7,
                api_key=do_gradient_key,
                base_url="https://inference.do-ai.run/v1"
            )
        else:
            raise ValueError("Either OPENAI_API_KEY or DO_GRADIENT_API_KEY must be set")

        spaces_info = "Spaces credentials are configured - deploy_to_spaces will work." if self.spaces_configured else "Spaces credentials are NOT set - deploy_to_spaces needs SPACES_ACCESS_KEY_ID and SPACES_SECRET_ACCESS_KEY."

        if self.use_gradient_tool_loop:
            # Custom tool loop for Gradient: we ask the LLM for TOOL_CALL + JSON or FINAL_ANSWER, parse, and run tools.
            self.tools_by_name = {t.name: t for t in self.tools}
            self.gradient_system_prompt = f"""You are a Static Site Generation and Deployment Agent. You MUST call tools by outputting exactly one of these two formats.

To call a tool, output on a single line:
TOOL_CALL
Then on the next line(s), output a single JSON object: {{"tool": "<tool_name>", "input": {{ ... tool arguments ... }}}}

To finish and reply to the user, output:
FINAL_ANSWER
Then on the next line(s), your final reply to the user.

Available tools:
1. analyze_reference_site - Args: url (full URL of a reference website). Analyzes a website to extract its visual design: colors, fonts, layout, mood, and image style. Returns a ReferenceDesignResult with colors, fonts, layout, mood, and image_style fields. Use this when the user wants their site to "look like", be "similar to", or be "inspired by" another website.
2. generate_static_site - Args: site_type (e.g. "portfolio", "landing page", "blog", "business"), style_hints (optional), site_name (optional), user_request (optional), user_content (optional), reference_design (optional JSON string from analyze_reference_site). When user_request is set, the site is customized: multi-page, images, and AI-generated or user-provided text. Always pass the user's full request as user_request so the design matches what they asked for. If they provided specific text to include, pass it as user_content. If a reference site was analyzed, pass the full result as reference_design (JSON string). Returns site_path.
3. containerize_site - Args: site_path (from generate_static_site), image_name (optional).
4. deploy_to_spaces - Args: site_path, bucket_name (3-63 chars, lowercase/dashes), region (default "nyc3"), spaces_access_key (optional), spaces_secret_key (optional), make_public (default true), create_bucket_if_missing (default true). Uploads the site to DigitalOcean Spaces.
5. list_spaces_buckets - Args: region (default "nyc3"), spaces_access_key (optional), spaces_secret_key (optional). Lists all Spaces buckets (sites) in the account.
6. download_site_from_spaces - Args: bucket_name, region (default "nyc3"), spaces_access_key (optional), spaces_secret_key (optional). Downloads a site from a Space to a local path for editing. Returns site_path.
7. delete_site_from_spaces - Args: bucket_name, region (default "nyc3"), spaces_access_key (optional), spaces_secret_key (optional). Permanently deletes a Space (site) by name. Use when the user asks to delete or remove a site.
8. read_file - Args: file_path (full path, e.g. site_path + "/index.html"). Reads file contents. Use only for paths under temp dir (downloaded or generated sites).
9. write_file - Args: file_path, content. Writes content to a file. Use only for paths under temp dir. After editing, call deploy_to_spaces to save back.

Rules:
- When the user references another website URL or says "looks like", "similar to", or "inspired by" another site, FIRST call analyze_reference_site(url) to extract the design. Tell the user what you found (colors, fonts, mood). THEN call generate_static_site with the analysis result as the reference_design parameter (pass it as a JSON string).
- When the user asks for a site (without a reference), output a TOOL_CALL for generate_static_site. Always pass the user's full message as user_request so the site is customized (multi-page, images, relevant or user text). Use the returned site_path in later steps.
- When the user wants to list their sites, call list_spaces_buckets. In your reply, include the full URL for each site (from the tool result) so the user can click to open the site in a new window.
- When the user wants to EDIT an existing site: (1) call list_spaces_buckets if they need to pick a site, (2) call download_site_from_spaces(bucket_name) to get site_path, (3) call read_file(site_path + "/index.html") and/or read_file(site_path + "/styles.css"), (4) call write_file with the modified content, (5) call deploy_to_spaces(site_path, bucket_name) to save back to the bucket.
- When the user wants to DELETE a site, call delete_site_from_spaces(bucket_name). Use the exact bucket name (e.g. from list_spaces_buckets).
- When the user wants to deploy to Spaces, output TOOL_CALL for deploy_to_spaces with site_path (from a previous result) and bucket_name. {spaces_info}
- Output only TOOL_CALL + JSON or FINAL_ANSWER + text. No other commentary before or after."""
            self.agent_executor = None
            logger.info("Using custom JSON tool loop for Gradient (tools will be executed)")
        else:
            # Native tool-calling agent (OpenAI)
            prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are a Static Site Generation and Deployment Agent with access to these tools:

1. analyze_reference_site(url) - Analyzes a reference website to extract its visual design: colors, fonts, layout, mood, and image style. Use when the user wants their site to "look like", be "similar to", or be "inspired by" another website. Returns a ReferenceDesignResult with colors, fonts, layout, mood, and image_style.
2. generate_static_site(site_type, style_hints, site_name, user_request, user_content, reference_design) - Creates HTML/CSS files. Pass the user's full request as user_request for customized multi-page sites with images and generated or user text; optional user_content for text they provided to include. Optional reference_design is a JSON string from analyze_reference_site to match another site's visual style.
3. containerize_site(site_path, image_name) - Creates Docker containers
4. deploy_to_spaces(site_path, bucket_name, region, ...) - Uploads the static site to the user's DigitalOcean Space. Creates the bucket if missing. Use to save a new or edited site.
5. list_spaces_buckets(region) - Lists all Spaces buckets (sites) in the account. Use when the user wants to see their sites or pick one to edit.
6. download_site_from_spaces(bucket_name, region) - Downloads a site from a Space to a local path. Returns site_path. Use when the user wants to edit an existing site.
7. delete_site_from_spaces(bucket_name, region) - Permanently deletes a site (Space/bucket) by name. Use when the user asks to delete or remove a site.
8. read_file(file_path) - Reads a file. file_path must be a full path (e.g. site_path + "/index.html" or site_path + "/styles.css"). Only works for paths under the temp directory (downloaded or generated sites).
9. write_file(file_path, content) - Writes content to a file. After editing files, call deploy_to_spaces(site_path, bucket_name) to save the site back to the bucket.

CRITICAL INSTRUCTIONS:
- When user references another website URL or says "looks like", "similar to", or "inspired by" another site, FIRST call analyze_reference_site(url) to extract the design. Tell the user what you found (colors, fonts, mood). THEN call generate_static_site with the analysis result as the reference_design parameter (pass it as a JSON string).
- When user asks for a site (without a reference), IMMEDIATELY call generate_static_site - don't just talk about it!
- When user wants to LIST their sites, call list_spaces_buckets. In your reply, include the full URL for each site (from the tool result) so the user can click to open the site in a new window.
- When user wants to EDIT an existing site: (1) list_spaces_buckets if needed to identify the bucket, (2) download_site_from_spaces(bucket_name) to get site_path, (3) read_file(site_path + "/index.html") and/or read_file(site_path + "/styles.css"), (4) write_file with your changes, (5) deploy_to_spaces(site_path, bucket_name) to save back to the bucket.
- When user wants to DELETE a site, use delete_site_from_spaces(bucket_name). Use the exact bucket name (e.g. from list_spaces_buckets).
- When user wants to deploy or save to Spaces, use deploy_to_spaces(site_path, bucket_name, ...). You need site_path (from generate_static_site or download_site_from_spaces) and bucket_name (ask if not provided).
- After each tool completes, tell the user what happened based on the tool's output.
- {spaces_info}

ALWAYS use the tools - never simulate or describe actions!"""),
                MessagesPlaceholder(variable_name="chat_history"),
                ("user", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ])
            agent = create_tool_calling_agent(self.llm, self.tools, prompt)
            self.agent_executor = AgentExecutor(
                agent=agent,
                tools=self.tools,
                verbose=True,
                callbacks=[DetailedLoggingCallback()],
                handle_parsing_errors=True,
            )
            logger.info("Using tool-calling agent (OpenAI)")
        
    def _run_gradient_tool_loop(self, message_text: str) -> str:
        """Custom loop for Gradient: ask LLM for TOOL_CALL+JSON or FINAL_ANSWER, execute tools, repeat."""
        max_iterations = 15
        messages: List = [
            SystemMessage(content=self.gradient_system_prompt),
            HumanMessage(content=message_text),
        ]
        for step in range(max_iterations):
            response = self.llm.invoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
            if not content or not content.strip():
                continue
            content = content.strip()
            logger.info(f"Gradient step {step + 1} LLM output (first 400 chars): {content[:400]}")

            # Parse TOOL_CALL + JSON first (takes priority over FINAL_ANSWER so that
            # stray mentions of "FINAL_ANSWER" in the LLM's reasoning don't
            # short-circuit an intended tool call).
            json_str = None
            tool_call_match = re.search(r"TOOL_CALL\s*\n?\s*(\{[\s\S]*\})", content, re.IGNORECASE)
            if tool_call_match:
                json_str = _extract_first_json(tool_call_match.group(1))
            if not json_str:
                code_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", content)
                if code_match:
                    json_str = _extract_first_json(code_match.group(1))
            if not json_str:
                brace = content.find('{"tool"')
                if brace < 0:
                    brace = content.find("{'tool'")
                if brace >= 0:
                    json_str = _extract_first_json(content[brace:])

            # No tool call found -- check for FINAL_ANSWER (must appear at the
            # very start of the output, ignoring leading whitespace).
            if not json_str:
                fa_match = re.match(r"\s*FINAL_ANSWER\s*[:\n]?\s*([\s\S]*)", content, re.IGNORECASE)
                if fa_match:
                    rest = fa_match.group(1).strip()
                    if rest:
                        return rest
                    return content
                # No tool call or final-answer marker; treat as plain reply.
                return content

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON from LLM: {e}. Sending back to LLM.")
                messages.append(AIMessage(content=content))
                messages.append(HumanMessage(content=f"Your last response did not contain valid JSON. Error: {e}. Output a valid TOOL_CALL with JSON or FINAL_ANSWER."))
                continue

            tool_name = data.get("tool") or data.get("tool_name")
            tool_input = data.get("input") or data.get("arguments") or {}
            if not tool_name or tool_name not in self.tools_by_name:
                messages.append(AIMessage(content=content))
                messages.append(HumanMessage(content=f"Unknown tool '{tool_name}'. Use one of: {', '.join(self.tools_by_name)}. Output TOOL_CALL with valid tool and input, or FINAL_ANSWER."))
                continue

            tool = self.tools_by_name[tool_name]
            try:
                logger.info(f"TOOL EXECUTION: {tool_name} with input {tool_input}")
                result = tool.invoke(tool_input)
                obs = str(result) if not hasattr(result, "model_dump") else str(result.model_dump())
                obs = obs[:2000]  # cap length
            except Exception as e:
                obs = f"Tool error: {e}"
                logger.exception(f"Tool {tool_name} failed")
            messages.append(AIMessage(content=content))
            messages.append(HumanMessage(content=f"Observation: {obs}\n\nIf you need to call another tool, output TOOL_CALL and JSON. Otherwise output FINAL_ANSWER and your reply to the user."))

        return "I reached the maximum number of steps. Please try a simpler request or ask again."

    def process_message(self, message_text: str) -> str:
        """
        Process the incoming message using the LangChain agent (OpenAI) or custom tool loop (Gradient).
        """
        try:
            logger.info(f"\n{'#'*80}\n# NEW MESSAGE FROM USER\n{'#'*80}")
            logger.info(f"User Input: {message_text}")
            logger.info(f"Chat History Length: {len(self.chat_history)} messages")

            if self.use_gradient_tool_loop:
                output = self._run_gradient_tool_loop(message_text)
            else:
                result = self.agent_executor.invoke({
                    "input": message_text,
                    "chat_history": self.chat_history
                })
                output = result["output"]

            self.chat_history.append(HumanMessage(content=message_text))
            self.chat_history.append(AIMessage(content=output))
            if len(self.chat_history) > 20:
                self.chat_history = self.chat_history[-20:]
                logger.info("Chat history trimmed to 20 messages")

            logger.info(f"\n{'#'*80}\n# AGENT RESPONSE\n{'#'*80}")
            logger.info(f"Response: {output[:500]}...")
            return output
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            return f"Error processing message: {str(e)}"
