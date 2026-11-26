"""Transcribe a WAV with the speech server (segments + timestamps) into JSON. Usage: python3 stt.py in.wav out.json"""
import json, sys, uuid, urllib.request
import sing

def transcribe(wav, out):
    key = sing.api_key()
    b = uuid.uuid4().hex
    parts = []
    for k, v in (("model", "Systran/faster-distil-whisper-small.en"), ("response_format", "verbose_json"), ("language", "en")):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="timestamp_granularities[]"\r\n\r\nsegment\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + open(wav, "rb").read() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"{sing.HOST}/v1/audio/transcriptions", data=b"".join(parts),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        data = json.load(r)
    json.dump(data, open(out, "w"))
    return data

if __name__ == "__main__":
    d = transcribe(sys.argv[1], sys.argv[2])
    print(len(d.get("segments", [])), "segments,", round(d.get("duration", 0)), "s")
