from pathlib import Path
import json
import re
from datetime import datetime
from llama_cpp import Llama
from .conversation_decision import ConversationDecision
from robo_core.utils.logger import get_logger

logger = get_logger(__name__)

class LocalLLM:
    def __init__(self, model_path="models/llm/phi-3-mini-4k-instruct-q4.gguf", wake_max_tokens=80, n_threads=4, n_ctx=2048):
        """
        Initialize Local LLM for wake detection only.
        
        This LLM is ONLY used to determine if the user is addressing the robot
        when there is no active conversation session. It does NOT handle
        conversation ending - that's handled by the cloud LLM.
        
        Args:
            model_path: Path to the GGUF model file
            wake_max_tokens: Maximum tokens for wake decisions (default: 80)
            n_threads: Number of CPU threads for llama-cpp (default: 4)
            n_ctx: Context window size (default: 2048)
        """
        # Check if model file exists
        model_path_obj = Path(model_path)
        if not model_path_obj.exists():
            abs_path = model_path_obj.absolute()
            raise FileNotFoundError(
                f"LLM model file not found: {abs_path}\n\n"
                f"To download the model:\n"
                f"  1. Run the setup script: python setup_models.py\n"
                f"  2. Or manually download from:\n"
                f"     https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-1.3B-q4_k_m.gguf\n"
                f"  3. Save it to: {abs_path}\n\n"
                f"See README.md for detailed setup instructions."
            )
        self.llm = Llama(
            model_path=str(model_path),
            verbose=False,
            n_threads=n_threads,
            n_ctx=n_ctx,
            n_batch=512
        )
        self.wake_max_tokens = wake_max_tokens
    
    def analyze_conversation(self, text, conversation_history=None):
        """
        Analyze if user is addressing the robot (wake detection only).
        
        This is ONLY called when there is NO active conversation session.
        It determines if the user is trying to start a conversation by
        addressing the robot (Johnny Hugenschmidt).
        
        Args:
            text: Current transcribed text
            conversation_history: List of (role, content, timestamp) tuples from previous turns
            
        Returns:
            ConversationDecision with action ("start conversation" or "no conversation") and reason
        """
        # Truncate text to reasonable length (200 chars should be enough for wake detection)
        truncated_text = text[:200] if len(text) > 200 else text
        
        # Build simple history context (last 2 turns max, truncated)
        history_text = ""
        if conversation_history:
            # Get last 2 turns (4 messages)
            recent_history = conversation_history[-4:] if len(conversation_history) > 4 else conversation_history
            history_lines = []
            for role, content, timestamp in recent_history:
                # Truncate each message to 100 chars
                truncated_content = content[:100] if len(content) > 100 else content
                timestamp_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S") if timestamp else "unknown"
                history_lines.append(f"{role}: {truncated_content}")
            if history_lines:
                history_text = " | ".join(history_lines)
        
        prompt = f"""You are deciding if a user is addressing a robot named "Johnny Hugenschmidt" (also called "Johnny" or "Hugenschmidt").

User input: "{truncated_text}"
Recent conversation: {history_text if history_text else "None"}

Rules:
- If the user is addressing the robot directly (saying "Johnny", "Hugenschmidt", "Johnny Hugenschmidt", or similar), respond with "start conversation"
- If the user is NOT addressing the robot, respond with "no conversation"
- Be lenient - if it sounds like they might be talking to the robot, choose "start conversation"

Respond with ONLY valid JSON:
{{"action": "start conversation" or "no conversation", "reason": "brief reason"}}"""
        
        logger.info("=" * 80)
        logger.info("LOCAL LLM WAKE DETECTION:")
        logger.info(f"Input: {text}")
        if history_text:
            logger.info(f"Recent history: {history_text}")
        
        try:
            # Generate response
            output = self.llm(prompt, max_tokens=self.wake_max_tokens, temperature=0.1)
            
            # Extract response text
            response_text = ""
            if "choices" in output and len(output["choices"]) > 0:
                if "text" in output["choices"][0]:
                    response_text = output["choices"][0]["text"].strip()
                elif "message" in output["choices"][0] and "content" in output["choices"][0]["message"]:
                    response_text = output["choices"][0]["message"]["content"].strip()
            
            if not response_text:
                logger.warning("Local LLM returned empty response")
                decision = ConversationDecision(action="no conversation", reason="Empty LLM response")
                logger.info(f"DECISION: {decision.action} - {decision.reason}")
                logger.info("=" * 80)
                return decision
            
            # Clean up response (remove markdown code blocks)
            response_text = re.sub(r'```json\s*', '', response_text)
            response_text = re.sub(r'```\s*', '', response_text)
            response_text = response_text.strip()
            
            logger.info(f"Raw LLM response: {response_text}")
            
            # Extract JSON from response
            json_match = re.search(r'\{[^}]+\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                try:
                    decision_dict = json.loads(json_str)
                    # Ensure action is valid (only "start conversation" or "no conversation" for wake detection)
                    action = decision_dict.get("action", "no conversation")
                    if action not in ["start conversation", "no conversation"]:
                        # If somehow we get "end conversation", treat as "no conversation" (we don't handle ending here)
                        action = "no conversation"
                    decision = ConversationDecision(
                        action=action,
                        reason=decision_dict.get("reason", "Wake detection")
                    )
                    logger.info(f"DECISION: {decision.action} - {decision.reason}")
                    logger.info("=" * 80)
                    return decision
                except (json.JSONDecodeError, ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse JSON from local LLM: {e}, response: {response_text[:100]}")
            
            # Fallback: try parsing entire response as JSON
            try:
                decision_dict = json.loads(response_text)
                action = decision_dict.get("action", "no conversation")
                if action not in ["start conversation", "no conversation"]:
                    action = "no conversation"
                decision = ConversationDecision(
                    action=action,
                    reason=decision_dict.get("reason", "Wake detection")
                )
                logger.info(f"DECISION (fallback): {decision.action} - {decision.reason}")
                logger.info("=" * 80)
                return decision
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
            
            # Final fallback: keyword detection
            response_upper = response_text.upper()
            if any(word in response_upper for word in ["START", "YES", "ADDRESSING", "JOHNNY", "HUGENSCHMIDT"]):
                decision = ConversationDecision(
                    action="start conversation",
                    reason="Detected addressing keywords in response"
                )
                logger.info(f"DECISION (keyword fallback): {decision.action} - {decision.reason}")
                logger.info("=" * 80)
                return decision
            
            # Default to no conversation
            decision = ConversationDecision(
                action="no conversation",
                reason=f"Could not parse response: {response_text[:50]}"
            )
            logger.warning(f"Local LLM defaulting to no conversation, response: {response_text[:100]}")
            logger.info(f"DECISION: {decision.action} - {decision.reason}")
            logger.info("=" * 80)
            return decision
            
        except Exception as e:
            logger.error(f"Error in local LLM wake detection: {e}")
            decision = ConversationDecision(
                action="no conversation",
                reason=f"Error: {str(e)}"
            )
            logger.info(f"DECISION: {decision.action} - {decision.reason}")
            logger.info("=" * 80)
            return decision