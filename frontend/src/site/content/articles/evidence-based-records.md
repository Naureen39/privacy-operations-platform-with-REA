# Evidence based record generation

A record of processing is usually written from memory. Someone interviews the system owner, fills a spreadsheet and the spreadsheet is out of date within a quarter. ProcessLedger takes the opposite route: the record is generated from evidence, and every statement in it keeps a pointer to the source it came from.

## Three kinds of source

A system is described by three kinds of source, and they rarely agree.

- **What the organization says.** The privacy notice and the questionnaire answered by the system owner.
- **What the system does.** A recorded browsing session (a HAR file), the database schema and the scripts it ships.
- **What the law asks for.** The text of the regulation, indexed so a draft can cite the article it relies on.

Extraction is deterministic. A capture is reduced to the hosts that received requests and the identifiers in them. A schema is reduced to the fields that look personal. Nothing in this stage involves a language model.

## Findings before prose

The comparison step lines the sources up. When the notice says data is not shared and the capture shows an identifier going to an analytics vendor, that is a finding. When a questionnaire states twelve months of retention and the schema has no way to delete a row, that is a finding too. Each finding carries the evidence on both sides.

On the reference estate, a fictional retailer with a clinic arm and eight systems, the seeded contradictions were all found: 19 of 19 expected finding types, with 24 of 24 expected system and type pairs reported. Precision was 88.9 percent, meaning 24 of the 27 pairs reported were expected ones. The first run was lower, at 80 percent. After reading the false positives, two general changes were made: findings need a classification confidence of at least 0.80, and cookies are reported under their own low severity type. These figures were measured on the same estate that was used to look at those mistakes, so they are optimistic for systems the rules have not seen.

## The record

Only after the comparison does the record get built, from a template. Purposes, categories, recipients, transfers and retention come from the extracted facts. The model is asked for two things only: a short suggestion for the purpose and a possible lawful basis, which a person must confirm.

A record is then versioned. A change creates a new version, and a second person approves it, because the author of a record cannot approve it. Exports are produced as PDF, spreadsheet and JSON, each carrying the notice that it is a draft for review by a qualified privacy professional.

## What it does not do

It does not decide the lawful basis, and it does not know about processing that leaves no technical trace. A record generated from evidence is a strong starting point for a privacy professional, not a replacement for one.
