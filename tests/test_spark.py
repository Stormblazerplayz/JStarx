"""Tests for Spark 1's model converter and downloader (no PyTorch needed)."""
import collections
import io
import json
import os
import pickle
import struct
import sys
import types
import urllib.error
import zipfile

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "os", "pkgs", "jstarx-core"))

from jstarx_core import spark, spark_convert as sc  # noqa: E402


# ---------------------------------------------------------------- make PyTorch-format checkpoints without torch
class _StorageRef:
    def __init__(self, key, n):
        self.key, self.n = key, n


def write_pt(path, state, extra=None, evil=None):
    """Write a checkpoint the way torch.save does (zip + pickle + raw tensor bytes)."""
    torch_mod, utils_mod = types.ModuleType("torch"), types.ModuleType("torch._utils")

    def _rebuild_tensor_v2(*args):
        raise AssertionError("never called")

    _rebuild_tensor_v2.__module__, _rebuild_tensor_v2.__qualname__ = "torch._utils", "_rebuild_tensor_v2"
    utils_mod._rebuild_tensor_v2 = _rebuild_tensor_v2
    FloatStorage = type("FloatStorage", (), {"__module__": "torch"})
    torch_mod.FloatStorage, torch_mod._utils = FloatStorage, utils_mod
    saved = {k: sys.modules.get(k) for k in ("torch", "torch._utils")}
    sys.modules["torch"], sys.modules["torch._utils"] = torch_mod, utils_mod
    blobs = {}

    class Tensor:
        def __init__(self, arr):
            self.arr = np.ascontiguousarray(arr, dtype=np.float32)

        def __reduce__(self):
            key = str(len(blobs))
            blobs[key] = self.arr.tobytes()
            shape = self.arr.shape
            stride = tuple(int(np.prod(shape[i + 1:])) for i in range(len(shape)))
            return (_rebuild_tensor_v2, (_StorageRef(key, self.arr.size), 0, shape, stride, False, collections.OrderedDict()))

    class Pickler(pickle.Pickler):
        def persistent_id(self, obj):
            if isinstance(obj, _StorageRef):
                return ("storage", FloatStorage, obj.key, "cpu", obj.n)
            return None

    obj = dict(extra or {})
    obj["model"] = collections.OrderedDict((k, Tensor(v)) for k, v in state.items())
    if evil is not None:
        obj["evil"] = evil
    buf = io.BytesIO()
    try:
        Pickler(buf, protocol=2).dump(obj)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("archive/data.pkl", buf.getvalue())
        z.writestr("archive/version", "3\n")
        for key, data in blobs.items():
            z.writestr(f"archive/data/{key}", data)


CFG = {"D_MODEL": 64, "N_LAYER": 2, "N_HEAD": 4, "N_KV_HEAD": 2, "D_FF": 96, "VOCAB": 300, "CTX": 256}


def tiny_state(seed=0, cfg=CFG):
    rng = np.random.default_rng(seed)
    d, v, ff, hd = cfg["D_MODEL"], cfg["VOCAB"], cfg["D_FF"], cfg["D_MODEL"] // cfg["N_HEAD"]
    kv = cfg["N_KV_HEAD"] * hd
    st = {"text.token_embd.weight": rng.normal(0, .5, (v, d))}
    for i in range(cfg["N_LAYER"]):
        p = f"text.blk.{i}."
        st.update({p + "attn_norm.weight": np.ones(d), p + "attn.attn_q.weight": rng.normal(0, .1, (d, d)),
                   p + "attn.attn_k.weight": rng.normal(0, .1, (kv, d)), p + "attn.attn_v.weight": rng.normal(0, .1, (kv, d)),
                   p + "attn.attn_output.weight": rng.normal(0, .1, (d, d)), p + "ffn_norm.weight": np.ones(d),
                   p + "ffn.ffn_gate.weight": rng.normal(0, .1, (ff, d)), p + "ffn.ffn_up.weight": rng.normal(0, .1, (ff, d)),
                   p + "ffn.ffn_down.weight": rng.normal(0, .1, (d, ff))})
    st["text.output_norm.weight"] = np.ones(d)
    st["text.output.weight"] = rng.normal(0, .5, (v, d))
    return st


