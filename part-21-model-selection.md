[← الجزء العشرون](./part-20-benchmark.md) · [الفهرس](./README.md)

# الجزء الحادي والعشرون: اختيار النموذج

## الفصل 40: Model Selection

### 40.1 لماذا لا نُثبّت اسم نموذج واحد في هذا الكتاب

أسماء النماذج المتاحة في نطاق 7B تتغيّر بوتيرة سريعة جدًا — نموذج يُعتبر الأفضل في فئته اليوم قد يُستبدَل خلال أشهر. تثبيت اسم محدد في كتاب مرجعي يجعله عرضة للتقادم السريع. لذلك هذا الفصل يبني **منهجية مقارنة** تبقى صالحة بصرف النظر عن أي نموذج يظهر لاحقًا، بدل التوصية بنموذج بعينه.

### 40.2 معايير المقارنة الإلزامية

| المعيار | كيف نقيسه عمليًا | لماذا يهم لهذا المشروع تحديدًا |
|---|---|---|
| **Coding ability** | نتائج Benchmarks عامة معروفة وقت الاختيار (HumanEval، أو ما يعادلها الأحدث)، **وليس فقط الادعاءات التسويقية للنموذج** | الأساس اللازم لفهم بنية Java/Kotlin المعقّدة |
| **Context length** | الحد الأقصى المُعلَن، **وما يُثبِته الأداء الفعلي** (كثير من النماذج تتدهور قبل الوصول للحد الأقصى المُعلَن) | يجب أن يتسع لـcontext الفصل 26 (current method + caller + helpers + sink) بارتياح |
| **License** | هل الترخيص يسمح صراحة بالاستخدام البحثي/التجاري المطلوب، وبإعادة توزيع الأوزان المُعدَّلة (LoRA adapters) | يمنع مفاجآت قانونية لاحقة — يُتحقَّق منه **قبل** أي استثمار وقت تدريب |
| **QLoRA support** | هل بنية النموذج مدعومة رسميًا في `transformers`/`peft`/`bitsandbytes` وقت الاختيار | نموذج غير مدعوم يعني عمل هندسي إضافي غير مخطَّط له |
| **Memory footprint (4-bit)** | حجم الأوزان بعد التكميم 4-bit + هامش لـLoRA adapters وactivations | يجب أن يعمل ضمن 16GB VRAM (الفصل 44 التالي يفصّل هذا الحساب) |
| **Instruction following** | الأداء على مهام تتبع تعليمات JSON-structured تحديدًا (وليس محادثة عامة فقط) | مخرجاتنا يجب أن تلتزم بـSchema الفصل 27 بدقة |
| **Base vs Instruct availability** | هل يتوفر كلا الإصدارين لنفس النموذج | ضروري لتجربة الفصل 41 |
| Multilingual ability | ليست أولوية | الكود والتحليل بالإنجليزية أساسًا (تسمية APIs، مصطلحات أمنية قياسية)؛ التوثيق العربي في هذا الكتاب منفصل عن مخرجات النموذج نفسه |

### 40.3 `model_selection/comparison_framework.py`

بدل جدول ثابت بأسماء نماذج، نبني **إطار تقييم قابل لإعادة التشغيل** على أي مرشّحين وقت اتخاذ القرار فعليًا:

