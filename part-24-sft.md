[← الجزء الثالث والعشرون](./part-23-qlora.md) · [الفهرس](./README.md)

# الجزء الرابع والعشرون: SFT

## الفصل 46: SFT Training Script

هذا الفصل يبني سكريبت التدريب الفعلي — نقطة التقاء كل ما سبق: الـDataset (الجزء الثالث عشر)، الـConfig (الفصل 45)، والنموذج المختار (الجزء الحادي والعشرون).

### 46.1 البنية العامة للسكريبت

```
تحميل Config (YAML)
        ↓
تحميل النموذج بتكميم 4-bit + إعداد LoRA
        ↓
تحميل وTokenize الـDataset (train + validation)
        ↓
إعداد SFTTrainer (من مكتبة TRL)
        ↓
التدريب مع logging دوري + مراقبة VRAM (الفصل 44)
        ↓
Checkpointing دوري + دعم Resume
        ↓
حفظ الـLoRA adapter النهائي
```

### 46.2 `training/train_sft.py`

```python
# training/train_sft.py
"""
سكريبت SFT كامل باستخدام Transformers + TRL + PEFT + bitsandbytes
+ Accelerate. يقرأ Config من ملف YAML (الفصل 45)، ويدعم Resume من
آخر checkpoint تلقائيًا لو وُجد.
"""
import os
import yaml
import random
import numpy as np
import torch
from pathlib import Path
from dataclasses import dataclass

from transformers import (
    AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
    TrainingArguments,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer, SFTConfig
from datasets import load_dataset

from training.vram_monitor import log_vram_periodically


def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def build_quantization_config(cfg: dict) -> BitsAndBytesConfig:
    q = cfg["quantization"]
    return BitsAndBytesConfig(
        load_in_4bit=q["load_in_4bit"],
        bnb_4bit_quant_type=q["bnb_4bit_quant_type"],
        bnb_4bit_compute_dtype=getattr(torch, q["bnb_4bit_compute_dtype"]),
        bnb_4bit_use_double_quant=q["bnb_4bit_use_double_quant"],
    )


def load_model_and_tokenizer(cfg: dict):
    model_id = cfg["model"]["base_model_id"]
    bnb_config = build_quantization_config(cfg)

    tokenizer = AutoTokenizer.from_pretrained(
        model_id, trust_remote_code=cfg["model"]["trust_remote_code"]
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=cfg["model"]["trust_remote_code"],
    )
    model = prepare_model_for_kbit_training(model)

    if cfg["training"]["gradient_checkpointing"]:
        model.gradient_checkpointing_enable()

    return model, tokenizer


def build_lora_config(cfg: dict) -> LoraConfig:
    l = cfg["lora"]
    return LoraConfig(
        r=l["r"],
        lora_alpha=l["lora_alpha"],
        lora_dropout=l["lora_dropout"],
        target_modules=l["target_modules"],
        bias=l["bias"],
        task_type=l["task_type"],
    )


def format_sample_for_training(sample: dict, tokenizer) -> str:
    """يبني نص التدريب النهائي من عينة متوافقة مع Schema الفصل 27.
    التنسيق الدقيق (JSON مقابل structured text) يُناقَش بالتفصيل
    في الفصل 47 — هنا نستخدم القرار المُتَّخَذ هناك (JSON structured)."""
    import json
    from baseline.run_baseline import SYSTEM_PROMPT, build_prompt

    user_prompt = build_prompt({"sample": sample})
    target_output = json.dumps({
        **sample["analysis"],
        "verdict": sample["verdict"],
    }, ensure_ascii=False)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": target_output},
    ]
    return tokenizer.apply_chat_template(messages, tokenize=False)


def build_training_arguments(cfg: dict) -> SFTConfig:
    t = cfg["training"]
    o = cfg["output"]
    return SFTConfig(
        output_dir=o["output_dir"],
        num_train_epochs=t["num_train_epochs"],
        per_device_train_batch_size=t["per_device_train_batch_size"],
        gradient_accumulation_steps=t["gradient_accumulation_steps"],
        learning_rate=t["learning_rate"],
        warmup_ratio=t["warmup_ratio"],
        weight_decay=t["weight_decay"],
        lr_scheduler_type=t["lr_scheduler_type"],
        bf16=t["bf16"],
        optim=t["optim"],
        logging_steps=t["logging_steps"],
        save_steps=t["save_steps"],
        eval_steps=t["eval_steps"],
        eval_strategy="steps",
        max_seq_length=t["max_seq_length"],
        seed=t["seed"],
        report_to=["none"],  # يُستبدَل بـ'wandb' أو ما يعادله إن رُغب لاحقًا
    )


def find_latest_checkpoint(output_dir: str) -> str | None:
    out_path = Path(output_dir)
    if not out_path.exists():
        return None
    checkpoints = sorted(
        out_path.glob("checkpoint-*"),
        key=lambda p: int(p.name.split("-")[-1]),
    )
    return str(checkpoints[-1]) if checkpoints else None


def run_training(config_path: Path):
    cfg = load_config(config_path)
    set_seed(cfg["training"]["seed"])

    model, tokenizer = load_model_and_tokenizer(cfg)
    lora_config = build_lora_config(cfg)
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()  # تحقق سريع: عدد صغير نسبيًا متوقَّع

    dataset = load_dataset(
        "json",
        data_files={
            "train": cfg["data"]["train_path"],
            "validation": cfg["data"]["validation_path"],
        },
    )

    def formatting_func(example):
        return format_sample_for_training(example, tokenizer)

    training_args = build_training_arguments(cfg)

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        formatting_func=formatting_func,
        tokenizer=tokenizer,
    )

    # OOM handling: التقاط الاستثناء وتسجيل حالة الذاكرة قبل الفشل الكامل
    try:
        resume_checkpoint = find_latest_checkpoint(cfg["output"]["output_dir"])
        if resume_checkpoint:
            print(f"Resuming from checkpoint: {resume_checkpoint}")
        trainer.train(resume_from_checkpoint=resume_checkpoint)
    except torch.cuda.OutOfMemoryError as e:
        print(f"OOM ERROR at step {trainer.state.global_step}: {e}")
        print(f"Peak VRAM: {torch.cuda.max_memory_allocated() / 1e9:.2f}GB")
        print("Suggestions: reduce max_seq_length, reduce batch size, "
              "or increase gradient_accumulation_steps")
        raise

    final_dir = Path(cfg["output"]["output_dir"]) / "final_adapter"
    trainer.model.save_pretrained(str(final_dir))
    tokenizer.save_pretrained(str(final_dir))
    print(f"Training complete. Final adapter saved to {final_dir}")


if __name__ == "__main__":
    import sys
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "configs/training_v0.1.yaml"
    )
    run_training(config_path)
```

