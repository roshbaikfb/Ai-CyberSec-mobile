[← الجزء الثامن والعشرون](./part-28-evaluation.md) · [الفهرس](./README.md)

# الجزء التاسع والعشرون: Confidence Calibration وما بعدها

هذا هو الجزء الأخير من الكتاب — يغطي الفصل 54 (Calibration)، ثم يجمع كل الأجزاء الثمانية والعشرين السابقة ضمن خارطة تنفيذ زمنية كاملة (Milestones 0-8)، المعمارية النهائية للمنتج، قواعد المشروع الحاكمة، وخاتمة.

## الفصل 54: Confidence Calibration

### 54.1 لماذا الثقة المُعلَنة نفسها تحتاج قياسًا منفصلاً

نموذج قد يكون دقيقًا (Accuracy عالية) لكن **غير معايَر** (miscalibrated) — يقول "95% ثقة" في أحكام صحيحة بنسبة 60% فقط فعليًا. هذا خطير في سياقنا تحديدًا: باحث بشري يستخدم الأداة سيثق أكثر بالنتائج ذات الثقة المُعلَنة العالية — لو هذه الثقة غير موثوقة، الأداة تُضلِّل بدل أن تساعد.

### 54.2 Reliability Diagrams

```python
# evaluation/calibration.py
"""
يبني Reliability Diagram: يقسّم التنبؤات لصناديق (bins) حسب الثقة
المُعلَنة، ويقارن الثقة المتوسطة في كل صندوق بالدقة الفعلية فيه.
نموذج معايَر تمامًا: كل نقطة تقع على الخط القطري (ثقة = دقة).
"""
from dataclasses import dataclass

@dataclass
class CalibrationBin:
    confidence_range: tuple[float, float]
    n_predictions: int
    mean_confidence: float
    actual_accuracy: float
    gap: float  # |mean_confidence - actual_accuracy| — كلما قلّ كان أفضل

def build_reliability_diagram(
    predictions: list[dict], n_bins: int = 10
) -> list[CalibrationBin]:
    """predictions: [{'confidence': float, 'correct': bool}, ...]"""
    bin_width = 1.0 / n_bins
    bins = []

    for i in range(n_bins):
        low, high = i * bin_width, (i + 1) * bin_width
        in_bin = [
            p for p in predictions
            if low <= p["confidence"] < high or (high == 1.0 and p["confidence"] == 1.0)
        ]
        if not in_bin:
            continue

        mean_conf = sum(p["confidence"] for p in in_bin) / len(in_bin)
        accuracy = sum(1 for p in in_bin if p["correct"]) / len(in_bin)

        bins.append(CalibrationBin(
            confidence_range=(low, high),
            n_predictions=len(in_bin),
            mean_confidence=round(mean_conf, 3),
            actual_accuracy=round(accuracy, 3),
            gap=round(abs(mean_conf - accuracy), 3),
        ))
    return bins

def expected_calibration_error(bins: list[CalibrationBin], total_predictions: int) -> float:
    """ECE: المتوسط المرجَّح (بعدد التنبؤات) للفجوة بين الثقة والدقة
    عبر كل الصناديق — مقياس واحد يلخّص جودة المعايرة الكلية."""
    weighted_gap_sum = sum(
        b.gap * b.n_predictions for b in bins
    )
    return round(weighted_gap_sum / total_predictions, 4) if total_predictions else 0.0
```

### 54.3 Brier Score

```python
def brier_score(predictions: list[dict]) -> float:
    """Brier Score: متوسط مربع الفرق بين الثقة المُعلَنة والنتيجة
    الفعلية (1 لو صحيح، 0 لو خاطئ). أقل = أفضل. يُكمِّل الـECE بمقياس
    حساس لحجم الخطأ الفردي، وليس فقط متوسط الفجوة على مستوى الصناديق."""
    if not predictions:
        return 0.0
    total = sum(
        (p["confidence"] - (1.0 if p["correct"] else 0.0)) ** 2
        for p in predictions
    )
    return round(total / len(predictions), 4)
```

### 54.4 التفسير العملي للنتائج

