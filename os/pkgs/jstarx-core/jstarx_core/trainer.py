#!/usr/bin/env python3
"""TinyStar: a small character-level language model trained with NumPy on the CPU.

It shows how 24/7 training works on JStarx:
  * progress goes to $STARAI_PROGRESS (the dynamic island shows it)
  * a checkpoint is saved every 100 steps; after a reboot or power cut it resumes from there
  * at the end it writes a sample of text it invented
Usage: trainer.py --steps 3000 --out /var/lib/starai/jobs/<id>
"""
import argparse
import json
import os
import signal
import time

import numpy as np

CORPUS = """
the stars shine over the quiet hills and the night is purple and orange.
a small robot looks up and counts the stars one by one.
every star is a sun, far away, and some of them have planets.
the jetson hums softly while it learns, day and night, without getting tired.
spark is a friendly assistant who loves questions about space and code.
the comet flies past the moon and leaves a glowing tail behind it.
the snake eats a golden star and grows a little longer.
rockets need fuel, courage and a good plan to reach the sky.
learning is like training a muscle: a little every day makes it strong.
the nebula glows in purple light and new stars are born inside it.
code is a set of steps, and a computer follows them very fast.
the starbreaker ball bounces and the glass bricks break into sparkles.
when the jetson gets too hot it rests, and when it is cool it works again.
the night sky is a map, and the stars are the cities of the universe.
"""

CTX = 8          # characters of context
EMB, HID = 16, 128


def save_progress(path, pct, msg):
    if not path:
        return
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"progress": round(pct, 1), "message": msg, "time": time.time()}, f)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--out", default=os.environ.get("STARAI_CHECKPOINT_DIR", "."))
    ap.add_argument("--lr", type=float, default=0.01)
    a = ap.parse_args()
    progress_file = os.environ.get("STARAI_PROGRESS", os.path.join(a.out, "progress.json"))
    os.makedirs(a.out, exist_ok=True)
    ckpt = os.path.join(a.out, "tinystar.npz")

    text = " ".join(CORPUS.split())
    chars = sorted(set(text))
    stoi = {c: i for i, c in enumerate(chars)}
    data = np.array([stoi[c] for c in text], dtype=np.int64)
    V = len(chars)
    rng = np.random.default_rng(7)

    params = {"E": rng.normal(0, .3, (V, EMB)), "W1": rng.normal(0, .3, (CTX * EMB, HID)) / np.sqrt(CTX * EMB),
              "b1": np.zeros(HID), "W2": rng.normal(0, .3, (HID, V)) / np.sqrt(HID), "b2": np.zeros(V)}
    m = {k: np.zeros_like(v) for k, v in params.items()}
    v = {k: np.zeros_like(v) for k, v in params.items()}
    step0 = 0
    if os.path.exists(ckpt):  # resume after a restart or power cut
        z = np.load(ckpt)
        for k in params:
            params[k], m[k], v[k] = z[k], z["m_" + k], z["v_" + k]
        step0 = int(z["step"])
        print(f"resuming from step {step0}", flush=True)

    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))

    def save(step):
        tmp = ckpt + ".tmp.npz"
        np.savez(tmp, step=step, **params, **{"m_" + k: m[k] for k in params}, **{"v_" + k: v[k] for k in params})
        os.replace(tmp, ckpt)

    B = 64
    loss_avg = None
    for step in range(step0, a.steps):
        ix = rng.integers(0, len(data) - CTX - 1, B)
        X = np.stack([data[i:i + CTX] for i in ix])
        Y = data[ix + CTX]
        emb = params["E"][X].reshape(B, -1)
        h_pre = emb @ params["W1"] + params["b1"]
        h = np.tanh(h_pre)
        logits = h @ params["W2"] + params["b2"]
        logits -= logits.max(1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(1, keepdims=True)
        loss = -np.log(p[np.arange(B), Y] + 1e-9).mean()
        loss_avg = loss if loss_avg is None else .98 * loss_avg + .02 * loss
        # backward
        d = p
        d[np.arange(B), Y] -= 1
        d /= B
        g = {"W2": h.T @ d, "b2": d.sum(0)}
        dh = d @ params["W2"].T * (1 - h ** 2)
        g["W1"], g["b1"] = emb.T @ dh, dh.sum(0)
        demb = (dh @ params["W1"].T).reshape(B, CTX, EMB)
        g["E"] = np.zeros_like(params["E"])
        np.add.at(g["E"], X, demb)
        t = step + 1
        for k in params:  # Adam
            m[k] = .9 * m[k] + .1 * g[k]
            v[k] = .999 * v[k] + .001 * g[k] ** 2
            params[k] -= a.lr * (m[k] / (1 - .9 ** t)) / (np.sqrt(v[k] / (1 - .999 ** t)) + 1e-8)
        if step % 25 == 0 or step == a.steps - 1:
            save_progress(progress_file, 100 * (step + 1) / a.steps, f"step {step + 1}/{a.steps} · loss {loss_avg:.2f}")
        if step % 100 == 0:
            save(step + 1)
            print(f"step {step + 1:6d}  loss {loss_avg:.3f}", flush=True)
        if stop["now"]:
            save(step + 1)
            print("stopping safely, checkpoint saved", flush=True)
            return
    save(a.steps)

    # write something new
    ctx = list(data[:CTX])
    out = []
    for _ in range(300):
        emb = params["E"][np.array(ctx[-CTX:])].reshape(1, -1)
        logits = np.tanh(emb @ params["W1"] + params["b1"]) @ params["W2"] + params["b2"]
        pr = np.exp((logits - logits.max()) / .8)
        pr = (pr / pr.sum()).ravel()
        nxt = int(rng.choice(V, p=pr))
        ctx.append(nxt)
        out.append(chars[nxt])
    sample = "".join(out)
    with open(os.path.join(a.out, "sample.txt"), "w") as f:
        f.write(sample + "\n")
    print("TinyStar wrote:\n" + sample, flush=True)
    save_progress(progress_file, 100, f"done · loss {loss_avg:.2f}")


if __name__ == "__main__":
    main()
