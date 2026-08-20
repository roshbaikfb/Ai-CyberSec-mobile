[← رجوع للفهرس](./README.md)

# الجزء الأول: تعريف المشروع

## الفصل 1: ما الذي نبنيه فعلًا؟

قبل كتابة أي سطر كود، لازم نحدد بدقة شديدة نوع النظام اللي بنبنيه، لأن الخلط بين الأنواع دي هو السبب الأول لفشل مشاريع الأمان المبنية على LLM. الست أنواع دول مختلفين جوهريًا في الهدف، وفي الـFailure Mode، وفي طريقة التقييم.

### 1.1 الأنواع الستة ولماذا نحن لسنا معظمها

| النوع | الهدف | لماذا هو غير كافٍ هنا |
|---|---|---|
| Security Chatbot | يجاوب على أسئلة أمنية عامة | لا يحلل كود فعلي، ولا يربط بسياق Binder/UID محدد |
| Code Assistant | يشرح أو يعدّل كود | لا هدف أمني، ولا Evidence، ولا Confidence |
| Static Analyzer | قواعد ثابتة (Regex/AST rules) | لا reasoning عبر عدة methods، معدل False Positive عالٍ جدًا في أنماط معقدة مثل identity transitions |
| Vulnerability Classifier | Vulnerable / Not Vulnerable فقط | بدون Evidence ولا موقع ولا سبب، غير قابل للاستخدام في بحث حقيقي |
| Vulnerability Research Model | يحاكي منهجية الباحث: تتبع الهوية، الصلاحيات، الـtrust boundary، الدليل | هذا هو الهدف — لكنه غير كافٍ بمفرده لأنه لا يملك حقائق حتمية عن الكود بحجم AOSP |
| Hybrid Static Analysis + LLM | Static layer يستخرج حقائق حتمية، وLLM يقوم بالـreasoning عليها | هذا ما سنبنيه فعليًا |

**الخلاصة:** النموذج اللغوي وحده ليس المنتج. المنتج هو نظام هجين — الـLLM هو محرك الـReasoning داخل نظام أكبر يوفر له حقائق حتمية (deterministic facts) بدل تركه يقرأ ملف ٢٠ ألف سطر ويخمّن.

### 1.2 لماذا لا نعطي النموذج الملف كاملًا؟

- Context محدود عمليًا حتى مع نوافذ سياق كبيرة — الدقة تنخفض كلما زاد الـnoise غير ذي الصلة.
- معظم الملف غير مرتبط بالثغرة المحتملة؛ إعطاء كل شيء يزيد الـhallucination بدل تقليله.
- الثغرة غالبًا موزعة عبر عدة methods (Binder entry + helper + sink) وليست في مكان واحد متجاور.
- بدون Static Analysis أولًا، النموذج يبدأ من الصفر في كل مرة بدل البناء على حقائق مؤكدة (مثل: هل توجد enforceCallingPermission في المسار؟).

لذلك التصميم المعماري الكامل للنظام هو:

```
AOSP Repository
      ↓
   Parser
      ↓
Static Analyzer
      ↓
Candidate Generator
      ↓
 Code Retriever
      ↓
Context Builder
      ↓
 Security LLM
      ↓
Finding Validator
      ↓
  Risk Ranker
      ↓
  Researcher
```

### 1.3 مسؤولية كل طبقة بدقة

| الطبقة | المسؤولية | Output |
|---|---|---|
| Parser | تحويل الكود إلى AST قابل للاستعلام | Syntax tree + symbol table |
| Static Analyzer | استخراج حقائق حتمية (calls, checks, identity ops) | Security Facts object |
| Candidate Generator | تطبيق قواعد ترشيح لإنتاج مواقع تستحق مراجعة عميقة | قائمة Candidates بـscore أولي |
| Code Retriever | جلب الـhelpers والـnamespace ذات الصلة | مجموعة methods مرتبطة |
| Context Builder | بناء prompt محدود ومركّز ضمن ميزانية Token | Context نهائي للـLLM |
| Security LLM | الـReasoning الفعلي: identity, trust boundary, invariant | JSON تحليل + verdict + confidence |
| Finding Validator | رفض Findings بلا Evidence كافٍ | Findings مصفّاة |
| Risk Ranker | ترتيب حسب الخطورة وقابلية الاستغلال المحتملة | تقرير مرتّب للباحث البشري |

> **قاعدة معمارية:** أي مكوّن يمكن حسمه بقاعدة حتمية (مثل: "هل توجد enforceCallingPermission قبل هذا الاستدعاء؟") يجب أن يُحسم بواسطة الـStatic Analyzer، وليس بواسطة الـLLM. نستخدم الـLLM فقط فيما يحتاج فعلًا إلى تفكير سياقي — العلاقة بين الهوية، صحة التحقق، واحتمالية الاستغلال.

---

## الفصل 2: تعريف النجاح

بدون مقاييس دقيقة، أي تحسّن في النموذج يصبح انطباعًا شخصيًا. هذا الفصل يحدد المقاييس الرسمية للمشروع بالكامل، وكل تجربة لاحقة (Baseline، QLoRA v1، v2...) ستُقاس بنفس المقاييس بالضبط.

### 2.1 المقاييس الأساسية

