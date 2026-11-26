"""Word timings for a speech clip from the local speech-to-text, cached by file content so each clip is only transcribed once."""
import hashlib
import json
import os
import urllib.request
import uuid

import sing

CACHE = os.path.join(sing.HERE, "cache")


def word_spans(path):
    """[(word, start_s, end_s), ...] for a WAV clip."""
    data = open(path, "rb").read()
    cf = os.path.join(CACHE, f"words-{hashlib.sha1(data).hexdigest()}.json")
    if os.path.exists(cf):
        return [tuple(x) for x in json.load(open(cf))]
    key = sing.api_key()
    b = uuid.uuid4().hex
    fields = {"model": "Systran/faster-distil-whisper-small.en", "response_format": "verbose_json", "language": "en", "temperature": "0"}
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="timestamp_granularities[]"\r\n\r\nword\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"{sing.HOST}/v1/audio/transcriptions", data=b"".join(parts),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={b}"})
    d = json.load(urllib.request.urlopen(req, timeout=300))
    words = d.get("words") or [w for sg in d.get("segments", []) for w in sg.get("words", [])]
    out = [(w["word"].strip(), float(w["start"]), float(w["end"])) for w in words]
    os.makedirs(CACHE, exist_ok=True)
    json.dump(out, open(cf, "w"))
    return out
