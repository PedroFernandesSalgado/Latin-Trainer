#!/usr/bin/env python3
"""Convert VulgateDict's dict.csv into lexemes.json.

Usage: python3 import_dict.py [dict.csv] [lexemes.json]

File format (as observed):
  header line (no leading space):  head[:part:part...],POS,"translation"
  form lines  (leading space):      form,POS-override-or-empty,tag,tag,...
For verbs the head is  infinitive:1sg:perfect:supine  (infinitive FIRST).
For nouns the head is  nominative:genitive.
"""
import csv
import json
import re
import sys
from collections import Counter

VERB_FILE_ORDER = ["inf", "1sg", "perf", "sup"]
VERB_DISPLAY_ORDER = ["1sg", "inf", "perf", "sup"]  # doceo, docere, docui, doctum
NOUN_KEYS = ["nom", "gen"]


def split_csv(line):
    """Quote-aware split of one line (translations may contain commas)."""
    return next(csv.reader([line]))


def build_parts(pos, texts):
    if pos == "verb" and len(texts) == 4:
        keys = VERB_FILE_ORDER
    elif pos.startswith("noun") and len(texts) == 2:
        keys = NOUN_KEYS
    else:
        keys = [f"p{i + 1}" for i in range(len(texts))]
    parts = [{"key": k, "text": t.strip()} for k, t in zip(keys, texts)]
    if keys is VERB_FILE_ORDER:
        by_key = {p["key"]: p for p in parts}
        parts = [by_key[k] for k in VERB_DISPLAY_ORDER]
    return [p for p in parts if p["text"]]   # empty slots are dropped, keys of the rest stay stable


def parse(path):
    warnings = []
    empty_parts = []
    lexemes = []
    id_count = Counter()
    cur = None
    cur_forms = None

    def finish():
        if cur is not None:
            cur["forms"] = list(cur_forms.values())
            lexemes.append(cur)

    with open(path, encoding="utf-8") as fh:
        lines = re.split(r"\r?\n", fh.read())

    for n, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue

        if raw[0] not in " \t":
            # ---- header line ----
            finish()
            fields = split_csv(raw)
            if len(fields) < 2:
                warnings.append(f"line {n}: header with fewer than 2 fields: {raw}")
                cur = None
                continue
            head, pos = fields[0], fields[1]
            if pos != pos.strip():
                warnings.append(f"line {n}: POS {pos!r} has surrounding whitespace (stripped)")
                pos = pos.strip()
            tr = fields[2] if len(fields) > 2 else ""
            id_count[head] += 1
            raw_texts = head.split(":")
            parts = build_parts(pos, raw_texts)
            if len(parts) < len(raw_texts):
                empty_parts.append(head)
            # The whole translation string is ONE meaning (e.g. "carry; bear");
            # "tmp" means it has not been filled in yet.
            tr = tr.strip()
            cur = {
                "id": head if id_count[head] == 1 else f"{head}#{id_count[head]}",
                "lemma": parts[0]["text"] if parts else head,
                "pos": pos,
                "parts": parts,
                "translations": [tr] if tr and tr != "tmp" else [],
                "forms": [],
            }
            cur_forms = {}
        else:
            # ---- form line ----
            if cur is None:
                warnings.append(f"line {n}: form line before any header")
                continue
            fields = split_csv(raw.strip())
            text = fields[0]
            if not text:
                warnings.append(f"line {n}: empty form")
                continue
            pos_override = fields[1] if len(fields) > 1 else ""
            tags = [t for t in fields[2:] if t]
            form = cur_forms.setdefault(text, {"text": text, "readings": []})
            form["readings"].append({"pos": pos_override or None, "tags": tags})
    finish()
    return lexemes, warnings, empty_parts


def spelling_index(lexemes):
    """spelling -> set of lexeme ids that contain it."""
    index = {}
    for lx in lexemes:
        for f in lx["forms"]:
            index.setdefault(f["text"], set()).add(lx["id"])
    return index


def has_targets(lx, form):
    """Mirror of the page's rule: can this (lexeme, form) produce any answer item?"""
    return (
        any(part["text"] != form["text"] for part in lx["parts"])
        or any(r["tags"] or r["pos"] for r in form["readings"])
        or bool(lx["translations"])
    )


def diagnostics(lexemes, empty_parts):
    out = []
    for pos_prefix in ("verb", "noun", "adj"):
        counts = Counter(len(lx["parts"]) for lx in lexemes if lx["pos"].startswith(pos_prefix))
        out.append(f"{pos_prefix}* by number of parts: {dict(sorted(counts.items()))}")
    if empty_parts:
        out.append(f"lexemes with empty part slots (dropped): {len(empty_parts)}, e.g. {', '.join(empty_parts[:6])}")

    index = spelling_index(lexemes)
    shared = Counter(len(ids) for ids in index.values() if len(ids) > 1)
    out.append(f"spellings shared by N lexemes: {dict(sorted(shared.items()))}")
    top = sorted(index.items(), key=lambda kv: -len(kv[1]))[:5]
    out.append("most ambiguous spellings: " + ", ".join(f"{s} ({len(ids)})" for s, ids in top))

    never = [lx["id"] for lx in lexemes if not any(has_targets(lx, f) for f in lx["forms"])]
    out.append(f"lexemes with nothing to ask yet (no parts/tags/meaning): {len(never)}")
    if never:
        out.append("  e.g. " + ", ".join(never[:10]))
    return out


def main():
    in_path = sys.argv[1] if len(sys.argv) > 1 else "dict.csv"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "lexemes.json"

    lexemes, warnings, empty_parts = parse(in_path)
    homographs = sum(1 for ids in spelling_index(lexemes).values() if len(ids) > 1)

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "lexemes": lexemes}, fh, ensure_ascii=False, separators=(",", ":"))

    n_forms = sum(len(lx["forms"]) for lx in lexemes)
    n_readings = sum(len(f["readings"]) for lx in lexemes for f in lx["forms"])
    print(f"lexemes: {len(lexemes)}, forms: {n_forms}, readings: {n_readings}")
    print(f"spellings that occur under more than one lexeme: {homographs}")
    print(f"lexemes without forms: {sum(1 for lx in lexemes if not lx['forms'])}")
    print(f"lexemes with real translations: {sum(1 for lx in lexemes if lx['translations'])}")
    print("by POS:", dict(Counter(lx["pos"] for lx in lexemes)))
    print()
    for line in diagnostics(lexemes, empty_parts):
        print(line)
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings[:20]:
            print("  " + w)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