تشغيل:

```bash
python training/train_sft.py configs/training_v0.1.yaml
```

### 46.3 لماذا `resume_from_checkpoint` تلقائي وليس اختياريًا

تدريب على 16GB VRAM أطول احتمالًا للانقطاع (OOM عرضي، انقطاع كهرباء، إلخ) من بيئة سحابية بموارد وفيرة. جعل اكتشاف آخر checkpoint **تلقائيًا** (`find_latest_checkpoint`) بدل الاعتماد على تذكّر المستخدم لتمرير المسار يدويًا يقلل فرصة فقدان ساعات تدريب بسبب خطأ بشري بسيط.

---

## الفصل 47: Formatting Training Samples

### 47.1 القرار: JSON أم Structured Text؟

| الخيار | الميزة | العيب |
|---|---|---|
| **JSON صريح** (ما اخترناه) | قابل للتحليل الآلي المباشر (`json.loads`)، يطابق الـSchema (الفصل 27) حرفيًا، سهل التحقق الآلي من الاكتمال | النماذج الصغيرة نسبيًا (7B) قد تُنتج JSON غير صالح أحيانًا (فاصلة زائدة، quotes غير مغلقة) |
| Structured text (مثل XML tags أو Markdown headers) | أكثر تسامحًا مع أخطاء التنسيق الصغيرة، بعض النماذج "تفكر" بشكل أوضح في نص حر منظَّم | يحتاج parser مخصص أكثر تعقيدًا من `json.loads` القياسي، وأصعب التحقق الآلي من اكتمال كل حقل |

**القرار النهائي: JSON**، لأن التحقق الآلي الصارم (Pydantic — الفصل 27.4) هو أولوية أعلى من التسامح مع الأخطاء الصغيرة. البديل: لو أظهرت نتائج الـBaseline (الفصل 42) نسبة فشل parsing عالية بشكل غير مقبول، نُضيف طبقة "إصلاح تلقائي خفيف" (مثل محاولة إغلاق أقواس JSON غير مكتملة) بدل التحول الكامل لـstructured text.

### 47.2 القالب النهائي الكامل

