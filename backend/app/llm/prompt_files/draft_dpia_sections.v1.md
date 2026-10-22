Task: draft parts of a data protection impact assessment from the activity facts and regulation passages.
Input fields: part ("description" or "risks"), activity (facts only), criteria_met, passages (each with id and text).
Part "description": fill description (what is processed, why, by whom) and necessity_and_proportionality; return risks as an empty list.
Part "risks": return up to 5 risks with likelihood and severity from 1 (low) to 5 (high), a mitigation and the ids of the passages that support the risk; leave description and necessity_and_proportionality as empty strings.
Cite only passage ids from the input. The result is a draft for the privacy officer.
