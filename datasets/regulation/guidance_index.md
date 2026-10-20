# Regulator Guidance Index

Links and the project's own short summaries. No guidance text is copied here. Read each publisher's reuse terms before copying any text, and check that a document is still current before relying on it.

| Source | Document | Used for | Reuse terms |
|---|---|---|---|
| European Data Protection Board | Guidelines on Data Protection Impact Assessment (WP248 rev.01, endorsed by the Board) | Screening criteria in `taxonomy/dpia_criteria.json` | Check the EDPB legal notice before copying text |
| European Data Protection Board | Guidelines on the concepts of controller and processor (07/2020) | Role labels in the vendor registry (`controller`, `processor`, `joint_controller`) | Check the EDPB legal notice |
| European Data Protection Board | Guidelines on the right of access (01/2022) | Access request module: scope of the search and the response | Check the EDPB legal notice |
| UK Information Commissioner's Office | Guide to the UK GDPR: documentation, DPIAs, right of access | Cross-check of record fields and request handling | Open Government Licence v3.0 for most content, confirm per page |
| French CNIL | Template for a register of processing activities | Column set of the exported register only (no text copied) | Check the CNIL legal notice |
| EUR-Lex / Publications Office | Regulation (EU) 2016/679, official text | `gdpr_articles.json`, built by `scripts/fetch_regulation.py` | See `datasets/README.md` |

## Own summaries

- **Record of processing (Article 30).** A register lists, per processing activity: the controller, purposes, categories of data subjects and data, recipients, transfers to third countries with safeguards, retention periods where possible, and a general description of security measures. The exported register in this project uses those columns.
- **Impact assessment (Article 35).** Required where processing is likely to result in a high risk. Two or more of the screening criteria is the working threshold in this project. The assessment describes the processing, assesses necessity and proportionality, identifies risks, and sets out measures. See `taxonomy/dpia_criteria.json`.
- **Access requests (Articles 12 and 15).** A response is due within one month of receipt. It may be extended by up to two further months where requests are complex or numerous, and the person must be told within the first month. Identity must be verified proportionately.
- **Transfers (Chapter V).** A transfer outside the EEA needs an adequacy decision (Article 45) or an appropriate safeguard (Article 46), or a specific derogation (Article 49). See `adequacy_countries.yaml`.
