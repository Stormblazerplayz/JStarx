"""Spark 1 converter: a PyTorch checkpoint (.pt, like Storm's sft_best.pt) -> GGUF for llama.cpp.

Safety: a .pt file is a zip with a Python pickle inside, and pickles can run code. This never
calls torch.load or pickle.load on it. A restricted unpickler only rebuilds tensors and plain
data; the tensor bytes are read straight from the zip (memory-mapped, so 4 GB of RAM is enough).

Steps
  1. read the checkpoint: hyperparameters + weights (Storm's "text.blk.N..." names or Hugging Face
     Llama names)
  2. find out how the model was trained to encode positions (rotary layout + base) with an
     induction test: a random token sequence is shown twice, and only the right setting lets
     the model copy the second half
  3. write a GGUF file (llama architecture) with the tokenizer and a chat template
  4. quantize it to Q8_0 with llama-quantize
"""
import collections
import glob
import hashlib
import json
import os
import pickle
import re
import struct
import subprocess
import zipfile

import numpy as np

# ---------------------------------------------------------------- safe checkpoint reader
_STORAGE_DTYPES = {
    "FloatStorage": "f4", "HalfStorage": "f2", "BFloat16Storage": "bf16", "DoubleStorage": "f8",
    "LongStorage": "i8", "IntStorage": "i4", "ShortStorage": "i2", "CharStorage": "i1",
    "ByteStorage": "u1", "BoolStorage": "?",
}
_TORCH_DTYPES = {
    "float32": "f4", "float": "f4", "float16": "f2", "half": "f2", "bfloat16": "bf16", "float64": "f8",
    "double": "f8", "int64": "i8", "long": "i8", "int32": "i4", "int": "i4", "int16": "i2",
    "int8": "i1", "uint8": "u1", "bool": "?",
}


class _DType:
    def __init__(self, code):
        self.code = code


class _Storage:
    __slots__ = ("code", "key")

    def __init__(self, code, key):
        self.code, self.key = code, key


class TensorRef:
    """A tensor inside the checkpoint, read only when needed."""
    __slots__ = ("storage", "offset", "shape", "stride")

    def __init__(self, storage, offset, shape, stride):
        self.storage, self.offset, self.shape, self.stride = storage, int(offset), tuple(int(s) for s in shape), tuple(int(s) for s in stride)


def _rebuild_tensor_v2(storage, storage_offset, size, stride, requires_grad=False, backward_hooks=None, metadata=None):
    return TensorRef(storage, storage_offset, size, stride)


def _rebuild_parameter(data, requires_grad=False, backward_hooks=None):
    return data


def _numpy_scalar(dtype, data=None):
    return np.frombuffer(data, dtype=dtype)[0].item() if data is not None else None


_SAFE_GLOBALS = {
    ("torch._utils", "_rebuild_tensor_v2"): _rebuild_tensor_v2,
    ("torch._utils", "_rebuild_parameter"): _rebuild_parameter,
    ("collections", "OrderedDict"): collections.OrderedDict,
    ("torch", "Size"): tuple,
    ("numpy", "dtype"): np.dtype,
    ("numpy.core.multiarray", "scalar"): _numpy_scalar,
    ("numpy._core.multiarray", "scalar"): _numpy_scalar,
}


class _SafeUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) in _SAFE_GLOBALS:
            return _SAFE_GLOBALS[(module, name)]
        if module == "torch" and name in _STORAGE_DTYPES:
            return _DType(_STORAGE_DTYPES[name])
        if module == "torch" and name in _TORCH_DTYPES:
            return _DType(_TORCH_DTYPES[name])
        raise pickle.UnpicklingError(f"refusing to load {module}.{name} from a model file")

    def persistent_load(self, pid):
        if not isinstance(pid, tuple) or len(pid) < 3 or pid[0] != "storage":
            raise pickle.UnpicklingError("unexpected data in the model file")
        kind = pid[1]
        code = kind.code if isinstance(kind, _DType) else "u1"
        return _Storage(code, str(pid[2]))


class Checkpoint:
    def __init__(self, path):
        self.path = path
        self.zip = zipfile.ZipFile(path)
        pkls = [n for n in self.zip.namelist() if n.endswith("data.pkl")]
        if not pkls:
            raise ValueError("this is not a PyTorch checkpoint (no data.pkl inside)")
        self.prefix = pkls[0][: -len("data.pkl")]
        with self.zip.open(pkls[0]) as f:
            self.obj = _SafeUnpickler(f).load()
        self._maps = {}

    def _storage_array(self, storage):
        key = (storage.key, storage.code)
        if key in self._maps:
            return self._maps[key]
        info = self.zip.getinfo(f"{self.prefix}data/{storage.key}")
        dtype = np.uint16 if storage.code == "bf16" else np.dtype("<" + storage.code if storage.code != "?" else "?")
        count = info.file_size // np.dtype(dtype).itemsize
        if info.compress_type == zipfile.ZIP_STORED:
            with open(self.path, "rb") as f:
                f.seek(info.header_offset)
                head = f.read(30)
            if head[:4] != b"PK\x03\x04":
                raise ValueError("damaged checkpoint (bad zip entry)")
            n, m = struct.unpack("<HH", head[26:30])
            arr = np.memmap(self.path, dtype=dtype, mode="r", offset=info.header_offset + 30 + n + m, shape=(count,))
        else:
            arr = np.frombuffer(self.zip.read(info), dtype=dtype, count=count)
        self._maps[key] = arr
        return arr

    def array(self, ref):
        """The tensor as a float32 numpy array (a view into the file when possible)."""
        base = self._storage_array(ref.storage)
        n = int(np.prod(ref.shape)) if ref.shape else 1
        contiguous = all(st == int(np.prod(ref.shape[i + 1:])) for i, st in enumerate(ref.stride)) if ref.shape else True
        if contiguous:
            a = base[ref.offset: ref.offset + n].reshape(ref.shape)
        else:
            a = np.lib.stride_tricks.as_strided(base[ref.offset:], shape=ref.shape,
                                                strides=[s * base.itemsize for s in ref.stride])
        if ref.storage.code == "bf16":
            return (np.asarray(a, dtype=np.uint32) << 16).view(np.float32)
        return np.asarray(a, dtype=np.float32)