```python
# training/prompt_template.py
"""
القالب الموحّد المستخدم في كل من: توليد بيانات التدريب (هذا الفصل)،
الـBaseline (الفصل 42)، والـInference لاحقًا — يجب أن يبقى مطابقًا
تمامًا عبر الثلاثة، وإلا يحدث تدريب/تقييم غير متسقين.
"""

SYSTEM_PROMPT_TEMPLATE = """You are an Android Framework security reviewer.

TASK:
Analyze the provided code context following this methodology:
Entry Point -> Caller -> Attacker-Controlled Input -> Binder Identity
-> Permissions/AppOps/Authorization -> User/UID/Package Relationship
-> Identity Transition -> Privileged Operation -> Trust Boundary
-> Security Invariant -> Potential Violation -> Evidence
-> Counter-Evidence -> Verdict -> Confidence

CODE CONTEXT:
{code_context}

REQUIRED OUTPUT:
Output ONLY a JSON object matching this exact structure, no additional text:

{{
  "entry_point": "...",
  "caller_identity": "...",
  "attacker_controlled_inputs": [...],
  "permission_checks": [...],
  "appops_checks": [...],
  "identity_transitions": [...],
  "cross_user_checks": [...],
  "privileged_operations": [...],
  "trust_boundary": "...",
  "security_invariant": "...",
  "candidate_issue": "...",
  "counter_evidence": [...],
  "missing_context": [...],
  "confidence": 0.0,
  "verdict": "vulnerable" | "secure" | "ambiguous" | "insufficient_context"
}}

RULES:
- clearCallingIdentity() alone is NOT evidence of a vulnerability.
- A permission check alone does NOT guarantee cross-user authorization.
- If required information is missing from the context, use verdict
  "insufficient_context" instead of guessing.
- Every claim in "candidate_issue" or "counter_evidence" must be
  traceable to the code shown above — do not invent details.
"""

def render_prompt(code_context_text: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(code_context=code_context_text)
```

### 47.3 لماذا القواعد (RULES) مكرَّرة داخل الـPrompt رغم وجودها كـInvariants في الفصل 9

الفصل 9 يحدد الـInvariants كمرجع **بنيوي** يُستخدم لتوليد الـDataset والتحقق منه برمجيًا. الـRULES هنا داخل الـPrompt هي **تذكير مباشر** موجَّه للنموذج وقت الاستدلال — أقرب لتوجيه سلوكي فوري من كونها مرجعًا معرفيًا شاملاً. تكرارهما مقصود: الأول (الفصل 9) بنية معرفية، والثاني (هنا) توجيه تشغيلي — فقدان أحدهما لا يُغني عن الآخر.

### 47.4 معالجة عدم اتساق طول الـCode Context

عينات مختلفة تحمل `code_context` بأطوال مختلفة جدًا (method قصيرة جدًا مقابل method + caller + عدة helpers). نتأكد أن `format_sample_for_training` (الفصل 46) يستخدم نفس `truncate_to_token_budget` من الفصل 26 على مستوى بناء الـDataset، بحيث لا تتجاوز أي عينة تدريب واحدة `max_seq_length` المحدَّد في Config (3072 من الفصل 45) — تجاوزها بصمت يعني فقدان جزء من الهدف (`verdict` وغيره) أثناء الـtokenization دون أي تحذير.

```python
# training/validate_sample_lengths.py
from transformers import AutoTokenizer
import json
from pathlib import Path

def validate_lengths(dataset_path: Path, tokenizer_id: str, max_seq_length: int):
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_id)
    total, overflowing = 0, 0

    for line in dataset_path.open():
        sample = json.loads(line)
        # نُقدِّر الطول الكامل (system + user + target) قبل التدريب الفعلي
        from training.train_sft import format_sample_for_training
        text = format_sample_for_training(sample, tokenizer)
        token_count = len(tokenizer.encode(text))
        total += 1
        if token_count > max_seq_length:
            overflowing += 1
            print(f"⚠ {sample['sample_id']}: {token_count} tokens "
                  f"(exceeds {max_seq_length})")

    print(f"\n{overflowing}/{total} samples exceed max_seq_length "
          f"({overflowing/total*100:.1f}%)")
    if overflowing / total > 0.05:
        print("⚠ More than 5% of samples overflow — consider tightening "
              "the Context Builder budget (Chapter 26) before training")
```

> **Definition of Done — الجزء الرابع والعشرون:** `validate_sample_lengths.py` يعمل على `train.jsonl` الكامل وينتج نسبة overflow أقل من 5%، وأول تشغيل SFT فعلي (من الفصل السابق) يكتمل حتى نهاية epoch واحد على الأقل مع حفظ checkpoint وسط الطريق، وإثبات نجاح `resume_from_checkpoint` عبر إيقاف التدريب يدويًا ثم إعادة تشغيله والتأكد أنه يكمل من نفس النقطة.

---

[← الجزء الثالث والعشرون](./part-23-qlora.md) · [الفهرس](./README.md) · [الجزء الخامس والعشرون →](./part-25-curriculum.md)
