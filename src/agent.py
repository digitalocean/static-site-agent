"""
Static Site Agent Logic - Using LangChain
"""
import os
import logging
from typing import List, Dict, Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage
from langchain.callbacks.base import BaseCallbackHandler

from tools import generate_static_site, containerize_site, deploy_to_digitalocean

# Setup logger
logger = logging.getLogger("static-site-agent")


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
        self.do_api_key = os.getenv('DIGITALOCEAN_API_KEY', '')
        self.chat_history = []
        
        # 1. Define Tools
        self.tools = [generate_static_site, containerize_site, deploy_to_digitalocean]
        
        # 2. Setup LLM
        # Check which API key is available
        openai_key = os.getenv('OPENAI_API_KEY')
        do_gradient_key = os.getenv('DO_GRADIENT_API_KEY')
        
        if openai_key:
            # Use OpenAI
            self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
        elif do_gradient_key:
            # Use DigitalOcean Gradient AI Platform
            self.llm = ChatOpenAI(
                model="llama3.3-70b-instruct",
                temperature=0.7,
                api_key=do_gradient_key,
                base_url="https://inference.do-ai.run/v1"
            )
        else:
            raise ValueError("Either OPENAI_API_KEY or DO_GRADIENT_API_KEY must be set")
        
        # 3. Setup Agent
        do_key_info = f"Note: DigitalOcean API key is {'configured' if self.do_api_key else 'NOT configured'}." if self.do_api_key else "The DigitalOcean API key is not currently set, so deployment won't work unless provided."
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", f"""You are a Static Site Generation and Deployment Agent with access to these tools:

1. generate_static_site(site_type, style_hints, site_name) - Creates actual HTML/CSS files
2. containerize_site(site_path, image_name) - Creates Docker containers
3. deploy_to_digitalocean(site_path, app_name, do_api_key, region) - Deploys to DigitalOcean

CRITICAL INSTRUCTIONS:
- When user asks for a site, IMMEDIATELY call generate_static_site - don't just talk about it!
- When user wants to deploy, call the actual tools in sequence
- After each tool completes, tell the user what happened based on the tool's output
- {do_key_info}

Example flow:
User: "Create a portfolio site"
You: [Call generate_static_site with appropriate parameters] then tell user it's done
User: "deploy it"
You: [Call containerize_site] [Call deploy_to_digitalocean] then report results

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
            callbacks=[DetailedLoggingCallback()]
        )
        
    def process_message(self, message_text: str) -> str:
        """
        Process the incoming message using the LangChain agent.
        """
        try:
            logger.info(f"\n{'#'*80}\n# NEW MESSAGE FROM USER\n{'#'*80}")
            logger.info(f"User Input: {message_text}")
            logger.info(f"Chat History Length: {len(self.chat_history)} messages")
            
            result = self.agent_executor.invoke({
                "input": message_text,
                "chat_history": self.chat_history
            })
            
            # Add to chat history
            self.chat_history.append(HumanMessage(content=message_text))
            self.chat_history.append(AIMessage(content=result["output"]))
            
            # Keep only last 10 messages to avoid token limits
            if len(self.chat_history) > 20:
                self.chat_history = self.chat_history[-20:]
                logger.info("Chat history trimmed to 20 messages")
            
            logger.info(f"\n{'#'*80}\n# AGENT RESPONSE\n{'#'*80}")
            logger.info(f"Response: {result['output'][:500]}...")
            
            return result["output"]
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            return f"Error processing message: {str(e)}"
