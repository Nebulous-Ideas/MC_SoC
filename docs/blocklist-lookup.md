# Block lists as Graylog lookup tables

`incident/blocklist.py` turns the feeds you choose into three small files. Graylog reads them like it reads the geoip files, and a pipeline
rule stamps matching messages. The steps below are what we expect to work on Graylog 7.x; **none of it has been run against a real server
yet**, so check each screen against your version.

## 1. Choose feeds and write a config (outside the repo)

No feed is built in: licences differ (some forbid redistribution or commercial use), so read each one's terms first.

```json
{"out_dir": "/var/lib/graylog-lookups", "max_age_days": 90,
 "allowlist": ["203.0.113.0/24", "example.org"],
 "feeds": [{"name": "example-ips", "url": "https://feeds.example.org/ips.txt", "kind": "auto"}]}
```

Put your own addresses, your CDN and your partners in `allowlist`, so a feed can never list them. Run it by hand first:

```bash
python3 -I incident/blocklist.py /etc/mc-soc/blocklist.json
```

It prints counts only (entries, skipped, and an error type if a feed failed). A feed that fails or shrinks by more than half keeps its previous
entries and the exit status is 1. Run it from a timer (cron or a systemd timer) every few hours.

## 2. Load the files in Graylog

- **Data adapter:** System > Lookup Tables > Data Adapters > Create, type *CSV file*. Path `/var/lib/graylog-lookups/blocklist_ip.csv`
  (the Graylog process must be able to read it), key column `key`, value column `list`, check interval a few minutes. Repeat for
  `blocklist_domain.csv`.
- **Cache:** a small in-memory cache is enough.
- **Lookup tables:** create `blocklist_ip` and `blocklist_domain` using those adapters. Set a default value of empty so a miss is easy to test.
- The CSV adapter matches exact keys, so ranges live in `blocklist_cidr.txt` and are handled in the rule below.

## 3. Pipeline rule (check the function names on your version)

```text
rule "flag listed addresses"
when has_field("src_ip") || has_field("dest_ip")
then
  let s = lookup_value("blocklist_ip", to_string($message.src_ip), "");
  let d = lookup_value("blocklist_ip", to_string($message.dest_ip), "");
  set_field("listed_in", concat(to_string(s), to_string(d)));
end
```

Attach it to the OpenSense and IDS streams. For DNS rows do the same with `dns_qname` against `blocklist_domain`. Ranges: either expand the few
ranges you care about into a list in the rule with `cidr_match`, or leave them to a periodic search. Drop the field when it is empty so
`_exists_:listed_in` means "listed".

## 4. Use it

- Seed a hunt with `_exists_:listed_in` rows (external address as the indicator, the list name as the source).
- In the case state, give each list its own source name and a **low or medium** trust level: a list hit can confirm only beside a system
  observation, and it never widens the case on its own.
- Listed entries are historical: a list hit means "reported bad at some point", not "attacking now". The `first_seen` column and `max_age_days`
  let you age entries out.

## What it does not do

It finds known-bad infrastructure. New infrastructure, or an attacker who is not on any list, still depends on the hunt and the expansion
gate. It also cannot tell shared hosting or a CDN address from a bad one: the allowlist is yours to keep.
