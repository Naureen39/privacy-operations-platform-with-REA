# Token efficient classification

A free tier language model is a scarce resource: a small number of tokens each minute and a daily cap. ProcessLedger is designed so that onboarding a system fits inside 4,000 tokens, and most of the work never reaches a model at all.

## Rules first

Every discovered field is a candidate: a column name, a request parameter, a form input. Classification decides what each one is, and it does so in layers.

1. **Rules.** Name patterns, a synonym list and the shape of the value (for example an email pattern) assign a category with a confidence.
2. **Embeddings.** A small local model (bge-small-en-v1.5, 384 dimensions, on the CPU) compares the field name with a personal data taxonomy that is stored in the database with a vector index.
3. **A review queue.** Anything below the confidence threshold is not guessed. It goes to a person.

On the reference estate the layers support each other. Rules alone classified 94.4 percent of the labelled fields correctly, embeddings alone 65.3 percent, and both together 98.6 percent (213 of 216, none wrong, three left unclassified). Special categories such as health data were flagged for all 17 expected fields, 16 of them strongly and one as a near match.

Those figures flatter the rule layer, because the synonym lists and the estate field names were written by the same author. A separate challenge set, with names the rules were not tuned on, scored 92.3 percent and no technical name was mistaken for personal data. That is the fairer estimate for an unseen system.

## What a model is allowed to do

The language model is used only where judgment is needed, and each task is bounded.

- One call per processing activity to suggest a purpose and a possible lawful basis.
- A call to settle a conflict only when the rules cannot, with the top three retrieved passages.
- Two calls per assessment to draft sections.

Only metadata is sent: field names, types and category labels. Sample values and identifiers are never sent. Every answer is validated against a schema, with at most one repair attempt, and cached by a hash of the normalized request, so re-running an unchanged system costs no new calls.

## Budgets that stop things

Each job has a token budget, 4,000 for onboarding a system, 6,000 for an assessment and 3,000 for an answer in chat. The router tracks provider limits, fails over to a second provider on a rate limit or a bad response, and writes every call to a log with its tokens, latency and cache status. The log is what the usage metering reads when a month is invoiced.
