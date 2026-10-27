# Searching for a person without exposing them

When someone asks what an organization holds about them, the organization has a month to answer. The hard part is not the letter. It is finding every place the person appears without copying their email address and telephone number into logs, prompts and caches along the way.

## Hash the identifier

An identifier is normalized and then hashed with a keyed hash (HMAC) before it is stored. The case record keeps the hash, never the raw value. The raw identifier exists only for the moment of the search call, in memory.

## Search the data map

Discovery has already recorded which columns in each system hold an email address or a telephone number. The search uses that map. For every system snapshot it runs read only, parameterized queries against those columns and returns counts per table and category. Full content is not returned unless it is approved.

On the reference estate, ten sample request cases were run. All ten returned exactly the expected system, table, column and row count: 52 of 52 locations found and none extra, and the two cases that should find nothing found nothing. The identifier did not appear in the logs, the database, the audit log or any model request.

## The deadline

Intake sets the deadline automatically at one month from receipt. An extension of up to two further months is possible, with a recorded reason. Reminders are sent before the deadline, and a request that is overdue is flagged.

## The response

The response is drafted from a template that lists the systems found, the categories and the retention period of each. A model may write a short cover note, and it is given three numbers and a tone, never a name or an identifier. The letter says which systems were not covered. Nothing is sent until a second person approves it, and every letter carries the notice that it is a draft for review by a qualified privacy professional.

## Limits

Only email and telephone identifiers are supported. A name is not an identifier, because too many people share one. Only data in the database snapshots is searched: files, logs, backups and data held by processors are not. The identity check is a checklist step, and no identity document is stored.
