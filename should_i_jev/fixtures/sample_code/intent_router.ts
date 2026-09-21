import OpenAI from "openai";

const openai = new OpenAI();

type Intent = "greeting" | "complaint" | "purchase" | "other";

export async function detectIntent(utterance: string): Promise<Intent> {
  const response = await openai.chat.completions.create({
    model: "gpt-4o",
    messages: [
      { role: "system", content: "You classify user intent for the support router." },
      { role: "user", content: `Label the intent of this utterance as one of: greeting, complaint, purchase, other: ${utterance}` },
    ],
  });
  const raw = response.choices[0].message.content ?? "other";
  const label = raw.trim().toLowerCase();
  return (["greeting", "complaint", "purchase"].includes(label) ? label : "other") as Intent;
}

export async function summarizeThread(thread: string): Promise<string> {
  const response = await openai.chat.completions.create({
    model: "gpt-4o",
    messages: [
      { role: "user", content: `Summarize this support thread in three bullets for the on-call engineer: ${thread}` },
    ],
  });
  return response.choices[0].message.content ?? "";
}
