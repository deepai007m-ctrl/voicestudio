"""Build the "HI Pro" Hindi voice set on a running VoiceStudio (stdlib only).

For every voice spec: render the reference line with VoxCPM2 voice design over
several seeds, score each take (noise floor in pauses, clipped head/tail,
length vs text, ASR match), keep the cleanest take, trim + normalise it, save
it as a clone profile, then render a sample line through /v1/speak and QC it
the same way. Voices that already exist (same name) are skipped, so the script
can be re-run after a failure.

    py -3 scripts/build_hindi_pro_voices.py --out <dir> [--only "Narrator"] [--limit 2]
"""

from __future__ import annotations

import argparse
import array
import difflib
import io
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
import zlib
from pathlib import Path

VS = "http://127.0.0.1:3900"
PREFIX = "HI Pro"
CLEAN = ("clean studio recording, close microphone, dry voice, no reverb, "
         "no background noise, speaking natural Hindi")

# (category, name, description, reference line, sample line)
VOICES = [
    ("Narrator", "Kahani Dada", "An elderly Indian grandfather storyteller, warm, slow, kind, slightly husky voice",
     "बहुत समय पहले, एक छोटे से गाँव में एक बूढ़ा किसान रहता था, जो हर शाम बच्चों को कहानियाँ सुनाता था।",
     "आज मैं तुम्हें एक ऐसी कहानी सुनाऊँगा, जो मेरे दादाजी ने मुझे सुनाई थी।"),
    ("Narrator", "Documentary", "A middle-aged Indian man, deep, rich, calm documentary narrator voice",
     "हिमालय की ऊँची चोटियों पर, जहाँ हवा भी ठहर जाती है, वहाँ जीवन अपने सबसे अनोखे रूप में मिलता है।",
     "हर साल लाखों पक्षी हज़ारों किलोमीटर का सफ़र तय करके यहाँ पहुँचते हैं।"),
    ("Narrator", "Audiobook Female", "A young adult Indian woman, clear, calm, pleasant audiobook narrator voice",
     "उस रात बारिश थमने का नाम नहीं ले रही थी, और मीरा खिड़की के पास बैठी किसी का इंतज़ार कर रही थी।",
     "अध्याय एक। पुरानी हवेली का दरवाज़ा बरसों बाद खुला था।"),
    ("Narrator", "Mystery", "A middle-aged Indian man, low, slow, mysterious, suspenseful narrator voice",
     "रात के ठीक बारह बजे, पुरानी हवेली के अंदर से किसी के चलने की आवाज़ आई, जबकि वहाँ कोई नहीं रहता था।",
     "दरवाज़ा धीरे से खुला, और अंदर अँधेरे में दो आँखें चमक रही थीं।"),
    ("News Anchor", "Male", "A middle-aged Indian man, confident, crisp, authoritative TV news anchor voice",
     "नमस्कार, आप देख रहे हैं आज की बड़ी ख़बरें। देश भर में आज मौसम ने अचानक करवट ली है।",
     "सरकार ने आज नई योजना की घोषणा की, जिसका फ़ायदा करोड़ों किसानों को मिलेगा।"),
    ("News Anchor", "Female", "A young adult Indian woman, crisp, confident, professional TV news anchor voice",
     "नमस्कार, ख़बरों की इस ख़ास पेशकश में आपका स्वागत है। सबसे पहले बात करते हैं आज की बड़ी ख़बर की।",
     "राजधानी में आज सुबह से ही तेज़ बारिश हो रही है, जिससे यातायात पर असर पड़ा है।"),
    ("Ad Voice", "Josh Male", "A young adult Indian man, energetic, punchy, exciting advertisement voice",
     "अब इंतज़ार ख़त्म! लाइए घर नया स्मार्ट फ़ोन, सबसे कम दाम में, सिर्फ़ इस हफ़्ते!",
     "धमाकेदार सेल शुरू हो चुकी है, आज ही ऑर्डर करें!"),
    ("Ad Voice", "Smile Female", "A young adult Indian woman, bright, smiling, friendly advertisement voice",
     "अपनी त्वचा को दीजिए प्राकृतिक चमक, हर दिन, हर मौसम में। आज ही आज़माइए!",
     "आपके परिवार की सेहत, अब हमारी ज़िम्मेदारी।"),
    ("Ad Voice", "Luxury", "A middle-aged Indian man, slow, smooth, deep, premium luxury brand voice",
     "कुछ चीज़ें सिर्फ़ ख़रीदी नहीं जातीं, उन्हें महसूस किया जाता है। पेश है शान का नया अंदाज़।",
     "जहाँ हर पल ख़ास है।"),
    ("Motivational", "Coach Male", "A young adult Indian man, powerful, passionate, inspiring motivational speaker voice",
     "याद रखो, हार तब होती है जब तुम कोशिश करना छोड़ देते हो। उठो, और फिर से शुरू करो!",
     "तुम्हारे सपने तुम्हारी मेहनत से बड़े नहीं हो सकते।"),
    ("Motivational", "Prerna Female", "A young adult Indian woman, warm, confident, uplifting motivational voice",
     "हर नई सुबह एक नया मौका लेकर आती है। खुद पर भरोसा रखिए, आप सब कुछ कर सकते हैं।",
     "छोटे कदम भी आपको मंज़िल तक पहुँचाते हैं।"),
    ("Devotional", "Pandit Ji", "An elderly Indian priest, calm, deep, reverent, peaceful devotional voice",
     "ईश्वर हर जगह है, बस उसे देखने के लिए मन की आँखें खोलनी पड़ती हैं। श्रद्धा से सब संभव है।",
     "आज की कथा में हम भक्त प्रह्लाद की अटूट भक्ति के बारे में जानेंगे।"),
    ("Devotional", "Bhakti Female", "A young adult Indian woman, soft, sweet, serene devotional voice",
     "जब मन शांत होता है, तब ईश्वर की आवाज़ सुनाई देती है। आइए, प्रेम से उनका नाम लें।",
     "हर साँस में उनका नाम हो, यही सच्ची भक्ति है।"),
    ("Kids", "Ladka", "An 8-year-old Indian boy, bright, cheerful, playful child voice",
     "मम्मी, आज स्कूल में मैंने एक बहुत बड़ी पतंग बनाई, और सबने मेरी तारीफ़ की!",
     "चलो ना, पार्क में चलकर फुटबॉल खेलते हैं!"),
    ("Kids", "Ladki", "An 8-year-old Indian girl, sweet, bright, curious child voice",
     "दीदी, देखो ना, मेरी गुड़िया ने आज नई फ्रॉक पहनी है, कितनी सुंदर लग रही है!",
     "पापा, आसमान नीला क्यों होता है?"),
    ("Kids", "Cartoon", "A young Indian cartoon character, high, squeaky, funny, animated voice",
     "अरे बाप रे! मेरा लड्डू किसने खा लिया? अब मैं क्या खाऊँगा?",
     "हा हा, पकड़ के दिखाओ मुझे, मैं तो सबसे तेज़ हूँ!"),
    ("Funny", "Desi Chacha", "An elderly Indian village uncle, funny, loud, rustic, humorous voice",
     "अरे भतीजे, हमारे ज़माने में तो लोग मोबाइल नहीं, कबूतर से चिट्ठी भेजते थे, समझे!",
     "ई का हो गया भाई, भैंस फिर से छत पे चढ़ गई!"),
    ("Funny", "Standup", "A young adult Indian man, fast, witty, sarcastic stand-up comedian voice",
     "मेरी डाइट का हाल ऐसा है, सुबह सलाद खाता हूँ, और रात को सलाद के साथ पिज़्ज़ा।",
     "जिम की फ़ीस भरी है, जाना ज़रूरी थोड़ी है।"),
    ("Funny", "Drama Queen", "A young adult Indian woman, dramatic, exaggerated, over-acting comic voice",
     "हाय राम! इतनी बड़ी बात और मुझे किसी ने बताया तक नहीं? मैं तो रूठ गई सबसे!",
     "ये दिन देखने से पहले मैं बेहोश क्यों नहीं हो गई!"),
    ("Love", "Romantic Male", "A young adult Indian man, soft, gentle, warm romantic voice",
     "तुम्हारी मुस्कान देखकर लगता है, जैसे सारी दुनिया की खुशियाँ यहीं आकर ठहर गई हों।",
     "तुम साथ हो, तो हर रास्ता आसान लगता है।"),
    ("Love", "Romantic Female", "A young adult Indian woman, soft, tender, affectionate romantic voice",
     "जब तुम पास होते हो, तो वक़्त जैसे थम जाता है, और दिल बस तुम्हें सुनना चाहता है।",
     "तुम्हारे बिना ये शाम अधूरी सी लगती है।"),
    ("Emotional", "Dard Male", "A young adult Indian man, sad, heavy, emotional, slow voice",
     "कभी सोचा नहीं था कि अपने ही लोग इस तरह साथ छोड़ देंगे। अब बस यादें बची हैं।",
     "वो घर अब भी वैसा ही है, बस उसमें कोई इंतज़ार नहीं करता।"),
    ("Emotional", "Dard Female", "A young adult Indian woman, sad, soft, emotional, slow voice",
     "माँ की आख़िरी बात आज भी कानों में गूँजती है, बेटा, हमेशा मुस्कुराती रहना।",
     "कुछ ज़ख़्म वक़्त के साथ भी नहीं भरते।"),
    ("Angry", "Villain", "A middle-aged Indian man, deep, cold, menacing villain voice",
     "तुमने सोचा था कि मुझसे बच जाओगे? इस शहर में मेरी मर्ज़ी के बिना पत्ता भी नहीं हिलता।",
     "खेल अब शुरू हुआ है।"),
    ("Angry", "Gussa Boss", "A middle-aged Indian man, loud, angry, strict boss voice",
     "ये रिपोर्ट कल तक मेरी टेबल पर चाहिए, वरना कल से ऑफ़िस आने की ज़रूरत नहीं है!",
     "मुझे बहाने नहीं, काम चाहिए!"),
    ("Calm", "Whisper Female", "A young adult Indian woman, very soft, gentle, whispery, soothing voice",
     "आँखें बंद कीजिए, और धीरे से एक गहरी साँस लीजिए। सब कुछ शांत है।",
     "हर साँस के साथ मन हल्का होता जा रहा है।"),
    ("Calm", "Meditation Male", "A middle-aged Indian man, slow, deep, calm, soothing meditation guide voice",
     "अपने शरीर को ढीला छोड़ दीजिए। हर साँस के साथ तनाव बाहर निकल रहा है।",
     "अब धीरे-धीरे अपना ध्यान अपनी साँसों पर लाइए।"),
    ("Conversational", "Dost Ladka", "A young adult Indian man, casual, friendly, relaxed conversational voice",
     "अरे यार, कल का मैच देखा? आख़िरी ओवर में तो कमाल ही हो गया, मज़ा आ गया!",
     "चल, शाम को चाय पीने चलते हैं।"),
    ("Conversational", "Dost Ladki", "A young adult Indian woman, casual, cheerful, friendly conversational voice",
     "सुनो, वो नया कैफ़े खुला है ना, वहाँ की कॉफ़ी सच में बहुत अच्छी है, चलोगी?",
     "अरे, तुमने बताया क्यों नहीं, मैं भी चलती!"),
    ("Conversational", "Podcast Host", "A young adult Indian man, warm, engaging, articulate podcast host voice",
     "नमस्ते दोस्तों, हमारे पॉडकास्ट में आपका स्वागत है। आज हम एक बहुत दिलचस्प विषय पर बात करेंगे।",
     "तो चलिए, आज के मेहमान से मिलते हैं।"),
    ("Job", "Doctor", "A middle-aged Indian woman doctor, calm, caring, reassuring professional voice",
     "घबराने की कोई बात नहीं है। ये दवाई दिन में दो बार खाना खाने के बाद लीजिए।",
     "आराम कीजिए, और खूब पानी पीजिए।"),
    ("Job", "Teacher", "A middle-aged Indian man teacher, clear, patient, friendly explaining voice",
     "बच्चों, आज हम सीखेंगे कि पौधे अपना भोजन कैसे बनाते हैं। ध्यान से सुनना।",
     "इसे प्रकाश संश्लेषण कहते हैं।"),
    ("Job", "Customer Care", "A young adult Indian woman, polite, clear, helpful customer care voice",
     "नमस्ते, हमें कॉल करने के लिए धन्यवाद। मैं आपकी किस तरह मदद कर सकती हूँ?",
     "आपकी शिकायत दर्ज कर ली गई है।"),
    ("Accent", "Bihari", "A middle-aged Indian man from Bihar, rustic, friendly voice with a Bihari Hindi accent",
     "का हो भैया, कहाँ जा रहे हो? आज तो बड़ी गर्मी है, तनी पानी पी लो।",
     "हमरा गाँव बहुत सुंदर है, एक बार आइए ज़रूर।"),
    ("Accent", "Haryanvi", "A middle-aged Indian man from Haryana, bold, loud, rustic Haryanvi Hindi accent",
     "अरे भाई, के होया? इतनी देर कित लगा दी? चाल, खेत में चालाँ।",
     "म्हारा छोरा तो पहलवान बनेगा।"),
    ("Accent", "Punjabi", "A middle-aged Indian man from Punjab, cheerful, hearty voice with a Punjabi Hindi accent",
     "ओए, चलो जी, आज तो जश्न मनाते हैं! लस्सी पीओ, और मस्त रहो।",
     "पुत्तर, मेहनत करो, रब सब देगा।"),
    ("Family", "Dadi Maa", "An elderly Indian grandmother, warm, loving, gentle, slightly shaky voice",
     "आ जा बेटा, मेरे पास बैठ। आज मैंने तेरे लिए तेरी पसंद के लड्डू बनाए हैं।",
     "जुग जुग जियो, सदा खुश रहो।"),
    ("Family", "Papa", "A middle-aged Indian father, firm, strict but caring voice",
     "पढ़ाई पर ध्यान दो बेटा। मेहनत आज करोगे, तो कल आराम मिलेगा।",
     "रात को देर तक फ़ोन मत चलाना।"),
]

