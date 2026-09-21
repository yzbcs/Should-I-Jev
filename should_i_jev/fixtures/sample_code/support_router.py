"""Support ticket routing — the classic hidden decision workload."""
import openai

client = openai.OpenAI()

ROUTE_OPTIONS = ("billing", "technical", "account", "other")


def route_ticket(ticket_text: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You route support tickets to exactly one team."},
            {"role": "user", "content": f"Route this ticket to billing, technical, account, or other: {ticket_text}"},
        ],
    )
    label = response.choices[0].message.content.strip().lower()
    if label in ROUTE_OPTIONS:
        return label
    return "other"
