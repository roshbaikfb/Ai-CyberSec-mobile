[← الجزء الثاني والعشرون](./part-22-baseline.md) · [الفهرس](./README.md)

# الجزء الثالث والعشرون: QLoRA

## الفصل 43: QLoRA Fundamentals

### 43.1 لماذا QLoRA وليس Full Fine-Tuning

Full Fine-Tuning لنموذج 7B يتطلب تحديث **كل** المعاملات (7 مليار قيمة)، مما يستهلك ذاكرة هائلة (أوزان + gradients + optimizer states لكل معامل). هذا غير عملي على 16GB VRAM. QLoRA يحل هذا عبر مزج تقنيتين:

```
Base Model (مُحمَّل بتكميم 4-bit — يقلل حجم الأوزان بشكل كبير)
              +
LoRA Adapters (طبقات صغيرة إضافية قابلة للتدريب، الأوزان الأصلية مجمَّدة)
              =
QLoRA Training
```

النتيجة: نُدرِّب فقط ملايين قليلة من المعاملات (الـLoRA adapters) بدل مليارات، بينما النموذج الأساسي يبقى مجمَّدًا بتكميم منخفض الذاكرة.

### 43.2 المفاهيم الأساسية بالتفصيل

| المفهوم | الشرح | الأثر العملي |
|---|---|---|
| **4-bit quantization** | تمثيل كل معامل بـ4 بت بدل 16/32 بت الاعتيادية | يقلل حجم الأوزان في الذاكرة إلى ~ربع الحجم الأصلي تقريبًا |
| **NF4 (NormalFloat4)** | نوع تكميم مصمَّم خصيصًا ليطابق التوزيع الطبيعي لأوزان الشبكات العصبية (أدق من int4 التقليدي لنفس عدد البتات) | جودة أعلى من 4-bit تكميم عام بنفس تكلفة الذاكرة |
| **Double quantization** | تكميم إضافي لثوابت التكميم نفسها (وليس فقط الأوزان) | يوفّر ذاكرة إضافية طفيفة لكن مفيدة تراكميًا |
| **LoRA rank (r)** | حجم المصفوفات المنخفضة الرتبة المُضافة — كلما زاد، زادت قدرة الـadapter على التعلّم لكن زادت الذاكرة والمعاملات القابلة للتدريب | نقطة توازن تُضبَط تجريبيًا (الفصل 45) |
| **LoRA alpha** | معامل قياس (scaling) يتحكم في تأثير الـLoRA adapter على المخرجات النهائية | يُضبَط عادة كمضاعف لـr (مثل alpha = 2×r كنقطة انطلاق شائعة) |
| **Dropout** | تعطيل عشوائي لجزء من الـLoRA activations أثناء التدريب لمنع overfitting | مهم خصوصًا مع Dataset متوسط الحجم مثل v0.1 |
| **Target modules** | أي طبقات في الـTransformer تحصل على LoRA adapters (عادة `q_proj`, `v_proj`, وأحيانًا `k_proj`, `o_proj`) | التوسع لطبقات أكثر يحسّن القدرة لكن يزيد الذاكرة |
| **Gradient accumulation** | تجميع gradients عبر عدة batches صغيرة قبل تحديث الأوزان، لمحاكاة batch size أكبر دون الحاجة لذاكرة batch كبير فعليًا | ضروري على 16GB VRAM حيث batch size الفعلي محدود جدًا |
| **Gradient checkpointing** | إعادة حساب بعض القيم الوسيطة أثناء backward pass بدل تخزينها بالكامل | يوفّر ذاكرة كبيرة مقابل زيادة طفيفة في زمن التدريب |
| **bf16/fp16** | دقة عائمة أخف من fp32 لعمليات التدريب غير الأوزان المكمَّمة (gradients، بعض activations) | bf16 مفضَّل على RTX 5070 Ti (Ampere/Ada وما بعدها يدعمانه جيدًا) لاستقرار رقمي أفضل من fp16 |

### 43.3 لماذا هذه التفاصيل مرتبطة بجهازنا تحديدًا

كل قرار أعلاه يُقيَّم عمليًا بمعيار واحد: **هل يتسع ضمن 16GB VRAM مع سياق كافٍ لعينات الفصل 26؟** الفصل التالي (44) يترجم هذا لأرقام فعلية.

---

## الفصل 44: VRAM Budget

### 44.1 المكوّنات التي تستهلك VRAM أثناء التدريب

```
Base model weights (4-bit)
        +
LoRA adapter weights (bf16، صغيرة نسبيًا)
        +
Optimizer states (فقط لمعاملات LoRA، ليس النموذج الكامل)
        +
Activations (تعتمد على batch size وmax_seq_length)
        +
Gradient buffers (لمعاملات LoRA فقط)
        +
CUDA overhead + fragmentation (هامش أمان دائمًا)
```