# ---------------------------------------------------------------- model description
_NAME_RULES = [
    (r"^(?:text\.)?token_embd\.weight$", "token_embd.weight"),
    (r"^(?:text\.)?output_norm\.weight$", "output_norm.weight"),
    (r"^(?:text\.)?output\.weight$", "output.weight"),
    (r"^(?:text\.)?blk\.(\d+)\.attn_norm\.weight$", "blk.{}.attn_norm.weight"),
    (r"^(?:text\.)?blk\.(\d+)\.ffn_norm\.weight$", "blk.{}.ffn_norm.weight"),
    (r"^(?:text\.)?blk\.(\d+)\.(?:attn\.)?attn_(q|k|v|output)\.weight$", "blk.{}.attn_{}.weight"),
    (r"^(?:text\.)?blk\.(\d+)\.(?:ffn\.)?ffn_(gate|up|down)\.weight$", "blk.{}.ffn_{}.weight"),
    # Hugging Face Llama names
    (r"^(?:model\.)?embed_tokens\.weight$", "token_embd.weight"),
    (r"^(?:model\.)?norm\.weight$", "output_norm.weight"),
    (r"^lm_head\.weight$", "output.weight"),
    (r"^(?:model\.)?layers\.(\d+)\.input_layernorm\.weight$", "blk.{}.attn_norm.weight"),
    (r"^(?:model\.)?layers\.(\d+)\.post_attention_layernorm\.weight$", "blk.{}.ffn_norm.weight"),
    (r"^(?:model\.)?layers\.(\d+)\.self_attn\.(q|k|v|o)_proj\.weight$", "blk.{}.attn_{}.weight"),
    (r"^(?:model\.)?layers\.(\d+)\.mlp\.(gate|up|down)_proj\.weight$", "blk.{}.ffn_{}.weight"),
]


def gguf_name(name):
    for prefix in ("_orig_mod.", "module."):
        while name.startswith(prefix):
            name = name[len(prefix):]
    for rx, out in _NAME_RULES:
        m = re.match(rx, name)
        if m:
            groups = list(m.groups())
            if groups and groups[-1] == "o":
                groups[-1] = "output"
            return out.format(*groups)
    return None


def _first(cfg, *keys, default=None):
    for k in keys:
        if k in cfg and cfg[k] is not None:
            return cfg[k]
    return default