| المقياس | التعريف | لماذا يهم هنا تحديدًا |
|---|---|---|
| Precision | من بين كل Findings التي أبلغ عنها النموذج، كم نسبة كانت حقيقية | يمنع نموذجًا يصرخ "ثغرة" في كل شيء |
| Recall | من بين كل الثغرات الحقيقية في Benchmark، كم اكتشف النموذج | يقيس القدرة الفعلية على الاكتشاف |
| F1 | التوازن التوافقي بين Precision وRecall | مقياس واحد للمقارنة بين تجارب |
| False Positive Rate | معدل الإنذارات الكاذبة على كود آمن فعلًا | أهم مقياس عمليًا — نموذج بمعدل FP مرتفع عديم الفائدة لباحث بشري |
| False Negative Rate | معدل تفويت ثغرات حقيقية | يقيس الفجوات الخطيرة في التغطية |
| Localization Accuracy | هل أشار للـmethod/السطر الصحيح؟ | Finding صحيح في مكان خاطئ عديم الفائدة |
| Root Cause Accuracy | هل حدد السبب الأمني الحقيقي وليس عرضًا جانبيًا؟ | يفرّق بين فهم حقيقي وتخمين موفّق |
| Evidence Quality | هل الأدلة المذكورة موجودة فعلًا في الكود المُعطى؟ | يمنع اختلاق أدلة (evidence hallucination) |
| Security Invariant Accuracy | هل القاعدة الأمنية المذكورة صحيحة ومنطبقة؟ | يقيس فهم المبدأ لا الحفظ |
| Insufficient-Context Accuracy | هل قال "غير كافٍ" في الحالات التي تستحق ذلك فعلًا؟ | يقيس الانضباط ضد التخمين |
| Confidence Calibration | هل نسبة الثقة المعلنة تعكس دقة فعلية؟ | ثقة 95% في نتيجة خاطئة أخطر من عدم اليقين |

### 2.2 الصيغ الحسابية

```
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 * (Precision * Recall) / (Precision + Recall)
FPR       = FP / (FP + TN)
FNR       = FN / (FN + TP)

# Localization Accuracy: نسبة الـFindings الصحيحة (TP)
# التي أشارت أيضًا لنفس method/سطر في الـground truth
LocalizationAccuracy = CorrectLocation_TP / TP

# Root Cause Accuracy: نسبة TP التي طابق فيها
# missing_invariant/root_cause المُخرَج مع الـground truth
# (بعد normalization للفئة، وليس مطابقة نصية حرفية)
RootCauseAccuracy = CorrectRootCause_TP / TP
```

### 2.3 سكريبت التقييم الأولي (`evaluation/metrics.py`)

هذا سكريبت مبدئي يعمل على مخرجات JSON من النموذج مقابل Ground Truth. سيتوسع لاحقًا في الفصل 52، لكنه هنا يحدد العقد (contract) الذي سيلتزم به كل شيء بعد ذلك.

```python
# evaluation/metrics.py
from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal[
    "vulnerable", "secure", "ambiguous", "insufficient_context"
]

@dataclass
class EvalCase:
    sample_id: str
    predicted_verdict: Verdict
    true_verdict: Verdict
    predicted_location: str | None = None
    true_location: str | None = None
    predicted_invariant: str | None = None
    true_invariant_category: str | None = None
    predicted_confidence: float = 0.0

@dataclass
class ConfusionCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

def is_positive(v: Verdict) -> bool:
    return v == "vulnerable"

def compute_confusion(cases: list[EvalCase]) -> ConfusionCounts:
    c = ConfusionCounts()
    for case in cases:
        pred = is_positive(case.predicted_verdict)
        true = is_positive(case.true_verdict)
        if pred and true:
            c.tp += 1
        elif pred and not true:
            c.fp += 1
        elif not pred and true:
            c.fn += 1
        else:
            c.tn += 1
    return c

def precision(c: ConfusionCounts) -> float:
    return c.tp / (c.tp + c.fp) if (c.tp + c.fp) else 0.0

def recall(c: ConfusionCounts) -> float:
    return c.tp / (c.tp + c.fn) if (c.tp + c.fn) else 0.0

def f1(c: ConfusionCounts) -> float:
    p, r = precision(c), recall(c)
    return 2 * p * r / (p + r) if (p + r) else 0.0

def false_positive_rate(c: ConfusionCounts) -> float:
    return c.fp / (c.fp + c.tn) if (c.fp + c.tn) else 0.0

def localization_accuracy(cases: list[EvalCase]) -> float:
    tp_cases = [
        c for c in cases
        if is_positive(c.predicted_verdict) and is_positive(c.true_verdict)
    ]
    if not tp_cases:
        return 0.0
    correct = sum(
        1 for c in tp_cases
        if c.predicted_location and c.true_location
        and c.predicted_location.strip() == c.true_location.strip()
    )
    return correct / len(tp_cases)

def insufficient_context_accuracy(cases: list[EvalCase]) -> float:
    ic_cases = [c for c in cases if c.true_verdict == "insufficient_context"]
    if not ic_cases:
        return 0.0
    correct = sum(
        1 for c in ic_cases if c.predicted_verdict == "insufficient_context"
    )
    return correct / len(ic_cases)

def summarize(cases: list[EvalCase]) -> dict:
    c = compute_confusion(cases)
    return {
        "n_cases": len(cases),
        "precision": round(precision(c), 4),
        "recall": round(recall(c), 4),
        "f1": round(f1(c), 4),
        "false_positive_rate": round(false_positive_rate(c), 4),
        "localization_accuracy": round(localization_accuracy(cases), 4),
        "insufficient_context_accuracy": round(
            insufficient_context_accuracy(cases), 4
        ),
    }
```

> **Definition of Done — الفصل 2:** المشروع لا ينتقل لأي تدريب فعلي قبل أن يعمل هذا السكريبت على الأقل على 20 حالة يدوية (10 vulnerable حقيقية معروفة + 10 secure) وتُخرج أرقامًا منطقية. لو النتائج غريبة على بيانات معروفة يدويًا، المشكلة في التقييم نفسه وليس في النموذج.

---

[← رجوع للفهرس](./README.md) · [الجزء الثاني →](./part-02-android-fundamentals.md)
