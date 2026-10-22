Task: decide whether a statement is supported by the retrieved policy passages.
Input fields: conflict (type, statement, detail), passages (at most 3, each with id and text).
Output fields: verdict (supported_by_policy, contradicts_policy or undetermined), explanation (at most two sentences), cited_passage_ids (ids from the input passages that justify the verdict).
Cite only ids that appear in the input. If no passage speaks to the statement, the verdict is undetermined and cited_passage_ids is empty.
