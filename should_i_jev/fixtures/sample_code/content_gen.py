"""Generative customer comms — should stay on an LLM."""
from openai import OpenAI

client = OpenAI()


def write_followup(customer_name: str, ticket_summary: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You write friendly, concise customer emails."},
            {"role": "user", "content": f"Write a follow-up email to {customer_name} about their resolved ticket: {ticket_summary}"},
        ],
    )
    return response.choices[0].message.content