### 44.2 تقدير عملي — وليس أرقامًا قطعية

| المكوّن | تقدير تقريبي لنموذج 7B | ملاحظة |
|---|---|---|
| أوزان النموذج (4-bit) | ~4-4.5 GB | يعتمد على البنية الدقيقة للنموذج المختار |
| LoRA adapters (r=16، عدة target modules) | ~0.1-0.3 GB | صغير جدًا نسبيًا — هذا جوهر كفاءة QLoRA |
| Optimizer states لمعاملات LoRA | ~0.2-0.6 GB | AdamW يحتاج حالتين لكل معامل قابل للتدريب |
| Activations @ context 2k | ~1.5-2.5 GB | يتناسب تقريبيًا خطيًا مع طول السياق وbatch size |
| Activations @ context 4k | ~3-5 GB | ضِعف تقريبًا مقارنة بـ2k |
| Activations @ context 8k | ~6-10 GB | يبدأ يقترب من حدود 16GB بسرعة مع بقية المكوّنات |
| CUDA overhead + هامش أمان | ~1-2 GB | لا يُترَك أبدًا خارج الحساب |

**الخلاصة العملية:** على 16GB VRAM، context في نطاق **2k-4k tokens** هو الأكثر واقعية لتدريب مستقر بدون OOM متكرر. context 8k ممكن لكن يتطلب batch size = 1 مع gradient accumulation عالٍ، وهامش أمان أقل للتجربة والخطأ.

### 44.3 لماذا Context Budget (الفصل 26) مصمَّم أصلًا لهذا الحد

تذكير مهم: ميزانية الـContext Builder في الفصل 26 (افتراضيًا 3000 token) لم تُختَر عشوائيًا — هي مصمَّمة لتقع مريحة ضمن نطاق 2k-4k الموصوف هنا. لو لاحقًا زادت الحاجة الفعلية للسياق (نتيجة ملاحظات من الـFailure Analysis لاحقًا)، القرار بزيادتها يجب أن يوازَن دائمًا مقابل هذا الجدول.

### 44.4 لماذا لا نعطي أرقامًا قطعية نهائية

الأرقام أعلاه تقريبية بصراحة لأنها تعتمد على: البنية الدقيقة للنموذج المختار فعليًا (الفصل 40)، إصدار `bitsandbytes`/`transformers` وقت التشغيل (تتحسّن الكفاءة بمرور الوقت)، وتفاصيل تنفيذ الـattention (مثل استخدام Flash Attention إن كان مدعومًا). **القياس الفعلي دائمًا يتفوّق على الجدول أعلاه** — استخدم `nvidia-smi` أثناء أول تشغيل تجريبي فعلي لمعرفة الاستهلاك الحقيقي بدقة.

### 44.5 سكريبت مراقبة VRAM أثناء التدريب

```python
# training/vram_monitor.py
import torch
import time
from dataclasses import dataclass

@dataclass
class VRAMSnapshot:
    step: int
    allocated_gb: float
    reserved_gb: float
    max_allocated_gb: float

def snapshot_vram(step: int) -> VRAMSnapshot:
    return VRAMSnapshot(
        step=step,
        allocated_gb=round(torch.cuda.memory_allocated() / 1e9, 2),
        reserved_gb=round(torch.cuda.memory_reserved() / 1e9, 2),
        max_allocated_gb=round(torch.cuda.max_memory_allocated() / 1e9, 2),
    )

def log_vram_periodically(step: int, log_every: int = 50):
    if step % log_every == 0:
        snap = snapshot_vram(step)
        print(f"[step {snap.step}] allocated={snap.allocated_gb}GB "
              f"reserved={snap.reserved_gb}GB "
              f"peak={snap.max_allocated_gb}GB")
        if snap.reserved_gb > 15.0:  # هامش أمان قبل 16GB
            print("⚠ WARNING: approaching VRAM limit — consider reducing "
                  "max_seq_length or batch size")
```

---

## الفصل 45: Training Config v0.1

### 45.1 الإعداد الأولي الكامل

هذا Config أولي — **نقطة انطلاق للتجربة، وليست قيمًا مقدَّسة** — سيُعدَّل بناءً على نتائج التشغيلات الفعلية.