# ── audio helpers (16-bit PCM wav) ───────────────────────────────────────────

def read_wav(data: bytes):
    with wave.open(io.BytesIO(data)) as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"expected 16-bit wav, got {sw * 8}-bit")
    s = array.array("h", raw)
    if ch > 1:
        s = array.array("h", s[::ch])
    return sr, s


def write_wav(sr: int, s: array.array) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(s.tobytes())
    return buf.getvalue()


def frame_db(s, sr, ms=20):
    n = max(1, sr * ms // 1000)
    out = []
    for i in range(0, len(s) - n + 1, n):
        seg = s[i:i + n]
        rms = math.sqrt(sum(x * x for x in seg) / n) or 1e-9
        out.append(20 * math.log10(rms / 32768))
    return out


def analyse(sr, s):
    db = frame_db(s, sr)
    srt = sorted(db)
    peak = max((abs(x) for x in s), default=1)
    speech = [d for d in db if d > -38]
    gaps = [d for d in db if d <= -38]
    # noise floor = the quietest 15% of non-silent frames (hiss/hum lives
    # there; pure digital zero at the edges is ignored).
    gap_vals = sorted(d for d in gaps if d > -110)
    floor = gap_vals[int(len(gap_vals) * 0.15)] if gap_vals else srt[0]
    return {
        "dur": len(s) / sr,
        "peak_db": 20 * math.log10(peak / 32768 or 1e-9),
        "floor_db": floor,
        "head_db": max(db[:2]) if db else -120,
        "tail_db": max(db[-3:]) if db else -120,
        "speech_ratio": len(speech) / max(1, len(db)),
        "clipped": sum(1 for x in s if abs(x) >= 32760),
    }


def gate(sr, s, thresh_db=-50.0, cut_db=-18.0, ms=10):
    """Soft downward gate: pull pause frames (hiss between words) down by
    `cut_db`, with gain ramped per sample so nothing clicks. Speech frames,
    and the 30 ms around them (consonant onsets/decays), are untouched."""
    n = max(1, sr * ms // 1000)
    db = frame_db(s, sr, ms)
    keep = [d > thresh_db for d in db]
    hold = 3
    open_ = [any(keep[max(0, i - hold):i + hold + 1]) for i in range(len(keep))]
    low = 10 ** (cut_db / 20)
    target = [1.0 if o else low for o in open_]
    out = array.array("h", s)
    g = 1.0
    for i in range(len(out)):
        t = target[min(i // n, len(target) - 1)] if target else 1.0
        g += (t - g) * (1.0 / n)
        out[i] = int(out[i] * g)
    return out


def clean_ref(sr, s, lead=0.15, tail=0.30):
    """Trim edge silence, pad, fade, peak-normalise to -1 dBFS."""
    db = frame_db(s, sr, 10)
    n = sr // 100
    voiced = [i for i, d in enumerate(db) if d > -45]
    if voiced:
        a = max(0, voiced[0] * n - int(lead * sr))
        b = min(len(s), (voiced[-1] + 1) * n + int(tail * sr))
        s = s[a:b]
    s = gate(sr, s)
    peak =max((abs(x) for x in s), default=1) or 1
    g = (32768 * 10 ** (-1 / 20)) / peak
    out = array.array("h", (max(-32768, min(32767, int(x * g))) for x in s))
    f = int(0.01 * sr)
    for i in range(min(f, len(out))):
        out[i] = int(out[i] * i / f)
        out[-1 - i] = int(out[-1 - i] * i / f)
    return out


def norm_text(t: str) -> str:
    t = re.sub(r"[\s।,.!?\"'’‘:;\-–—()]+", "", t)
    return t.replace("़", "")  # nukta differences are not errors


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def http(method, path, body=None, headers=None, timeout=1800):
    req = urllib.request.Request(VS + path, data=body, method=method, headers=headers or {})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 5:
                time.sleep(float(e.headers.get("Retry-After") or 10))
                continue
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read()[:300]!r}") from None


def post_json(path, payload):
    return http("POST", path, json.dumps(payload).encode(), {"Content-Type": "application/json"})[0]


def multipart(fields: dict, files: dict):
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    for k, (fname, data, ctype) in files.items():
        out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                  f"Content-Type: {ctype}\r\n\r\n".encode())
        out.write(data)
        out.write(b"\r\n")
    out.write(f"--{b}--\r\n".encode())
    return out.getvalue(), {"Content-Type": f"multipart/form-data; boundary={b}"}


def transcribe(wav: bytes) -> str:
    body, h = multipart({"model": "whisper-1", "language": "hi", "response_format": "json"},
                        {"file": ("take.wav", wav, "audio/wav")})
    try:
        return json.loads(http("POST", "/v1/audio/transcriptions", body, h)[0]).get("text", "")
    except Exception as e:  # ASR unavailable → score without it
        print(f"    asr failed: {e}", flush=True)
        return ""


def score_take(text: str, wav: bytes):
    sr, s = read_wav(wav)
    a = analyse(sr, s)
    hyp = transcribe(wav)
    a["asr"] = hyp
    ref_n, hyp_n = norm_text(text), norm_text(hyp)
    a["match"] = difflib.SequenceMatcher(None, ref_n, hyp_n).ratio() if hyp_n else None
    # Hindi narration runs ~11-17 Devanagari chars/sec.
    exp = len(ref_n) / 13.0
    a["len_ratio"] = a["dur"] / exp if exp else 1
    probs = []
    if a["floor_db"] > -52:
        probs.append(f"noise floor {a['floor_db']:.0f} dB")
    if a["tail_db"] > -38:
        probs.append(f"tail cut ({a['tail_db']:.0f} dB at end)")
    if a["head_db"] > -38:
        probs.append(f"head cut ({a['head_db']:.0f} dB at start)")
    if not 0.55 <= a["len_ratio"] <= 1.7:
        probs.append(f"length {a['len_ratio']:.2f}x")
    if a["match"] is not None and a["match"] < 0.78:
        probs.append(f"asr match {a['match']:.2f}")
    if a["clipped"] > 20:
        probs.append(f"clipping {a['clipped']}")
    a["problems"] = probs
    # lower is better
    a["score"] = len(probs) * 100 + a["floor_db"] - 40 * (a["match"] or 0.8)
    return a


# ── main flow ────────────────────────────────────────────────────────────────

def build(spec, out: Path, seeds_per_voice: int, existing: set):
    cat, short, desc, ref_text, sample_text = spec
    name = f"{PREFIX} · {cat} · {short}"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{cat}_{short}").strip("_")
    rec = {"name": name, "category": cat}
    if name in existing:
        print(f"= {name}: exists, skip", flush=True)
        rec["status"] = "exists"
        return rec
    full_desc = f"{desc}, {CLEAN}"
    base = 1000 + zlib.crc32(name.encode()) % 8000
    best = None
    for k in range(seeds_per_voice):
        seed = base + k * 37
        wav = post_json("/v1/audio/speech", {
            "model": "voxcpm2", "input": ref_text, "description": full_desc,
            "language": "hi", "response_format": "wav", "seed": seed,
            "num_step": 32, "denoise": True, "humanize": False,
        })
        a = score_take(ref_text, wav)
        print(f"  {short} seed {seed}: floor {a['floor_db']:.0f} dB, match {a['match']}, "
              f"len {a['len_ratio']:.2f} -> {a['problems'] or 'OK'}", flush=True)
        if best is None or a["score"] < best[1]["score"]:
            best = (seed, a, wav)
        if not a["problems"] and a["floor_db"] < -60 and (a["match"] or 0) >= 0.9:
            break
    seed, a, wav = best
    rec.update(seed=seed, ref_qc={k: a[k] for k in ("floor_db", "match", "len_ratio", "problems")})
    if a["problems"]:
        print(f"! {name}: best take still has {a['problems']} - not saved", flush=True)
        rec["status"] = "rejected"
        return rec
    sr, s = read_wav(wav)
    cleaned = clean_ref(sr, s)
    rec["ref_clean_floor_db"] = analyse(sr, cleaned)["floor_db"]
    ref_wav = write_wav(sr, cleaned)
    (out / "refs").mkdir(parents=True, exist_ok=True)
    (out / "refs" / f"{slug}.wav").write_bytes(ref_wav)

    body, h = multipart({
        "name": name, "ref_text": ref_text, "language": "Hindi", "seed": str(seed), "kind": "clone",
        "personality": f"{desc}. Synthetic voice made with VoxCPM2 voice design "
                       f"(HI Pro set, seed {seed}), not a real person.",
    }, {"ref_audio": (f"{slug}.wav", ref_wav, "audio/wav")})
    prof = json.loads(http("POST", "/profiles", body, h)[0])
    rec["id"] = prof.get("id")

    # sample through the public API, retried on a bad take
    for k in range(3):
        payload = {"text": sample_text, "voice": name}
        if k:
            payload["seed"] = seed + 101 * k
        wav = post_json("/v1/speak", payload)
        sa = score_take(sample_text, wav)
        if not sa["problems"]:
            break
    rec["sample_qc"] = {k: sa[k] for k in ("floor_db", "match", "len_ratio", "problems")}
    (out / "samples").mkdir(parents=True, exist_ok=True)
    (out / "samples" / f"{slug}.wav").write_bytes(wav)
    rec["status"] = "ok" if not sa["problems"] else "saved_sample_warn"
    print(f"+ {name} ({rec['id']}) sample: {sa['problems'] or 'OK'}", flush=True)
    return rec


def concat_category(out: Path, report):
    """One wav per category (samples back to back) for easy listening."""
    by_cat = {}
    for r in report:
        p = out / "samples" / (re.sub(r"[^A-Za-z0-9]+", "_", f"{r['category']}_{r['name'].split(' · ')[-1]}").strip("_") + ".wav")
        if p.exists():
            by_cat.setdefault(r["category"], []).append(p)
    for cat, paths in by_cat.items():
        sr0, joined = None, array.array("h")
        for p in paths:
            sr, s = read_wav(p.read_bytes())
            sr0 = sr0 or sr
            if sr != sr0:
                continue
            joined.extend(s)
            joined.extend(array.array("h", [0]) * int(0.7 * sr))
        (out / "by_category").mkdir(parents=True, exist_ok=True)
        (out / "by_category" / f"{re.sub(r'[^A-Za-z0-9]+', '_', cat)}.wav").write_bytes(write_wav(sr0, joined))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", help="comma list of categories")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--seeds", type=int, default=5)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    specs = VOICES
    if args.only:
        want = {c.strip().lower() for c in args.only.split(",")}
        specs = [v for v in specs if v[0].lower() in want]
    if args.limit:
        specs = specs[: args.limit]
    existing = {p["name"] for p in json.loads(http("GET", "/profiles")[0])}
    rep_path = out / "report.json"
    report = json.loads(rep_path.read_text(encoding="utf-8")) if rep_path.exists() else []
    done = {r["name"] for r in report if r.get("status") in ("ok", "saved_sample_warn", "exists")}
    for spec in specs:
        if f"{PREFIX} · {spec[0]} · {spec[1]}" in done:
            continue
        try:
            rec = build(spec, out, args.seeds, existing)
        except Exception as e:
            rec = {"name": f"{PREFIX} · {spec[0]} · {spec[1]}", "category": spec[0], "status": f"error: {e}"}
            print(f"! {rec['name']}: {e}", flush=True)
        report = [r for r in report if r["name"] != rec["name"]] + [rec]
        rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    concat_category(out, report)
    ok = sum(r.get("status") in ("ok", "exists") for r in report)
    print(f"done: {ok}/{len(report)} clean", flush=True)


if __name__ == "__main__":
    sys.exit(main())
