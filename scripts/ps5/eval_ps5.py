"""SEÇİCİyi PS5'teki sunucudan ölçer. İstekte yalnızca tam sayı (v0.8.3 ondalıkta çöküyor).
Kayıt biçimi `eval --record` ile aynı. Dış API yok."""
import json, re, sys, time
import httpx
from transformers import AutoTokenizer

host, n, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-3B-Instruct")
rows = [json.loads(l) for _, l in zip(range(n), open("data/dataset/select_valid.jsonl"))]
c = httpx.Client(timeout=60); t0 = time.time(); ok = 0
with open(out, "w") as f:
    for i, row in enumerate(rows):
        text = tok.apply_chat_template(row["messages"][:-1], tokenize=False, add_generation_prompt=True)
        r = c.post(f"http://{host}/completion", json={"prompt": text, "n_predict": 60, "top_k": 1, "cache_prompt": False,
                   "lora": [{"id": 0, "scale": 1}, {"id": 1, "scale": 0}]}).json()
        raw = r["content"]; valid = re.findall(r"^\[(a\d+)\]", row["messages"][1]["content"], re.M)
        try: ids = json.loads(raw)["ids"]; err = None; ok += 1
        except Exception as e: ids, err = [], str(e)[:60]
        ref = json.loads(row["messages"][-1]["content"])["ids"]
        f.write(json.dumps({"i": i, "valid_ids": sorted(valid), "reference": ref,
                            "ids": [x for x in ids if isinstance(x, str)], "error": err}, ensure_ascii=False) + "\n"); f.flush()
        if (i + 1) % 25 == 0: print(f"{i+1}/{n} · {(time.time()-t0)/(i+1):.2f} sn/örnek", flush=True)
print(f"{n} örnek {time.time()-t0:.0f} sn · geçerli JSON {ok}/{n}")
