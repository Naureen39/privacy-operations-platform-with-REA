Task: answer a question about the organisation's privacy documentation and the GDPR using only the retrieved passages.
Input fields: question, passages (each with id and text).
Output fields: answer (a short answer in plain language), supported (true only when the passages answer the question), cited_passage_ids (ids of the passages the answer relies on).
Cite only ids from the input. If the passages do not answer the question, set supported to false, leave cited_passage_ids empty and answer "No supporting evidence found."