```python
# model_selection/comparison_framework.py
"""
إطار تقييم عام — يُشغَّل يدويًا على أي قائمة مرشحين متاحة وقت التنفيذ.
لا يفترض أسماء نماذج محددة؛ القائمة تُمرَّر كمُدخَل.
"""
from dataclasses import dataclass, field

@dataclass
class ModelCandidate:
    name: str
    huggingface_id: str
    license: str
    license_allows_commercial_use: bool
    license_allows_derivative_redistribution: bool
    max_context_length: int
    parameter_count_b: float
    has_base_variant: bool
    has_instruct_variant: bool
    qlora_supported_in_peft: bool
    published_humaneval_score: float | None = None
    notes: str = ""

@dataclass
class EvaluationResult:
    candidate: ModelCandidate
    passes_hard_filters: bool
    disqualification_reasons: list[str] = field(default_factory=list)
    estimated_4bit_vram_gb: float = 0.0

def estimate_4bit_vram_gb(parameter_count_b: float, context_length: int) -> float:
    """تقدير تقريبي: ~0.75 GB لكل مليار معامل بعد تكميم 4-bit للأوزان
    نفسها، + هامش تقريبي لـKV cache يتناسب مع طول السياق.
    هذا تقدير تخطيطي أولي فقط — الفصل 44 يقدّم حسابًا أدق."""
    weights_gb = parameter_count_b * 0.75
    kv_cache_overhead_gb = (context_length / 4096) * 1.0
    adapter_and_activation_margin_gb = 2.0
    return round(weights_gb + kv_cache_overhead_gb + adapter_and_activation_margin_gb, 1)

def evaluate_candidate(
    candidate: ModelCandidate, max_available_vram_gb: float = 16.0,
    min_required_context: int = 4096
) -> EvaluationResult:
    reasons = []

    if not candidate.license_allows_commercial_use:
        reasons.append("License does not clearly permit intended use")
    if not candidate.qlora_supported_in_peft:
        reasons.append("QLoRA not supported in current PEFT integration")
    if not candidate.has_base_variant or not candidate.has_instruct_variant:
        reasons.append("Missing base or instruct variant — blocks Chapter 41 experiment")
    if candidate.max_context_length < min_required_context:
        reasons.append(
            f"Context length {candidate.max_context_length} below "
            f"minimum requirement {min_required_context}"
        )

    estimated_vram = estimate_4bit_vram_gb(
        candidate.parameter_count_b, candidate.max_context_length
    )
    if estimated_vram > max_available_vram_gb:
        reasons.append(
            f"Estimated VRAM {estimated_vram}GB exceeds available "
            f"{max_available_vram_gb}GB"
        )

    return EvaluationResult(
        candidate=candidate,
        passes_hard_filters=(len(reasons) == 0),
        disqualification_reasons=reasons,
        estimated_4bit_vram_gb=estimated_vram,
    )

def rank_candidates(results: list[EvaluationResult]) -> list[EvaluationResult]:
    passing = [r for r in results if r.passes_hard_filters]
    passing.sort(
        key=lambda r: r.candidate.published_humaneval_score or 0.0,
        reverse=True,
    )
    return passing
```

### 40.4 مثال استخدام (يُعبَّأ بمرشحين فعليين وقت التنفيذ)

```python
# model_selection/run_comparison.py
from model_selection.comparison_framework import (
    ModelCandidate, evaluate_candidate, rank_candidates,
)

# مثال توضيحي فقط — القيم الفعلية يجب تحديثها وقت اتخاذ القرار الحقيقي
# من صفحات النماذج الرسمية على Hugging Face ومصادر licensing الرسمية
candidates = [
    ModelCandidate(
        name="Candidate A", huggingface_id="org/model-a-7b",
        license="Apache-2.0", license_allows_commercial_use=True,
        license_allows_derivative_redistribution=True,
        max_context_length=32768, parameter_count_b=7.0,
        has_base_variant=True, has_instruct_variant=True,
        qlora_supported_in_peft=True, published_humaneval_score=0.0,  # يُحدَّث فعليًا
    ),
    # أضف مرشحين آخرين هنا وقت التنفيذ الفعلي
]

results = [evaluate_candidate(c) for c in candidates]
ranked = rank_candidates(results)

for r in results:
    status = "✅ PASS" if r.passes_hard_filters else "❌ FAIL"
    print(f"{status} {r.candidate.name} "
          f"(est. VRAM: {r.estimated_4bit_vram_gb}GB)")
    for reason in r.disqualification_reasons:
        print(f"    - {reason}")
```

> **قاعدة الحسم:** لا يُختار نموذج بناءً على "سمعة" أو منشور تسويقي وحده. الجدول أعلاه (`evaluate_candidate` + `rank_candidates`) يجب أن يُشغَّل فعليًا على الأقل على 3 مرشحين حقيقيين متاحين وقت القرار، مع توثيق النتيجة الكاملة (بما فيها أسباب الرفض للمرشحين الذين لم يُختاروا) في `experiments/model_selection_log.md`.

---

## الفصل 41: Base vs Instruct

### 41.1 التجربة الحقيقية

بعد اختيار عائلة نموذج واحدة (7B) عبر الفصل 40، القرار التالي هو: نبدأ من نسخة **Base** أم **Instruct**؟ هذا لا يُقرَّر نظريًا — يُختبَر فعليًا.

```
Experiment A: 7B Base      + Dataset v0.1 (نفسه بالضبط)
Experiment B: 7B Instruct  + Dataset v0.1 (نفسه بالضبط)
```

كل شيء آخر (البيانات، الـConfig، عدد الـepochs، الـBenchmark) يُثبَّت بين التجربتين — المتغيّر الوحيد هو نقطة الانطلاق.

### 41.2 لماذا لا نفترض إجابة مسبقة