class Model:
    """Hyperparameters + tensor references of a Llama-style checkpoint."""

    def __init__(self, path):
        self.ck = Checkpoint(path)
        obj = self.ck.obj
        state = None
        if isinstance(obj, dict):
            for k in ("model", "state_dict", "model_state_dict", "module"):
                if isinstance(obj.get(k), dict):
                    state = obj[k]
                    break
            if state is None and any(isinstance(v, TensorRef) for v in obj.values()):
                state = obj
        if not state:
            raise ValueError("no model weights found in the checkpoint")
        self.tensors = {}
        skipped = []
        for k, v in state.items():
            if not isinstance(v, TensorRef):
                continue
            g = gguf_name(str(k))
            if g:
                self.tensors[g] = v
            else:
                skipped.append(k)
        self.skipped = skipped
        if "token_embd.weight" not in self.tensors:
            raise ValueError("the checkpoint has no token embedding: is this a language model?")
        if "output.weight" not in self.tensors:  # tied embeddings
            self.tensors["output.weight"] = self.tensors["token_embd.weight"]
        cfg = {}
        if isinstance(obj, dict):
            for k in ("cfg", "config", "model_args", "args", "hparams"):
                if isinstance(obj.get(k), dict):
                    cfg = obj[k]
                    break
        self.cfg = cfg
        self.meta = {k: v for k, v in obj.items() if k not in ("model", "state_dict", "model_state_dict", "optimizer")
                     and isinstance(v, (dict, str, int, float))} if isinstance(obj, dict) else {}
        emb = self.tensors["token_embd.weight"].shape
        self.vocab = int(_first(cfg, "VOCAB", "vocab_size", "n_vocab", default=emb[0]))
        self.d_model = int(_first(cfg, "D_MODEL", "dim", "n_embd", "hidden_size", "d_model", default=emb[1]))
        self.n_layer = 1 + max(int(n.split(".")[1]) for n in self.tensors if n.startswith("blk."))
        self.n_head = int(_first(cfg, "N_HEAD", "n_heads", "n_head", "num_attention_heads", default=self.d_model // 64))
        self.head_dim = self.d_model // self.n_head
        kv_rows = self.tensors["blk.0.attn_k.weight"].shape[0]
        self.n_kv_head = int(_first(cfg, "N_KV_HEAD", "n_kv_heads", "n_kv_head", "num_key_value_heads", default=kv_rows // self.head_dim))
        self.d_ff = int(_first(cfg, "D_FF", "hidden_dim", "intermediate_size", "ffn_dim", default=self.tensors["blk.0.ffn_gate.weight"].shape[0]))
        self.ctx = int(_first(cfg, "CTX", "max_seq_len", "block_size", "max_position_embeddings", "n_ctx", default=2048))
        self.rope_theta = _first(cfg, "ROPE_THETA", "rope_theta", "rope_base", "theta")
        self.norm_eps = float(_first(cfg, "NORM_EPS", "norm_eps", "rms_norm_eps", "eps", default=1e-5))
        self.name = str((self.meta.get("sft") or {}).get("name") or self.meta.get("name") or "Spark 1") if isinstance(self.meta.get("sft", {}), dict) else "Spark 1"
        self._check()

    def _check(self):
        need = ["token_embd.weight", "output_norm.weight", "output.weight"]
        for i in range(self.n_layer):
            need += [f"blk.{i}.{n}.weight" for n in ("attn_norm", "attn_q", "attn_k", "attn_v", "attn_output",
                                                      "ffn_norm", "ffn_gate", "ffn_up", "ffn_down")]
        missing = [n for n in need if n not in self.tensors]
        if missing:
            raise ValueError(f"the checkpoint is missing {len(missing)} weight(s), e.g. {missing[0]}")
        if self.d_model % self.n_head or self.n_head % self.n_kv_head:
            raise ValueError("the head counts do not fit the model size")

    def w(self, name):
        return self.ck.array(self.tensors[name])

    def tokenizer_sha256(self):
        sft = self.meta.get("sft") if isinstance(self.meta.get("sft"), dict) else {}
        return sft.get("tokenizer_sha256") or self.meta.get("tokenizer_sha256")


# ---------------------------------------------------------------- reference forward pass (numpy)
def _rms(x, w, eps):
    return x / np.sqrt((x * x).mean(-1, keepdims=True) + eps) * w


def _rope(x, theta, layout, hd):
    t = x.shape[1]
    inv = theta ** (-np.arange(0, hd, 2, dtype=np.float64) / hd)
    ang = np.arange(t)[:, None] * inv[None, :]
    c, s = np.cos(ang).astype(np.float32), np.sin(ang).astype(np.float32)
    if layout == "interleaved":
        a, b = x[..., 0::2], x[..., 1::2]
        out = np.empty_like(x)
        out[..., 0::2] = a * c - b * s
        out[..., 1::2] = a * s + b * c
        return out
    a, b = x[..., : hd // 2], x[..., hd // 2:]
    return np.concatenate([a * c - b * s, a * s + b * c], axis=-1)


def forward(model, tokens, theta, layout):
    """Logits for a token sequence (used to check settings and to test conversions)."""
    t = len(tokens)
    H, KV, D, hd = model.n_head, model.n_kv_head, model.d_model, model.head_dim
    eps = model.norm_eps
    x = model.w("token_embd.weight")[np.asarray(tokens)].astype(np.float32)
    mask = np.triu(np.full((t, t), -np.inf, dtype=np.float32), 1)
    for i in range(model.n_layer):
        p = f"blk.{i}."
        xn = _rms(x, model.w(p + "attn_norm.weight"), eps)
        q = (xn @ model.w(p + "attn_q.weight").T).reshape(t, H, hd).transpose(1, 0, 2)
        k = (xn @ model.w(p + "attn_k.weight").T).reshape(t, KV, hd).transpose(1, 0, 2)
        v = (xn @ model.w(p + "attn_v.weight").T).reshape(t, KV, hd).transpose(1, 0, 2)
        q, k = _rope(q, theta, layout, hd), _rope(k, theta, layout, hd)
        k, v = np.repeat(k, H // KV, axis=0), np.repeat(v, H // KV, axis=0)
        s = q @ k.transpose(0, 2, 1) / np.float32(np.sqrt(hd)) + mask
        s = np.exp(s - s.max(-1, keepdims=True))
        s /= s.sum(-1, keepdims=True)
        x = x + (s @ v).transpose(1, 0, 2).reshape(t, D) @ model.w(p + "attn_output.weight").T
        hn = _rms(x, model.w(p + "ffn_norm.weight"), eps)
        g = hn @ model.w(p + "ffn_gate.weight").T
        u = hn @ model.w(p + "ffn_up.weight").T
        x = x + ((g / (1 + np.exp(-g))) * u) @ model.w(p + "ffn_down.weight").T
    return _rms(x, model.w("output_norm.weight"), eps) @ model.w("output.weight").T


def _mean_nll(logits, target):
    m = logits.max(-1, keepdims=True)
    logp = logits - m - np.log(np.exp(logits - m).sum(-1, keepdims=True))
    return float(-logp[np.arange(len(target)), target].mean())


def copy_score(model, theta, layout, n=32, seed=7):
    """Show a random sequence twice; how well does the model copy the second half?"""
    rng = np.random.default_rng(seed)
    lo = min(300, model.vocab // 4)
    seq = rng.integers(lo, max(lo + 1, model.vocab - 50), size=n)
    tokens = np.concatenate([seq, seq])
    logits = forward(model, tokens, theta, layout)[n:-1]
    target = tokens[n + 1:]
    return _mean_nll(logits, target), float((logits.argmax(-1) == target).mean())


def text_loss(model, ids, theta, layout):
    """Average loss on real text (lower = the model reads it better)."""
    ids = np.asarray(ids)
    return _mean_nll(forward(model, ids, theta, layout)[:-1], ids[1:])


THETAS = (10000.0, 50000.0, 100000.0, 500000.0, 1000000.0)


def detect_rope(model, ids=None, log=print):
    """Work out the rotary layout (copy test) and base (text test when a tokenizer is available)."""
    probe = float(model.rope_theta or 100000.0)
    layouts = {l: copy_score(model, probe, l, n=48) for l in ("neox", "interleaved")}
    for l, (loss, acc) in layouts.items():
        log(f"rotary {l}: copy accuracy {acc:.0%}")
    layout = min(layouts, key=lambda l: layouts[l][0])
    copy_acc = layouts[layout][1]
    if model.rope_theta:
        return {"layout": layout, "theta": float(model.rope_theta), "method": "config", "copy_accuracy": copy_acc,
                "confident": copy_acc >= 0.3}
    scores = {}
    if ids is not None and len(ids) >= 64:
        method = "text"
        for t in THETAS:
            scores[t] = text_loss(model, ids, t, layout)
            log(f"rotary base {t:g}: text loss {scores[t]:.3f}")
    else:
        method = "copy"
        for t in THETAS:
            scores[t] = copy_score(model, t, layout, n=192)[0]
            log(f"rotary base {t:g}: copy loss {scores[t]:.3f}")
    theta = min(scores, key=scores.get)
    return {"layout": layout, "theta": theta, "method": method, "copy_accuracy": copy_acc, "confident": copy_acc >= 0.3,
            "scores": {f"{k:g}": round(v, 4) for k, v in scores.items()}}


SAMPLE_TEXT = """The Moon is the only natural satellite of the Earth. It is about one quarter as wide as the Earth, and it is
the fifth largest moon in the Solar System. The Moon takes about twenty-seven days to travel around the Earth, and
the same side of it always faces us. Its light is sunlight that bounces off its gray, dusty surface.

People have watched the Moon for thousands of years. Ancient farmers used its phases to keep track of time and to
know when to plant their crops. In 1969, the astronauts of Apollo 11 became the first people to walk on the Moon.
Neil Armstrong stepped onto the surface and said that it was one small step for a man, and one giant leap for mankind.

A computer is a machine that follows a list of instructions called a program. Early computers filled whole rooms,
but today a small computer can fit in the palm of your hand. Computers store information as numbers, and they can do
millions of calculations every second. They help people write stories, draw pictures, talk to friends, and learn
new things. Many computers are connected to each other through the internet, which lets them share information
quickly across the world.

Water covers most of the surface of the Earth. Oceans, rivers and lakes are home to many kinds of fish, plants and
other living things. When the sun warms the water, some of it turns into vapor and rises into the sky, where it cools
and forms clouds. Later the water falls back to the ground as rain or snow. This journey is called the water cycle,
and it happens again and again.
"""


def sample_ids(model, tok, workdir, log=print, limit=384):
    """Token ids of SAMPLE_TEXT, using llama.cpp's own tokenizer on a vocabulary-only GGUF."""
    exe = _which("llama-tokenize")
    if not exe:
        return None
    vocab = os.path.join(workdir, ".spark-vocab.gguf")
    text = os.path.join(workdir, ".spark-sample.txt")
    try:
        write_gguf(model, tok, {"layout": "neox", "theta": 10000.0}, vocab, log=None, tensors=False)
        with open(text, "w") as f:
            f.write(SAMPLE_TEXT)
        r = subprocess.run([exe, "-m", vocab, "-f", text, "--ids", "--log-disable"], capture_output=True, text=True, timeout=300)
        line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("[")), None)
        ids = json.loads(line) if line else None
        if not ids:
            log("could not tokenize the sample text: " + (r.stderr or "")[-200:])
            return None
        return [i for i in ids if 0 <= i < model.vocab][:limit]
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        log(f"could not tokenize the sample text: {e}")
        return None
    finally:
        for p in (vocab, text):
            if os.path.exists(p):
                os.remove(p)


# ---------------------------------------------------------------- tokenizer
NORMAL, UNKNOWN, CONTROL, USER_DEFINED, UNUSED, BYTE = 1, 2, 3, 4, 5, 6

_PRE_PATTERNS = {
    "gpt-2": r"'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)",
    "llama-bpe": r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+",
    "qwen2": r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+",
}

_BOS = ("<|bos|>", "<s>", "<|begin_of_text|>", "<|startoftext|>", "<bos>", "<|start|>")
_EOS = ("<|eos|>", "</s>", "<|end_of_text|>", "<|endoftext|>", "<eos>")
_EOT = ("<|im_end|>", "<|end|>", "<|eot_id|>", "<end_of_turn>", "<|eot|>", "<|end_of_turn|>", "<|assistant_end|>")
_PAD = ("<|pad|>", "<pad>", "[PAD]")
_UNK = ("<unk>", "<|unk|>", "[UNK]")


def _token_text(v):
    if isinstance(v, dict):
        return v.get("content")
    return v if isinstance(v, str) else None


def _read_varint(buf, i):
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _proto_fields(buf):
    """Minimal protobuf reader: yields (field number, wire type, value)."""
    i = 0
    while i < len(buf):
        key, i = _read_varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            val, i = _read_varint(buf, i)
        elif wire == 1:
            val, i = buf[i:i + 8], i + 8
        elif wire == 2:
            ln, i = _read_varint(buf, i)
            val, i = buf[i:i + ln], i + ln
        elif wire == 5:
            val, i = buf[i:i + 4], i + 4
        else:
            raise ValueError("unsupported protobuf data in tokenizer.model")
        yield field, wire, val


def _sentencepiece(path):
    tokens, scores, types = [], [], []
    spec = {}
    with open(path, "rb") as f:
        data = f.read()
    for field, wire, val in _proto_fields(data):
        if field == 1 and wire == 2:
            piece, score, typ = "", 0.0, NORMAL
            for f2, w2, v2 in _proto_fields(val):
                if f2 == 1:
                    piece = v2.decode("utf-8", "replace")
                elif f2 == 2 and w2 == 5:
                    score = struct.unpack("<f", v2)[0]
                elif f2 == 3:
                    typ = int(v2)
            tokens.append(piece)
            scores.append(score)
            types.append(typ)
        elif field == 2 and wire == 2:
            for f2, w2, v2 in _proto_fields(val):
                if w2 == 0 and f2 in (40, 41, 42, 43):
                    spec[{40: "unk", 41: "bos", 42: "eos", 43: "pad"}[f2]] = v2 if v2 < (1 << 63) else v2 - (1 << 64)
    ids = {"unk": spec.get("unk", 0), "bos": spec.get("bos", 1), "eos": spec.get("eos", 2), "pad": spec.get("pad", -1)}
    return {"model": "llama", "pre": None, "tokens": tokens, "scores": scores, "types": types, "merges": None,
            "ids": {k: v for k, v in ids.items() if v is not None and v >= 0}}


def _hf_tokenizer(path):
    with open(path, encoding="utf-8") as f:
        tj = json.load(f)
    model = tj.get("model") or {}
    mtype = model.get("type")
    vocab = model.get("vocab")
    added = tj.get("added_tokens") or []
    if mtype == "BPE":
        n = max([*vocab.values(), *(a["id"] for a in added)]) + 1
        tokens = [None] * n
        types = [NORMAL] * n
        for tok, i in vocab.items():
            tokens[i] = tok
        merges = [m if isinstance(m, str) else " ".join(m) for m in model.get("merges") or []]
        text = json.dumps([tj.get("pre_tokenizer"), tj.get("decoder")])
        byte_level = "ByteLevel" in text
        if byte_level:
            kind, scores = "gpt2", None
            pre = "default"
            rx = re.findall(r'"Regex":\s*"((?:[^"\\]|\\.)*)"', json.dumps(tj.get("pre_tokenizer")))
            if rx:
                pattern = json.loads(f'"{rx[0]}"')
                pre = next((k for k, v in _PRE_PATTERNS.items() if v == pattern), "default")
            elif '"use_regex": true' in json.dumps(tj.get("pre_tokenizer")).replace("True", "true"):
                pre = "gpt-2"
        else:  # SentencePiece-style BPE ("▁" for spaces, byte fallback)
            kind, pre = "llama", None
            rank = {}
            for r, m in enumerate(merges):
                rank.setdefault(m.replace(" ", ""), r)
            scores = [-float(rank.get(t, len(merges) + i)) if t is not None else -1e9 for i, t in enumerate(tokens)]
            for i, t in enumerate(tokens):
                if t is not None and re.fullmatch(r"<0x[0-9A-Fa-f]{2}>", t):
                    types[i] = BYTE
    elif mtype == "Unigram":
        n = len(vocab) if isinstance(vocab, list) else 0
        tokens = [v[0] for v in vocab]
        scores = [float(v[1]) for v in vocab]
        types = [NORMAL] * n
        kind, pre, merges = "llama", None, None
        if model.get("unk_id") is not None:
            types[model["unk_id"]] = UNKNOWN
    else:
        raise ValueError(f"tokenizer type {mtype!r} is not supported yet")
    for a in added:
        i = a["id"]
        while i >= len(tokens):
            tokens.append(None)
            types.append(NORMAL)
            if scores is not None:
                scores.append(0.0)
        tokens[i] = a["content"]
        types[i] = CONTROL if a.get("special") else USER_DEFINED
    return {"model": kind, "pre": pre, "tokens": tokens, "scores": scores, "types": types,
            "merges": merges if kind == "gpt2" else None, "ids": {}}


def find_tokenizer_files(folder):
    files = sorted(glob.glob(os.path.join(folder, "**", "*"), recursive=True))
    tj = [f for f in files if f.lower().endswith(".json") and "tokenizer" in os.path.basename(f).lower()
          and "config" not in os.path.basename(f).lower()]
    sp = [f for f in files if f.lower().endswith(".model")]
    cfg = [f for f in files if os.path.basename(f).lower() == "tokenizer_config.json"]
    tmpl = [f for f in files if f.lower().endswith(".jinja")]
    return {"tokenizer": (tj or sp or [None])[0], "config": (cfg or [None])[0], "template": (tmpl or [None])[0]}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_tokenizer(folder, vocab_size):
    found = find_tokenizer_files(folder)
    path = found["tokenizer"]
    if not path:
        return None
    tok = _sentencepiece(path) if path.lower().endswith(".model") else _hf_tokenizer(path)
    tok["path"] = path
    tok["sha256"] = sha256_file(path)
    n = len(tok["tokens"])
    if n > vocab_size:
        raise ValueError(f"the tokenizer has {n} tokens but the model only knows {vocab_size}")
    for i in range(vocab_size):  # fill gaps and pad up to the model's vocabulary
        if i >= len(tok["tokens"]):
            tok["tokens"].append(None)
            tok["types"].append(UNUSED)
            if tok["scores"] is not None:
                tok["scores"].append(-1e9)
        if tok["tokens"][i] is None:
            tok["tokens"][i] = f"[PAD{i}]"
            tok["types"][i] = UNUSED
    conf = {}
    if found["config"]:
        with open(found["config"], encoding="utf-8") as f:
            conf = json.load(f)
    tok["config"] = conf
    template = None
    if found["template"]:
        with open(found["template"], encoding="utf-8") as f:
            template = f.read()
    elif isinstance(conf.get("chat_template"), str):
        template = conf["chat_template"]
    elif isinstance(conf.get("chat_template"), list):
        template = next((t.get("template") for t in conf["chat_template"] if t.get("name") == "default"), None)
    index = {t: i for i, t in enumerate(tok["tokens"])}
    ids = dict(tok["ids"])
    for role, names, key in (("bos", _BOS, "bos_token"), ("eos", _EOS, "eos_token"), ("pad", _PAD, "pad_token"), ("unk", _UNK, "unk_token")):
        name = _token_text(conf.get(key))
        if name in index:
            ids[role] = index[name]
        elif role not in ids:
            hit = next((index[t] for t in names if t in index), None)
            if hit is not None:
                ids[role] = hit
    eot = next((index[t] for t in _EOT if t in index), None)
    if eot is not None:
        ids["eot"] = eot
    tok["ids"] = ids
    tok["template"] = template or guess_template(index)
    tok["add_bos"] = bool(conf.get("add_bos_token", tok["model"] == "llama" and "bos" in ids))
    return tok


def guess_template(index):
    """A chat template from the special tokens the tokenizer has."""
    has = lambda *t: all(x in index for x in t)
    if has("<|im_start|>", "<|im_end|>"):
        return ("{% for m in messages %}<|im_start|>{{ m['role'] }}\n{{ m['content'] }}<|im_end|>\n{% endfor %}"
                "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}")
    if has("<|start_header_id|>", "<|end_header_id|>", "<|eot_id|>"):
        return ("{% for m in messages %}<|start_header_id|>{{ m['role'] }}<|end_header_id|>\n\n{{ m['content'] }}<|eot_id|>{% endfor %}"
                "{% if add_generation_prompt %}<|start_header_id|>assistant<|end_header_id|>\n\n{% endif %}")
    if has("<|user|>", "<|assistant|>"):
        end = next((t for t in ("<|end|>", "<|eot|>", "<|endoftext|>", "</s>", "<|eos|>") if t in index), "")
        return ("{% for m in messages %}<|{{ m['role'] }}|>\n{{ m['content'] }}" + end + "\n{% endfor %}"
                "{% if add_generation_prompt %}<|assistant|>\n{% endif %}")
    if has("<start_of_turn>", "<end_of_turn>"):
        return ("{% for m in messages %}<start_of_turn>{{ 'model' if m['role'] == 'assistant' else m['role'] }}\n"
                "{{ m['content'] }}<end_of_turn>\n{% endfor %}{% if add_generation_prompt %}<start_of_turn>model\n{% endif %}")
    return ("{% for m in messages %}{% if m['role'] == 'system' %}{{ m['content'] }}\n\n{% elif m['role'] == 'user' %}"
            "User: {{ m['content'] }}\n{% else %}Spark: {{ m['content'] }}\n{% endif %}{% endfor %}"
            "{% if add_generation_prompt %}Spark:{% endif %}")


# ---------------------------------------------------------------- GGUF writer
GGML_F32, GGML_F16 = 0, 1
_T_U32, _T_I32, _T_F32, _T_BOOL, _T_STR, _T_ARR = 4, 5, 6, 7, 8, 9
ALIGN = 32


def _gstr(s):
    b = s.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def _kv(key, vtype, value):
    out = _gstr(key) + struct.pack("<I", vtype)
    if vtype == _T_U32:
        out += struct.pack("<I", int(value))
    elif vtype == _T_I32:
        out += struct.pack("<i", int(value))
    elif vtype == _T_F32:
        out += struct.pack("<f", float(value))
    elif vtype == _T_BOOL:
        out += struct.pack("<?", bool(value))
    elif vtype == _T_STR:
        out += _gstr(value)
    elif vtype == _T_ARR:
        itype, items = value
        out += struct.pack("<IQ", itype, len(items))
        if itype == _T_STR:
            out += b"".join(_gstr(s) for s in items)
        elif itype == _T_F32:
            out += np.asarray(items, dtype="<f4").tobytes()
        elif itype == _T_I32:
            out += np.asarray(items, dtype="<i4").tobytes()
        else:
            raise ValueError("unsupported array type")
    else:
        raise ValueError("unsupported value type")
    return out


def _permute_rope(w, n_head):
    """Rotate-half (NeoX) rows -> the interleaved order llama.cpp's llama architecture uses."""
    rows = w.shape[0]
    return w.reshape(n_head, 2, rows // n_head // 2, *w.shape[1:]).swapaxes(1, 2).reshape(w.shape)


def write_gguf(model, tok, rope, out_path, log=print, tensors=True):
    log = log or (lambda *_: None)
    kvs = [
        ("general.architecture", _T_STR, "llama"),
        ("general.name", _T_STR, "Spark 1"),
        ("general.file_type", _T_U32, 1),
        ("llama.context_length", _T_U32, model.ctx),
        ("llama.embedding_length", _T_U32, model.d_model),
        ("llama.block_count", _T_U32, model.n_layer),
        ("llama.feed_forward_length", _T_U32, model.d_ff),
        ("llama.attention.head_count", _T_U32, model.n_head),
        ("llama.attention.head_count_kv", _T_U32, model.n_kv_head),
        ("llama.rope.freq_base", _T_F32, rope["theta"]),
        ("llama.rope.dimension_count", _T_U32, model.head_dim),
        ("llama.attention.layer_norm_rms_epsilon", _T_F32, model.norm_eps),
        ("llama.vocab_size", _T_U32, model.vocab),
        ("tokenizer.ggml.model", _T_STR, tok["model"]),
        ("tokenizer.ggml.tokens", _T_ARR, (_T_STR, tok["tokens"])),
        ("tokenizer.ggml.token_type", _T_ARR, (_T_I32, tok["types"])),
    ]
    if tok.get("pre"):
        kvs.append(("tokenizer.ggml.pre", _T_STR, tok["pre"]))
    if tok.get("scores") is not None:
        kvs.append(("tokenizer.ggml.scores", _T_ARR, (_T_F32, tok["scores"])))
    if tok.get("merges"):
        kvs.append(("tokenizer.ggml.merges", _T_ARR, (_T_STR, tok["merges"])))
    for role, key in (("bos", "bos_token_id"), ("eos", "eos_token_id"), ("unk", "unknown_token_id"),
                      ("pad", "padding_token_id"), ("eot", "eot_token_id")):
        if role in tok["ids"]:
            kvs.append((f"tokenizer.ggml.{key}", _T_U32, tok["ids"][role]))
    kvs.append(("tokenizer.ggml.add_bos_token", _T_BOOL, tok["add_bos"]))
    kvs.append(("tokenizer.ggml.add_eos_token", _T_BOOL, False))
    if tok.get("template"):
        kvs.append(("tokenizer.chat_template", _T_STR, tok["template"]))

    order = ["token_embd.weight"]
    for i in range(model.n_layer):
        order += [f"blk.{i}.{n}.weight" for n in ("attn_norm", "attn_q", "attn_k", "attn_v", "attn_output",
                                                   "ffn_norm", "ffn_gate", "ffn_up", "ffn_down")]
    order += ["output_norm.weight", "output.weight"]
    if not tensors:
        order = []
    infos, offset = [], 0
    for name in order:
        shape = model.tensors[name].shape
        gtype = GGML_F32 if len(shape) == 1 else GGML_F16
        nbytes = int(np.prod(shape)) * (4 if gtype == GGML_F32 else 2)
        infos.append((name, shape, gtype, offset))
        offset += (nbytes + ALIGN - 1) // ALIGN * ALIGN

    tmp = out_path + ".part"
    with open(tmp, "wb") as f:
        f.write(struct.pack("<IIQQ", 0x46554747, 3, len(order), len(kvs)))
        for key, vtype, value in kvs:
            f.write(_kv(key, vtype, value))
        for name, shape, gtype, off in infos:
            f.write(_gstr(name) + struct.pack("<I", len(shape)))
            for d in reversed(shape):
                f.write(struct.pack("<Q", d))
            f.write(struct.pack("<IQ", gtype, off))
        f.write(b"\0" * (-f.tell() % ALIGN))
        start = f.tell()
        for n, (name, shape, gtype, off) in enumerate(infos):
            w = model.w(name)
            if rope["layout"] == "neox" and name.endswith(("attn_q.weight", "attn_k.weight")):
                heads = model.n_head if name.endswith("attn_q.weight") else model.n_kv_head
                w = _permute_rope(w, heads)
            data = np.ascontiguousarray(w, dtype="<f4" if gtype == GGML_F32 else "<f2") if gtype == GGML_F32 \
                else np.ascontiguousarray(np.clip(w, -65504, 65504).astype("<f2"))
            f.seek(start + off)
            f.write(data.tobytes())
            if n % 20 == 0:
                log(f"writing weights {n + 1}/{len(infos)}")
        f.write(b"\0" * (-f.tell() % ALIGN))
    os.replace(tmp, out_path)
    return out_path


def read_gguf_header(path):
    """Read a GGUF file's metadata and tensor list back (used by the tests)."""
    with open(path, "rb") as f:
        data = f.read(64 << 20)
    magic, version, n_t, n_kv = struct.unpack_from("<IIQQ", data, 0)
    if magic != 0x46554747:
        raise ValueError("not a GGUF file")
    pos = 24

    def rstr():
        nonlocal pos
        (ln,) = struct.unpack_from("<Q", data, pos)
        s = data[pos + 8: pos + 8 + ln].decode("utf-8")
        pos += 8 + ln
        return s

    def rval(t):
        nonlocal pos
        if t == _T_STR:
            return rstr()
        if t == _T_ARR:
            it, cnt = struct.unpack_from("<IQ", data, pos)
            pos += 12
            return [rval(it) for _ in range(cnt)]
        fmt = {_T_U32: "<I", _T_I32: "<i", _T_F32: "<f", _T_BOOL: "<?"}[t]
        (v,) = struct.unpack_from(fmt, data, pos)
        pos += struct.calcsize(fmt)
        return v

    kv = {}
    for _ in range(n_kv):
        k = rstr()
        (t,) = struct.unpack_from("<I", data, pos)
        pos += 4
        kv[k] = rval(t)
    tensors = {}
    for _ in range(n_t):
        name = rstr()
        (nd,) = struct.unpack_from("<I", data, pos)
        pos += 4
        dims = struct.unpack_from(f"<{nd}Q", data, pos)
        pos += 8 * nd
        gtype, off = struct.unpack_from("<IQ", data, pos)
        pos += 12
        tensors[name] = (tuple(reversed(dims)), gtype, off)
    return {"version": version, "kv": kv, "tensors": tensors}


# ---------------------------------------------------------------- whole conversion
def convert(checkpoint, folder, out_dir=None, quantize="Q8_0", log=print, detect=True):
    """Checkpoint + tokenizer files in `folder` -> spark-1-<quant>.gguf. Returns a result dict."""
    out_dir = out_dir or folder
    model = Model(checkpoint)
    log(f"model: {model.n_layer} layers, {model.d_model} wide, {model.n_head} heads ({model.n_kv_head} KV), "
        f"vocabulary {model.vocab}, context {model.ctx}")
    tok = load_tokenizer(folder, model.vocab)
    if tok is None:
        return {"state": "needs-tokenizer", "model": model.name,
                "message": "Spark 1's tokenizer file is missing. Upload tokenizer.json (and tokenizer_config.json) to the Spark1 release, then press Download again."}
    want = model.tokenizer_sha256()
    tok_ok = (not want) or want == tok["sha256"]
    if not tok_ok:
        log(f"warning: tokenizer sha256 {tok['sha256'][:12]} differs from the one Spark 1 was trained with ({want[:12]})")
    cache = os.path.join(out_dir, "spark-1.rope.json")
    rope = None
    stamp = f"{os.path.getsize(checkpoint)}:{int(os.path.getmtime(checkpoint))}"
    try:
        with open(cache) as f:
            c = json.load(f)
        if c.get("stamp") == stamp:
            rope = c["rope"]
    except (OSError, ValueError, KeyError):
        pass
    if rope is None:
        if detect:
            log("checking how Spark 1 encodes word positions…")
            rope = detect_rope(model, ids=sample_ids(model, tok, out_dir, log=log), log=log)
        else:
            rope = {"layout": "neox", "theta": float(model.rope_theta or 10000.0), "confident": False}
        with open(cache, "w") as f:
            json.dump({"stamp": stamp, "rope": rope}, f)
    log(f"rotary layout {rope['layout']}, base {rope['theta']:g}")
    f16 = os.path.join(out_dir, "spark-1-f16.gguf")
    write_gguf(model, tok, rope, f16, log=log)
    final = f16
    if quantize:
        exe = _which("llama-quantize")
        if exe:
            q = os.path.join(out_dir, f"spark-1-{quantize.lower()}.gguf")
            log(f"quantizing to {quantize}…")
            r = subprocess.run([exe, f16, q, quantize], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if r.returncode == 0 and os.path.exists(q):
                os.remove(f16)
                final = q
            else:
                log("quantize failed, keeping the f16 file: " + (r.stderr or "")[-200:])
    return {"state": "converted", "gguf": final, "rope": rope, "tokenizer_matches": tok_ok,
            "tokenizer": os.path.basename(tok["path"]), "template_guessed": not (tok["config"].get("chat_template") or find_tokenizer_files(folder)["template"])}


def _which(name):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        sys.exit("usage: python3 -m jstarx_core.spark_convert CHECKPOINT.pt FOLDER_WITH_TOKENIZER [OUT_DIR]")
    print(json.dumps(convert(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None), indent=2))