def write_tokenizer(folder, n=300, specials=("<|bos|>", "<|eos|>", "<|im_start|>", "<|im_end|>")):
    vocab = {chr(0x100 + i) if i >= 94 else chr(33 + i): i for i in range(n - len(specials))}
    added = [{"id": n - len(specials) + i, "content": t, "special": True} for i, t in enumerate(specials)]
    tj = {"added_tokens": added, "pre_tokenizer": {"type": "ByteLevel", "use_regex": True}, "decoder": {"type": "ByteLevel"},
          "model": {"type": "BPE", "vocab": vocab, "merges": ["! \""]}}
    with open(os.path.join(folder, "tokenizer.json"), "w") as f:
        json.dump(tj, f)


# ---------------------------------------------------------------- tests
def test_reads_storm_checkpoint(tmp_path):
    st = tiny_state()
    write_pt(tmp_path / "sft_best.pt", st, {"cfg": CFG, "step": 600, "sft": {"name": "spark1-r2", "tokenizer_sha256": "ab"}})
    m = sc.Model(str(tmp_path / "sft_best.pt"))
    assert (m.n_layer, m.d_model, m.n_head, m.n_kv_head, m.d_ff, m.vocab, m.ctx) == (2, 64, 4, 2, 96, 300, 256)
    assert np.allclose(m.w("blk.1.attn_k.weight"), st["text.blk.1.attn.attn_k.weight"])
    assert m.tokenizer_sha256() == "ab" and m.name == "spark1-r2"
    logits = sc.forward(m, [1, 2, 3, 4], 10000.0, "neox")
    assert logits.shape == (4, 300) and np.isfinite(logits).all()


class _Evil:
    def __init__(self, path):
        self.path = path

    def __reduce__(self):
        return (os.system, (f"touch {self.path}",))


def test_refuses_checkpoint_that_runs_code(tmp_path):
    flag = tmp_path / "hacked"
    write_pt(tmp_path / "evil.pt", tiny_state(), {"cfg": CFG}, evil=_Evil(str(flag)))
    with pytest.raises(pickle.UnpicklingError):
        sc.Model(str(tmp_path / "evil.pt"))
    assert not flag.exists()


def test_name_mapping():
    assert sc.gguf_name("text.blk.3.attn.attn_q.weight") == "blk.3.attn_q.weight"
    assert sc.gguf_name("_orig_mod.text.blk.0.ffn.ffn_down.weight") == "blk.0.ffn_down.weight"
    assert sc.gguf_name("model.layers.7.self_attn.o_proj.weight") == "blk.7.attn_output.weight"
    assert sc.gguf_name("lm_head.weight") == "output.weight"
    assert sc.gguf_name("text.something_else") is None


def test_needs_tokenizer(tmp_path):
    write_pt(tmp_path / "sft_best.pt", tiny_state(), {"cfg": CFG})
    res = sc.convert(str(tmp_path / "sft_best.pt"), str(tmp_path), detect=False, quantize=None, log=lambda *_: None)
    assert res["state"] == "needs-tokenizer" and "tokenizer" in res["message"]