| النمط المُلاحَظ | ماذا يعني | ماذا نفعل |
|---|---|---|
| ثقة عالية باستمرار + دقة منخفضة | **Overconfidence** — النموذج واثق أكثر مما يستحق | نُضيف عينات تدريب أكثر من فئة Hard Negatives (الفصل 31) ومن insufficient_context (الفصل 32) لتعليم النموذج التردد المبرَّر |
| ثقة منخفضة باستمرار + دقة عالية | **Underconfidence** — النموذج متردد أكثر من اللازم | أقل خطورة عمليًا من Overconfidence، لكن يقلل فائدة حقل confidence نفسه في ترتيب الأولويات (Risk Ranker) |
| فجوة كبيرة فقط في فئة معيّنة (من تحليل الفصل 52) | مشكلة محلية وليست عامة | نراجع تحديدًا عينات هذه الفئة — قد تحتاج المزيد من التنويع أو التصحيح |

> **Definition of Done — الفصل 54:** حساب `expected_calibration_error` وBrier Score فعليًا على نتائج Benchmark v0.1 لأول نموذج مدرَّب، مع توثيق ECE في `experiments/v0.1_qlora_run1/calibration_report.json` — هذا الرقم يصبح خط أساس لمقارنة أي تحسين معايرة لاحق (مثل Temperature Scaling، الذي يُترَك كتوسّع لإصدارات لاحقة بعد v0.1).

---

## خارطة التنفيذ الزمنية الكاملة (Milestones 0-8)

الأجزاء التسعة والعشرون السابقة تُبنى بترتيب منطقي، لكن التنفيذ الفعلي يتقدّم عبر تسع محطات (Milestones) واضحة الحدود، كل واحدة لها Definition of Done صريح قبل الانتقال للتالية.

### Milestone 0 — Research Environment
**يغطي:** الجزء الخامس (البيئة والبنية).
**DoD:** `check_env.py` يطبع `ALL CHECKS PASSED`، بنية المشروع كاملة على القرص، أول commit في Git.

### Milestone 1 — Dataset Collector
**يغطي:** الأجزاء 6-9 (جمع AOSP، Patch Mining، Bulletins، Parsing).
**الهدف:** 10,000 candidate خام — وليس 10,000 عينة تدريب جاهزة. هذا الفرق مهم: هذه المرحلة تجمع مادة خام، لا تُنتج بيانات تدريب معتمدة بعد.
**DoD:** ملفات JSONL من `collector/`, `patch_miner/`, `bulletin_collector/` تحتوي بيانات حقيقية موثَّقة المصدر.

### Milestone 2 — Dataset v0.1
**يغطي:** الأجزاء 10-18 (Static Analysis، Call Graph، Retrieval، Dataset Design، Vulnerable/Fixed Pairs، Negatives، Insufficient Context، Provenance، Deduplication).
**التوزيع المبدئي المستهدف (حسب نوع المحتوى، بالتكامل مع توزيع الفصل 28.4 حسب verdict):**
```
30% security patch reasoning (Vulnerable/Fixed pairs)
20% Binder/identity
15% authorization
10% cross-user
10% secure negatives
10% hard negatives
5%  insufficient context
```
**DoD:** 5,000-20,000 عينة معتمدة (بعد Quality Scoring — الجزء السابع والعشرون) في `dataset/v0.1/`.

### Milestone 3 — Baseline Benchmark
**يغطي:** الأجزاء 19-22 (Leakage Prevention، Benchmark، اختيار النموذج، Baseline).
**قاعدة صارمة:** لا نتجاوز هذه المرحلة قبل تسجيل Baseline كاملة موثَّقة.
**DoD:** `experiments/baseline/summary.json` موجود ومكتمل (كما حُدِّد في الفصل 42).

### Milestone 4 — QLoRA Experiment 1
**يغطي:** الأجزاء 23-24 (QLoRA، SFT).
**السؤال المحوري:** "هل الـDataset تحسّن Android vulnerability reasoning فعليًا مقارنة بالـBaseline؟"
**قاعدة:** لو لم يتحسّن الأداء، لا نزيد عدد الـepochs عشوائيًا — نحلل الأخطاء أولًا (الجزء الثامن والعشرون) لفهم السبب الجذري.
**DoD:** أول checkpoint مدرَّب + مقارنة كاملة مقابل Baseline عبر كل مقاييس الفصل 2.