```yaml
# configs/training_v0.1.yaml

model:
  base_model_id: "PLACEHOLDER — يُحدَّد فعليًا من نتائج الفصل 40-41"
  trust_remote_code: false

quantization:
  load_in_4bit: true
  bnb_4bit_quant_type: "nf4"
  bnb_4bit_compute_dtype: "bfloat16"
  bnb_4bit_use_double_quant: true

lora:
  r: 16                     # نقطة انطلاق متوسطة — سيُختبَر أيضًا r=8 وr=32
  lora_alpha: 32            # = 2 × r كقاعدة ابتدائية شائعة
  lora_dropout: 0.05
  target_modules:
    - "q_proj"
    - "k_proj"
    - "v_proj"
    - "o_proj"
  bias: "none"
  task_type: "CAUSAL_LM"

training:
  learning_rate: 2.0e-4
  num_train_epochs: 3
  max_seq_length: 3072       # يتماشى مع ميزانية الفصل 26 (3000) + هامش
  per_device_train_batch_size: 1
  gradient_accumulation_steps: 16   # batch size فعّال = 16
  gradient_checkpointing: true
  warmup_ratio: 0.03
  weight_decay: 0.01
  lr_scheduler_type: "cosine"
  bf16: true
  optim: "paged_adamw_8bit"   # optimizer مُحسَّن للذاكرة، متوافق مع bitsandbytes
  logging_steps: 10
  save_steps: 100
  eval_steps: 100
  seed: 42

data:
  train_path: "dataset/v0.1/splits/train.jsonl"
  validation_path: "dataset/v0.1/splits/validation.jsonl"

output:
  output_dir: "experiments/v0.1_qlora_run1"
```

### 45.2 لماذا كل قيمة ابتدائية اختيرت تحديدًا

| القيمة | لماذا هذه نقطة انطلاق معقولة |
|---|---|
| `r=16` | متوسط شائع في الأدبيات لمهام fine-tuning متخصصة بحجم Dataset متوسط (آلاف العينات) — ليس أصغر قيمة (قد لا تكفي التعقيد) ولا أكبرها (تكلفة ذاكرة/overfitting غير مبرَّرة في هذه المرحلة) |
| `lora_alpha=32` | قاعدة `alpha = 2×r` نقطة انطلاق مستقرة تجريبيًا عبر مشاريع متعددة، تُعدَّل لاحقًا لو لوحظ تأثير LoRA ضعيفًا جدًا أو قويًا جدًا على المخرجات |
| `gradient_accumulation_steps=16` مع `batch_size=1` | يحاكي batch size فعّال = 16 رغم القيد الشديد على الذاكرة من batch size الفعلي — ضروري ضمن ميزانية الفصل 44 |
| `max_seq_length=3072` | يطابق ميزانية Context Builder (الفصل 26) — لا فائدة من رفعه دون رفع الميزانية نفسها أولًا |
| `paged_adamw_8bit` | optimizer مصمَّم للعمل بكفاءة مع bitsandbytes ضمن قيود VRAM محدودة، بدل AdamW القياسي الأثقل في الذاكرة |
| `warmup_ratio=0.03` | قيمة متحفظة تمنع قفزات تعلّم مبكرة غير مستقرة، خصوصًا مع Dataset غير ضخم |

### 45.3 التجارب المخطَّطة على هذا الأساس

Config أعلاه هو التشغيل الأول فقط. المخطَّط التجريبي الكامل (يُفصَّل التنفيذ في الجزء الرابع والعشرين):

```
Run 1: r=16, lr=2e-4    (هذا الـConfig تحديدًا)
Run 2: r=8,  lr=2e-4    (هل rank أصغر يكفي؟)
Run 3: r=32, lr=2e-4    (هل rank أكبر يحسّن فعليًا، أم فقط يبطئ؟)
Run 4: r=16, lr=1e-4    (هل معدل تعلّم أبطأ أكثر استقرارًا؟)
```

كل تشغيل يُقاس على نفس Benchmark v0.1 (الفصل 38) بنفس مقاييس الفصل 2 — والمقارنة تكون دائمًا نسبةً لـBaseline الموثَّق في الفصل 42، **وليس** بين التشغيلات فقط بمعزل عن نقطة البداية.

> **Definition of Done — الجزء الثالث والعشرون:** أول تشغيل تدريب فعلي (ولو مصغّر — subset من train.jsonl، epoch واحد) يكتمل بنجاح دون OOM، مع سجل `vram_monitor.py` يوثّق أن الاستهلاك بقي ضمن الحدود الآمنة (< 15GB reserved طوال التشغيل)، وملف checkpoint ناتج فعليًا في `experiments/v0.1_qlora_run1/`.

---

[← الجزء الثاني والعشرون](./part-22-baseline.md) · [الفهرس](./README.md) · [الجزء الرابع والعشرون →](./part-24-sft.md)
