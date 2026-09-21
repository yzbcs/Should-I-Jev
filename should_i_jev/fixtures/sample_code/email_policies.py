"""Inbound email policies: spam screening and escalation gating."""
import anthropic

client = anthropic.Anthropic()

ESCALATION_MODEL = "claude-3-5-haiku"


def is_spam(message: str) -> bool:
    resp = client.messages.create(
        model="claude-3-5-haiku",
        max_tokens=8,
        messages=[
            {"role": "user", "content": f"Is this message spam? Answer yes or no: {message}"},
        ],
    )
    answer = resp.content[0].text.strip().lower()
    return answer == "yes"


def needs_escalation(ticket: str) -> bool:
    resp = client.messages.create(
        model=ESCALATION_MODEL,
        max_tokens=8,
        messages=[
            {"role": "user", "content": f"Should this ticket be escalated to the on-call engineer right now? Ticket: {ticket}"},
        ],
    )
    return resp.content[0].text.strip().lower() == "yes"