### Milestone 5 — Dataset v0.2
**يغطي:** إعادة تطبيق الأجزاء 14، 15، 26 (Vulnerable/Fixed Pairs، Hard Negatives، Synthetic Data) بناءً على نتائج تحليل الأخطاء من Milestone 4.
**مثال قرار:** لو النموذج يفشل تحديدًا في تمييز package ↔ UID mismatch (الفصل 10.1)، نضيف عينات مخصصة إضافية من هذه الفئة تحديدًا عبر Hard Negative Mining الموسَّع.
**DoD:** `dataset/v0.2/` موجود مع سجل تغييرات واضح (`CHANGELOG.md`) يوثّق بالضبط ماذا أُضيف أو حُذف ولماذا.

### Milestone 6 — AFVRM-7B-v1
**يغطي:** إعادة تشغيل الأجزاء 23-28 (QLoRA → Evaluation) على Dataset v0.2، مع تطبيق Curriculum Learning (الجزء الخامس والعشرون) كاملاً هذه المرة.
**الهدف:** نموذج يستطيع فعليًا: قراءة candidate، تحليل trust boundary، تحديد source/sink، تتبّع UID، تحليل permissions، تقديم evidence، إخراج confidence معايَر بشكل معقول.
**DoD:** نموذج يتفوّق بوضوح على Baseline وعلى v0.1 QLoRA عبر كل الفئات الرئيسية في Benchmark v0.1 (وليس فقط في المتوسط الإجمالي).

### Milestone 7 — Repository Scanner
**يغطي:** دمج كل مكوّنات النظام (الأجزاء 1، 10-12، بالإضافة لنموذج Milestone 6) في أداة تشغيلية واحدة.

```bash
afvrm scan frameworks/base/services/core/java/com/android/server/
```

**تدفق العمل الداخلي:**
```
Parse (الجزء التاسع)
    ↓
Rank files (أولوية حسب كثافة الأنماط الأمنية التاريخية)
    ↓
Generate candidates (الجزء العاشر)
    ↓
Retrieve context (الجزء الثاني عشر)
    ↓
Run LLM (نموذج Milestone 6)
    ↓
Rank findings (حسب confidence وseverity الفئة)
    ↓
Generate report (تنسيق موضَّح أدناه)
```
**DoD:** تشغيل ناجح على مجلد AOSP حقيقي كامل (وليس عينة صغيرة)، مع تقرير Findings منظَّم وقابل للمراجعة البشرية خلال وقت معقول (وليس آلاف الصفحات غير مُرتَّبة).

### Milestone 8 — 14B Experiment (اختياري، بعد نجاح Milestone 7 فقط)
**السؤال:** هل الانتقال لنموذج 14B يبرر تكلفة التشغيل الإضافية؟
**معيار القرار:**
```
لو:  F1(7B) = 0.73   و   F1(14B) = 0.75   →  الفرق غير كافٍ لتبرير التكلفة
لو:  F1(7B) = 0.73   و   F1(14B) = 0.86   →  الفرق يبرر الانتقال
```
**شرط أساسي:** لا تُجرى هذه التجربة إطلاقًا قبل نجاح Milestone 7 الكامل — القرار بين 7B وb14 له معنى فقط بعد إثبات أن المنهجية بالكامل (وليس فقط حجم النموذج) تعمل.

---

## المعمارية النهائية الكاملة للمنتج

بعد Milestone 7، الشكل النهائي للنظام ليس LLM منفردًا — كما أُكِّد منذ الفصل الأول — بل:

```
                    AOSP Repository
                          │
                          ▼
                  Static Analyzer        (الجزء العاشر)
                          │
                          ▼
                 Candidate Generator     (الجزء العاشر)
                          │
                          ▼
                    Code Retriever       (الجزء الثاني عشر)
                          │
                          ▼
                  Context Builder        (الجزء الثاني عشر)
                          │
                          ▼
                AFVRM Security Model     (Milestone 6)
                          │
                          ▼
                  Finding Validator      (يرفض Findings بلا Evidence كافٍ)
                          │
                          ▼
                    Risk Ranker          (حسب confidence معايَر + severity)
                          │
                          ▼
                     Researcher
```

### شكل التقرير النهائي — مثال

```
Finding #27

Component:           PackageManagerService
Category:            Cross-user authorization gap (Taxonomy 10.2)
Entry point:         someBinderMethod()
Caller:               Untrusted application UID
Attacker-controlled:  targetUserId
Trust boundary:       Application -> system_server
Authorization:        Permission X is checked; no cross-user check found
Identity transition:  Binder.clearCallingIdentity() occurs before privileged work
Evidence:             [مقتطف الكود الفعلي مع رقم السطر]
Counter-evidence:     A downstream helper may perform a cross-user check
Required context:     Inspect helperMethod() -- currently unresolved
Confidence:           0.72 (calibrated -- الفصل 54)
Verdict:              Needs investigation
```

