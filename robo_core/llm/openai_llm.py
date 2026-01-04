import os
import json
from openai import OpenAI

class CloudLLMResponse:
    """
    Structured response from cloud LLM.
    """
    def __init__(self, response, conversation_finished):
        self.response = response
        self.conversation_finished = conversation_finished

class OpenAILLM:
    def __init__(self, api_key=None, model="gpt-4o-mini"):
        """
        Initialize OpenAI LLM for online use.
        
        Args:
            api_key: OpenAI API key. If None, will try to get from OPENAI_API_KEY env var.
            model: Model to use (gpt-4o-mini, gpt-4o, gpt-3.5-turbo, etc.)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key parameter.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model

    def generate(self, text, max_tokens=150, conversation_history=None, decision_context=None):
        """
        Generate a reply using OpenAI LLM with structured output.
        
        Args:
            text: Input text/prompt
            max_tokens: Maximum tokens to generate
            conversation_history: List of previous messages for context
            decision_context: ConversationDecision object with action and reason from local LLM (only used when starting conversation)
            
        Returns:
            CloudLLMResponse object with response text and conversation_finished flag
        """
        system_content = """You are Johnny Hugenschmidt, a helpful and friendly robot who talks to children ages 6-9. Your name is 'Johnny Hugenschmidt' and you respond to 'Johnny', 'Hugenschmidt', or 'Johnny Hugenschmidt'. You are talking to a child between 6-9 years old, so use simple words, short sentences, and be enthusiastic and friendly. Be encouraging, age-appropriate, and engaging. Keep your responses concise but complete - aim for 2-4 sentences unless more detail is needed. Always finish your thoughts completely and never cut off mid-sentence.

IMPORTANT: You must respond in JSON format with two fields:
1. "response": Your response text to the child
2. "conversation_finished": A boolean (true/false) indicating if the conversation should end. Set this to true if the child says goodbye, thanks you and is leaving, or indicates they're done talking. Examples: "goodbye", "bye", "see you later", "thanks, bye", "I have to go", etc.

Always respond with valid JSON in this exact format:
{
  "response": "Your response text here",
  "conversation_finished": false
}"""
        
        # Add decision context to system message if provided (only when starting conversation)
        if decision_context:
            system_content += f"\n\n[Conversation Context: Starting a new conversation. The local LLM determined this is a '{decision_context.action}' because: {decision_context.reason}]"
        
        messages = [
            {"role": "system", "content": system_content}
        ]
        
        # Add conversation history if provided
        if conversation_history:
            from datetime import datetime
            for msg in conversation_history:
                # Create a copy of the message
                formatted_msg = {"role": msg["role"], "content": msg["content"]}
                
                # Add timestamp to content if available
                if "timestamp" in msg and msg["timestamp"]:
                    timestamp_str = datetime.fromtimestamp(msg["timestamp"]).strftime("%H:%M:%S")
                    formatted_msg["content"] = f"[{timestamp_str}] {msg['content']}"
                
                messages.append(formatted_msg)
        
        # Add current user message
        messages.append({"role": "user", "content": text})
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            response_format={"type": "json_object"}  # Force JSON output
        )
        
        # Parse JSON response
        try:
            response_text = response.choices[0].message.content.strip()
            response_json = json.loads(response_text)
            
            return CloudLLMResponse(
                response=response_json.get("response", ""),
                conversation_finished=response_json.get("conversation_finished", False)
            )
        except json.JSONDecodeError as e:
            # Fallback: if JSON parsing fails, treat entire response as text and assume conversation continues
            response_text = response.choices[0].message.content.strip()
            return CloudLLMResponse(
                response=response_text,
                conversation_finished=False
            )

