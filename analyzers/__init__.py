"""Analyzer adapters: each module has read(path) -> feature table (see features.py).

An analyzer here only READS what a measuring tool already wrote (a TSV of numbers); it never touches audio.
To add one: drop a module in this folder with read(path), and list it below. The core never branches on a name.
"""
from . import flow_tsv, flow_voices_tsv, rhythm_tsv

ANALYZERS = {"flow-tsv": flow_tsv, "flow-voices-tsv": flow_voices_tsv, "rhythm-tsv": rhythm_tsv}