لاحظ أن التقرير لا يقول "Critical vulnerability!" دون دليل — هذه النقطة، المؤكَّدة منذ الفصل الأول وحتى هنا، هي الفارق الجوهري بين أداة بحث احترافية وChatbot أمني يتصرف بثقة زائفة.

---

## قواعد المشروع الحاكمة — ملخّص نهائي

القواعد العشر التالية ظهرت موزَّعة عبر الكتاب بالكامل؛ هذا تجميعها كمرجع نهائي واحد:

1. **لا تدريب على كمية كبيرة قبل بناء Benchmark** (الجزء العشرون قبل الثالث والعشرين).
2. **لا Dataset بدون provenance** (الجزء السابع عشر).
3. **لا يدخل نفس الـpatch لـtrain ونسخته القريبة لـtest** (الجزء التاسع عشر).
4. **كل Vulnerable sample يقابله اهتمام جدي بالـnegative samples** (الجزء الخامس عشر).
5. **clearCallingIdentity() ليس ثغرة بمفرده** (الفصل 5، مُطبَّق عبر الكتاب بالكامل).
6. **وجود permission check لا يعني أن الكود آمن** (الفصل 6، الجزء الرابع عشر).
7. **وجود bug لا يعني إمكانية استغلال أمني** (الفصل 39 — تمييز CONFIRMED_BUG عن CONFIRMED_SECURITY_ISSUE).
8. **النموذج يجب أن يقول "Insufficient context" عند الحاجة** (الجزء السادس عشر).
9. **لا Finding بدون Evidence** (الفصل 27، الفصل السابع).
10. **كل Fine-Tuning جديد يجب أن يثبت تحسنًا على Benchmark مستقل** (الجزء الثاني والعشرون، الفصل 41).

---

## الخاتمة

المشروع الصحيح، كما فصَّله هذا الكتاب عبر تسعة وعشرين جزءًا، ليس:

```
Download 7B + 50k cybersecurity questions + QLoRA = Android Hacker AI
```

هذا المسار المختصر ينتج على الأرجح Chatbot أمنيًا آخر — عام، غير موثوق، عالي False Positives.

المسار الذي غطّاه هذا الكتاب بالكامل هو:

```
Understand Android Security              (الأجزاء 1-4)
            v
Mine AOSP History                        (الأجزاء 5-9)
            v
Extract Security Patches                 (الجزء السابع)
            v
Build Vulnerable/Fixed Pairs             (الجزء الرابع عشر)
            v
Build Secure Negatives + Hard Negatives  (الجزء الخامس عشر)
            v
Define Security Invariants               (الفصل 9)
            v
Build Leakage-Free Benchmark             (الأجزاء 19-20)
            v
Baseline 7B                              (الجزء الثاني والعشرون)
            v
QLoRA/SFT                                (الأجزاء 23-25)
            v
Failure Analysis                         (الجزء الثامن والعشرون)
            v
Dataset Improvement                      (Milestone 5)
            v
Hybrid Static Analysis + LLM             (طوال الكتاب)
            v
Unseen-Patch Evaluation                  (الفصل 37)
            v
AFVRM-7B                                 (Milestone 6)
            v
14B Comparison                           (Milestone 8، اختياري)
            v
Android Framework Security Research Agent (Milestone 7)
```

الهدف النهائي لم يكن أبدًا جعل النموذج يتكلم عن ثغرات Android بطلاقة. الهدف كان تعليمه كيف يبحث عنها — بمنهجية، بأدلة، وبانضباط ضد التخمين. هذا هو الفارق بين نموذج يبدو ذكيًا وأداة بحث تستحق ثقة باحث أمني حقيقي.

---

[← الجزء الثامن والعشرون](./part-28-evaluation.md) · [الفهرس](./README.md) · [ملحق: الجزء الثلاثون →](./part-30-data-sources-deep-dive.md)

**هذا الفصل يُكمل بنية الكتاب الأساسية — 29 جزءًا، 54 فصلًا. الأجزاء 30-31 ملحق تفصيلي إضافي عن مصادر البيانات وTeacher Model.**
