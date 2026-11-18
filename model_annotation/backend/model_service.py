"""BERT NER 模型训练、推理、管理服务

训练数据格式 (Doccano JSON):
[
    {
        "text": "GB 26572-2025 规定了...",
        "entities": [
            {"start_offset": 0, "end_offset": 13, "label": "标准编号"},
            {"start_offset": 16, "end_offset": 19, "label": "动作"}
        ]
    }
]
"""
import sys as _sys
# 移除用户级 site-packages 以防与 conda 环境冲突 (导致 BertModel 导入失败)
_sys.path = [p for p in _sys.path if 'Roaming' not in p.replace('\\', '/') and 'AppData' not in p.replace('\\', '/')]
import json
import math
import os
import uuid
import time
import shutil
import re
import random
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")
warnings.filterwarnings("ignore", message=".*incorrect regex pattern.*")

# ── 环境配置 ──
CACHE_DIR = Path(__file__).resolve().parent / ".model_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(CACHE_DIR / "hf"))
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(CACHE_DIR / "st"))
os.environ.setdefault("TORCH_HOME", str(CACHE_DIR / "torch"))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import torch
from torch.utils.data import Dataset as TorchDataset, DataLoader
from transformers import (
    AutoTokenizer,
    AutoModel,
    AutoConfig,
)
from ner_crf import CRF

BACKBONE_NAME = "models/chinese-roberta-wwm-ext"  # 本地路径, 网络恢复后可切回 hf hub


# ── NER Model ───────────────────────────────────────────────

class NERModel(torch.nn.Module):
    """NER 模型: encoder (e.g. RoBERTa) + Linear + CRF

    用于序列标注任务。支持 train_model / run_inference / continue_train 三个入口。
    """
    def __init__(self, encoder, classifier, crf, config):
        super().__init__()
        self.encoder = encoder
        self.classifier = classifier
        self.crf = crf
        self.config = config

    def forward(self, input_ids, attention_mask, labels=None):
        outputs = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        hidden = outputs.last_hidden_state  # (B, S, 768)
        emissions = self.classifier(hidden)  # (B, S, num_labels)
        if labels is not None:
            mask = attention_mask.bool()
            loss = self.crf(emissions, labels, mask)
            return {"loss": loss, "emissions": emissions}
        return {"emissions": emissions}

    def save_pretrained(self, save_dir):
        os.makedirs(save_dir, exist_ok=True)
        self.encoder.save_pretrained(save_dir)
        self.config.save_pretrained(save_dir)
        torch.save(self.classifier.state_dict(), os.path.join(save_dir, "classifier.pt"))
        torch.save(self.crf.state_dict(), os.path.join(save_dir, "crf.pt"))

    @classmethod
    def from_pretrained(cls, model_dir, device="cpu"):
        config = AutoConfig.from_pretrained(model_dir, local_files_only=True)
        encoder = AutoModel.from_pretrained(model_dir, local_files_only=True)
        num_labels = config.num_labels
        classifier = torch.nn.Linear(config.hidden_size, num_labels)
        classifier.load_state_dict(torch.load(
            os.path.join(model_dir, "classifier.pt"), map_location=device, weights_only=True
        ))
        crf = CRF(num_tags=num_labels)
        crf.load_state_dict(torch.load(
            os.path.join(model_dir, "crf.pt"), map_location=device, weights_only=True
        ))
        model = cls.__new__(cls)
        torch.nn.Module.__init__(model)
        model.encoder = encoder
        model.classifier = classifier
        model.crf = crf
        model.config = config
        model.to(device)
        return model


_quick_models: dict[str, Any] = {}
MODELS_DIR = Path(__file__).resolve().parent / "models"


# ── 进度回调 ──────────────────────────────────────────────

class TrainingProgressCallback:
    """训练进度回调，将进度推送到线程安全队列。"""
    def __init__(self, queue):
        self.queue = queue

    def on_progress(self, epoch: float, max_epochs: int, step: int, max_steps: int,
                    loss: float | None, lr: float | None, grad_norm: float | None,
                    loss_smooth: float | None = None, accuracy: float | None = None):
        self.queue.put({
            "type": "progress",
            "epoch": round(epoch, 2),
            "max_epochs": max_epochs,
            "step": step,
            "max_steps": max_steps,
            "loss": loss,
            "learning_rate": lr,
            "grad_norm": grad_norm,
            "loss_smooth": loss_smooth,
            "accuracy": accuracy,
        })

    def on_validation(self, val_loss: float, val_accuracy: float):
        self.queue.put({
            "type": "validation",
            "val_loss": round(val_loss, 4),
            "val_accuracy": round(val_accuracy, 4),
        })

    def on_status(self, message: str):
        self.queue.put({"type": "status", "message": message})

    def on_log(self, message: str):
        self.queue.put({"type": "log", "message": message})


class HistoryCollectingCallback:
    """包装进度回调，同时收集训练历史数据"""
    def __init__(self, inner_callback, history_list):
        self._inner = inner_callback
        self._history = history_list

    def on_progress(self, epoch, max_epochs, step, max_steps, loss, lr, grad_norm, loss_smooth=None, accuracy=None):
        if self._inner:
            self._inner.on_progress(epoch, max_epochs, step, max_steps, loss, lr, grad_norm, loss_smooth, accuracy)
        self._history.append({
            "step": step,
            "loss": round(loss, 4) if loss is not None else None,
            "learning_rate": round(lr, 10) if lr is not None else None,
            "grad_norm": round(grad_norm, 4) if grad_norm is not None else None,
            "loss_smooth": round(loss_smooth, 4) if loss_smooth is not None else None,
            "accuracy": round(accuracy, 4) if accuracy is not None else None,
        })

    def on_log(self, message):
        if self._inner:
            self._inner.on_log(message)

    def on_validation(self, val_loss, val_accuracy):
        if self._inner:
            self._inner.on_validation(val_loss, val_accuracy)

    def on_status(self, message):
        if self._inner:
            self._inner.on_status(message)


