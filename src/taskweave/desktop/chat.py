"""Compatibility exports for framework-independent web-chat reply parsing."""
from taskweave.presentation.chat import _reply_document, parse_chat_reply, parse_goal_reply

__all__ = ['parse_chat_reply', 'parse_goal_reply']