| الافتراض الشائع | لماذا قد يكون خاطئًا هنا تحديدًا |
|---|---|
| "Instruct دائمًا أفضل لأنه يفهم التعليمات" | الـpost-training السابق على Instruct قد يكون "علّم" النموذج أنماط استجابة (مثل الحذر المفرط، أو أسلوب محادثة عام) تتعارض مع الحسم المطلوب في مهمة تحليل أمني دقيقة |
| "Base دائمًا أفضل لأنه 'نظيف' بلا تحيّزات post-training" | Base يحتاج بيانات أكثر بكثير ليتعلم حتى الشكل الأساسي للاستجابة المتوقَّعة (JSON منظَّم وفق Schema الفصل 27) — قد لا يكفيه حجم Dataset v0.1 |

القرار الصحيح الوحيد: **قياس فعلي على نفس الـBenchmark (الفصل 38)**، وليس تفضيلًا نظريًا.

### 41.3 `experiments/base_vs_instruct.py`

```python
# experiments/base_vs_instruct.py
"""
هيكل تجربة موحّد — نفس دالة التدريب والتقييم تُستدعى مرتين
بنفس المعاملات تمامًا عدا اسم النموذج الأساسي، لضمان مقارنة عادلة.
تفاصيل SFTTrainer الكاملة تُشرح في الفصل 46 — هذا الفصل يُركّز على
بنية المقارنة نفسها.
"""
from dataclasses import dataclass, replace

@dataclass
class ExperimentConfig:
    base_model_id: str
    dataset_path: str
    output_dir: str
    learning_rate: float = 2e-4
    epochs: int = 3
    max_seq_length: int = 4096
    lora_r: int = 16
    lora_alpha: int = 32

def build_experiment_pair(
    base_model_id: str, instruct_model_id: str, dataset_path: str
) -> tuple[ExperimentConfig, ExperimentConfig]:
    common = ExperimentConfig(
        base_model_id=base_model_id,   # يُستبدَل أدناه لكل تجربة
        dataset_path=dataset_path,
        output_dir="experiments/base_vs_instruct",
    )
    exp_a = replace(common, base_model_id=base_model_id,
                     output_dir="experiments/base_vs_instruct/exp_a_base")
    exp_b = replace(common, base_model_id=instruct_model_id,
                     output_dir="experiments/base_vs_instruct/exp_b_instruct")
    return exp_a, exp_b

def compare_results(result_a: dict, result_b: dict) -> dict:
    """result_a/result_b: مخرجات evaluation/metrics.py (الفصل 2) لكل تجربة."""
    comparison = {}
    for metric in ["precision", "recall", "f1", "false_positive_rate",
                   "localization_accuracy", "insufficient_context_accuracy"]:
        a_val = result_a.get(metric, 0.0)
        b_val = result_b.get(metric, 0.0)
        comparison[metric] = {
            "base": a_val, "instruct": b_val,
            "winner": "base" if a_val > b_val else (
                "instruct" if b_val > a_val else "tie"
            ),
        }
    return comparison
```

### 41.4 معايير القرار النهائي

القرار لا يُبنى على مقياس واحد (مثل F1 فقط). نستخدم هذا الترتيب الهرمي عند التعارض:

1. **False Positive Rate أولًا** — نموذج بمعدل FP أعلى بشكل ملحوظ أقل فائدة عمليًا حتى لو F1 أعلى قليلًا.
2. **Insufficient-Context Accuracy** ثانيًا — الانضباط ضد التخمين له أولوية على الدقة الخام.
3. **F1 العام** ثالثًا — كمقياس توازن شامل بعد استيفاء الشرطين أعلاه.
4. **Instruction-following الشكلي** (نسبة المخرجات التي تلتزم بـSchema الفصل 27 دون أخطاء تحليل JSON) كعامل حاسم عند التعادل التام في المقاييس الثلاثة أعلاه — نموذج لا يمكن تحليل مخرجاته آليًا عديم الفائدة عمليًا مهما كانت دقته الجوهرية.

> **Definition of Done — الجزء الحادي والعشرون:** تشغيل فعلي (ولو مصغّر — عدد epochs منخفض، عينة فرعية من Dataset v0.1) لكل من `exp_a_base` و`exp_b_instruct` حتى الاكتمال، مع تقرير `compare_results` كامل موثَّق في `experiments/model_selection_log.md`، وقرار نهائي مكتوب صراحة (أي نسخة استخدمناها ولماذا، وفق الترتيب الهرمي في 41.4).

---

[← الجزء العشرون](./part-20-benchmark.md) · [الفهرس](./README.md) · [الجزء الثاني والعشرون →](./part-22-baseline.md)