# ── 模型加载 ──────────────────────────────────────────────

def _load_backbone_tokenizer(model_name: str):
    """加载 tokenizer，优先缓存，失败则从镜像下载。"""
    try:
        return AutoTokenizer.from_pretrained(model_name, local_files_only=True, )
    except Exception:
        print(f"[model_service] Tokenizer not in cache, downloading from {os.environ.get('HF_ENDPOINT', 'HF')}...")
        return AutoTokenizer.from_pretrained(model_name, )


def _build_model_with_crf(model_name: str, num_labels: int, id2label: dict, label2id: dict, device: str):
    """构建 chinese-roberta-wwm-ext + Linear + CRF 模型"""
    config = AutoConfig.from_pretrained(model_name, num_labels=num_labels, id2label=id2label, label2id=label2id)
    try:
        encoder = AutoModel.from_pretrained(model_name, config=config, local_files_only=True)
    except Exception:
        print(f"[model_service] Model not in cache, downloading from {os.environ.get('HF_ENDPOINT', 'HF')}...")
        encoder = AutoModel.from_pretrained(model_name, config=config)

    hidden_size = config.hidden_size
    classifier = torch.nn.Linear(hidden_size, num_labels)
    crf = CRF(num_tags=num_labels)

    model = NERModel(encoder, classifier, crf, config)
    model.to(device)
    return model


# ── 文本工具 ──────────────────────────────────────────────

RE_MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~<>])")


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"<\s*br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:p|div|li|tr|table|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = RE_MD_ESCAPE.sub(r"\1", text)
    chunks = re.split(r"(?:\n+|[。！？；;]+|\s+\|\s+)", text)
    results = []
    for chunk in chunks:
        cleaned = chunk.strip()
        if cleaned and len(cleaned) >= 2:
            results.append(cleaned)
    return results


def _normalize_text(text: str) -> str:
    """文本归一化：统一 Unicode 变体，避免 [UNK] token。"""
    # 统一破折号/连字符
    text = text.replace("—", "-")  # — em dash
    text = text.replace("–", "-")  # — en dash
    text = text.replace("―", "-")  # ― horizontal bar
    text = text.replace("－", "-")  # － fullwidth hyphen-minus
    # 统一引号
    text = text.replace("‘", "'")   # ' left single
    text = text.replace("’", "'")   # ' right single
    text = text.replace("“", "\"")  # " left double
    text = text.replace("”", "\"")  # " right double
    # 统一空格
    text = text.replace("\xa0", " ")
    text = text.replace("　", " ")
    return text