def test_convert_writes_valid_gguf(tmp_path):
    st = tiny_state(3)
    write_pt(tmp_path / "sft_best.pt", st, {"cfg": CFG})
    write_tokenizer(str(tmp_path))
    res = sc.convert(str(tmp_path / "sft_best.pt"), str(tmp_path), detect=False, quantize=None, log=lambda *_: None)
    assert res["state"] == "converted"
    g = sc.read_gguf_header(res["gguf"])
    kv, tensors = g["kv"], g["tensors"]
    assert g["version"] == 3 and kv["general.architecture"] == "llama"
    assert kv["llama.block_count"] == 2 and kv["llama.attention.head_count_kv"] == 2 and kv["llama.rope.dimension_count"] == 16
    assert len(kv["tokenizer.ggml.tokens"]) == 300 and kv["tokenizer.ggml.model"] == "gpt2" and kv["tokenizer.ggml.pre"] == "gpt-2"
    assert kv["tokenizer.ggml.bos_token_id"] == 296 and kv["tokenizer.ggml.eos_token_id"] == 297 and kv["tokenizer.ggml.eot_token_id"] == 299
    assert "<|im_start|>" in kv["tokenizer.chat_template"]
    assert len(tensors) == 3 + 2 * 9 and tensors["blk.0.attn_k.weight"][0] == (32, 64)
    assert tensors["blk.0.attn_norm.weight"][1] == sc.GGML_F32 and tensors["blk.0.attn_q.weight"][1] == sc.GGML_F16
    # the stored Q weight is the rotate-half -> interleaved permutation of the original
    with open(res["gguf"], "rb") as f:
        raw = f.read()
    header_end = len(raw) - sum(((int(np.prod(s)) * (4 if t == 0 else 2) + 31) // 32 * 32) for s, t, _ in tensors.values())
    shape, _, off = tensors["blk.0.attn_q.weight"]
    q = np.frombuffer(raw, dtype="<f2", count=64 * 64, offset=header_end + off).reshape(shape)
    want = sc._permute_rope(st["text.blk.0.attn.attn_q.weight"].astype(np.float32), 4).astype(np.float16)
    assert np.array_equal(q, want)


def test_permutation_matches_rotary_layouts():
    """Rotate-half on the original weights == interleaved rotary on the permuted weights."""
    rng = np.random.default_rng(1)
    heads, hd, d = 2, 8, 6
    w = rng.normal(size=(heads * hd, d)).astype(np.float32)
    x = rng.normal(size=(5, d)).astype(np.float32)
    a = sc._rope((x @ w.T).reshape(5, heads, hd).transpose(1, 0, 2), 10000.0, "neox", hd)
    b = sc._rope((x @ sc._permute_rope(w, heads).T).reshape(5, heads, hd).transpose(1, 0, 2), 10000.0, "interleaved", hd)
    q_a = (a @ a.transpose(0, 2, 1))  # attention scores do not depend on the order inside a head
    q_b = (b @ b.transpose(0, 2, 1))
    assert np.allclose(q_a, q_b, atol=1e-4)


def test_template_guesses():
    assert "<|im_start|>" in sc.guess_template({"<|im_start|>": 1, "<|im_end|>": 2})
    t = sc.guess_template({"<|user|>": 1, "<|assistant|>": 2, "<|end|>": 3})
    assert "<|end|>" in t and "<|assistant|>" in t
    assert "Spark:" in sc.guess_template({})


def test_sentencepiece_reader(tmp_path):
    def field(num, wire, payload):
        key = bytes([(num << 3) | wire])
        if wire == 2:
            return key + bytes([len(payload)]) + payload
        return key + payload

    pieces = b""
    for text, score, typ in (("<unk>", 0.0, 2), ("<s>", 0.0, 3), ("</s>", 0.0, 3), ("▁hi", -1.5, 1)):
        body = field(1, 2, text.encode()) + field(2, 5, struct.pack("<f", score)) + field(3, 0, bytes([typ]))
        pieces += field(1, 2, body)
    (tmp_path / "tokenizer.model").write_bytes(pieces)
    tok = sc._sentencepiece(str(tmp_path / "tokenizer.model"))
    assert tok["tokens"] == ["<unk>", "<s>", "</s>", "▁hi"] and tok["types"] == [2, 3, 3, 1]
    assert tok["scores"][3] == pytest.approx(-1.5) and tok["ids"] == {"unk": 0, "bos": 1, "eos": 2}


def test_release_lookup_tries_tag_spellings(monkeypatch):
    asked = []

    def fake_release(owner, repo, tag):
        asked.append(tag)
        if tag != "Spark1":
            raise urllib.error.HTTPError("u", 404, "nope", {}, None)
        return {"tag_name": "Spark1", "assets": [
            {"name": "sft_best.pt", "browser_download_url": "https://x/sft_best.pt", "size": 10, "digest": "sha256:aa"},
            {"name": "tokenizer.json", "browser_download_url": "https://x/tokenizer.json", "size": 5},
            {"name": "notes.png", "browser_download_url": "https://x/notes.png", "size": 5}]}

    monkeypatch.setattr(spark, "_release_json", fake_release)
    files = spark.resolve_assets("https://github.com/Stormblazerplayz/JStarx/releases/tag/spark-1")
    assert asked[0] == "spark-1" and "Spark1" in asked
    assert [f[0] for f in files] == ["sft_best.pt", "tokenizer.json"] and files[0][3] == "aa"
    assert spark.resolve_assets("")[0][0] == "sft_best.pt"  # default release


def test_release_without_model_is_explained(monkeypatch):
    monkeypatch.setattr(spark, "_release_json", lambda o, r, t: {"tag_name": t, "assets": []})
    with pytest.raises(ValueError, match="No model files"):
        spark.resolve_assets("https://github.com/a/b/releases/tag/Spark1")