def _clean_text(text: str) -> str:
    cleaned = _normalize_text(text)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = RE_MD_ESCAPE.sub(r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


# ── BIO 标注编码／解码 ────────────────────────────────────

def _normalize_examples(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将各种输入格式统一为 Doccano 实体格式。

    支持格式：
    1. Doccano 格式: {text, entities: [{start_offset, end_offset, label}]}
    2. Doccano 备选格式: {text, labels: [[start, end, label], ...]}
    3. 旧版句子格式: {text, label} → 整句作为一个实体
    """
    normalized = []
    for ex in examples:
        text = ex.get("text", "")
        entities = ex.get("entities")

        if entities is None and "labels" in ex:
            raw_labels = ex["labels"]
            if isinstance(raw_labels, list) and raw_labels and isinstance(raw_labels[0], list):
                entities = [
                    {"start_offset": int(s), "end_offset": int(e), "label": str(l)}
                    for s, e, l in raw_labels
                ]

        if entities is None and "spans" in ex:
            raw_spans = ex["spans"]
            if isinstance(raw_spans, list) and raw_spans:
                entities = [
                    {"start_offset": int(s["start"]), "end_offset": int(s["end"]), "label": str(s["label"])}
                    for s in raw_spans if isinstance(s, dict)
                ]

        if entities is not None:
            valid_entities = []
            for ent in entities:
                s = int(ent["start_offset"])
                e = int(ent["end_offset"])
                lbl = str(ent["label"])
                if 0 <= s < e <= len(text) and lbl:
                    valid_entities.append({"start_offset": s, "end_offset": e, "label": lbl})
            # 正样本和负样本都保留：空实体列表的负样本教会模型预测 O
            normalized.append({"text": text, "entities": valid_entities})
        elif "label" in ex:
            normalized.append({
                "text": text,
                "entities": [{"start_offset": 0, "end_offset": len(text), "label": str(ex["label"])}],
            })
    return normalized


def _augment_training_data(
    examples: list[dict[str, Any]],
    document_text: str | None,
) -> list[dict[str, Any]]:
    """自动扩展训练数据：用完整句子替换孤立实体，并添加负样本。

    解决的问题：
    - 用户标注时只选了实体文本（如 "GB/T 26572—2011"），没有上下文
    - 缺乏负样本导致模型只能预测实体，不会预测 O
    """
    if not document_text or not examples:
        return examples

    sentences = _split_sentences(document_text)
    if len(sentences) < 2:
        return examples

    augmented: list[dict[str, Any]] = []
    entity_texts_used: set[str] = set()

    for ex in examples:
        entity_text = _clean_text(ex["text"])
        entities = ex.get("entities", [])

        # 短文（< 50 字符）大概率是孤立实体，需要从文档中找上下文
        if len(entity_text) < 50 and entity_text not in entity_texts_used:
            entity_texts_used.add(entity_text)
            found_sentence = None
            for sent in sentences:
                cleaned_sent = _clean_text(sent)
                if entity_text in cleaned_sent:
                    found_sentence = sent
                    break

            if found_sentence:
                # 重新计算实体在完整句子中的偏移
                cleaned_sent = _clean_text(found_sentence)
                offset_shift = cleaned_sent.find(entity_text)
                if offset_shift >= 0:
                    new_entities = []
                    for ent in entities:
                        new_start = offset_shift + int(ent["start_offset"])
                        new_end = offset_shift + int(ent["end_offset"])
                        if 0 <= new_start < new_end <= len(cleaned_sent):
                            new_entities.append({
                                "start_offset": new_start,
                                "end_offset": new_end,
                                "label": str(ent["label"]),
                            })
                    if new_entities:
                        augmented.append({"text": cleaned_sent, "entities": new_entities})
                        continue

        # 如果无法扩展，保留原始样本
        augmented.append(ex)

    # 自动添加负样本：从文档中采样不包含已标记实体的句子
    all_labeled_texts = {_clean_text(ex["text"]) for ex in examples}
    # 也排除已找到的上下文句子
    context_sentences = {_clean_text(a["text"]) for a in augmented}
    neg_candidates = [
        s for s in sentences
        if _clean_text(s) not in all_labeled_texts
        and _clean_text(s) not in context_sentences
        and len(_clean_text(s)) >= 8
    ]

    if neg_candidates:
        random.shuffle(neg_candidates)
        n_pos = len(augmented)
        n_neg = max(min(n_pos, len(neg_candidates)), 3)
        neg_candidates = neg_candidates[:n_neg]

        print(f"[augment] 添加 {len(neg_candidates)} 条负样本 (原正样本: {len(examples)}, "
              f"扩展后: {len(augmented)})")
        for sent in neg_candidates:
            augmented.append({"text": _clean_text(sent), "entities": []})

    return augmented


def _collect_labels(examples: list[dict[str, Any]]) -> list[str]:
    """从 Doccano 格式的样本中收集所有唯一的实体标签。

    返回 BIO 标签列表: [O, B-标签1, I-标签1, B-标签2, I-标签2, ...]
    """
    unique_labels = set()
    for ex in examples:
        for ent in ex.get("entities", []):
            unique_labels.add(ent["label"])
    sorted_labels = sorted(unique_labels)
    bio_tags = ["O"]
    for lbl in sorted_labels:
        bio_tags.append(f"B-{lbl}")
        bio_tags.append(f"I-{lbl}")
    return bio_tags


def _encode_bio_tags(
    text: str,
    entities: list[dict[str, Any]],
    tokenizer,
    label_to_id: dict[str, int],
    max_length: int = 256,
) -> dict[str, list[int]]:
    """将一条 Doccano 样本转为 BIO 标注的 token ids。"""
    text = _normalize_text(text)
    tokenized = tokenizer(
        text,
        truncation=True,
        max_length=max_length,
        return_offsets_mapping=True,
    )
    input_ids = tokenized["input_ids"]
    attention_mask = tokenized["attention_mask"]
    offset_mapping = tokenized["offset_mapping"]

    n_tokens = len(input_ids)
    bio_tags = ["O"] * n_tokens

    for ent in sorted(entities, key=lambda e: (e["start_offset"], -e["end_offset"])):
        s_char = ent["start_offset"]
        e_char = ent["end_offset"]
        lbl = ent["label"]
        start_token = None
        for t_idx, (cs, ce) in enumerate(offset_mapping):
            if cs == ce == 0:
                continue
            if ce is not None and ce <= s_char:
                continue
            if cs is not None and cs >= e_char:
                break
            if start_token is None:
                start_token = t_idx
                bio_tags[t_idx] = f"B-{lbl}"
            else:
                bio_tags[t_idx] = f"I-{lbl}"

    label_ids = []
    for i, (cs, ce) in enumerate(offset_mapping):
        if cs == ce == 0:
            label_ids.append(-100)
        else:
            label_ids.append(label_to_id.get(bio_tags[i], label_to_id["O"]))

    return {"input_ids": input_ids, "attention_mask": attention_mask, "labels": label_ids}


def _decode_bio_tags(
    token_ids: list[int],
    label_ids: list[int],
    id_to_label: dict[int, str],
    offset_mapping: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    """将 BIO 预测结果解码为实体列表（带字符偏移）。"""
    entities: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for t_idx, (cs, ce) in enumerate(offset_mapping):
        if cs == ce == 0:
            if current:
                entities.append(current)
                current = None
            continue

        tag = id_to_label.get(label_ids[t_idx], "O")

        if tag.startswith("B-"):
            if current:
                entities.append(current)
            current = {"label": tag[2:], "start_offset": cs, "end_offset": ce}
        elif tag.startswith("I-"):
            if current and current["label"] == tag[2:]:
                current["end_offset"] = ce
            else:
                if current:
                    entities.append(current)
                current = {"label": tag[2:], "start_offset": cs, "end_offset": ce}
        else:
            if current:
                entities.append(current)
                current = None

    if current:
        entities.append(current)

    return entities


# ── PyTorch Dataset ──────────────────────────────────────

class NERDataset(TorchDataset):
    """NER 训练数据集，将 Doccano 样本转为 PyTorch tensors。"""
    def __init__(self, examples: list[dict[str, Any]], tokenizer,
                 label_to_id: dict[str, int], max_length: int = 256):
        self.records = []
        for ex in examples:
            encoded = _encode_bio_tags(
                ex["text"], ex.get("entities", []), tokenizer, label_to_id, max_length
            )
            self.records.append({
                "input_ids": torch.tensor(encoded["input_ids"], dtype=torch.long),
                "attention_mask": torch.tensor(encoded["attention_mask"], dtype=torch.long),
                "labels": torch.tensor(encoded["labels"], dtype=torch.long),
            })

    def __len__(self):
        return len(self.records)

    def __getitem__(self, idx):
        return self.records[idx]


def _collate_batch(batch: list[dict[str, torch.Tensor]], pad_token_id: int) -> dict[str, torch.Tensor]:
    """对 batch 进行 padding，labels 的 padding 值设为 -100。"""
    max_len = max(item["input_ids"].size(0) for item in batch)
    batch_size = len(batch)

    input_ids = torch.full((batch_size, max_len), pad_token_id, dtype=torch.long)
    attention_mask = torch.zeros((batch_size, max_len), dtype=torch.long)
    labels = torch.full((batch_size, max_len), -100, dtype=torch.long)

    for i, item in enumerate(batch):
        ilen = item["input_ids"].size(0)
        input_ids[i, :ilen] = item["input_ids"]
        attention_mask[i, :ilen] = item["attention_mask"]
        labels[i, :ilen] = item["labels"]

    return {"input_ids": input_ids, "attention_mask": attention_mask, "labels": labels}


# ── 手动训练循环 ──────────────────────────────────────────

def _run_training_loop(
    model, train_dataset: NERDataset, tokenizer,
    epochs: int, batch_size: int, lr: float,
    warmup_ratio: float, weight_decay: float,
    device: str,
    progress_callback: TrainingProgressCallback | None = None,
    shuffle: bool = True,
    val_dataset: NERDataset | None = None,
    patience: int = 2,
) -> None:
    """纯 PyTorch 训练循环，避免 HuggingFace Trainer 的兼容性问题。"""
    model.train()

    n_samples = len(train_dataset)
    steps_per_epoch = max(1, math.ceil(n_samples / batch_size))
    total_steps = epochs * steps_per_epoch
    warmup_steps = max(1, int(total_steps * warmup_ratio))

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)

    def lr_lambda(current_step):
        if current_step < warmup_steps:
            return float(current_step) / max(1, warmup_steps)
        progress = float(current_step - warmup_steps) / max(1, total_steps - warmup_steps)
        return max(0.0, 0.5 * (1.0 + math.cos(math.pi * progress)))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)

    collate_fn = lambda batch: _collate_batch(batch, tokenizer.pad_token_id)
    global_step = 0

    if progress_callback:
        progress_callback.on_log(f"[training] {epochs=}, {batch_size=}, {lr=}, steps_per_epoch={steps_per_epoch}, total={total_steps}")

    if progress_callback:
        progress_callback.on_status(f"开始训练: {epochs} epochs, {n_samples} 样本, batch={batch_size}")
        progress_callback.on_progress(0, epochs, 0, total_steps, None, lr, None)

    ema_loss = None  # 指数移动平均 loss，用于平滑曲线

    for epoch in range(epochs):
        loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=shuffle,
                            collate_fn=collate_fn)

        epoch_loss = 0.0
        epoch_steps = 0

        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            outputs = model(**batch)
            loss = outputs["loss"]

            optimizer.zero_grad()
            loss.backward()

            # 梯度裁剪
            total_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

            # ── FGM 对抗训练 ──
            # 对 embedding 层加扰动，增强边界噪声鲁棒性
            embedding = model.encoder.embeddings.word_embeddings
            embedding_weight = embedding.weight
            if embedding_weight.grad is not None:
                # 计算扰动方向 (normalized gradient)
                embed_grad = embedding_weight.grad.detach().clone()
                norm = embed_grad.norm(p=2, dim=1, keepdim=True)
                perturbation = 0.5 * embed_grad / (norm + 1e-12)

                # 添加扰动
                with torch.no_grad():
                    embedding_weight.add_(perturbation)

                # 重新 forward + backward
                adv_outputs = model(**{k: v for k, v in batch.items()})
                adv_loss = adv_outputs["loss"]
                adv_loss.backward()

                # 恢复原始 embedding 权重
                with torch.no_grad():
                    embedding_weight.sub_(perturbation)

            optimizer.step()
            scheduler.step()

            loss_val = loss.item()
            epoch_loss += loss_val
            epoch_steps += 1
            global_step += 1

            # 计算 Token Accuracy
            with torch.no_grad():
                emissions = outputs["emissions"]
                mask = batch["attention_mask"].bool()
                predictions = model.crf.decode(emissions, mask)
                labels = batch["labels"]
                correct = 0
                total = 0
                for pred_list, label_seq, m in zip(predictions, labels, mask):
                    # pred_list 长度 = 有效 token 数 = m.sum()
                    label_valid = label_seq[m]
                    pred_tensor = torch.tensor(pred_list, device=labels.device, dtype=torch.long)
                    correct += (pred_tensor == label_valid).sum().item()
                    total += len(pred_list)
                batch_acc = round(correct / max(1, total), 4)

            # 更新 EMA loss
            if ema_loss is None:
                ema_loss = loss_val
            else:
                ema_loss = 0.1 * loss_val + 0.9 * ema_loss

            if progress_callback and global_step % 10 == 0:
                epoch_fraction = epoch + epoch_steps / steps_per_epoch
                progress_callback.on_progress(
                    round(epoch_fraction, 2), epochs, global_step, total_steps,
                    round(loss_val, 4), scheduler.get_last_lr()[0],
                    round(total_norm.item(), 4) if isinstance(total_norm, torch.Tensor) else round(total_norm, 4),
                    round(ema_loss, 4),
                    batch_acc,
                )

        avg_loss = epoch_loss / max(1, epoch_steps)
        epoch_done = epoch + 1
        if progress_callback:
            progress_callback.on_log(f"[training] epoch {epoch_done}/{epochs} done, avg_loss={avg_loss:.4f}")

        if progress_callback:
            progress_callback.on_progress(
                float(epoch_done), epochs, global_step, total_steps,
                round(avg_loss, 4), scheduler.get_last_lr()[0], None,
                round(ema_loss, 4) if ema_loss is not None else None,
            )

        # ── 验证集评估 + 早停 ──
        if val_dataset is not None:
            model.eval()
            val_loss_sum = 0.0
            val_correct = 0
            val_total = 0
            val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False,
                                     collate_fn=lambda b: _collate_batch(b, tokenizer.pad_token_id))
            with torch.no_grad():
                for val_batch in val_loader:
                    val_batch = {k: v.to(device) for k, v in val_batch.items()}
                    val_outputs = model(**val_batch)
                    val_loss_sum += val_outputs["loss"].item()
                    # Token accuracy
                    val_emissions = val_outputs["emissions"]
                    val_mask = val_batch["attention_mask"].bool()
                    val_preds = model.crf.decode(val_emissions, val_mask)
                    val_labels = val_batch["labels"]
                    for pred_list, label_seq, m in zip(val_preds, val_labels, val_mask):
                        label_valid = label_seq[m]
                        pred_tensor = torch.tensor(pred_list, device=device, dtype=torch.long)
                        val_correct += (pred_tensor == label_valid).sum().item()
                        val_total += len(pred_list)
            val_loss = round(val_loss_sum / max(1, len(val_loader)), 4)
            val_acc = round(val_correct / max(1, val_total), 4)
            if progress_callback:
                progress_callback.on_log(
                    f"[validation] epoch {epoch_done}/{epochs} val_loss={val_loss:.4f} val_acc={val_acc:.2%}"
                )
                progress_callback.on_validation(val_loss, val_acc)
            model.train()

            # 早停逻辑
            if not hasattr(_run_training_loop, '_best_val_loss'):
                _run_training_loop._best_val_loss = float('inf')
                _run_training_loop._patience_counter = 0
                _run_training_loop._best_model_state = None
            if val_loss < _run_training_loop._best_val_loss:
                _run_training_loop._best_val_loss = val_loss
                _run_training_loop._patience_counter = 0
                _run_training_loop._best_model_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                if progress_callback:
                    progress_callback.on_log(f"[early_stop] best val_loss={val_loss:.4f}, patience reset")
            else:
                _run_training_loop._patience_counter += 1
                if progress_callback:
                    progress_callback.on_log(
                        f"[early_stop] no improvement ({_run_training_loop._patience_counter}/{patience}), best={_run_training_loop._best_val_loss:.4f}"
                    )
                if _run_training_loop._patience_counter >= patience:
                    if progress_callback:
                        progress_callback.on_log(f"[early_stop] stopping early at epoch {epoch_done}")
                    break
        # ── 结束 ──

    # 恢复最佳模型
    if val_dataset is not None and _run_training_loop._best_model_state is not None and hasattr(_run_training_loop, '_best_model_state'):
        model.load_state_dict(_run_training_loop._best_model_state)
        if progress_callback:
            progress_callback.on_log(f"[early_stop] restored best model (val_loss={_run_training_loop._best_val_loss:.4f})")

    if progress_callback:
        progress_callback.on_status("训练完成")


# ── 模型路径工具 ──────────────────────────────────────────

def _model_path(model_id: str) -> Path:
    return MODELS_DIR / model_id


def _load_metadata(model_id: str) -> dict[str, Any]:
    path = _model_path(model_id) / "metadata.json"
    if not path.exists():
        raise FileNotFoundError(f"Model {model_id} not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_metadata(model_id: str, metadata: dict[str, Any]) -> None:
    _model_path(model_id).mkdir(parents=True, exist_ok=True)
    with open(_model_path(model_id) / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


# ── 模型管理 ──────────────────────────────────────────────

def list_models() -> list[dict[str, Any]]:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    models = []
    for d in sorted(MODELS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if d.is_dir():
            meta_path = d / "metadata.json"
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                # 兼容旧 SetFit 模型格式
                if "entity_labels" not in meta:
                    meta["entity_labels"] = meta.get("labels", [])
                if "backbone" not in meta:
                    meta["backbone"] = meta.get("backbone", "unknown")
                models.append(meta)
    return models


def get_model(model_id: str) -> dict[str, Any]:
    return _load_metadata(model_id)


def delete_model(model_id: str) -> None:
    path = _model_path(model_id)
    if path.exists():
        shutil.rmtree(path)
    _quick_models.pop(model_id, None)


# ── 训练 ──────────────────────────────────────────────────

def train_model(
    mode: str,
    model_name: str,
    labels: list[str],
    examples: list[dict[str, str]],
    progress_callback=None,
    document_text: str | None = None,
    epochs: int = 0,
    batch_size: int = 0,
    lr: float = 0.0,
) -> dict[str, Any]:
    start = time.time()
    model_id = uuid.uuid4().hex[:12]

    examples = _normalize_examples(examples)
    if len(examples) < 1:
        raise ValueError("至少需要 1 个训练样本")

    # 数据增强：扩展上下文 + 添加负样本
    examples = _augment_training_data(examples, document_text)

    bio_tags = _collect_labels(examples)
    label_to_id = {tag: i for i, tag in enumerate(bio_tags)}
    id_to_label = {i: tag for tag, i in label_to_id.items()}
    entity_labels = sorted({t[2:] for t in bio_tags if t.startswith("B-")})

    if progress_callback:
        progress_callback.on_log(f"[train_model] {model_name=}, entity_labels={entity_labels}, "
              f"bio_tags={len(bio_tags)}, samples={len(examples)}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if progress_callback:
        progress_callback.on_log(f"[train_model] device={device}, loading backbone {BACKBONE_NAME}...")

    if progress_callback:
        progress_callback.on_status(f"加载模型: {BACKBONE_NAME}，设备: {device}...")

    tokenizer = _load_backbone_tokenizer(BACKBONE_NAME)
    model = _build_model_with_crf(BACKBONE_NAME, len(bio_tags), id_to_label, label_to_id, device)

    n_samples = len(examples)
    avg_text_len = sum(len(e["text"]) for e in examples) / max(1, n_samples)
    max_length = min(512, max(192 if avg_text_len < 128 else 384, 256))

    if progress_callback:
        progress_callback.on_status(
            f"准备训练: {len(bio_tags)} 个 BIO 标签, {n_samples} 条样本"
        )

    train_dataset = NERDataset(examples, tokenizer, label_to_id, max_length=max_length)

    # 划分验证集 (10%)
    val_dataset = None
    if n_samples >= 20:
        split_idx = int(n_samples * 0.9)
        val_examples = examples[split_idx:]
        examples = examples[:split_idx]
        n_samples = len(examples)
        train_dataset = NERDataset(examples, tokenizer, label_to_id, max_length=max_length)
        val_dataset = NERDataset(val_examples, tokenizer, label_to_id, max_length=max_length)
        if progress_callback:
            progress_callback.on_log(
                f"[train_model] split: train={n_samples}, val={len(val_examples)} (10%)"
            )

    # 动态训练参数：用户指定值优先，未指定时按样本数自动计算
    if epochs <= 0 or batch_size <= 0 or lr <= 0.0:
        if n_samples <= 3:
            _epochs, _batch_size, _lr = 12, 2, 5e-5
        elif n_samples <= 10:
            _epochs, _batch_size, _lr = 10, 2, 3e-5
        elif n_samples <= 30:
            _epochs, _batch_size, _lr = 8, 2, 2e-5
        elif n_samples <= 50:
            _epochs, _batch_size, _lr = 6, 2, 2e-5
        elif n_samples <= 120:
            _epochs, _batch_size, _lr = 5, 4, 2e-5
        else:
            _epochs, _batch_size, _lr = 8, 8, 2e-5
        epochs = epochs if epochs > 0 else _epochs
        batch_size = batch_size if batch_size > 0 else _batch_size
        lr = lr if lr > 0.0 else _lr

    if progress_callback:
        progress_callback.on_log(f"[train_model] epochs={epochs}, batch={batch_size}, lr={lr}, max_length={max_length}")

    # 创建训练历史收集器
    training_history = []
    if progress_callback:
        wrapped_callback = HistoryCollectingCallback(progress_callback, training_history)
    else:
        wrapped_callback = HistoryCollectingCallback(None, training_history)

    _run_training_loop(
        model, train_dataset, tokenizer,
        epochs=epochs, batch_size=batch_size, lr=lr,
        warmup_ratio=0.1, weight_decay=0.01,
        device=device, progress_callback=wrapped_callback,
        val_dataset=val_dataset,
    )

    elapsed = round(time.time() - start, 1)
    if progress_callback:
        progress_callback.on_log(f"[train_model] training done in {elapsed}s")

    metadata = {
        "model_id": model_id,
        "mode": mode,
        "model_name": model_name,
        "entity_labels": entity_labels,
        "bio_tags": bio_tags,
        "label_to_id": label_to_id,
        "example_count": n_samples,
        "train_duration_seconds": elapsed,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "backbone": BACKBONE_NAME,
        "max_length": max_length,
        "training_history": training_history,
    }

    if mode == "persistent":
        save_dir = _model_path(model_id) / "model"
        save_dir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(save_dir))
        tokenizer.save_pretrained(str(save_dir))
        _save_metadata(model_id, metadata)
        with open(_model_path(model_id) / "examples.json", "w", encoding="utf-8") as f:
            json.dump(examples, f, ensure_ascii=False, indent=2)

    _quick_models[model_id] = {"model": model, "tokenizer": tokenizer, "metadata": metadata}

    return metadata


# ── 推理 ──────────────────────────────────────────────────

def run_inference(model_id: str, document_text: str) -> dict[str, Any]:
    cached = _quick_models.get(model_id)
    model = None
    tokenizer = None
    metadata = {}

    if cached:
        model = cached["model"]
        tokenizer = cached["tokenizer"]
        metadata = cached.get("metadata", {})
    else:
        model_dir = _model_path(model_id) / "model"
        meta_path = _model_path(model_id) / "metadata.json"
        if not model_dir.exists() or not meta_path.exists():
            raise FileNotFoundError(f"Model {model_id} not found")

        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        model = NERModel.from_pretrained(str(model_dir), device)

    device = next(model.parameters()).device
    id_to_label = model.config.id2label
    entity_labels = metadata.get("entity_labels", [])
    max_length = metadata.get("max_length", 256)

    sentences = _split_sentences(document_text)
    if not sentences:
        sentences = [document_text]

    print(f"[run_inference] {model_id=}, sentences={len(sentences)}, labels={entity_labels}")

    model.eval()
    all_entities: list[dict[str, Any]] = []
    entity_idx = 0

    for sentence_idx, sentence in enumerate(sentences):
        original_sentence = sentence
        sentence = _normalize_text(sentence)

        tokenized = tokenizer(
            sentence,
            truncation=True,
            max_length=max_length,
            return_offsets_mapping=True,
            return_tensors="pt",
        )
        input_ids = tokenized["input_ids"].to(device)
        attention_mask = tokenized["attention_mask"].to(device)
        offset_mapping = tokenized["offset_mapping"][0].tolist()

        with torch.no_grad():
            outputs = model(input_ids=input_ids, attention_mask=attention_mask)
            emissions = outputs["emissions"][0]  # (S, num_labels)
            mask = attention_mask.bool()[0]
            predictions = model.crf.decode(emissions.unsqueeze(0), mask.unsqueeze(0))[0]

        # 计算 softmax 概率用于置信度
        probs = torch.softmax(emissions, dim=-1)  # (S, num_labels)

        entities = _decode_bio_tags(
            input_ids[0].cpu().tolist(), predictions, id_to_label, offset_mapping
        )

        # 为每个实体计算置信度
        token_info = []
        pred_idx = 0
        for t_idx, (cs, ce) in enumerate(offset_mapping):
            if cs == ce == 0:
                continue
            if pred_idx < len(predictions):
                token_info.append((cs, ce, predictions[pred_idx], float(probs[t_idx][predictions[pred_idx]])))
            pred_idx += 1

        for ent in entities:
            conf_sum = 0.0
            conf_count = 0
            for cs, ce, _pred_id, prob in token_info:
                if cs < ent["end_offset"] and ce > ent["start_offset"]:
                    conf_sum += prob
                    conf_count += 1
            conf = conf_sum / conf_count if conf_count > 0 else 0.0
            ent["confidence"] = round(conf, 4)

        for ent in entities:
            # 边界修复: "05" 前有 "OP" → 扩展为 "OP05"
            start_off = ent["start_offset"]
            end_off = ent["end_offset"]
            lbl = ent["label"]
            raw_text = sentence[start_off:end_off]
            # 若实体为纯数字/字母且紧接 "OP" 前缀，扩展左边界
            if start_off >= 2 and sentence[start_off-2:start_off].upper() == 'OP':
                # 检查 "OP" 不被已有实体占据（排除自身）
                op_overlap = False
                for prev_ent in entities:
                    if prev_ent is ent:
                        continue
                    if prev_ent["end_offset"] > start_off - 2 and prev_ent["start_offset"] <= start_off:
                        op_overlap = True
                        break
                if not op_overlap:
                    start_off -= 2
                    raw_text = sentence[start_off:end_off]
            entity_text = raw_text
            cleaned = _clean_text(entity_text)
            if not cleaned or len(cleaned) < 2:
                continue
            context = sentence[max(0, start_off - 40):min(len(sentence), end_off + 40)]
            lbl = ent["label"]
            all_entities.append({
                "id": f"{lbl}:{entity_idx}",
                "rule_id": lbl,
                "rule_label": lbl,
                "type": lbl,
                "label": cleaned,
                "text": cleaned,
                "context": _clean_text(context),
                "confidence": ent.get("confidence", 0),
                "start_offset": start_off,
                "end_offset": end_off,
                "sentence_index": sentence_idx,
                "sentence_original": original_sentence,
            })
            entity_idx += 1

    entries: list[dict[str, Any]] = []
    for ent in all_entities:
        entries.append({
            "id": ent["id"],
            "rule_id": ent["rule_id"],
            "rule_label": ent["rule_label"],
            "text": ent["text"],
            "context": ent["context"],
            "tags": [ent["text"]],
            "confidence": ent.get("confidence", 0),
        })

    counts: dict[str, int] = {}
    for lbl in entity_labels:
        counts[lbl] = sum(1 for e in entries if e["rule_id"] == lbl)

    print(f"[run_inference] done: {len(all_entities)} entities, {len(entries)} entries")

    return {
        "entities": all_entities,
        "entries": entries,
        "counts": counts,
        "rules": [{"id": lbl, "label": lbl, "count": counts.get(lbl, 0)} for lbl in entity_labels],
    }


# ── 继续训练 ──────────────────────────────────────────────

def continue_train(model_id: str, new_examples: list[dict[str, str]]) -> dict[str, Any]:
    metadata = _load_metadata(model_id)
    model_dir = _model_path(model_id) / "model"

    examples_path = _model_path(model_id) / "examples.json"
    if examples_path.exists():
        with open(examples_path, "r", encoding="utf-8") as f:
            old_examples = json.load(f)
    else:
        old_examples = []

    new_examples = _normalize_examples(new_examples)
    all_examples = old_examples + new_examples

    start = time.time()
    bio_tags = _collect_labels(all_examples)
    label_to_id = {tag: i for i, tag in enumerate(bio_tags)}
    id_to_label = {i: tag for tag, i in label_to_id.items()}
    entity_labels = sorted({t[2:] for t in bio_tags if t.startswith("B-")})

    n_samples = len(all_examples)
    avg_len = sum(len(e["text"]) for e in all_examples) / max(1, n_samples)
    max_length = min(512, max(192 if avg_len < 128 else 384, 256))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, )

    model = NERModel.from_pretrained(str(model_dir), device)

    train_dataset = NERDataset(all_examples, tokenizer, label_to_id, max_length=max_length)

    if n_samples <= 3:
        epochs, batch_size, lr = 6, 2, 3e-5
    elif n_samples <= 15:
        epochs, batch_size, lr = 5, 2, 2e-5
    elif n_samples <= 30:
        epochs, batch_size, lr = 3, 4, 1e-5
    else:
        epochs, batch_size, lr = 2, 8, 8e-6

    _run_training_loop(
        model, train_dataset, tokenizer,
        epochs=epochs, batch_size=batch_size, lr=lr,
        warmup_ratio=0.1, weight_decay=0.01,
        device=device,
    )

    elapsed = round(time.time() - start, 1)

    save_dir = _model_path(model_id) / "model"
    if save_dir.exists():
        shutil.rmtree(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(save_dir))
    tokenizer.save_pretrained(str(save_dir))

    metadata["entity_labels"] = entity_labels
    metadata["bio_tags"] = bio_tags
    metadata["label_to_id"] = label_to_id
    metadata["example_count"] = n_samples
    metadata["train_duration_seconds"] = elapsed
    metadata["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    metadata["max_length"] = max_length
    _save_metadata(model_id, metadata)

    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(all_examples, f, ensure_ascii=False, indent=2)

    _quick_models.pop(model_id, None)
    _quick_models[model_id] = {"model": model, "tokenizer": tokenizer, "metadata": metadata}

    return metadata


# ── JSONL 解析工具 ───────────────────────────────────────

def _coerce_entity_span(
    text: str,
    raw: Any,
    *,
    start_keys: tuple[str, ...],
    end_keys: tuple[str, ...],
) -> dict[str, Any] | None:
    """把一条原始实体/span 转为标准 Doccano 实体；字段非法时返回 None。

    校验 start/end 可转 int、0 <= start < end <= len(text)，并丢弃
    缺少 label 或 label 为空的项，避免 KeyError/ValueError 中断整行解析。
    """
    if not isinstance(raw, dict) or "label" not in raw:
        return None
    start_value = next((raw[key] for key in start_keys if key in raw), None)
    end_value = next((raw[key] for key in end_keys if key in raw), None)
    if start_value is None or end_value is None:
        return None
    label = str(raw.get("label") or "").strip()
    if not label:
        return None
    try:
        start = int(start_value)
        end = int(end_value)
    except (TypeError, ValueError):
        return None
    if start < 0 or end <= start or end > len(text):
        return None
    return {"start_offset": start, "end_offset": end, "label": label}


def _coerce_label_entry(text: str, raw: Any) -> dict[str, Any] | None:
    """兼容 [start, end, label] 元组/列表以及同结构 dict。"""
    if isinstance(raw, dict):
        return _coerce_entity_span(
            text,
            raw,
            start_keys=("start", "start_offset"),
            end_keys=("end", "end_offset"),
        )
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        start = int(raw[0])
        end = int(raw[1])
    except (TypeError, ValueError):
        return None
    label = str(raw[2] or "").strip()
    if not label:
        return None
    if start < 0 or end <= start or end > len(text):
        return None
    return {"start_offset": start, "end_offset": end, "label": label}


def parse_jsonl_training_data(content: str) -> list[dict[str, Any]]:
    """解析 JSONL 格式的训练数据文件。

    支持格式：
    1. Doccano spans 格式: {text, spans: [{start, end, label}]}
    2. Doccano entities 格式: {text, entities: [{start_offset, end_offset, label}]}
    3. 旧版 labels 格式: {text, labels: [[start, end, label], ...]}

    单条实体字段非法时只跳过该实体，不中断整行；无法解析的行直接忽略。
    """
    # 兼容带 BOM 的首行（Windows 记事本/Excel 导出常见）。
    content = content.lstrip("\ufeff")
    examples: list[dict[str, Any]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(item, dict):
            continue

        text = item.get("text")
        if not isinstance(text, str) or not text:
            continue

        # 三种格式按 spans → entities → labels 的优先级尝试。
        entities: list[dict[str, Any]] = []
        raw_spans = item.get("spans")
        raw_entities = item.get("entities")
        raw_labels = item.get("labels")
        if isinstance(raw_spans, list):
            for raw in raw_spans:
                entity = _coerce_entity_span(
                    text, raw, start_keys=("start",), end_keys=("end",)
                )
                if entity is not None:
                    entities.append(entity)
        elif isinstance(raw_entities, list):
            for raw in raw_entities:
                entity = _coerce_entity_span(
                    text,
                    raw,
                    start_keys=("start_offset", "start"),
                    end_keys=("end_offset", "end"),
                )
                if entity is not None:
                    entities.append(entity)
        elif isinstance(raw_labels, list):
            for raw in raw_labels:
                entity = _coerce_label_entry(text, raw)
                if entity is not None:
                    entities.append(entity)

        examples.append({"text": text, "entities": entities})

    return examples


# ── 模型评估 ──────────────────────────────────────────────

def evaluate_model(model_id: str, test_examples: list[dict[str, Any]]) -> dict[str, Any]:
    """评估模型：对测试集运行推理，计算精确率/召回率/F1

    Args:
        model_id: 已训练的模型 ID
        test_examples: 测试样本列表 [{"text": "...", "entities": [...]}, ...]

    Returns:
        {
            "overall": {precision, recall, f1, tp, fp, fn},
            "per_class": {label: {precision, recall, f1, tp, fp, fn}},
            "macro_avg": {precision, recall, f1},
            "sample_count": int
        }
    """
    from evaluation import compute_entity_metrics, compute_per_class_metrics

    # 1. 加载模型（复用 run_inference 的加载逻辑）
    cached = _quick_models.get(model_id)
    model = None
    tokenizer = None
    metadata = {}

    if cached:
        model = cached["model"]
        tokenizer = cached["tokenizer"]
        metadata = cached.get("metadata", {})
    else:
        model_dir = _model_path(model_id) / "model"
        meta_path = _model_path(model_id) / "metadata.json"
        if not model_dir.exists() or not meta_path.exists():
            raise FileNotFoundError(f"Model {model_id} not found")

        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        model = NERModel.from_pretrained(str(model_dir), device)

    device = next(model.parameters()).device
    id_to_label = model.config.id2label
    max_length = metadata.get("max_length", 256)

    model.eval()

    # 2. 对每个测试样本运行推理，收集 y_true 和 y_pred
    y_true_all: list[dict[str, Any]] = []
    y_pred_all: list[dict[str, Any]] = []

    for ex in test_examples:
        text = ex["text"]
        true_entities = ex.get("entities", [])

        # 收集真实标注实体
        for ent in true_entities:
            y_true_all.append({
                "start_offset": int(ent["start_offset"]),
                "end_offset": int(ent["end_offset"]),
                "label": str(ent["label"]),
            })

        # 推理：对单条文本编码 → 推理 → BIO 解码
        text = _normalize_text(text)
        tokenized = tokenizer(
            text,
            truncation=True,
            max_length=max_length,
            return_offsets_mapping=True,
            return_tensors="pt",
        )
        input_ids = tokenized["input_ids"].to(device)
        attention_mask = tokenized["attention_mask"].to(device)
        offset_mapping = tokenized["offset_mapping"][0].tolist()

        with torch.no_grad():
            outputs = model(input_ids=input_ids, attention_mask=attention_mask)
            emissions = outputs["emissions"][0]
            mask = attention_mask.bool()[0]
            predictions = model.crf.decode(emissions.unsqueeze(0), mask.unsqueeze(0))[0]

        entities = _decode_bio_tags(
            input_ids[0].cpu().tolist(), predictions, id_to_label, offset_mapping
        )

        for ent in entities:
            y_pred_all.append({
                "start_offset": int(ent["start_offset"]),
                "end_offset": int(ent["end_offset"]),
                "label": str(ent["label"]),
            })

    # 3. 计算评估指标
    overall = compute_entity_metrics(y_true_all, y_pred_all)
    per_class_result = compute_per_class_metrics(y_true_all, y_pred_all)

    return {
        "overall": overall,
        "per_class": per_class_result["per_class"],
        "macro_avg": per_class_result["macro_avg"],
        "sample_count": len(test_examples),
    }
